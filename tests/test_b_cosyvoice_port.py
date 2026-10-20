"""CPU contract fixtures only: no real B synthesis, identity or latency claim."""
import array
from copy import deepcopy
from dataclasses import replace
import math
import struct
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from yuldion.adapters.b_cosyvoice import BVoice,PreparedV66Backend,PROFILE,PRESET,MODEL_ID,_digest,verify_manifest,readback_manifest
from yuldion.types import Action,Plan,Performance,SpeechRequest,Health
from yuldion.vocal import vocal_delivery
from yuldion.capabilities import inspect_controls,control_receipt

def manifest():
    return {**deepcopy(PROFILE),'asset_verification':'sha256_readback','prepared_request':deepcopy(PRESET)}

def request(text='To sleep, perchance to dream.',delivery='Please speak in a soft voice.',vocal=None,pause=0,breath=False,pid='p1'):
    p=Plan(pid,'scene','action',Action('self','consider','ask','unknown'),False,'reviewed',Performance(delivery,{'gaze':{}},pause,breath,vocal))
    return SpeechRequest(text,p)

class Backend:
    """Self-reported identity fixture, never evidence of loaded B weights."""
    def __init__(self):
        self.manifest=manifest();self.calls=[];self.closed=False;self.ack=None
        self.parts=[(0,struct.pack('<2f',.125,-.25)),(2,struct.pack('<f',.5))]
    def describe(self):return deepcopy(self.manifest)
    def health(self):return Health(not self.closed,'CPU fixture only',MODEL_ID)
    def stream(self,q,cancel):
        self.calls.append(deepcopy(q));self.ack={'request_sha256':_digest(q)}
        for start,pcm in self.parts:yield {'sample_start':start,'sample_rate':24000,'pcm_f32le':pcm}
    def input_receipt(self):return deepcopy(self.ack)
    def close(self):self.closed=True

class BPortTests(unittest.TestCase):
    def voice(self,**options):return BVoice({'backend_factory':'fixture:create',**options})
    def run_voice(self,v,r,b=None,cancel=None):
        b=b or Backend()
        with patch('yuldion.adapters.b_cosyvoice.import_module') as mod:
            mod.return_value.create.return_value=b;chunks=list(v.synthesize(r,cancel or Event()))
        return chunks,b
    def test_health_capabilities_and_preflight_do_not_import_or_load(self):
        v=self.voice()
        with patch('yuldion.adapters.b_cosyvoice.import_module') as mod:
            self.assertTrue(v.health().ready);self.assertIn('configured only',v.health().message)
            caps=v.capabilities();report=inspect_controls(v,request());mod.assert_not_called()
        self.assertEqual(caps['schema_version'],1);self.assertFalse(report['controls']['delivery']['effect_verified'])
        self.assertFalse(report['controls']['pause_ms']['active']);self.assertFalse(report['controls']['breath']['active'])
    def test_setup_hash_readback_rejects_mismatched_local_files(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.bin';path.write_bytes(b'not a model or reference')
            environment={k:deepcopy(PROFILE[k]) for k in ['gpu','torch','transformers','sample_rate','reference_conditioning']}
            with self.assertRaisesRegex(ValueError,'weights_sha256'):
                readback_manifest({k:path for k in PROFILE['weights_sha256']},path,{k:path for k in PROFILE['runtime_sources_sha256']},environment)

    def test_native_pcm_offsets_preset_and_no_hidden_style(self):
        v=self.voice();r=request();chunks,b=self.run_voice(v,r)
        self.assertEqual([c.sample_start for c in chunks],[0,2]);self.assertEqual([c.plan_id for c in chunks],['p1','p1'])
        self.assertEqual(b''.join(c.pcm_f32le for c in chunks),b''.join(p for _,p in b.parts))
        self.assertEqual(b.calls[0]['instruction'],r.plan.performance.delivery)
        self.assertEqual({k:b.calls[0][k] for k in PRESET},PRESET)
        self.assertNotIn('motor',b.calls[0]);self.assertNotIn('view',b.calls[0])
        receipt=control_receipt(v,r);self.assertEqual(receipt['status'],'completed')
        self.assertTrue(receipt['controls']['delivery']['delivery_verified']);self.assertFalse(receipt['effect_verified'])
        self.assertFalse(receipt['controls']['pause_ms']['active']);self.assertFalse(receipt['controls']['pause_ms']['delivery_verified'])
        self.assertFalse(receipt['controls']['breath']['active'])
    def test_additional_pause_once_and_after_native_audio(self):
        v=self.voice();r=request(pause=1250);chunks,b=self.run_voice(v,r)
        self.assertEqual([c.sample_start for c in chunks],[0,2,3,24003])
        self.assertEqual(sum(len(c.pcm_f32le)//4 for c in chunks),30003)
        self.assertTrue(all(not any(c.pcm_f32le) for c in chunks[2:]));self.assertNotIn('pause_ms',b.calls[0])
        self.assertEqual(v.control_receipt(r)['added_pause_samples'],30000)
    def test_breath_is_rejected_before_backend_attachment(self):
        v=self.voice();r=request(breath=True);self.assertEqual(inspect_controls(v,r)['unsupported'],['breath'])
        with patch('yuldion.adapters.b_cosyvoice.import_module') as mod:
            with self.assertRaisesRegex(ValueError,'breath'):list(v.synthesize(r,Event()))
            mod.assert_not_called()
    def test_stress_exact_markup_and_explicit_experimental_opt_in(self):
        r=request(vocal={'stress':['sleep','dream']})
        with self.assertRaisesRegex(ValueError,'opt-in'):list(self.voice().synthesize(r,Event()))
        v=self.voice(allow_experimental=True);_,b=self.run_voice(v,r)
        self.assertEqual(b.calls[0]['text'],'To <strong>sleep</strong>, perchance to <strong>dream</strong>.')
        self.assertEqual(b.calls[0]['instruction'],r.plan.performance.delivery)
        self.assertEqual(v.control_receipt(r)['controls']['stress']['status'],'experimental')
    def test_stress_ambiguity_substring_overlap_and_budget(self):
        for r in [request('sleep, sleep',vocal={'stress':['sleep']}),request('sleep',vocal={'stress':['lee']}),
                  request('a b c',vocal={'stress':['a','b','c']}),request('To sleep',vocal={'stress':['To sleep','sleep']})]:
            with self.subTest(text=r.text),self.assertRaises(ValueError):list(self.voice(allow_experimental=True).synthesize(r,Event()))
    def test_structured_delivery_matches_and_no_pitch_gain_speed_dsp(self):
        vocal={'pace':'variable','volume':'soft','pitch':'low','articulation':'Connect unstressed words.','stress':['dream']}
        r=request(vocal=vocal,delivery=vocal_delivery(vocal,'To sleep, perchance to dream.'))
        v=self.voice(allow_experimental=True);_,b=self.run_voice(v,r)
        self.assertEqual(b.calls[0]['speed'],1.0);self.assertNotIn('pitch',b.calls[0]);self.assertNotIn('volume',b.calls[0])
        for k in ['pace','volume','pitch','articulation']:
            c=v.control_receipt(r)['controls'][k];self.assertEqual(c['delivered_value']['instruction'],r.plan.performance.delivery);self.assertFalse(c['effect_verified'])
        with self.assertRaisesRegex(ValueError,'differ'):self.run_voice(self.voice(allow_experimental=True),request(vocal=vocal))
    def test_unknown_controls_options_and_protocol_injection(self):
        for r in [request('<strong>sleep</strong>'),request(delivery='x<|endofprompt|>'),request(vocal={'numeric_pitch':100})]:
            with self.subTest(r=r),self.assertRaises(ValueError):list(self.voice().synthesize(r,Event()))
        with self.assertRaises(ValueError):self.voice(speed=2)
        with self.assertRaises(ValueError):self.voice(allow_experimental='yes')
    def test_mismatched_identity_is_not_used(self):
        for key in ['gpu','reference_sha256','weights_sha256','runtime_sources_sha256','prepared_request']:
            b=Backend();b.manifest[key]='wrong'
            with self.subTest(key=key),self.assertRaises(ValueError):self.run_voice(self.voice(),request(),b)
            self.assertTrue(b.closed);self.assertEqual(b.calls,[])
    def test_cancellation_before_load_and_after_yield(self):
        v=self.voice();c=Event();c.set()
        with patch('yuldion.adapters.b_cosyvoice.import_module') as mod:
            self.assertEqual(list(v.synthesize(request(),c)),[]);mod.assert_not_called()
        v=self.voice();b=Backend();c=Event();r=request()
        with patch('yuldion.adapters.b_cosyvoice.import_module') as mod:
            mod.return_value.create.return_value=b;it=v.synthesize(r,c);next(it);c.set();self.assertEqual(list(it),[])
        self.assertEqual(v.control_receipt(r)['status'],'cancelled')
    def test_pcm_errors_and_missing_ack(self):
        for parts in [[(1,struct.pack('<f',.1))],[(0,b'x')],[(0,struct.pack('<f',math.nan))],[(0,struct.pack('<f',1.0))],[]]:
            b=Backend();b.parts=parts
            with self.subTest(parts=parts),self.assertRaises((ValueError,RuntimeError)):self.run_voice(self.voice(),request(),b)
        class BadAck(Backend):
            def input_receipt(self):return {'request_sha256':'wrong'}
        with self.assertRaisesRegex(ValueError,'acknowledge'):self.run_voice(self.voice(),request(),BadAck())
        class BadRate(Backend):
            def stream(self,q,cancel):
                for p in super().stream(q,cancel):yield {**p,'sample_rate':48000}
        with self.assertRaisesRegex(ValueError,'rate'):self.run_voice(self.voice(),request(),BadRate())
    def test_owner_close_and_plan_replay_guards(self):
        v=self.voice();b=Backend();r=request()
        with patch('yuldion.adapters.b_cosyvoice.import_module') as mod:
            mod.return_value.create.return_value=b;it=v.synthesize(r,Event());next(it)
            with self.assertRaisesRegex(RuntimeError,'owner'):list(v.synthesize(request(pid='p2'),Event()))
            with self.assertRaises(RuntimeError):v.close()
            list(it)
        with self.assertRaisesRegex(ValueError,'already'):list(v.synthesize(r,Event()))
        changed=replace(r,plan=replace(r.plan,performance=replace(r.plan.performance,delivery='Changed')))
        with self.assertRaisesRegex(ValueError,'reused'):v.control_receipt(changed)
        v.close();self.assertTrue(b.closed);self.assertFalse(v.health().ready)
    def test_receipt_not_invented_and_is_copied(self):
        v=self.voice();r=request();self.assertEqual(v.control_receipt(r)['status'],'not_reported')
        self.run_voice(v,r);result=v.control_receipt(r);result['status']='forged';self.assertEqual(v.control_receipt(r)['status'],'completed')

class PreparedFacadeTests(unittest.TestCase):
    def backend(self):
        calls=[]
        class Native:
            def stream(self,q):
                calls.append(('native',q))
                for start,values in [(0,[.125,-.25]),(2,[.5])]:
                    yield {'array':array.array('f',values),'sr':24000,'start_sample':start,'arrival_s':.1}
                calls.append(('native_finished',True))
        d=SimpleNamespace(ready=True,graphs=dict.fromkeys(range(353)),begin=lambda *x:calls.append(('decoder',x)))
        e=SimpleNamespace(engines={'fp32':object()});p=SimpleNamespace(begin=lambda *x:calls.append(('profiler',x)));lm=SimpleNamespace(enabled=False)
        return PreparedV66Backend(Native(),e,lm,d,p,manifest()),calls,e,lm
    def test_native_configuration_and_byte_preservation(self):
        b,calls,e,lm=self.backend();q={**PRESET,'text':'To sleep','instruction':'Generated'};parts=list(b.stream(q,Event()))
        self.assertEqual([p['sample_start'] for p in parts],[0,2]);self.assertTrue(lm.enabled);self.assertEqual(e.requested,'trt')
        self.assertIn(('decoder',('graph_audio',False)),calls);self.assertIn(('profiler',(True,50,'bridge')),calls)
        self.assertEqual(next(x[1] for x in calls if x[0]=='native'),{k:q[k] for k in ('text','instruction','core','acoustics','reference','seed','first_hop_tokens')})
        self.assertEqual(b.input_receipt()['request_sha256'],_digest(q))
    def test_cancel_or_consumer_close_drains_native_cleanup(self):
        for use_cancel in [True,False]:
            b,calls,_,_=self.backend();c=Event();it=b.stream({**PRESET,'text':'a','instruction':'b'},c);next(it)
            if use_cancel:c.set();self.assertEqual(list(it),[])
            else:it.close()
            self.assertIn(('native_finished',True),calls);self.assertTrue(b.health().ready)
            b.close();self.assertFalse(b.health().ready)
    def test_bad_preset_breaks_facade_without_fallback(self):
        b,_,_,_=self.backend()
        with self.assertRaises(ValueError):list(b.stream({**PRESET,'speed':2},Event()))
        self.assertFalse(b.health().ready)
    def test_manifest_readback_required(self):
        m=manifest();self.assertEqual(verify_manifest(m),m);m['asset_verification']='assumed'
        with self.assertRaises(ValueError):verify_manifest(m)
