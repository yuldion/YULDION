"""Synchronous headless orchestration; model computation lives behind adapters.

Phrase boundaries are safe checkpoints, not reasons to change action. This is
not a low-latency playback server. Event/artifact timestamps distinguish model
generation from the sample clock that a future player can use.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event, Timer
import hashlib
import json
import math
import struct
import time
import uuid
from .config import Config
from .errors import Cancelled, ContractError
from .events import Journal, canonical
from .types import (Action, Adapters, AudioChunk, Audit, Context, FaceFrame, FaceRequest,
                    Observation, Performance, Plan, Proposal, SpeechRequest)

def require(condition, message):
    if not condition:
        raise ContractError(message)

def text(value):
    return isinstance(value, str) and bool(value.strip())

def normalized(value):
    return " ".join(value.casefold().split())

class Engine:
    def __init__(self, config: Config, adapters: Adapters, cancel: Event | None = None):
        self.config = config
        self.adapters = adapters
        self.cancel = cancel if cancel is not None else Event()
        self.scene_hash = hashlib.sha256(canonical(config.scene).encode()).hexdigest()
        self.plan: Plan | None = None
        self.observations: list[Observation] = []
        self._ids = {"scene"}
        self._consumed_external: set[str] = set()
        self.discoveries: list[str] = []
        self.prior_views: list[str] = []
        self.feedback: dict = {}
        self.total_samples = 0
        self.sample_rate: int | None = None
        self._last_frame = -1
        self._has_run = False

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled("실행 중단 요청: 반환된 이후 출력은 사용하지 않습니다.")

    def observe(self, observation: Observation):
        require(isinstance(observation, Observation), "Expected Observation")
        require(observation.kind == "external_text", "Only explicit external text can enter externally")
        require(text(observation.id) and text(observation.text), "External input requires ID/text")
        require(not observation.id.startswith(("script:", "speech:")), "Reserved event ID")
        require(observation.id not in self._ids, "Duplicate event ID")
        self._ids.add(observation.id)
        self.observations.append(observation)

    def context(self, fragment: str, segment: int):
        script = Observation(f"script:{segment}", "authored_script", fragment)
        new_external = tuple(o.id for o in self.observations
                             if o.kind == "external_text" and o.id not in self._consumed_external)
        # Keep all unconsumed stimuli even if they exceed the ordinary context tail.
        selected = {o.id: o for o in self.observations[-24:]}
        selected.update({o.id: o for o in self.observations if o.id in new_external})
        evidence = (Observation("scene", "scene", self.config.scene.given), *selected.values(), script)
        return Context(self.config.scene, self.scene_hash, script, tuple(evidence),
                       self.plan.action if self.plan else None, self.plan.action_id if self.plan else None,
                       tuple(self.prior_views[-4:]), tuple(self.discoveries), new_external,
                       deepcopy(self.plan.performance.motor) if self.plan else None,
                       deepcopy(self.feedback))

    def choose(self, context: Context, proposal: Proposal, audit: Audit):
        require(isinstance(proposal, Proposal) and isinstance(audit, Audit), "Invalid reasoner result types")
        require(type(audit.grounded) is bool and type(audit.genuinely_new) is bool
                and type(audit.action_change_necessary) is bool, "Audit flags must be booleans")
        require(audit.grounded, "Ungrounded interpretation/action: stop instead of using a preset")
        require(text(proposal.view) and proposal.basis, "View and evidence basis are required")
        ids = {o.id for o in context.evidence}
        require(set(proposal.basis) <= ids, "Unknown evidence ID")
        if proposal.action is not None:
            require(isinstance(proposal.action, Action), "Invalid action type")
            require(all(text(v) for v in asdict(proposal.action).values()), "Action fields must be nonempty")
            require(proposal.action.target_id == context.scene.target_id, "Target relationship is immutable")
        if self.plan is None:
            require(proposal.decision == "initialize" and proposal.action is not None,
                    "First phrase needs a generated target-directed action")
            require(context.script.id in proposal.basis, "First action must cite the current unspoken script")
            return proposal.action, True, "initialized from scene and current script"
        if proposal.decision == "retain":
            return self.plan.action, False, "retained across speech checkpoint"
        require(proposal.decision == "change" and proposal.action is not None, "Cannot reinitialize a running scene")
        trigger = proposal.trigger
        require(trigger.kind in ("none", "external_event", "discovery"), "Unknown trigger kind")
        basis = set(trigger.basis)
        valid = bool(basis) and basis <= ids and all(text(s) for s in
                  (trigger.prior_assumption, trigger.new_insight, trigger.why_action_insufficient))
        if trigger.kind == "external_event":
            valid = valid and bool(basis & set(context.new_external_ids))
        elif trigger.kind == "discovery":
            fresh = {context.script.id}
            previous = next((o.id for o in reversed(context.evidence) if o.kind == "generated_speech"), None)
            if previous:
                fresh.add(previous)
            valid = valid and bool(basis & fresh) and normalized(trigger.new_insight) not in self.discoveries
        else:
            valid = False
        changed = bool(valid and proposal.action != self.plan.action and audit.genuinely_new
                       and audit.action_change_necessary)
        return (proposal.action, True, "grounded new trigger and necessary tactic change") if changed else (
            self.plan.action, False, "change rejected; existing action retained")

    def make_plan(self, fragment: str, segment: int, journal: Journal):
        context = self.context(fragment, segment)
        journal.emit("reasoner.request", context=context)
        proposal = self.adapters.reasoner.propose(deepcopy(context), self.cancel)
        self.check_cancel()
        journal.emit("reasoner.proposal", proposal=proposal)
        audit = self.adapters.reasoner.audit(deepcopy(context), deepcopy(proposal), self.cancel)
        self.check_cancel()
        journal.emit("reasoner.audit", audit=audit)
        action, changed, reason = self.choose(context, proposal, audit)
        journal.emit("action.decision", changed=changed, reason=reason, action=action,
                     trigger=proposal.trigger, scene_hash=self.scene_hash)
        performance = self.adapters.reasoner.perform(deepcopy(context), deepcopy(action), proposal.view,
                                                     changed, self.cancel)
        self.check_cancel()
        require(isinstance(performance, Performance), "Expected Performance")
        require(text(performance.delivery), "Generated delivery is required; no default vocal style")
        require(type(performance.pause_ms) is int and 0 <= performance.pause_ms <= 10000,
                "pause_ms must be an integer in 0..10000")
        require(type(performance.breath) is bool and isinstance(performance.motor, dict)
                and bool(performance.motor), "Generated motor controls and breath flag are required")
        canonical(performance)  # Reject NaN/unserializable motor states.
        if not changed:
            require(canonical(performance.motor) == canonical(self.plan.performance.motor),
                    "Retained action must retain the same face/gaze target")
        action_id = f"action-{uuid.uuid4().hex[:12]}" if changed else self.plan.action_id
        plan = Plan(f"plan-{uuid.uuid4().hex}", self.scene_hash, action_id, action, changed,
                    proposal.view, deepcopy(performance))
        # Commit only after the full performance plan validates.
        self.plan = plan
        self.prior_views.append(plan.view)
        if changed and proposal.trigger.kind == "discovery":
            self.discoveries.append(normalized(proposal.trigger.new_insight))
        self._consumed_external.update(context.new_external_ids)
        journal.emit("plan.committed", segment=segment, plan=plan)
        return plan

    def validate_audio(self, chunk: AudioChunk, plan: Plan, expected: int):
        require(isinstance(chunk, AudioChunk), "Expected AudioChunk")
        require(chunk.plan_id == plan.id, "Voice returned a different plan ID")
        require(type(chunk.sample_start) is int and chunk.sample_start == expected,
                "Voice chunks must be contiguous and start at zero for each request")
        require(type(chunk.sample_rate) is int and 8000 <= chunk.sample_rate <= 192000, "Invalid sample rate")
        require(isinstance(chunk.pcm_f32le, bytes) and 0 < len(chunk.pcm_f32le) <= 16 * 1024 * 1024
                and len(chunk.pcm_f32le) % 4 == 0, "Expected bounded nonempty mono float32 PCM")
        require(all(math.isfinite(v[0]) for v in struct.iter_unpack("<f", chunk.pcm_f32le)), "Nonfinite PCM")
        require(self.sample_rate in (None, chunk.sample_rate), "Sample rate changed during run")
        self.sample_rate = chunk.sample_rate
        return len(chunk.pcm_f32le) // 4

    def validate_frame(self, frame: FaceFrame, plan: Plan, chunk: AudioChunk, start: int, end: int):
        require(isinstance(frame, FaceFrame), "Expected FaceFrame")
        require(frame.plan_id == plan.id and frame.sample_rate == chunk.sample_rate, "Face/audio plan or clock mismatch")
        require(type(frame.sample_start) is int and start <= frame.sample_start < end
                and frame.sample_start > self._last_frame, "Face timestamp outside chunk or not monotonic")
        require(isinstance(frame.image, bytes) and 0 < len(frame.image) <= 16 * 1024 * 1024, "Invalid frame bytes")
        require((frame.format == "png" and frame.image.startswith(b"\x89PNG\r\n\x1a\n"))
                or (frame.format == "jpeg" and frame.image.startswith(b"\xff\xd8")), "Image format/signature mismatch")
        canonical(frame.controls)
        self._last_frame = frame.sample_start

    def run(self, on_event=None, stimuli=None, max_seconds=300):
        require(not self._has_run, "Create a new engine instance for each run")
        require(type(max_seconds) in (int, float) and 0 < max_seconds <= 3600, "Invalid execution limit")
        self._has_run = True
        health_records = {}
        for role in ("reasoner", "voice", "face"):
            health = getattr(self.adapters, role).health()
            require(health.ready, f"{role}: {health.message}")
            health_records[role] = asdict(health)
        self.check_cancel()
        run_id = "run-" + uuid.uuid4().hex
        directory = self.config.output_dir / run_id
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "audio").mkdir()
        (directory / "frames").mkdir()
        journal = Journal(directory, run_id)
        if on_event:
            journal.subscribe(on_event)
        deadline = time.monotonic() + max_seconds
        timer = Timer(max_seconds, self.cancel.set)
        timer.daemon = True
        timer.start()
        try:
            journal.emit("run.started", scene=self.config.scene, scene_hash=self.scene_hash,
                         adapters=health_records,
                         prepared=["scene", "script", "model weights and identity references", "adapter control rules"],
                         generated=["interpretation", "action", "delivery", "motor targets", "PCM", "frames"],
                         scope="generation/artifact clock; no playback or hard backend termination")
            for segment, fragment in enumerate(self.config.script):
                self.check_cancel()
                if time.monotonic() >= deadline:
                    raise Cancelled("Execution time limit reached")
                if stimuli:
                    for observation in stimuli(segment):
                        self.observe(observation)
                        journal.emit("external.observed", observation=observation)
                journal.emit("script.current", segment=segment, text=fragment, kind="unspoken authored script")
                plan = self.make_plan(fragment, segment, journal)
                self.check_cancel()
                request = SpeechRequest(fragment, deepcopy(plan))
                expected = 0
                frames = 0
                sum_squares = 0.0
                clipped = 0
                audio_path = directory / "audio" / f"{segment:04d}.f32le"
                phrase_start = self.total_samples
                with audio_path.open("xb") as output:
                    journal.emit("voice.request", segment=segment, request=request)
                    for chunk in self.adapters.voice.synthesize(request, self.cancel):
                        self.check_cancel()
                        if time.monotonic() >= deadline:
                            raise Cancelled("Execution time limit reached")
                        count = self.validate_audio(chunk, plan, expected)
                        start = self.total_samples
                        output.write(chunk.pcm_f32le)
                        for (value,) in struct.iter_unpack("<f", chunk.pcm_f32le):
                            sum_squares += value * value
                            clipped += int(abs(value) > 1.0)
                        journal.emit("audio.chunk", segment=segment, plan_id=plan.id,
                                     sample_start=start, samples=count, sample_rate=chunk.sample_rate,
                                     artifact=str(audio_path.relative_to(directory)), artifact_offset_bytes=expected * 4)
                        face_request = FaceRequest(deepcopy(plan), chunk, start)
                        for frame in self.adapters.face.render(face_request, self.cancel):
                            self.check_cancel()
                            if time.monotonic() >= deadline:
                                raise Cancelled("Execution time limit reached")
                            self.validate_frame(frame, plan, chunk, start, start + count)
                            suffix = ".png" if frame.format == "png" else ".jpg"
                            frame_path = directory / "frames" / f"{frame.sample_start:012d}{suffix}"
                            frame_path.write_bytes(frame.image)
                            frames += 1
                            journal.emit("face.frame", plan_id=plan.id, sample_start=frame.sample_start,
                                         sample_rate=frame.sample_rate, controls=frame.controls,
                                         artifact=str(frame_path.relative_to(directory)))
                        expected += count
                        self.total_samples += count
                require(expected > 0, "Voice produced no audio; no fallback")
                require(frames > 0, "Face produced no frames; no stored-video fallback")
                audio_path.with_suffix(".json").write_text(canonical({
                    "format": "mono-float32-little-endian", "sample_rate": self.sample_rate,
                    "samples": expected, "global_sample_start": phrase_start, "plan_id": plan.id,
                    "action_id": plan.action_id, "pause_ms_requested": plan.performance.pause_ms,
                    "sha256": hashlib.sha256(audio_path.read_bytes()).hexdigest()}) + "\n", encoding="utf-8")
                self.feedback = {"duration_s": expected / self.sample_rate,
                                 "rms": math.sqrt(sum_squares / expected), "samples_outside_unit_range": clipped,
                                 "frames": frames, "scope": "technical outputs, not audience response"}
                self.observations.append(Observation(f"speech:{segment}", "generated_speech", fragment))
                self._ids.add(f"speech:{segment}")
                journal.emit("performance.feedback", technical=self.feedback, partner_outcome="unobserved",
                             action_id=plan.action_id, desired_change=plan.action.desired_change,
                             no_response_is_not_agreement_or_failure=True)
                (directory / "state.json").write_text(canonical({"plan": self.plan, "scene_hash": self.scene_hash,
                     "discoveries": self.discoveries, "feedback": self.feedback}) + "\n", encoding="utf-8")
            journal.emit("run.completed", samples=self.total_samples, sample_rate=self.sample_rate)
            return directory
        except Exception as error:
            journal.emit("run.cancelled" if isinstance(error, Cancelled) else "run.failed",
                         error_type=type(error).__name__, message=str(error), fallback=False)
            raise
        finally:
            timer.cancel()
            journal.close()
