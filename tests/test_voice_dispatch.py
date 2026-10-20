"""CPU-only contract tests; no synthesis, GPU, speaker or perceptual validation."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from test_engine import FakeReasoner,FakeVoice,FakeFace,SCENE
from yuldion.config import Config
from yuldion.engine import Engine
from yuldion.errors import ContractError
from yuldion.types import Adapters
from yuldion.streaming import FaceConsumer


class DispatchTests(unittest.TestCase):
    def test_slow_face_does_not_block_next_audio_chunk(self):
        second_pcm=Event();entered=Event()
        class SlowFace(FakeFace):
            def render(self,request,cancel):
                entered.set()
                if not second_pcm.wait(2):raise AssertionError('Audio waited on face')
                yield from super().render(request,cancel)
        class Voice(FakeVoice):
            def synthesize(self,request,cancel):
                for index,chunk in enumerate(super().synthesize(request,cancel)):
                    if index and not entered.wait(2):raise AssertionError('Face consumer never started')
                    yield chunk
        received=[]
        def sink(chunk,start,cancel):
            received.append((chunk,start))
            if len(received)==2:second_pcm.set()
        with TemporaryDirectory() as folder:
            engine=Engine(Config(SCENE,('test line',),{},Path(folder)),Adapters(FakeReasoner(),Voice(),SlowFace()))
            out=engine.run_streaming(sink)
            self.assertEqual([start for _,start in received],[0,16])
            self.assertEqual(len(list((out/'frames').glob('*.png'))),2)
            events=[json.loads(line) for line in (out/'events.jsonl').read_text().splitlines()]
            sinks=[e for e in events if e['type']=='audio.sink_delivered']
            self.assertEqual(len(sinks),2)
            self.assertTrue(all(e['payload']['playback_verified'] is False for e in sinks))

    def test_explicit_unsupported_request_stops_before_synthesis(self):
        class Voice(FakeVoice):
            def capabilities(self):return {'schema_version':1,'controls':{'delivery':{'status':'unsupported'}}}
        with TemporaryDirectory() as folder:
            voice=Voice();engine=Engine(Config(SCENE,('line',),{},Path(folder)),Adapters(FakeReasoner(),voice,FakeFace()))
            with self.assertRaises(ContractError):engine.run()
            self.assertEqual(voice.calls,[])
            events=[json.loads(line) for line in next(Path(folder).glob('run-*/events.jsonl')).read_text().splitlines()]
            report=next(e['payload']['report'] for e in events if e['type']=='voice.controls.preflight')
            self.assertEqual(report['unsupported'],['delivery'])

    def test_receipt_is_not_inferred_from_capabilities(self):
        class Voice(FakeVoice):
            def capabilities(self):return {'schema_version':1,'controls':{'delivery':{'status':'experimental','transport':'free_text','effect_verified':False}}}
            def control_receipt(self,request):return {'plan_id':request.plan.id,'delivered':{'instruction':request.plan.performance.delivery},'effect_verified':False}
        with TemporaryDirectory() as folder:
            voice=Voice();engine=Engine(Config(SCENE,('line',),{},Path(folder)),Adapters(FakeReasoner(),voice,FakeFace()))
            out=engine.run()
            events=[json.loads(line) for line in (out/'events.jsonl').read_text().splitlines()]
            before=next(e['payload']['report'] for e in events if e['type']=='voice.controls.preflight')
            after=next(e['payload']['receipt'] for e in events if e['type']=='voice.controls.receipt')
            self.assertIsNone(before['controls']['delivery']['delivered_value'])
            self.assertFalse(after['effect_verified'])
            self.assertIn('instruction',after['delivered'])
            self.assertEqual(voice.calls[0].control_report,before)

    def test_audio_only_does_not_touch_face(self):
        class Face:
            def health(self):raise AssertionError('Face must not load')
            def render(self,*args):raise AssertionError('Face must not render')
        with TemporaryDirectory() as folder:
            engine=Engine(Config(SCENE,('line',),{},Path(folder)),Adapters(FakeReasoner(),FakeVoice(),Face()))
            received=[];out=engine.run_streaming(lambda chunk,start,cancel:received.append(start),face_enabled=False)
            self.assertEqual(received,[0,16]);self.assertEqual(list((out/'frames').glob('*')),[])

    def test_b_adapter_receipt_flows_through_engine_without_runtime_loading(self):
        from unittest.mock import patch
        from yuldion.adapters.b_cosyvoice import BVoice
        from test_b_cosyvoice_port import Backend as FixtureBackend
        with TemporaryDirectory() as folder:
            voice=BVoice({'backend_factory':'cpu_fixture:create'})
            engine=Engine(Config(SCENE,('A test line.',),{},Path(folder)),Adapters(FakeReasoner(),voice,FakeFace()))
            received=[]
            with patch('yuldion.adapters.b_cosyvoice.import_module') as module:
                module.return_value.create.return_value=FixtureBackend()
                out=engine.run_streaming(lambda chunk,start,cancel:received.append(start))
            events=[json.loads(line) for line in (out/'events.jsonl').read_text().splitlines()]
            receipt=next(e['payload']['receipt'] for e in events if e['type']=='voice.controls.receipt')
            self.assertEqual(received,[0,2])
            self.assertEqual(receipt['status'],'completed')
            self.assertTrue(receipt['controls']['delivery']['delivery_verified'])
            self.assertFalse(receipt['effect_verified'])

    def test_face_off_loader_does_not_import_face_plugin(self):
        from yuldion.config import load_adapters
        from yuldion.adapters.unconfigured import Unconfigured
        with TemporaryDirectory() as folder:
            specs={'reasoner':{'kind':'unconfigured'},'voice':{'kind':'unconfigured'},
                   'face':{'kind':'plugin','entrypoint':'must_not_exist_face_plugin:create'}}
            adapters=load_adapters(Config(SCENE,('line',),specs,Path(folder)),skip_face=True)
            self.assertIsInstance(adapters.face,Unconfigured)
            adapters.close()

    def test_face_queue_saturation_records_drop_without_blocking(self):
        entered=Event();release=Event();dropped=[]
        def consume(task,stop):entered.set();release.wait(2)
        c=FaceConsumer(consume,Event(),dropped.append,capacity=1)
        try:
            c.submit(1);self.assertTrue(entered.wait(2))
            c.submit(2);c.submit(3)
            self.assertEqual(dropped,[3]);release.set();c.finish(time.monotonic()+2)
            self.assertEqual(c.completed,2)
        finally:release.set();c.close()
