"""Test-only model replies verify ordered analysis -> actor handoff, not acting quality."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch
from yuldion.config import load_config
from yuldion.preparation import prepare, bind_config, validate_document, for_segment
from yuldion.providers import provider_options
from yuldion.pipeline import main

EXAMPLE=Path(__file__).resolve().parents[1]/'examples/hamlet.json'


def analysis_response(options,messages):
    payload=json.loads(messages[1]['content'])
    if 'current_line' in payload:
        line=payload['current_line'];previous=payload['previous_score']
        action=previous['action'] if previous else {'target_id':payload['source']['input_scene']['target_id'],
            'desired_change':'Consider a limited comparison.','tactic':'challenge','observable_test':'Response unobserved'}
        return {'line_id':line['id'],'quote':line['text'],'meaning':'Generated meaning of '+line['text'],
            'intention':action['desired_change'],'action':action,
            'transition':{'decision':'retain' if previous else 'initialize','prior_assumption':'','discovery':'','why_action_insufficient':''},
            'evidence':[{'line_id':line['id'],'quote':line['text']}]},{'reported_model':'test-only'}
    task=payload['current_task'];lines=payload['source']['lines']
    stage=task['stage'];data={}
    if stage=='unit':data={'start_line_id':lines[0]['id'],'end_line_id':lines[-1]['id']}
    if stage=='candidates':data={'verbs':['persuade','challenge','invite','reassure']}
    return {'task':task,'items':[{'claim':'Generated '+stage,'kind':'interpretation_hypothesis',
        'evidence':[{'line_id':lines[0]['id'],'quote':lines[0]['text']}]}],'data':data},{'reported_model':'test-only'}


class PreparationTests(TestCase):
    def setup_files(self,folder):
        source=Path(folder)/'source.local.json';raw=json.loads(EXAMPLE.read_text())
        raw['script']=['To die, to sleep—No more—','To die, to sleep—No more—']
        raw['adapters']['reasoner']={'kind':'python','entrypoint':'yuldion.adapters.chat_reasoner:create_reasoner',
                                    'options':provider_options('local')}
        source.write_text(json.dumps(raw));return source

    def test_order_binding_and_sequential_performance_without_media(self):
        from test_pipeline import fixture_response
        with tempfile.TemporaryDirectory() as folder:
            source=self.setup_files(folder);document=Path(folder)/'preparation.json';bound=Path(folder)/'bound.local.json'
            with patch('yuldion.preparation.generate',side_effect=analysis_response):
                doc=prepare(load_config(source),provider_options('local'),document)
            stages=[s['task']['stage'] for s in doc['steps']]
            self.assertEqual(stages[:5],['desire','scene_goal','relationship','circumstances','obstacles'])
            self.assertEqual(stages[-2:],['final_table','performance_review'])
            self.assertFalse(doc['human_approved'])
            self.assertEqual([s['task']['stage'] for s in doc['steps'] if s['status']=='human_validation_pending'],
                             ['body_test','body_selection','user_acts','performance_review'])
            with self.assertRaises(ValueError):validate_document(doc,load_config(source).script,'hamlet')
            bind_config(source,document,bound,allow_draft=True)
            from yuldion.review import run_review,bind_review
            review_path=Path(folder)/'review.json';reviewed=Path(folder)/'reviewed.local.json'
            answer={'checked_line_ids':[line['id'] for line in doc['source']['lines']],'issues':[]}
            with patch('yuldion.review.generate',return_value=(answer,{'reported_model':'test-only'})):
                run_review(document,provider_options('local'),review_path)
            bind_review(bound,review_path,reviewed)
            bound=reviewed
            config=load_config(bound)
            self.assertEqual(config.scene.scene_goal,'Generated scene_goal')
            self.assertEqual(for_segment(config.preparation,config.script,1)['current_line_ids'],['L0002'])
            payloads=[]
            def actor_reply(options,messages):
                payload=json.loads(messages[1]['content']);payloads.append(payload)
                self.assertEqual(payload['prepared_analysis']['document_sha256'],config.preparation['document_sha256'])
                if payload['operation']=='perform':
                    return {'vocal':{'pace':'even','volume':'conversational','pitch':'middle','articulation':'또렷하게 발음한다','stress':[]},'motor':{'gaze':len(payloads)},'pause_ms':0,'breath':False},{'reported_model':'test-only'}
                response=fixture_response(payload)
                if payload['operation']=='propose' and payload['context']['current_action']:
                    response['decision']='retain';response['basis']=['script:1']
                return response,{'reported_model':'test-only'}
            out=Path(folder)/'plans'
            with patch('yuldion.adapters.chat_reasoner.generate',side_effect=actor_reply), \
                 patch('yuldion.config.load_adapters',side_effect=AssertionError('No media adapters')), \
                 redirect_stdout(StringIO()),redirect_stderr(StringIO()):
                self.assertEqual(main(['plan','--config',str(bound),'--output-dir',str(out)]),0)
            result=json.loads((out/'result.json').read_text())
            self.assertEqual(len(result['plans']),2)
            self.assertEqual(result['plans'][0]['plan']['action_id'],result['plans'][1]['plan']['action_id'])
            self.assertTrue(result['plans'][1]['plan']['performance']['delivery'].startswith('속도:'))
            self.assertNotEqual(result['plans'][0]['plan']['performance']['motor'],result['plans'][1]['plan']['performance']['motor'])
            self.assertFalse(result['voice_face_loaded'])
            self.assertEqual(len(payloads),2)
            document.write_text(document.read_text()+' ')
            with self.assertRaises(Exception):load_config(bound)

    def test_failed_or_wrong_source_preparation_cannot_bind(self):
        with tempfile.TemporaryDirectory() as folder:
            source=self.setup_files(folder);document=Path(folder)/'preparation.json'
            with patch('yuldion.preparation.generate',side_effect=analysis_response):
                with self.assertRaises(ValueError):prepare(load_config(source),provider_options('local'),document,max_calls=1)
            self.assertEqual(json.loads(document.read_text())['status'],'failed')
            with self.assertRaises(ValueError):bind_config(source,document,Path(folder)/'bound.local.json',True)

    def test_unprepared_normal_path_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            source=self.setup_files(folder)
            with patch('urllib.request.build_opener') as network,redirect_stderr(StringIO()):
                self.assertEqual(main(['interpret','--config',str(source)]),2)
                self.assertEqual(main(['plan','--config',str(source),'--output-dir',str(Path(folder)/'out')]),2)
            network.assert_not_called()

    def test_prepare_cli_requires_consent_and_rejects_changed_scene(self):
        with tempfile.TemporaryDirectory() as folder:
            source=self.setup_files(folder);out=Path(folder)/'analysis';bound=Path(folder)/'bound.local.json'
            with patch('yuldion.preparation.generate',side_effect=analysis_response),redirect_stdout(StringIO()):
                self.assertEqual(main(['prepare','--config',str(source),'--output-dir',str(out),
                    '--bound-config',str(bound),'--allow-draft']),0)
            self.assertEqual(json.loads((out/'manifest.json').read_text())['status'],'draft_complete')
            raw=json.loads(bound.read_text());raw['scene']['relationship']='Changed input'
            bound.write_text(json.dumps(raw))
            with self.assertRaises(Exception):load_config(bound)

    def test_string_task_is_rejected_and_regenerated_without_advancing(self):
        with tempfile.TemporaryDirectory() as folder:
            source=self.setup_files(folder);out=Path(folder)/'preparation.json'
            calls=[]
            def reply(options,messages):
                payload=json.loads(messages[1]['content']);calls.append(payload)
                answer,receipt=analysis_response(options,messages)
                if len(calls)==1:answer['task']='desire'
                return answer,receipt
            with patch('yuldion.preparation.generate',side_effect=reply):
                doc=prepare(load_config(source),provider_options('local'),out)
            self.assertEqual(calls[0]['current_task'],calls[1]['current_task'])
            self.assertTrue(calls[1]['format_corrections'])
            self.assertIn('validation_error',doc['calls'][0])
            self.assertEqual(doc['steps'][0]['proposal']['task']['stage'],'desire')
            self.assertFalse(doc['human_approved'])

    def test_invalid_task_retries_are_bounded_and_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            source=self.setup_files(folder);out=Path(folder)/'preparation.json'
            def reply(options,messages):
                answer,receipt=analysis_response(options,messages);answer['task']='desire'
                return answer,receipt
            with patch('yuldion.preparation.generate',side_effect=reply):
                with self.assertRaises(ValueError):prepare(load_config(source),provider_options('local'),out)
            doc=json.loads(out.read_text())
            self.assertEqual(len(doc['calls']),3)
            self.assertEqual(doc['steps'],[])
            self.assertEqual(doc['status'],'failed')

    def test_resume_keeps_validated_stages_and_does_not_repeat_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            source=self.setup_files(folder);failed=Path(folder)/'failed.json';resumed=Path(folder)/'resumed.json'
            with patch('yuldion.preparation.generate',side_effect=analysis_response):
                with self.assertRaises(ValueError):prepare(load_config(source),provider_options('local'),failed,max_calls=1)
            before=json.loads(failed.read_text());requests=[]
            def response(options,messages):
                requests.append(json.loads(messages[1]['content']))
                return analysis_response(options,messages)
            with patch('yuldion.preparation.generate',side_effect=response):
                doc=prepare(load_config(source),provider_options('local'),resumed,resume_from=failed)
            self.assertEqual(requests[0]['current_task']['stage'],'scene_goal')
            self.assertEqual(doc['steps'][0],before['steps'][0])
            self.assertEqual(doc['calls'][0],before['calls'][0])
            self.assertEqual(doc['status'],'draft_complete')
            self.assertEqual(len(doc['acting_score']),2)
            self.assertEqual(json.loads(failed.read_text()),before)

    def test_resume_rejects_changed_source_before_model_request(self):
        with tempfile.TemporaryDirectory() as folder:
            source=self.setup_files(folder);failed=Path(folder)/'failed.json'
            with patch('yuldion.preparation.generate',side_effect=analysis_response):
                with self.assertRaises(ValueError):prepare(load_config(source),provider_options('local'),failed,max_calls=1)
            raw=json.loads(source.read_text());raw['script'][0]='Changed source';source.write_text(json.dumps(raw))
            with patch('yuldion.preparation.generate') as model:
                with self.assertRaises(ValueError):prepare(load_config(source),provider_options('local'),Path(folder)/'resume.json',resume_from=failed)
                model.assert_not_called()
