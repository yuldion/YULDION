"""Synthetic CPU protocol tests only. No portrait/model/render quality evidence."""
from copy import deepcopy
from dataclasses import replace
import math
import struct
from threading import Event
import unittest
from unittest.mock import patch
import zlib

from yuldion.adapters.hamlet_face import (
    COMPONENTS, PROFILE, HamletFace, sample_positions, verify_manifest,
)
from yuldion.types import Action, AudioChunk, FaceRequest, Health, Performance, Plan


def manifest():
    # Fake hashes are test fixtures, never claims about actual model files.
    return {**PROFILE, "components_sha256": {name: "a"*64 for name in COMPONENTS},
            "asset_verification": "sha256_readback"}


def png():
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind+data)))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 512, 512, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + b"\0"*(512*3))*512))
            + chunk(b"IEND", b""))


PNG = png()


def request(motor=None, count=1920, start=0, relative=0, pid="p1", sr=24000):
    motor = {"head": {"yaw_deg": 0.}, "gaze": {"target": "partner"}} if motor is None else motor
    p = Plan(pid, "scene", "action", Action("partner", "consider", "ask", "unobserved"),
             False, "reviewed", Performance("delivery", motor))
    audio = AudioChunk(pid, relative, sr, struct.pack("<f", .125)*count)
    return FaceRequest(p, audio, start)


class Backend:
    def __init__(self):
        self.manifest = manifest()
        self.calls = []
        self.closed = False
        self.ack = None
        self.iterator_closed = 0

    def describe(self):
        return deepcopy(self.manifest)

    def health(self):
        return Health(not self.closed, "CPU fixture only", PROFILE["profile_id"])

    def render_packet(self, packet, cancel):
        self.calls.append(deepcopy(packet))
        self.ack = {"request_sha256": packet["request_sha256"], "trajectory_replayed": False,
                    "temporal_state_reset": packet["reset_temporal_state"]}
        try:
            for sample in packet["frame_samples"]:
                applied = deepcopy(packet["delivered_motor"])
                # Deliberately differs from requested goal: prove the port reports
                # the backend's intermediate applied state, not a fabricated copy.
                if "head.yaw_deg" in applied:
                    applied["head.yaw_deg"] *= .5
                yield {"sample_start": sample, "request_sha256": packet["request_sha256"],
                       "image": PNG, "format": "png", "applied_state": applied,
                       "application_status": "applied"}
        finally:
            self.iterator_closed += 1

    def input_receipt(self):
        return deepcopy(self.ack)

    def close(self):
        self.closed = True


class HamletFaceTests(unittest.TestCase):
    def port(self, **options):
        return HamletFace({"enabled": True, "backend_factory": "fixture:create",
                           "manifest": manifest(), "allow_experimental": True,
                           "target_positions_m": {"partner": [.3, 0., 2.]}, **options})

    def declare(self, face, r):
        face.declare_utterance(r.plan, r.audio, r.global_sample_start)

    def render(self, face, r, backend=None, cancel=None):
        backend = backend or Backend()
        with patch("yuldion.adapters.hamlet_face.import_module") as module:
            module.return_value.create.return_value = backend
            frames = list(face.render(r, cancel or Event()))
        return frames, backend

    def test_no_import_from_configuration_health_capabilities_or_declaration(self):
        face = self.port()
        with patch("yuldion.adapters.hamlet_face.import_module") as module:
            self.assertTrue(face.health().ready)
            self.assertIn("unverified", face.health().message)
            caps = face.capabilities()
            self.declare(face, request())
            module.assert_not_called()
        self.assertEqual(caps["controls"]["gaze.hold"]["status"], "unsupported")
        self.assertFalse(caps["controls"]["head.yaw_deg"]["effect_verified"])
        self.assertEqual(caps["audio_context"], "utterance")

    def test_completed_engine_request_needs_no_external_registration(self):
        face = self.port()
        r = replace(request(), audio_complete=True)
        frames, backend = self.render(face, r)
        self.assertEqual(len(frames), 2)
        self.assertEqual(backend.calls[0]["utterance_pcm_f32le"], r.audio.pcm_f32le)
        from yuldion.face_capabilities import inspect_motor
        self.assertEqual(inspect_motor(face, r.plan)["audio_context"], "utterance")
        for bad in (replace(r, audio_complete=1),
                    replace(r, audio=replace(r.audio, sample_start=1))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.render(self.port(), bad)

    def test_second_completed_utterance_keeps_original_global_clock(self):
        face = self.port()
        first = replace(request(), audio_complete=True)
        _, backend = self.render(face, first)
        second = replace(request(pid="p2", start=1920), audio_complete=True)
        frames, _ = self.render(face, second)
        self.assertEqual([f.sample_start for f in frames], [1920, 2880])
        self.assertEqual(backend.calls[-1]["relative_sample_start"], 0)
        self.assertEqual(backend.calls[-1]["missing_audio_span"], None)

    def test_complete_context_required_without_inventing_chunk_end(self):
        face = self.port()
        with patch("yuldion.adapters.hamlet_face.import_module") as module:
            with self.assertRaisesRegex(ValueError, "Complete utterance"):
                list(face.render(request(), Event()))
            module.assert_not_called()

    def test_actual_motor_pcm_target_and_applied_receipt(self):
        r = request({"head": {"yaw_deg": 4.}, "gaze": {"target": "partner"},
                     "expression": {"brow_inner": 0.}})
        face = self.port()
        self.declare(face, r)
        frames, backend = self.render(face, r)
        self.assertEqual([f.sample_start for f in frames], [0, 960])
        q = backend.calls[0]
        self.assertEqual(q["pcm_f32le"], r.audio.pcm_f32le)
        self.assertEqual(q["utterance_pcm_f32le"], r.audio.pcm_f32le)
        self.assertEqual(q["delivered_motor"]["head.yaw_deg"], 4.)
        self.assertEqual(q["delivered_motor"]["gaze.target_m"], [.3, 0., 2.])
        self.assertIn("expression.brow_inner", q["delivered_motor"])
        for f in frames:
            self.assertEqual(f.controls["requested_motor"], r.plan.performance.motor)
            self.assertEqual(f.controls["applied_state"]["head.yaw_deg"], 2.)
            self.assertFalse(f.controls["effect_verified"])
            self.assertFalse(f.controls["trajectory_replayed"])
        self.assertEqual(face.control_receipt(r)["status"], "completed")

    def test_new_motor_not_old_trajectory_is_delivered(self):
        face = self.port()
        r = request({"head": {"yaw_deg": 3.}})
        self.declare(face, r)
        _, backend = self.render(face, r)
        second = request({"head": {"yaw_deg": -2.}}, start=1920, pid="p2")
        self.declare(face, second)
        self.render(face, second)
        self.assertEqual([q["delivered_motor"]["head.yaw_deg"] for q in backend.calls], [3., -2.])
        self.assertFalse(backend.calls[-1]["reset_temporal_state"])

    def test_semantic_target_without_mapping_rejected_no_camera_fallback(self):
        face = self.port()
        with self.assertRaisesRegex(ValueError, "Unmapped semantic"):
            self.declare(face, request({"gaze": {"target": "internal_judge"}}))
        face = self.port(target_positions_m={})
        self.assertEqual(face.capabilities()["controls"]["gaze.target"]["status"], "unsupported")
        with self.assertRaises(ValueError):
            self.declare(face, request({"gaze": {"target": "camera"}}))

    def test_explicit_zero_and_false_are_not_silently_disabled(self):
        face = self.port()
        for motor in ({"gaze": {"hold": False}}, {"neck": {"yaw_deg": 0}},
                      {"expression": {"smile": 0}}):
            with self.subTest(motor=motor), self.assertRaisesRegex(ValueError, "Unsupported"):
                self.declare(face, request(motor))
        self.declare(face, request({"head": {"yaw_deg": 0.}}))

    def test_invalid_controls_bounds_and_unknown_options(self):
        bad = [
            {"head": {"pitch_deg": 3.1}}, {"head": {"yaw_deg": 6.1}},
            {"head": {"roll_deg": math.nan}}, {"head": {"yaw_deg": True}},
            {"gaze": {"target_m": [0, 0, 0]}},
            {"gaze": {"target": "partner", "target_m": [0, 0, 2]}},
            {"expression": {}}, {"expression": {"brow_inner": .03}},
            {"head.yaw_deg": 1},
        ]
        for motor in bad:
            with self.subTest(motor=motor), self.assertRaises(ValueError):
                self.declare(self.port(), request(motor))
        with self.assertRaises(ValueError):
            self.port(auto_download=True)
        with self.assertRaisesRegex(ValueError, "opt-in"):
            self.declare(self.port(allow_experimental=False), request())

    def test_rational_global_frame_clock_no_chunk_restart(self):
        positions = []
        for a, b in [(0, 511), (511, 1003), (1003, 22050)]:
            positions += list(sample_positions(a, b, 22050))
        self.assertEqual(positions, list(sample_positions(0, 22050, 22050)))
        self.assertEqual(len(positions), 25)
        self.assertEqual(list(sample_positions(1000, 1001, 24000)), [])

    def test_chunks_original_samples_and_gap_reset(self):
        face = self.port()
        whole = request(count=3840)
        self.declare(face, whole)
        first = replace(whole, audio=replace(whole.audio, pcm_f32le=whole.audio.pcm_f32le[:3840]))
        _, backend = self.render(face, first)
        # The engine dropped [960,1920). Only the next actual chunk is rendered.
        third = replace(whole, global_sample_start=1920,
                        audio=replace(whole.audio, sample_start=1920,
                                      pcm_f32le=whole.audio.pcm_f32le[7680:11520]))
        frames, _ = self.render(face, third)
        self.assertEqual([f.sample_start for f in frames], [1920])
        self.assertEqual(backend.calls[-1]["missing_audio_span"], [960, 1920])
        self.assertTrue(backend.calls[-1]["reset_temporal_state"])

    def test_pcm_or_plan_or_clock_substitution_rejected(self):
        r = request()
        variants = [
            replace(r, audio=replace(r.audio, pcm_f32le=struct.pack("<f", .2)*1920)),
            replace(r, global_sample_start=1),
            replace(r, audio=replace(r.audio, plan_id="wrong")),
            replace(r, audio=replace(r.audio, sample_rate=48000)),
            replace(r, plan=replace(r.plan, performance=Performance("d", {"head": {"yaw_deg": 1}}))),
        ]
        for v in variants:
            face = self.port()
            self.declare(face, r)
            with self.subTest(v=v), self.assertRaises(ValueError):
                self.render(face, v)

    def test_backend_profile_and_checksum_mismatch(self):
        for key, value in (("eye_compositor", "v10_unselected_aperture"),
                           ("trajectory_replay", True), ("brow_context", "chunk_only"),
                           ("components_sha256", {name: "b"*64 for name in COMPONENTS})):
            face = self.port()
            self.declare(face, request())
            backend = Backend()
            backend.manifest[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.render(face, request(), backend)
            self.assertTrue(backend.closed)
            self.assertEqual(backend.calls, [])
        with self.assertRaises(ValueError):
            verify_manifest({**manifest(), "asset_verification": "assumed"})

    def test_missing_or_wrong_backend_acknowledgement(self):
        for bad in ({}, {"request_sha256": "wrong"}, {"trajectory_replayed": True},
                    {"temporal_state_reset": False}):
            class BadAck(Backend):
                def input_receipt(self):
                    return {**super().input_receipt(), **bad} if bad else {}
            face = self.port()
            self.declare(face, request())
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "acknowledgement"):
                self.render(face, request(), BadAck())
            self.assertFalse(face.health().ready)

    def test_missing_frames_invalid_png_and_invented_applied_state(self):
        for field, value in (("sample_start", 5), ("image", b"not a png"),
                             ("applied_state", {}), ("request_sha256", "wrong"),
                             ("application_status", "requested")):
            class BadFrame(Backend):
                def render_packet(self, q, c):
                    for part in super().render_packet(q, c):
                        yield {**part, field: value}
            face = self.port()
            self.declare(face, request())
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.render(face, request(), BadFrame())
        class Missing(Backend):
            def render_packet(self, q, c):
                for i, part in enumerate(super().render_packet(q, c)):
                    if i == 0:
                        yield part
        face = self.port()
        self.declare(face, request())
        with self.assertRaisesRegex(ValueError, "omitted"):
            self.render(face, request(), Missing())

    def test_cancellation_and_consumer_close_only_close_owned_iterator(self):
        r = request()
        face = self.port()
        self.declare(face, r)
        cancel = Event()
        cancel.set()
        with patch("yuldion.adapters.hamlet_face.import_module") as module:
            self.assertEqual(list(face.render(r, cancel)), [])
            module.assert_not_called()
        for cancel_after in (True, False):
            face = self.port()
            self.declare(face, r)
            backend = Backend()
            cancel = Event()
            with patch("yuldion.adapters.hamlet_face.import_module") as module:
                module.return_value.create.return_value = backend
                it = face.render(r, cancel)
                next(it)
                with self.assertRaises(RuntimeError):
                    face.close()
                if cancel_after:
                    cancel.set()
                    self.assertEqual(list(it), [])
                else:
                    it.close()
            self.assertEqual(backend.iterator_closed, 1)
            self.assertFalse(backend.closed)
            face.close()
            self.assertTrue(backend.closed)

    def test_missing_hashes_replay_and_receipt_copy(self):
        with self.assertRaises(ValueError):
            self.port(manifest={**manifest(), "components_sha256": {}})
        face = self.port()
        r = request()
        self.assertEqual(face.control_receipt(r)["status"], "not_reported")
        self.declare(face, r)
        self.render(face, r)
        receipt = face.control_receipt(r)
        receipt["status"] = "forged"
        self.assertEqual(face.control_receipt(r)["status"], "completed")
        with self.assertRaises(ValueError):
            self.render(face, r)
        with self.assertRaises(ValueError):
            self.declare(face, r)

    def test_common_engine_utterance_pcm_first_and_real_port_receipts(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from test_engine import FakeReasoner, FakeVoice, SCENE
        from yuldion.config import Config
        from yuldion.engine import Engine
        from yuldion.types import Adapters

        received = []
        class Reasoner(FakeReasoner):
            def perform(self, context, action, view, action_changed, cancel):
                return Performance("Fixture only", {"head": {"yaw_deg": 2.}})

        class Voice(FakeVoice):
            def synthesize(self, req, cancel):
                for start in (0, 960):
                    yield AudioChunk(req.plan.id, start, 24000, struct.pack("<f", .1)*960)

        class Prepared(Backend):
            def render_packet(self, q, cancel):
                # Both original chunks were delivered before the face call.
                assert len(received) >= (q["global_sample_start"] + q["sample_count"]) // 960
                assert q["sample_count"] == 1920
                assert q["relative_sample_start"] == 0
                yield from super().render_packet(q, cancel)

        backend = Prepared()
        face = self.port()
        with TemporaryDirectory() as directory:
            engine = Engine(Config(SCENE, ("first", "second"), {}, Path(directory)),
                            Adapters(Reasoner(), Voice(), face))
            with patch("yuldion.adapters.hamlet_face.import_module") as module:
                module.return_value.create.return_value = backend
                out = engine.run_streaming(lambda chunk, start, cancel: received.append((start, chunk.pcm_f32le)))
            events = [json.loads(line) for line in (out/"events.jsonl").read_text().splitlines()]
            receipts = [e["payload"] for e in events if e["type"] == "face.controls.receipt"]
            self.assertEqual([r["sample_start"] for r in receipts], [0, 960, 1920, 2880])
            self.assertEqual([p for p, _ in received], [0, 960, 1920, 2880])
            self.assertEqual(len(backend.calls), 2)
            self.assertEqual(backend.calls[0]["pcm_f32le"], received[0][1]+received[1][1])
            self.assertTrue(all(not r["receipt"]["effect_verified"] for r in receipts))


if __name__ == "__main__":
    unittest.main()
