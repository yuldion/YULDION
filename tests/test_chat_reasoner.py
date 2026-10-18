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

    def answer(self):
        return {'decision':'initialize','view':'Death is proposed as an end to disturbance, not established fact.',
                'basis':['script:0'],'action':{'target_id':'self','desired_change':'consider the proposal',
                'tactic':'invite','observable_test':'an actual response if observed'},
                'trigger':{'kind':'none','basis':[],'prior_assumption':'','new_insight':'','why_action_insufficient':''}}

    def test_actual_request_contains_current_line_not_future_script(self):
        reasoner=ChatReasoner({'endpoint':'http://localhost:8000/v1/chat/completions','model':'test'})
        with patch('yuldion.adapters.chat_reasoner.generate',return_value=(self.answer(),{'origin':'test fixture'})) as generate:
            result=reasoner.propose(self.context(),Event())
        self.assertEqual(result.action.target_id,'self')
        self.assertIn('To die, to sleep',generate.call_args.args[1][1]['content'])
        self.assertEqual(reasoner.calls[0]['response'],self.answer())

    def test_invalid_evidence_rejected_and_raw_response_kept(self):
        reasoner=ChatReasoner({}); answer=self.answer();answer['basis']=['future-line']
        with patch('yuldion.adapters.chat_reasoner.generate',return_value=(answer,{})):
            with self.assertRaises(ValueError): reasoner.propose(self.context(),Event())
        self.assertEqual(len(reasoner.calls),1)

    def test_cancellation_never_requests_model(self):
        cancel=Event();cancel.set()
        with patch('yuldion.adapters.chat_reasoner.generate') as generate:
            with self.assertRaises(RuntimeError): ChatReasoner({}).propose(self.context(),cancel)
        generate.assert_not_called()
