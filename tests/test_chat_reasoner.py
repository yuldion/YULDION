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
        return {'observations':[{'quote':'To die','reading':'A possible ending is proposed.'},
                                {'quote':'to sleep','reading':'Sleep is used as a comparison.'},
                                {'quote':'No more','reading':'The preceding comparison is provisionally limited.'}],
                'relations':[{'earlier_quote':'To die','later_quote':'to sleep',
                              'effect':'The following words compare the proposed ending to sleep.',
                              'not_established':'The comparison is not established as a fact.'},
                             {'earlier_quote':'to sleep','later_quote':'No more',
                              'effect':'The final words provisionally limit what is added to the comparison.',
                              'not_established':'The full scope of the ellipsis is uncertain.'}],
                'not_established':'Death is not proved to be sleep.'}

    def answer(self):
        return {'decision':'initialize','view':'to sleep is proposed as an end to disturbance, not established fact.',
                'textual_support':[{'quote':item['quote'],'interpretation':item['reading'],
                                    'intention_link':'This supports the target considering the limited proposal.'}
                                   for item in self.reading()['observations']],
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
        second=generate.call_args_list[1].args[1][1]['content']
        self.assertNotIn('seek grounds',second)
        self.assertNotIn('consider relief',second)
        options=generate.call_args_list[0].args[0]
        quotes=[item['properties']['quote']['const'] for item in
                options['response_schema']['properties']['observations']['prefixItems']]
        self.assertEqual(set(quotes),{'To die','to sleep','No more'})

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
            else:a['textual_support'][0]['intention_link']=''
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

    def test_prepared_goal_copy_is_rejected(self):
        a=self.answer();a['action']['desired_change']=self.context().scene.scene_goal
        with patch('yuldion.adapters.chat_reasoner.generate',side_effect=[(self.reading(),{}),(a,{})]):
            with self.assertRaisesRegex(ValueError,'prepared scene goal'):
                ChatReasoner({}).propose(self.context(),Event())

    def test_local_timeout_is_bounded(self):
        from yuldion.inference import generate
        for timeout in (0,181,float('nan'),True):
            with self.assertRaises(ValueError):
                generate({'endpoint':'http://localhost:8000/v1/chat/completions',
                          'model':'test','request_timeout_seconds':timeout},[])

    def test_final_clause_cannot_be_omitted(self):
        reading=self.reading();reading['observations'].pop()
        with patch('yuldion.adapters.chat_reasoner.generate',return_value=(reading,{})) as generate:
            with self.assertRaises(ValueError):ChatReasoner({}).propose(self.context(),Event())
        self.assertEqual(generate.call_count,1)

    def test_reversed_relation_and_missing_final_support_are_rejected(self):
        reading=self.reading();reading['relations'][1]['earlier_quote']='No more'
        with patch('yuldion.adapters.chat_reasoner.generate',return_value=(reading,{})):
            with self.assertRaises(ValueError):ChatReasoner({}).propose(self.context(),Event())
        answer=self.answer();answer['textual_support'].pop()
        with patch('yuldion.adapters.chat_reasoner.generate',side_effect=[(self.reading(),{}),(answer,{})]):
            with self.assertRaises(ValueError):ChatReasoner({}).propose(self.context(),Event())

    def test_five_line_current_fragment_covers_every_line_and_intention_link(self):
        from dataclasses import replace
        from yuldion.types import Observation
        fragment='First question\nSecond alternative\nThird consequence\nFourth obstacle\nFifth uncertainty'
        context=self.context()
        script=Observation('script:0','authored_script',fragment)
        context=replace(context,script=script,evidence=(*context.evidence[:-1],script))
        quotes=fragment.splitlines()
        reading={'observations':[{'quote':q,'reading':'Provisional meaning of '+q} for q in quotes],
            'relations':[{'earlier_quote':a,'later_quote':b,'effect':'Continues the inquiry',
                          'not_established':'No resolution established'} for a,b in zip(quotes,quotes[1:])],
            'not_established':'No chosen outcome'}
        answer=self.answer()
        answer['textual_support']=[{'quote':q,'interpretation':'Provisional reading',
                                   'intention_link':'Invites consideration of this possibility'} for q in quotes]
        with patch('yuldion.adapters.chat_reasoner.generate',side_effect=[(reading,{}),(answer,{})]) as generate:
            result=ChatReasoner({}).propose(context,Event())
        self.assertEqual(result.decision,'initialize')
        schema=generate.call_args_list[0].args[0]['response_schema']['properties']['observations']
        self.assertEqual(schema['maxItems'],5)
