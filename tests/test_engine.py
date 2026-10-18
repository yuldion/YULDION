"""Test-only deterministic doubles. No learned models, GPUs or network requests."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import base64
import json
import struct
import unittest
from yuldion.config import Config
from yuldion.engine import Engine
from yuldion.errors import Cancelled, ContractError
from yuldion.types import (Action, Adapters, AudioChunk, Audit, FaceFrame, Health,
                           Observation, Performance, Proposal, Scene, Trigger)

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
ACTION = Action('judge', 'Consider the proposal without a premature verdict.', 'Offer a possibility.', 'An explicit judgment addresses it.')
OTHER = replace(ACTION, tactic='Suspend the conclusion.')
SCENE = Scene('actor', 'Find defensible grounds.', 'Examine relief.', 'Consequences are unknown.', 'judge', 'Internal judging position.')

class FakeReasoner:
    def __init__(self, proposals=None, audits=None):
        self.proposals = proposals or []
        self.audits = audits or []
        self.contexts = []
        self.performance_calls = []
        self.closed = False
    def health(self): return Health(True, 'test-only fixture', 'test-reasoner')
    def close(self): self.closed = True
    def propose(self, context, cancel):
        self.contexts.append(context)
        if self.proposals:
            return self.proposals.pop(0)
        return Proposal('initialize' if context.current_action is None else 'retain',
                        'Test-only interpretation.', (context.script.id,), ACTION if context.current_action is None else None)
    def audit(self, context, proposal, cancel):
        return self.audits.pop(0) if self.audits else Audit(True)
    def perform(self, context, action, view, action_changed, cancel):
        self.performance_calls.append((context, action, action_changed))
        motor = {'gaze_x': 1 if action == OTHER else 0} if action_changed else dict(context.previous_motor)
        return Performance('Test-only generated delivery.', motor)

class FakeVoice:
    def __init__(self): self.calls = []; self.closed = False
    def health(self): return Health(True, 'test-only fixture', 'test-voice')
    def close(self): self.closed = True
    def synthesize(self, request, cancel):
        self.calls.append(request)
        for start in (0, 16):
            yield AudioChunk(request.plan.id, start, 24000, struct.pack('<16f', *([.05] * 16)))

class FakeFace:
    def __init__(self): self.calls = []; self.closed = False
    def health(self): return Health(True, 'test-only fixture', 'test-face')
    def close(self): self.closed = True
    def render(self, request, cancel):
        self.calls.append(request)
        yield FaceFrame(request.plan.id, request.global_sample_start, request.audio.sample_rate,
                        PNG, 'png', dict(request.plan.performance.motor))

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def setup_engine(self, script=('To die, to sleep', 'No more'), reasoner=None, voice=None, face=None, cancel=None):
        self.adapters = Adapters(reasoner or FakeReasoner(), voice or FakeVoice(), face or FakeFace())
        config = Config(SCENE, script, {}, self.root)
        return Engine(config, self.adapters, cancel)
    def records(self):
        path = next(self.root.glob('run-*/events.jsonl'))
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_first_plan_precedes_voice_and_next_clause_retains_action_motor(self):
        engine = self.setup_engine()
        folder = engine.run()
        records = self.records()
        plans = [e['payload']['plan'] for e in records if e['type'] == 'plan.committed']
        self.assertTrue(plans[0]['changed'])
        self.assertFalse(plans[1]['changed'])
        self.assertEqual(plans[0]['action_id'], plans[1]['action_id'])
        self.assertEqual(plans[0]['performance']['motor'], plans[1]['performance']['motor'])
        types = [e['type'] for e in records]
        self.assertLess(types.index('plan.committed'), types.index('voice.request'))
        self.assertEqual(len(list((folder / 'frames').glob('*.png'))), 4)
        audio = json.loads((folder / 'audio/0001.json').read_text())
        self.assertEqual(audio['global_sample_start'], 32)
        self.assertEqual(audio['samples'], 32)
        for call in self.adapters.face.calls:
            self.assertEqual(call.audio.plan_id, call.plan.id)

    def test_novel_and_necessary_discovery_changes_tactic_preserving_scene(self):
        trigger = Trigger('discovery', ('script:1',), 'The offer could settle it.',
                          'The consequence remains uncertain.', 'An offer alone no longer serves examination.')
        r = FakeReasoner([Proposal('initialize', 'First.', ('script:0',), ACTION),
                          Proposal('change', 'New possibility.', ('script:1',), OTHER, trigger)],
                         [Audit(True), Audit(True, True, True)])
        engine = self.setup_engine(reasoner=r)
        engine.run()
        plans = [e['payload']['plan'] for e in self.records() if e['type'] == 'plan.committed']
        self.assertNotEqual(plans[0]['action_id'], plans[1]['action_id'])
        self.assertEqual(plans[0]['scene_hash'], plans[1]['scene_hash'])
        self.assertEqual(engine.config.scene, SCENE)

    def test_change_without_trigger_is_retained_even_with_positive_audit(self):
        r = FakeReasoner([Proposal('initialize', 'First.', ('script:0',), ACTION),
                          Proposal('change', 'New wording.', ('script:1',), OTHER)],
                         [Audit(True), Audit(True, True, True)])
        engine = self.setup_engine(reasoner=r)
        engine.run()
        self.assertEqual(engine.plan.action, ACTION)
        self.assertFalse(engine.plan.changed)

    def test_same_discovery_does_not_switch_twice(self):
        def trigger(i): return Trigger('discovery', (f'script:{i}',), 'Old.', 'Same new insight.', 'Old tactic insufficient.')
        r = FakeReasoner([Proposal('initialize', 'A.', ('script:0',), ACTION),
                          Proposal('change', 'B.', ('script:1',), OTHER, trigger(1)),
                          Proposal('change', 'C.', ('script:2',), ACTION, trigger(2))],
                         [Audit(True), Audit(True, True, True), Audit(True, True, True)])
        engine = self.setup_engine(script=('A', 'B', 'C'), reasoner=r)
        engine.run()
        self.assertEqual(engine.plan.action, OTHER)
        self.assertFalse(engine.plan.changed)

    def test_external_evidence_only_changes_once_and_missing_response_stays_unknown(self):
        trigger = Trigger('external_event', ('partner-1',), 'Old.', 'An explicit objection.', 'Address the objection.')
        r = FakeReasoner([Proposal('initialize', 'A.', ('script:0',), ACTION),
                          Proposal('change', 'B.', ('partner-1',), OTHER, trigger),
                          Proposal('change', 'C.', ('partner-1',), ACTION, trigger)],
                         [Audit(True), Audit(True, True, True), Audit(True, True, True)])
        engine = self.setup_engine(script=('A', 'B', 'C'), reasoner=r)
        engine.run(stimuli=lambda i: [Observation('partner-1', 'external_text', 'I disagree.')] if i == 1 else [])
        self.assertEqual(engine.plan.action, OTHER)
        feedback = [e['payload'] for e in self.records() if e['type'] == 'performance.feedback']
        self.assertTrue(all(f['partner_outcome'] == 'unobserved' for f in feedback))
        self.assertEqual(r.contexts[2].new_external_ids, ())

    def test_ungrounded_first_action_never_calls_voice(self):
        engine = self.setup_engine(reasoner=FakeReasoner(audits=[Audit(False)]))
        with self.assertRaisesRegex(ContractError, 'Ungrounded'): engine.run()
        self.assertEqual(self.adapters.voice.calls, [])
        self.assertIsNone(engine.plan)
        self.assertEqual(self.records()[-1]['type'], 'run.failed')

    def test_relationship_cannot_be_changed(self):
        wrong = replace(ACTION, target_id='invented-person')
        engine = self.setup_engine(reasoner=FakeReasoner([Proposal('initialize', 'A.', ('script:0',), wrong)]))
        with self.assertRaisesRegex(ContractError, 'immutable'): engine.run()

    def test_retained_action_rejects_replaced_face_target(self):
        class BadReasoner(FakeReasoner):
            def perform(self, *args): return Performance('Test-only.', {'x': len(self.contexts)})
        engine = self.setup_engine(reasoner=BadReasoner())
        with self.assertRaisesRegex(ContractError, 'retain the same'): engine.run()
        self.assertEqual(len(self.adapters.voice.calls), 1)

    def test_bad_audio_plan_id_fails_and_preserves_journal(self):
        class WrongVoice(FakeVoice):
            def synthesize(self, request, cancel): yield AudioChunk('wrong-id', 0, 24000, struct.pack('<f', 0.))
        engine = self.setup_engine(voice=WrongVoice())
        with self.assertRaisesRegex(ContractError, 'different plan'): engine.run()
        self.assertEqual(self.records()[-1]['type'], 'run.failed')

    def test_noncontiguous_audio_and_nonfinite_audio_are_rejected(self):
        for chunk in [AudioChunk('x', 4, 24000, struct.pack('<f', 0.)),
                      AudioChunk('x', 0, 24000, struct.pack('<f', float('nan')))]:
            class BadVoice(FakeVoice):
                def synthesize(self, request, cancel): yield replace(chunk, plan_id=request.plan.id)
            engine = self.setup_engine(voice=BadVoice())
            with self.assertRaises(ContractError): engine.run()

    def test_frame_clock_mismatch_rejected(self):
        class BadFace(FakeFace):
            def render(self, request, cancel):
                yield FaceFrame(request.plan.id, request.global_sample_start + 16,
                                request.audio.sample_rate, PNG, 'png')
        engine = self.setup_engine(face=BadFace())
        with self.assertRaisesRegex(ContractError, 'outside chunk'): engine.run()

    def test_cancel_discards_late_backend_output(self):
        cancel = Event()
        class LateVoice(FakeVoice):
            def synthesize(self, request, token):
                token.set()
                yield AudioChunk(request.plan.id, 0, 24000, struct.pack('<f', .1))
        engine = self.setup_engine(voice=LateVoice(), cancel=cancel)
        with self.assertRaises(Cancelled): engine.run()
        types = [e['type'] for e in self.records()]
        self.assertNotIn('audio.chunk', types)
        self.assertEqual(types[-1], 'run.cancelled')

    def test_observer_failure_does_not_stop_actor(self):
        engine = self.setup_engine()
        def broken_observer(event): raise RuntimeError('UI disconnected')
        engine.run(on_event=broken_observer)
        self.assertEqual(self.records()[-1]['type'], 'run.completed')

    def test_engine_cannot_reuse_completed_run_or_overwrite_artifacts(self):
        engine = self.setup_engine()
        first = engine.run()
        with self.assertRaisesRegex(ContractError, 'new engine'): engine.run()
        self.assertTrue((first / 'state.json').exists())

if __name__ == '__main__': unittest.main()
