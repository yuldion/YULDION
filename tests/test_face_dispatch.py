"""CPU contract fixtures, not face-model inference or visual verification."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from test_engine import FakeReasoner,FakeVoice,FakeFace,SCENE,ACTION
from yuldion.config import Config
from yuldion.engine import Engine
from yuldion.errors import ContractError
from yuldion.face_capabilities import inspect_motor
from yuldion.types import Adapters,Plan,Performance


class FaceDispatchTests(unittest.TestCase):
    def test_attention_target_is_preserved_without_invented_coordinates(self):
        plan=Plan('p','s','a',ACTION,False,'view',Performance('delivery',{'gaze':{'target':'internal_judge','focus':.8}}))
        report=inspect_motor(FakeFace(),plan)
        self.assertEqual(report['controls']['gaze.target']['requested'],'internal_judge')
        self.assertEqual(report['controls']['gaze.target']['status'],'unknown')
        self.assertIsNone(report['controls']['gaze.target']['delivered_value'])
        self.assertFalse(report['controls']['gaze.target']['effect_verified'])
        self.assertEqual(set(report['controls']),{'gaze.target','gaze.focus'})

    def test_neutral_zero_control_is_not_silently_treated_as_no_request(self):
        class Face:
            def capabilities(self):return {'schema_version':1,'controls':{'gaze_x':{'status':'unsupported'}}}
        plan=Plan('p','s','a',ACTION,False,'view',Performance('delivery',{'gaze_x':0}))
        report=inspect_motor(Face(),plan)
        self.assertEqual(report['unsupported'],['gaze_x']);self.assertTrue(report['controls']['gaze_x']['active'])

    def test_declared_unsupported_motor_stops_before_audio_generation(self):
        class Face(FakeFace):
            def capabilities(self):return {'schema_version':1,'controls':{'gaze_x':{'status':'unsupported'}}}
        with TemporaryDirectory() as folder:
            voice=FakeVoice();engine=Engine(Config(SCENE,('line',),{},Path(folder)),Adapters(FakeReasoner(),voice,Face()))
            with self.assertRaises(ContractError):engine.run()
            self.assertEqual(voice.calls,[])

    def test_hamlet_face_port_accepts_engine_complete_utterance_without_external_hook(self):
        from unittest.mock import patch
        from yuldion.adapters.hamlet_face import HamletFace
        from test_hamlet_face_port import Backend,manifest
        class Reasoner(FakeReasoner):
            def perform(self,context,action,view,changed,cancel):
                return Performance('test-only delivery',{'head':{'yaw_deg':2.},'gaze':{'target':'partner'}})
        face=HamletFace({'enabled':True,'backend_factory':'cpu_fixture:create','manifest':manifest(),
                         'allow_experimental':True,'target_positions_m':{'partner':[.3,0.,2.]}})
        backend=Backend();received=[]
        with TemporaryDirectory() as folder:
            engine=Engine(Config(SCENE,('line',),{},Path(folder)),Adapters(Reasoner(),FakeVoice(),face))
            with patch('yuldion.adapters.hamlet_face.import_module') as module:
                module.return_value.create.return_value=backend
                out=engine.run_streaming(lambda chunk,start,cancel:received.append(start))
            self.assertEqual(received,[0,16])
            self.assertEqual(len(backend.calls),1)
            self.assertEqual(len(list((out/'frames').glob('*.png'))),1)
            events=[json.loads(line) for line in (out/'events.jsonl').read_text().splitlines()]
            proof=next(e['payload'] for e in events if e['type']=='face.controls.receipt')
            self.assertFalse(proof['receipt']['effect_verified'])
            self.assertEqual(proof['sample_start'],0)

    def test_utterance_context_batches_face_without_delaying_pcm_sink(self):
        class Face(FakeFace):
            def capabilities(self):return {'schema_version':1,'audio_context':'utterance','controls':{}}
        face=Face();received=[]
        with TemporaryDirectory() as folder:
            engine=Engine(Config(SCENE,('first','second'),{},Path(folder)),Adapters(FakeReasoner(),FakeVoice(),face))
            out=engine.run_streaming(lambda chunk,start,cancel:received.append(start))
            self.assertEqual(received,[0,16,32,48])
            self.assertEqual([r.global_sample_start for r in face.calls],[0,32])
            self.assertEqual([r.audio.sample_start for r in face.calls],[0,0])
            self.assertTrue(all(r.audio_complete for r in face.calls))
            self.assertEqual([len(r.audio.pcm_f32le)//4 for r in face.calls],[32,32])
            events=[json.loads(line) for line in (out/'events.jsonl').read_text().splitlines()]
            ready=[e for e in events if e['type']=='face.utterance_ready']
            sinks=[e for e in events if e['type']=='audio.sink_delivered']
            self.assertEqual(len(ready),2)
            self.assertLess(sinks[1]['sequence'],ready[0]['sequence'])

    def test_request_report_and_backend_receipt_keep_common_sample_clock(self):
        face=FakeFace()
        with TemporaryDirectory() as folder:
            engine=Engine(Config(SCENE,('line',),{},Path(folder)),Adapters(FakeReasoner(),FakeVoice(),face))
            out=engine.run_streaming(lambda *args:None)
            self.assertEqual([r.global_sample_start for r in face.calls],[0,16])
            self.assertTrue(all(r.control_report['plan_id']==r.plan.id for r in face.calls))
            events=[json.loads(line) for line in (out/'events.jsonl').read_text().splitlines()]
            receipts=[e for e in events if e['type']=='face.controls.receipt']
            self.assertEqual([e['payload']['sample_start'] for e in receipts],[0,16])
            self.assertTrue(all('not verified' in e['payload']['scope'] for e in receipts))
