from copy import deepcopy
from threading import Event
from unittest import TestCase
from unittest.mock import Mock
from yuldion.acting_score import check_entry,PreparedReasoner
from yuldion.types import Action,Context,Observation,Scene


def entry():
    return {'line_id':'L0001','quote':'To be','meaning':'존재의 선택을 묻는다','intention':'판단을 재검토하게 한다',
        'action':{'target_id':'self','desired_change':'판단을 재검토하게 한다','tactic':'challenge','observable_test':'unobserved'},
        'transition':{'decision':'initialize','prior_assumption':'','discovery':'','why_action_insufficient':''},
        'evidence':[{'line_id':'L0001','quote':'To be'}]}


class ScoreTest(TestCase):
    def test_runtime_never_reinterprets_or_calls_model_audit(self):
        score=entry();delegate=Mock();delegate.calls=[]
        reasoner=PreparedReasoner(delegate,[score]);scene=Scene('hamlet','goal','goal','given','self','self')
        script=Observation('script:0','authored_script','To be')
        context=Context(scene,'hash',script,(script,),None,None,(),(),(),None,{})
        proposal=reasoner.propose(context,Event());audit=reasoner.audit(context,proposal,Event())
        reasoner.perform(context,proposal.action,proposal.view,True,Event())
        delegate.propose.assert_not_called();delegate.audit.assert_not_called();delegate._call.assert_not_called()
        delegate.perform.assert_called_once()
        self.assertEqual(proposal.view,score['meaning']);self.assertTrue(audit.grounded)
        self.assertIn('structural',audit.note)

    def test_retained_action_cannot_silently_change_intention(self):
        previous=entry();score=deepcopy(previous);score.update(line_id='L0002',quote='To sleep')
        score['transition']['decision']='retain';score['evidence']=[{'line_id':'L0002','quote':'To sleep'}]
        line={'id':'L0002','text':'To sleep'}
        check_entry(score,line,previous,'self')
        score['action']['tactic']='reassure'
        with self.assertRaises(ValueError):check_entry(score,line,previous,'self')

    def test_no_future_line_can_justify_current_action(self):
        score=entry();score['evidence'][0]['line_id']='L0030'
        with self.assertRaises(ValueError):check_entry(score,{'id':'L0001','text':'To be'},None,'self')
