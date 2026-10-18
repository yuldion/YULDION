from dataclasses import asdict
from threading import Event
from unittest import TestCase
from unittest.mock import patch
from yuldion.adapters.chat_reasoner import ChatReasoner
from yuldion.types import Scene, Observation, Context

class ChatReasonerTest(TestCase):
    def context(self):
        scene=Scene('hamlet','seek grounds','consider relief','uncertain','self','self-address')
        line=Observation('script:0','authored_script','To die, to sleep—No more—')
        return Context(scene,'hash',line,(line,),None,None,(),(),(),None,{})

    def reading(self):
        return {'observations':[{'quote':'to sleep','reading':'Sleep is suggested as relief.'}],
                'not_established':'Death is not proved to be sleep.'}

    def answer(self):
        return {'decision':'initialize','view':'to sleep is proposed as an end to disturbance, not established fact.',
                'textual_support':[{'quote':'to sleep','interpretation':'Sleep is suggested as relief.',
                                    'intended_change':'consider the proposal'}],
                'basis':['script:0'],'action':{'target_id':'self','desired_change':'consider the proposal',
                'tactic':'invite','observable_test':'an actual response if observed'},
                'trigger':{'kind':'none','basis':[],'prior_assumption':'','new_insight':'','why_action_insufficient':''}}

    def test_actual_request_contains_current_line_not_future_script(self):
        reasoner=ChatReasoner({'endpoint':'http://localhost:8000/v1/chat/completions','model':'test'})
        with patch('yuldion.adapters.chat_reasoner.generate',side_effect=[(self.reading(),{}),(self.answer(),{'origin':'test fixture'})]) as generate:
            result=reasoner.propose(self.context(),Event())
        self.assertEqual(result.action.target_id,'self')
        self.assertIn('To die, to sleep',generate.call_args.args[1][1]['content'])
        self.assertEqual(reasoner.calls[1]['response'],self.answer())
        first=generate.call_args_list[0].args[1][1]['content']
        self.assertNotIn('seek grounds',first)
        self.assertNotIn('scene_goal',first)
        self.assertNotIn('self-address',first)

    def test_invalid_evidence_rejected_and_raw_response_kept(self):
        reasoner=ChatReasoner({}); answer=self.answer();answer['basis']=['future-line']
        with patch('yuldion.adapters.chat_reasoner.generate',side_effect=[(self.reading(),{}),(answer,{})]):
            with self.assertRaises(ValueError): reasoner.propose(self.context(),Event())
        self.assertEqual(len(reasoner.calls),2)

    def test_cancellation_never_requests_model(self):
        cancel=Event();cancel.set()
        with patch('yuldion.adapters.chat_reasoner.generate') as generate:
            with self.assertRaises(RuntimeError): ChatReasoner({}).propose(self.context(),cancel)
        generate.assert_not_called()

    def test_invented_quote_rejected_before_scene_conditioned_generation(self):
        reading=self.reading();reading['observations'][0]['quote']='there is a dream'
        reasoner=ChatReasoner({})
        with patch('yuldion.adapters.chat_reasoner.generate',return_value=(reading,{})) as generate:
            with self.assertRaises(ValueError): reasoner.propose(self.context(),Event())
        self.assertEqual(generate.call_count,1)

    def test_quote_only_view_and_disconnected_intention_are_rejected(self):
        for field in ('view','intention'):
            a=self.answer()
            if field=='view':a['view']=self.context().script.text
            else:a['textual_support'][0]['intended_change']='unrelated goal'
            with patch('yuldion.adapters.chat_reasoner.generate',side_effect=[(self.reading(),{}),(a,{})]):
                with self.assertRaises(ValueError):ChatReasoner({}).propose(self.context(),Event())

    def test_audit_receives_exact_reading_and_support_without_changing_verdict(self):
        verdict={'grounded':False,'genuinely_new':False,'action_change_necessary':False,'note':'Unsupported inference.'}
        reasoner=ChatReasoner({})
        with patch('yuldion.adapters.chat_reasoner.generate',side_effect=[(self.reading(),{}),(self.answer(),{}),(verdict,{})]) as generate:
            proposal=reasoner.propose(self.context(),Event())
            audit=reasoner.audit(self.context(),proposal,Event())
        self.assertFalse(audit.grounded)
        payload=__import__('json').loads(generate.call_args.args[1][1]['content'])
        self.assertEqual(payload['text_reading'],self.reading())
        self.assertEqual(payload['textual_support'],self.answer()['textual_support'])
