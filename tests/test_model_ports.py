import struct
import unittest
from dataclasses import replace
from threading import Event
from unittest.mock import patch
from yuldion.adapters.cosyvoice import CosyVoice
from yuldion.adapters.controlled_face import ControlledFace, REQUIRED
from yuldion.types import Action, Plan, Performance, SpeechRequest, AudioChunk, FaceRequest, FaceFrame, Health


def plan():
    return Plan('p', 's', 'a', Action('judge', 'consider', 'test', 'unknown'),
                False, 'view', Performance('Speak tentatively.', {'gaze': {'yaw': 0.1}}, 100))


class Tensor:
    shape = (1, 2)
    def detach(self): return self
    def float(self): return self
    def cpu(self): return self
    def reshape(self, *args): return self
    def tolist(self): return [0.1, -0.1]


class Model:
    sample_rate = 24000
    def inference_instruct2(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        yield {'tts_speech': Tensor()}


class Backend:
    capabilities = REQUIRED
    def health(self): return Health(True, 'test only')
    def close(self): self.closed = True
    def render(self, request, cancel):
        yield FaceFrame(request.plan.id, request.global_sample_start,
                        request.audio.sample_rate, b'fixture', 'png', {
                            'requested_motor': dict(request.plan.performance.motor),
                            'applied_plan_id': request.plan.id,
                            'trajectory_replayed': False,
                            'applied_state': {'gaze_yaw': 0.1}})


class PortsTest(unittest.TestCase):
    def voice(self):
        voice = CosyVoice({'checkpoint': 'missing', 'reference': 'missing'})
        voice.model = Model()
        return voice

    def test_voice_instruction_and_pause_once(self):
        voice = self.voice()
        chunks = list(voice.synthesize(SpeechRequest('To die', plan()), Event()))
        self.assertEqual(voice.model.args[:2], ('To die', 'Speak tentatively.<|endofprompt|>'))
        self.assertEqual(voice.model.kwargs['stream'], True)
        self.assertEqual([c.sample_start for c in chunks], [0, 2])
        self.assertEqual(len(chunks[1].pcm_f32le), 2400 * 4)
        self.assertEqual(struct.unpack('<2f', chunks[0].pcm_f32le)[0], struct.unpack('<f', struct.pack('<f', 0.1))[0])

    def test_breath_is_explicitly_unsupported(self):
        p = replace(plan(), performance=replace(plan().performance, breath=True))
        with self.assertRaisesRegex(ValueError, 'breath'):
            list(self.voice().synthesize(SpeechRequest('text', p), Event()))

    def test_cancelled_voice_never_loads(self):
        v = CosyVoice({'checkpoint': 'missing', 'reference': 'missing'})
        event = Event(); event.set()
        self.assertEqual(list(v.synthesize(SpeechRequest('text', plan()), event)), [])
        self.assertIsNone(v.model)

    def request(self):
        return FaceRequest(plan(), AudioChunk('p', 0, 24000, bytes(960)), 0)

    def test_face_disabled_and_lazy(self):
        face = ControlledFace({'backend_factory': 'does_not_exist:create'})
        self.assertFalse(face.health().ready)
        self.assertIsNone(face.backend)

    def test_live_receipt_and_clock(self):
        face = ControlledFace({}); face.backend = Backend()
        frames = list(face.render(self.request(), Event()))
        self.assertEqual(frames[0].controls['applied_plan_id'], 'p')
        with self.assertRaisesRegex(ValueError, 'position'):
            list(face.render(self.request(), Event()))

    def test_replay_receipt_rejected(self):
        class Bad(Backend):
            def render(self, request, cancel):
                for frame in super().render(request, cancel):
                    yield replace(frame, controls={**frame.controls, 'trajectory_replayed': True})
        face = ControlledFace({}); face.backend = Bad()
        with self.assertRaisesRegex(ValueError, 'receipt'):
            list(face.render(self.request(), Event()))

    def test_old_backend_rejected_and_closed(self):
        backend = Backend(); backend.capabilities = {'received_audio'}
        face = ControlledFace({'backend_factory': 'private_module:create'})
        with patch('yuldion.adapters.controlled_face.import_module') as module:
            module.return_value.create.return_value = backend
            with self.assertRaisesRegex(ValueError, 'lacks'):
                list(face.render(self.request(), Event()))
        self.assertTrue(backend.closed)
        self.assertIsNone(face.backend)

    def test_invalid_voice_tensor_rejected(self):
        voice = self.voice()
        class Stereo(Tensor): shape = (2, 2)
        voice.model.inference_instruct2 = lambda *a, **k: iter([{'tts_speech': Stereo()}])
        with self.assertRaisesRegex(ValueError, 'mono'):
            list(voice.synthesize(SpeechRequest('text', plan()), Event()))
