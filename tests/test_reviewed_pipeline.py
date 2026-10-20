"""Local fixtures test fail-closed review, typed realization and exact-stage resume."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import tempfile
from unittest import TestCase
from unittest.mock import patch,Mock
from urllib.error import HTTPError
import io
import test_preparation as fixtures
from yuldion.config import load_config
from yuldion.errors import InferenceFailure
from yuldion.planning import run_plans
from yuldion.preparation import prepare,bind_config
from yuldion.providers import provider_options
from yuldion.review import run_review,bind_review
from yuldion.tools.inspector.server import snapshot,worker
from yuldion.vocal import vocal_delivery


def response(options,messages):
    payload=json.loads(messages[1]['content'])
    assert payload['operation']=='perform','Runtime must ONLY realize performance'
    assert 'steps' not in payload['prepared_analysis'] and 'source_lines' not in payload['prepared_analysis']
    assert 'acting_score' not in payload['context']['preparation']
    assert payload['prepared_analysis']['current_score']['quote']==payload['context']['script']['text']
    return {'vocal':{'pace':'even','volume':'conversational','pitch':'middle',
        'articulation':'자음을 명료하게 이어 발음한다','stress':[]},
        'motor':{'gaze':payload['context']['script']['id']},'pause_ms':100,'breath':False},{'reported_model':'test-fixture'}


class ReviewedPipelineTests(TestCase):
    def test_invalid_vocal_is_retried_on_same_line_with_explicit_correction(self):
        with tempfile.TemporaryDirectory() as folder:
            config_path,_,_=self.fixture(folder)
            output=Path(folder)/'plans';output.mkdir();requests=[]
            def reply(options,messages):
                requests.append(messages)
                answer,receipt=response(options,messages)
                if len(requests)==1:answer['vocal']['pace']='firm'
                return answer,receipt
            with patch('yuldion.adapters.chat_reasoner.generate',side_effect=reply):
                done=run_plans(load_config(config_path),provider_options('local'),output,1)
            self.assertEqual(done['status'],'completed')
            self.assertEqual(len(done['calls']),2)
            self.assertEqual(done['calls'][0]['validation_error'],'Invalid vocal pace')
            self.assertIn('firm is a VOLUME only',requests[1][0]['content'])
            self.assertEqual(json.loads(requests[0][1]['content'])['context']['script'],
                             json.loads(requests[1][1]['content'])['context']['script'])

    def test_invalid_shape_retry_is_bounded_and_never_advances_line(self):
        with tempfile.TemporaryDirectory() as folder:
            config_path,_,_=self.fixture(folder)
            output=Path(folder)/'plans';output.mkdir();requests=[]
            def reply(options,messages):
                requests.append(json.loads(messages[1]['content']))
                return {'delivery':'invalid legacy shape'},{}
            with patch('yuldion.adapters.chat_reasoner.generate',side_effect=reply):
                with self.assertRaises(ValueError):
                    run_plans(load_config(config_path),provider_options('local'),output,1)
            self.assertEqual(len(requests),3)
            self.assertEqual(len({r['context']['script']['id'] for r in requests}),1)
            saved=json.loads((output/'result.json').read_text())
            self.assertEqual(saved['plans'],[])
            self.assertEqual(saved['next_segment'],0)
            self.assertEqual(len(saved['calls']),3)

    def test_session_key_reuse_clear_and_instance_isolation(self):
        from yuldion.tools.inspector.server import SessionKey
        key=SessionKey();self.assertFalse(key.available())
        key.set('test-only-placeholder')
        for _ in range(2):
            env={};key.apply(env,'TEST_KEY')
            self.assertEqual(env,{'TEST_KEY':'test-only-placeholder'})
        self.assertFalse(SessionKey().available())
        key.clear();env={};key.apply(env,'TEST_KEY')
        self.assertFalse(key.available());self.assertEqual(env,{})

    def test_extend_completed_prefix_only_calls_new_line(self):
        with tempfile.TemporaryDirectory() as folder:
            config_path,_,_=self.fixture(folder);config=load_config(config_path)
            first=Path(folder)/'first';first.mkdir()
            with patch('yuldion.adapters.chat_reasoner.generate',side_effect=response):
                before=run_plans(config,provider_options('local'),first,1)
            second=Path(folder)/'second';second.mkdir();seen=[]
            def reply(options,messages):
                seen.append(json.loads(messages[1]['content'])['context']['script']['id'])
                return response(options,messages)
            with patch('yuldion.adapters.chat_reasoner.generate',side_effect=reply):
                after=run_plans(config,provider_options('local'),second,2,extend_from=first/'result.json')
            self.assertEqual(seen,['script:1'])
            self.assertEqual(after['plans'][0],before['plans'][0])
            self.assertEqual(after['status'],'completed')

    def test_supervisor_restarts_only_from_recorded_failed_attempt(self):
        from yuldion.tools.inspector.server import supervised_worker,paths
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'job';root.mkdir();seen=[];delays=[]
            def run(config,out,previous):
                seen.append(previous)
                (out/'analysis').mkdir();(out/'plans').mkdir()
                (out/'analysis/preparation.json').write_text(json.dumps({'source':{'lines':[{}]}}))
                if len(seen)==1:
                    record={'status':'failed','plans':[],'failure':{'retryable':True,'category':'http','http_status':429,'retry_after_seconds':2}}
                else:
                    self.assertEqual(previous,root/'attempt-1')
                    record={'status':'completed','plans':[{}]}
                (out/'plans/result.json').write_text(json.dumps(record))
                return 2 if len(seen)==1 else 0
            self.assertEqual(supervised_worker('config',root,run=run,sleep=delays.append),0)
            self.assertEqual(delays,[2]);self.assertEqual(len(seen),2)
            self.assertEqual(Path(paths(root)['performance']),root/'attempt-2/plans/result.json')
            self.assertEqual(json.loads((root/'job.json').read_text())['status'],'finished')

    def test_supervisor_does_not_retry_authentication_or_semantic_findings(self):
        from yuldion.tools.inspector.server import supervised_worker
        for code,status,failure in [(2,'failed',{'category':'http','http_status':401,'retryable':False}),(3,'needs_revision',None)]:
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);seen=[]
                def run(config,out,previous):
                    seen.append(previous);(out/'review').mkdir()
                    (out/'review/review.json').write_text(json.dumps({'status':status,'failure':failure}))
                    return code
                self.assertEqual(supervised_worker('config',root,run=run,sleep=lambda _:self.fail('No retry')),code)
                self.assertEqual(len(seen),1)

    def fixture(self,folder,issues=False):
        source=fixtures.PreparationTests().setup_files(folder);document=Path(folder)/'preparation.json';bound=Path(folder)/'prepared.local.json'
        with patch('yuldion.preparation.generate',side_effect=fixtures.analysis_response):
            doc=prepare(load_config(source),provider_options('local'),document)
        bind_config(source,document,bound,True)
        answer={'checked_line_ids':[l['id'] for l in doc['source']['lines']],'issues':[]}
        if issues:
            answer['issues']=[{'line_id':'L0001','category':'future_knowledge','claim':doc['acting_score'][0]['meaning'],
                'explanation':'Test-only finding','evidence':[{'line_id':'L0001','quote':doc['source']['lines'][0]['text']}]}]
        review=Path(folder)/'review.json'
        with patch('yuldion.review.generate',return_value=(answer,{'reported_model':'test-fixture'})):
            result=run_review(document,provider_options('local'),review)
        if issues:return bound,review,result
        reviewed=Path(folder)/'reviewed.local.json';bind_review(bound,review,reviewed)
        return reviewed,review,result

    def test_flagged_review_cannot_run_or_bind(self):
        from yuldion.acting_score import select_reasoner
        with tempfile.TemporaryDirectory() as folder:
            config_path,review,result=self.fixture(folder,True)
            self.assertEqual(result['status'],'needs_revision')
            with self.assertRaises(ValueError):bind_review(config_path,review,Path(folder)/'invalid.local.json')
            with self.assertRaises(ValueError):select_reasoner(load_config(config_path),Mock())

    def test_failed_performance_resumes_only_failed_line(self):
        with tempfile.TemporaryDirectory() as folder:
            config_path,_,_=self.fixture(folder);config=load_config(config_path)
            first=Path(folder)/'first';first.mkdir()
            count=[]
            def fail_second(options,messages):
                payload=json.loads(messages[1]['content']);count.append(payload['context']['script']['id'])
                if len(count)==2:raise InferenceFailure('http',429,2)
                return response(options,messages)
            with patch('yuldion.adapters.chat_reasoner.generate',side_effect=fail_second):
                with self.assertRaises(InferenceFailure):run_plans(config,provider_options('local'),first,2)
            failed=json.loads((first/'result.json').read_text());self.assertEqual(failed['next_segment'],1)
            self.assertEqual(failed['failure']['http_status'],429);self.assertTrue(failed['failure']['retryable'])
            self.assertEqual(failed['failed_stage']['line_id'],'L0002')
            self.assertEqual(len(failed['plans']),1);self.assertIn('error',failed['calls'][-1])
            second=Path(folder)/'second';second.mkdir();resumed=[]
            def reply(options,messages):
                resumed.append(json.loads(messages[1]['content']));return response(options,messages)
            with patch('yuldion.adapters.chat_reasoner.generate',side_effect=reply),patch('yuldion.preparation.generate',side_effect=AssertionError('No reanalysis')):
                done=run_plans(config,provider_options('local'),second,2,first/'result.json')
            self.assertEqual(done['status'],'completed');self.assertEqual(len(resumed),1)
            self.assertEqual(resumed[0]['context']['script']['id'],'script:1')
            self.assertEqual(resumed[0]['context']['current_action'],failed['plans'][0]['plan']['action'])
            self.assertEqual(done['plans'][0],failed['plans'][0])
            self.assertEqual(done['plans'][0]['plan']['action_id'],done['plans'][1]['plan']['action_id'])
            self.assertNotEqual(done['plans'][0]['plan']['performance']['motor'],done['plans'][1]['plan']['performance']['motor'])
            self.assertFalse(done['voice_face_loaded'])

    def test_review_hash_invalidates_execution_after_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            config_path,review,_=self.fixture(folder);review.write_text(review.read_text()+' ')
            with self.assertRaises(Exception):load_config(config_path)

    def test_partial_coverage_cannot_pass_review(self):
        with tempfile.TemporaryDirectory() as folder:
            config_path,review,_=self.fixture(folder)
            raw=json.loads(config_path.read_text());document=Path(raw['preparation']['path']);output=Path(folder)/'bad-review.json'
            with patch('yuldion.review.generate',return_value=({'checked_line_ids':['L0001'],'issues':[]},{})):
                with self.assertRaises(ValueError):run_review(document,provider_options('local'),output)
            self.assertEqual(json.loads(output.read_text())['status'],'failed')

    def test_vocal_controls_reject_dialogue_as_articulation(self):
        vocal={'pace':'even','volume':'conversational','pitch':'middle','articulation':'To be','stress':[]}
        with self.assertRaises(ValueError):vocal_delivery(vocal,'To be')
        vocal['articulation']='자음의 경계를 분명히 발음';vocal['stress']=['invented phrase']
        with self.assertRaises(ValueError):vocal_delivery(vocal,'To be')

    def test_http_failure_never_retains_response_body_or_secret(self):
        from yuldion.inference import generate
        secret='secret-must-not-be-logged'
        error=HTTPError('https://secret.invalid/',401,'rejected',{},io.BytesIO(secret.encode()))
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(InferenceFailure) as caught:generate(provider_options('local'),[])
        self.assertEqual(caught.exception.http_status,401);self.assertFalse(caught.exception.retryable)
        self.assertNotIn(secret,str(caught.exception))

    def test_observer_keeps_analysis_review_performance_status_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            config_path,review,_=self.fixture(folder,True)
            config=load_config(config_path)
            root=Path(folder)/'observer';root.mkdir()
            raw=json.loads(config_path.read_text())
            (root/'job.json').write_text(json.dumps({'analysis':raw['preparation']['path'],'prepared_config':str(config_path),'review':str(review)}))
            view=snapshot(root)
            self.assertEqual(view['analysis_status'],'completed')
            self.assertEqual(view['structure_status'],'passed')
            self.assertEqual(view['review_status'],'needs_revision')
            self.assertEqual(view['performance_status'],'not_started')
            self.assertEqual(view['media_status'],'not_run')
            self.assertFalse(view['can_start'])
            self.assertTrue(view['review_issues'])

    def test_worker_never_repeats_finished_analysis_after_review_http_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            reviewed,review,_=self.fixture(folder);base=Path(folder)
            raw=json.loads(reviewed.read_text());prior=base/'prior';prior.mkdir()
            failure=base/'failed-review.json';old=json.loads(review.read_text());old.update(status='failed',issues=[],checked_line_ids=[],failure={'http_status':429})
            failure.write_text(json.dumps(old))
            (prior/'job.json').write_text(json.dumps({'analysis':raw['preparation']['path'],
                'prepared_config':str(base/'prepared.local.json'),'review':str(failure)}))
            out=base/'next';out.mkdir();commands=[]
            def cli(args):commands.append(args);return 2
            with patch('yuldion.pipeline.main',side_effect=cli):self.assertEqual(worker(str(base/'source.local.json'),out,prior),2)
            self.assertEqual([c[0] for c in commands],['review'])
            self.assertIn('--resume-from',commands[0])
            job=json.loads((out/'job.json').read_text())
            self.assertEqual(job['analysis'],raw['preparation']['path'])

    def test_worker_only_resumes_performance_when_review_already_passed(self):
        with tempfile.TemporaryDirectory() as folder:
            reviewed,review,_=self.fixture(folder);base=Path(folder);config=load_config(reviewed)
            performance=base/'old-performance';performance.mkdir()
            with patch('yuldion.adapters.chat_reasoner.generate',side_effect=InferenceFailure('http',503)):
                with self.assertRaises(InferenceFailure):run_plans(config,provider_options('local'),performance,2)
            raw=json.loads(reviewed.read_text());prior=base/'prior';prior.mkdir()
            (prior/'job.json').write_text(json.dumps({'analysis':raw['preparation']['path'],'prepared_config':str(base/'prepared.local.json'),
                'review':str(review),'reviewed_config':str(reviewed),'performance':str(performance/'result.json')}))
            out=base/'next';out.mkdir();commands=[]
            with patch('yuldion.pipeline.main',side_effect=lambda args:commands.append(args) or 0):
                self.assertEqual(worker(str(base/'source.local.json'),out,prior),0)
            self.assertEqual([c[0] for c in commands],['plan'])
            self.assertIn('--resume-from',commands[0])

    def test_http_error_records_safe_status_in_review_and_can_retry_review_only(self):
        with tempfile.TemporaryDirectory() as folder:
            reviewed,review,_=self.fixture(folder);raw=json.loads(reviewed.read_text());document=Path(raw['preparation']['path'])
            failed=Path(folder)/'review-failed.json'
            with patch('yuldion.review.generate',side_effect=InferenceFailure('http',429,5)):
                with self.assertRaises(InferenceFailure):run_review(document,provider_options('local'),failed)
            record=json.loads(failed.read_text());self.assertEqual(record['failure']['http_status'],429)
            answer={'checked_line_ids':['L0001','L0002'],'issues':[]};out=Path(folder)/'review-retry.json'
            with patch('yuldion.review.generate',return_value=(answer,{})),patch('yuldion.preparation.generate',side_effect=AssertionError('No reanalysis')):
                done=run_review(document,provider_options('local'),out,failed)
            self.assertEqual(done['status'],'passed');self.assertEqual(len(done['calls']),2)

    def test_review_can_flag_an_analysis_fact_not_only_line_score(self):
        with tempfile.TemporaryDirectory() as folder:
            reviewed,review,_=self.fixture(folder);raw=json.loads(reviewed.read_text());document=Path(raw['preparation']['path']);prep=json.loads(document.read_text())
            answer={'checked_line_ids':['L0001','L0002'],'issues':[{'scope':'analysis','line_id':'L0001',
                'category':'fact_hypothesis_confusion','claim':prep['steps'][0]['proposal']['items'][0]['claim'],
                'explanation':'Test-only provenance check','evidence':[{'line_id':'L0001','quote':prep['source']['lines'][0]['text']}]}]}
            before=document.read_bytes()
            with patch('yuldion.review.generate',return_value=(answer,{})):
                result=run_review(document,provider_options('local'),Path(folder)/'analysis-review.json')
            self.assertEqual(result['status'],'needs_revision');self.assertEqual(document.read_bytes(),before)

    def test_dialogue_returned_as_delivery_cannot_commit_a_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            reviewed,_,_=self.fixture(folder);config=load_config(reviewed);out=Path(folder)/'bad-output';out.mkdir()
            bad={'delivery':config.execution_script[0],'motor':{'gaze':0},'pause_ms':0,'breath':False}
            with patch('yuldion.adapters.chat_reasoner.generate',return_value=(bad,{})):
                with self.assertRaises(ValueError):run_plans(config,provider_options('local'),out,2)
            record=json.loads((out/'result.json').read_text());self.assertEqual(record['plans'],[])
            self.assertEqual(record['next_segment'],0);self.assertIn('validation_error',record['calls'][0])
            repaired=Path(folder)/'fixed-output';repaired.mkdir();payloads=[]
            def reply(options,messages):
                payloads.append(json.loads(messages[1]['content']));return response(options,messages)
            with patch('yuldion.adapters.chat_reasoner.generate',side_effect=reply):
                done=run_plans(config,provider_options('local'),repaired,2,out/'result.json')
            self.assertEqual(done['status'],'completed');self.assertEqual(len(payloads),2)
            self.assertIn('format_correction',payloads[0])
