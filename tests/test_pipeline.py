from contextlib import redirect_stdout, redirect_stderr
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
from unittest import TestCase
from unittest.mock import patch, Mock
from yuldion.cli import main
from yuldion.providers import provider_options, validate_provider

EXAMPLE=Path(__file__).resolve().parents[1]/'examples/hamlet.json'


def fixture_response(payload):
    # Test-only scripted responses, never a production model adapter.
    op=payload['operation']
    reading={'observations':[{'quote':quote,'reading':'Provisional reading of '+quote}
                             for quote in ('To die','to sleep','No more')],
             'relations':[{'earlier_quote':a,'later_quote':b,'effect':'Provisional qualification.',
                           'not_established':'Scope remains uncertain.'}
                          for a,b in [('To die','to sleep'),('to sleep','No more')]],
             'not_established':'The comparison is not proven true.'}
    if op=='read_text':return reading
    if op=='audit':return {'grounded':True,'genuinely_new':False,'action_change_necessary':False,'note':'Test verdict only.'}
    return {'decision':'initialize','view':'A limited comparison is being proposed.',
            'basis':['script:0'],'textual_support':[{'quote':o['quote'],
                'interpretation':o['reading'],'intention_link':'Supports testing the limited comparison.'}
                for o in reading['observations']],
            'action':{'target_id':'internal_judge','desired_change':'Consider a limited comparison.',
                      'tactic':'invite consideration','observable_test':'A response if observed.'},
            'trigger':{'kind':'none','basis':[],'prior_assumption':'','new_insight':'','why_action_insufficient':''}}


class PipelineTests(TestCase):
    def call(self, args):
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            return main(['pipeline',*args])

    def init(self, folder, provider='local', endpoint=None):
        path=Path(folder)/'pipeline.local.json'
        args=['init','--scene',str(EXAMPLE),'--provider',provider,'--config',str(path)]
        if endpoint:args+=['--endpoint',endpoint]
        self.assertEqual(self.call(args),0)
        return path

    def test_init_and_check_are_offline_and_non_overwriting(self):
        with tempfile.TemporaryDirectory() as folder,patch('urllib.request.build_opener') as network:
            path=self.init(folder);before=path.read_bytes()
            self.assertEqual(self.call(['check','--config',str(path)]),0)
            self.assertEqual(self.call(['init','--scene',str(EXAMPLE),'--provider','openai','--config',str(path)]),2)
            self.assertEqual(path.read_bytes(),before)
            network.assert_not_called()

    def test_provider_boundary_and_no_embedded_credentials(self):
        for provider,endpoint in [('local','https://api.openai.com/v1/chat/completions'),
                                  ('local','http://remote.example/v1/chat/completions'),
                                  ('openai','https://other.example/v1/chat/completions'),
                                  ('local','http://secret@127.0.0.1:8080/v1/chat/completions')]:
            with self.assertRaises(ValueError):provider_options(provider,endpoint=endpoint)
        with self.assertRaises(ValueError):validate_provider({**provider_options('openai'),'api_key':'not-a-real-secret'})
        with self.assertRaises(ValueError):validate_provider({**provider_options('local'),'api_key_env':'OPENAI_API_KEY'})

    def test_missing_openai_key_blocks_before_inference(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=True),patch('urllib.request.build_opener') as network:
            path=self.init(folder,'openai')
            self.assertEqual(self.call(['check','--config',str(path)]),2)
            self.assertEqual(self.call(['interpret','--config',str(path),'--output-dir',str(Path(folder)/'run')]),2)
            self.assertFalse((Path(folder)/'run').exists())
            network.assert_not_called()

    def test_local_real_http_pipeline_and_provenance(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                packet=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((packet,self.headers.get('Authorization')))
                payload=json.loads(packet['messages'][1]['content'])
                response={'model':'test-double-only','choices':[{'message':{'content':json.dumps(fixture_response(payload))}}]}
                data=json.dumps(response).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'OPENAI_API_KEY':'test-key-never-send'}):
                endpoint='http://127.0.0.1:'+str(server.server_address[1])+'/v1/chat/completions'
                config=self.init(folder,endpoint=endpoint);out=Path(folder)/'run'
                with patch('yuldion.config.load_adapters',side_effect=AssertionError('Voice/face must not load')):
                    self.assertEqual(self.call(['interpret','--config',str(config),'--output-dir',str(out)]),0)
                result=json.loads((out/'result.json').read_text());manifest=json.loads((out/'manifest.json').read_text())
                self.assertEqual(result['status'],'completed')
                self.assertEqual(manifest['provider'],'local')
                self.assertFalse(manifest['voice_face_loaded'])
                self.assertFalse(manifest['human_approved'])
                self.assertEqual(manifest['result_sha256'],hashlib.sha256((out/'result.json').read_bytes()).hexdigest())
                self.assertEqual(len(requests),3)
                self.assertTrue(all(auth is None for _,auth in requests))
                self.assertEqual(self.call(['interpret','--config',str(config),'--output-dir',str(out)]),2)
                self.assertEqual(len(requests),3)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)

    def test_openai_request_shape_and_credentials_not_saved(self):
        packets=[];token='test-api-key-not-real'
        def respond(request,**kwargs):
            packet=json.loads(request.data);packets.append(packet)
            self.assertEqual(request.get_header('Authorization'),'Bearer '+token)
            response={'model':'test-double-only','choices':[{'message':{'content':json.dumps(fixture_response(json.loads(packet['messages'][1]['content'])))}}]}
            obj=Mock();obj.__enter__=Mock(return_value=obj);obj.__exit__=Mock(return_value=False)
            obj.read.return_value=json.dumps(response).encode()
            return obj
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'OPENAI_API_KEY':token}),patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=respond
            config=self.init(folder,'openai');out=Path(folder)/'run'
            self.assertEqual(self.call(['interpret','--config',str(config),'--output-dir',str(out)]),0)
            self.assertEqual(len(packets),3)
            self.assertTrue(all(p['response_format']=={'type':'json_object'} for p in packets))
            self.assertTrue(all(any('JSON' in message['content'] for message in p['messages']) for p in packets))
            for path in [config,*out.iterdir()]:self.assertNotIn(token,path.read_text())

    def test_failed_model_output_is_preserved_without_fallback(self):
        with tempfile.TemporaryDirectory() as folder,patch('yuldion.adapters.chat_reasoner.generate',return_value=({'invalid':'model output'},{})):
            config=self.init(folder);out=Path(folder)/'run'
            self.assertEqual(self.call(['interpret','--config',str(config),'--output-dir',str(out)]),2)
            result=json.loads((out/'result.json').read_text());manifest=json.loads((out/'manifest.json').read_text())
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['calls'][0]['response'],{'invalid':'model output'})
            self.assertEqual(manifest['status'],'failed')
            self.assertNotIn('proposal',result)

    def test_full_run_unconfigured_media_fails_before_network(self):
        with tempfile.TemporaryDirectory() as folder,patch('urllib.request.build_opener') as network:
            config=self.init(folder)
            self.assertEqual(self.call(['run','--config',str(config)]),2)
            network.assert_not_called()

    def test_local_server_has_explicit_resources_and_no_shell(self):
        with tempfile.TemporaryDirectory() as folder,patch('yuldion.pipeline.subprocess.run') as run:
            model=Path(folder)/'test-only.gguf';model.write_bytes(b'test-only')
            run.return_value.returncode=0
            self.assertEqual(self.call(['serve-local','--model-path',str(model),'--binary',sys.executable]),0)
            command=run.call_args.args[0]
            self.assertEqual(command[command.index('--host')+1],'127.0.0.1')
            self.assertEqual(command[command.index('-ngl')+1],'0')
            self.assertNotIn('shell',run.call_args.kwargs)

    def test_hidden_key_is_removed_after_failure_and_never_written(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=True),             patch('yuldion.pipeline.getpass.getpass',return_value='test-key-not-real'),             patch('yuldion.adapters.chat_reasoner.generate',side_effect=RuntimeError('test transport failure')):
            config=self.init(folder,'openai');out=Path(folder)/'run'
            self.assertEqual(self.call(['interpret','--config',str(config),'--prompt-api-key','--output-dir',str(out)]),2)
            self.assertNotIn('OPENAI_API_KEY',os.environ)
            for path in out.iterdir():self.assertNotIn('test-key-not-real',path.read_text())

    def test_interrupt_preserves_cancelled_manifest(self):
        with tempfile.TemporaryDirectory() as folder,patch('yuldion.adapters.chat_reasoner.generate',side_effect=KeyboardInterrupt):
            config=self.init(folder);out=Path(folder)/'run'
            self.assertEqual(self.call(['interpret','--config',str(config),'--output-dir',str(out)]),130)
            self.assertEqual(json.loads((out/'manifest.json').read_text())['status'],'cancelled')
