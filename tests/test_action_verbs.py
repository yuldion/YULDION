from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
from yuldion.tools.action_verbs.core import (prepare, next_task, submit, human_input, review,
                                   rewind, validate, prompt, markdown)
from yuldion.tools.action_verbs.__main__ import main
from yuldion.tools.action_verbs.model import generate

SOURCE = {'character':'Actor','relationship_targets':['Other','Self'],
          'lines':[{'id':'1','text':'Stay here.'},{'id':'2','text':'But why?'},{'id':'3','text':'Listen.'}]}

def answer(state, end=None):
    t = next_task(state)
    data = {}
    if t['stage']=='unit':
        previous=[r['proposal']['data']['end_line_id'] for r in state['reviews'] if r['task']['stage']=='unit']
        ids=[l['id'] for l in SOURCE['lines']]
        data={'start_line_id':ids[ids.index(previous[-1])+1] if previous else '1','end_line_id':end or '3'}
    if t['stage']=='candidates': data={'verbs':['persuade','challenge','invite','reassure']}
    return {'task':t,'items':[{'claim':'Provisional analysis','kind':'interpretation_hypothesis',
                              'evidence':[{'line_id':'1','quote':'Stay'}]}],'data':data}

def advance(state, end=None):
    if next_task(state)['human_input']: human_input(state,'I tried this and recorded my observation.')
    else: submit(state,answer(state,end),{'origin':'test fixture only'})
    review(state,True)

class WorkflowTest(unittest.TestCase):
    def test_full_two_unit_workflow_and_gates(self):
        s=prepare(SOURCE); seen=[]
        while next_task(s):
            t=next_task(s); seen.append((t['stage'],t['unit'],t['target']))
            if t['human_input']:
                with self.assertRaises(ValueError): prompt(s)
                with self.assertRaises(ValueError): submit(s,answer(s),{})
            advance(s,'1' if t['stage']=='unit' and t['unit']==1 else None)
            validate(s)
        self.assertEqual(seen[:4],[('desire',None,None),('scene_goal',None,None),
                                  ('relationship',None,'Other'),('relationship',None,'Self')])
        self.assertLess(seen.index(('candidates',2,None)),seen.index(('goal_fit',1,None)))
        self.assertLess(seen.index(('target_selection',2,None)),seen.index(('script_acts',1,None)))
        self.assertEqual(seen[-1][0],'performance_review')
        self.assertIn('완료',markdown(s))

    def test_pending_reject_edit_and_no_skip(self):
        s=prepare(SOURCE)
        with self.assertRaises(ValueError): review(s,True)
        bad=answer(s); bad['task']['stage']='scene_goal'
        with self.assertRaises(ValueError): submit(s,bad,{})
        submit(s,answer(s),{})
        with self.assertRaises(ValueError): submit(s,answer(s),{})
        with self.assertRaises(ValueError): prompt(s)
        review(s,False); self.assertEqual(next_task(s)['stage'],'desire')
        submit(s,answer(s),{}); edited=answer(s); edited['items'][0]['claim']='Human correction'
        review(s,True,edited)
        self.assertTrue(s['reviews'][0]['human_edited'])
        self.assertEqual(s['history'][0]['status'],'rejected')

    def test_bad_quote_duplicate_items_and_bad_candidates(self):
        s=prepare(SOURCE); a=answer(s); a['items'][0]['evidence'][0]['quote']='invented'
        with self.assertRaises(ValueError): submit(s,a,{})
        a=answer(s); a['items']*=2
        with self.assertRaises(ValueError): submit(s,a,{})
        while next_task(s)['stage']!='candidates': advance(s)
        a=answer(s); a['data']['verbs']=['sad']
        with self.assertRaises(ValueError): submit(s,a,{})

    def test_units_no_gaps_and_rewind_invalidates_downstream(self):
        s=prepare(SOURCE)
        while next_task(s)['stage']!='unit': advance(s)
        a=answer(s); a['data']['start_line_id']='2'
        with self.assertRaises(ValueError): submit(s,a,{})
        advance(s,'1'); advance(s)
        count=len(s['reviews']); rewind(s,count-2)
        self.assertEqual(next_task(s)['unit'],1)
        self.assertEqual(len(s['history'][-1]['invalidated']),2)
        advance(s); self.assertEqual(next_task(s)['stage'],'units_summary')

    def test_human_input_still_needs_separate_approval(self):
        s=prepare(SOURCE)
        while next_task(s)['stage']!='body_test': advance(s)
        human_input(s,'The second verb felt physically unclear.')
        self.assertEqual(next_task(s)['stage'],'body_test')
        self.assertEqual(s['pending']['proposal']['items'][0]['kind'],'user_input')
        review(s,True); self.assertEqual(next_task(s)['stage'],'body_selection')

    def test_source_and_order_tampering(self):
        s=prepare(SOURCE); advance(s)
        broken=deepcopy(s); broken['source']['lines'][0]['text']='altered'
        with self.assertRaises(ValueError): validate(broken)
        broken=deepcopy(s); broken['reviews'][0]['task']['stage']='unit'
        with self.assertRaises(ValueError): validate(broken)

    def test_cli_offline_review_export_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            root=Path(folder); source=root/'script.json'; state=root/'state.json'; proposal=root/'proposal.json'; out=root/'analysis.md'
            source.write_text(json.dumps(SOURCE))
            self.assertEqual(main(['init','--script',str(source),'--state',str(state)]),0)
            self.assertEqual(main(['init','--script',str(source),'--state',str(state)]),2)
            proposal.write_text(json.dumps(answer(json.loads(state.read_text()))))
            self.assertEqual(main(['propose','--state',str(state),'--proposal-file',str(proposal)]),0)
            self.assertEqual(main(['review','--state',str(state),'--approve']),0)
            self.assertEqual(main(['export','--state',str(state),'--output',str(out)]),0)
            self.assertEqual(main(['export','--state',str(state),'--output',str(out)]),2)
            self.assertIn('미완료',out.read_text())

    def test_endpoint_blocks_secret_url_and_non_tls_remote(self):
        for endpoint in ['http://remote.example/v1','https://user:secret@example.com/v1','https://example.com/v1?key=secret']:
            with self.assertRaises(ValueError): generate({'endpoint':endpoint,'model':'test'},[])

    def test_model_transport_payload_and_receipt_without_real_network(self):
        packet={'model':'test','choices':[{'message':{'content':json.dumps(answer(prepare(SOURCE)))}}],'usage':{'total_tokens':12}}
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value=json.dumps(packet).encode()
            result,receipt=generate({'endpoint':'http://localhost:8000/v1/chat/completions','model':'test'},[{'role':'user','content':'data'}])
            self.assertEqual(result['task']['stage'],'desire')
            self.assertEqual(receipt['usage']['total_tokens'],12)
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(json.loads(request.data)['model'],'test')
