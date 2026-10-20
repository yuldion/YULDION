"""Version-one adapter contracts. No GPU, network or framework dependencies."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, Protocol
from threading import Event

@dataclass(frozen=True)
class Scene:
    character_id: str
    overarching_goal: str
    scene_goal: str
    given: str
    target_id: str
    relationship: str
    interpretation_status: str = "rehearsal_hypothesis"

@dataclass(frozen=True)
class Observation:
    id: str
    kind: Literal["scene", "authored_script", "generated_speech", "external_text"]
    text: str

@dataclass(frozen=True)
class Action:
    target_id: str
    desired_change: str
    tactic: str
    observable_test: str

@dataclass(frozen=True)
class Trigger:
    kind: Literal["none", "external_event", "discovery"] = "none"
    basis: tuple[str, ...] = ()
    prior_assumption: str = ""
    new_insight: str = ""
    why_action_insufficient: str = ""

@dataclass(frozen=True)
class Proposal:
    decision: Literal["initialize", "retain", "change"]
    view: str
    basis: tuple[str, ...]
    action: Action | None = None
    trigger: Trigger = field(default_factory=Trigger)

@dataclass(frozen=True)
class Audit:
    grounded: bool
    genuinely_new: bool = False
    action_change_necessary: bool = False
    note: str = ""

@dataclass(frozen=True)
class Context:
    scene: Scene
    scene_hash: str
    script: Observation
    evidence: tuple[Observation, ...]
    current_action: Action | None
    action_id: str | None
    prior_views: tuple[str, ...]
    discoveries: tuple[str, ...]
    new_external_ids: tuple[str, ...]
    previous_motor: Mapping[str, Any] | None
    technical_feedback: Mapping[str, Any]
    partner_outcome: str = "unobserved"
    preparation: Mapping[str, Any] | None = None

@dataclass(frozen=True)
class Performance:
    delivery: str
    motor: Mapping[str, Any]
    pause_ms: int = 0
    breath: bool = False
    vocal: Mapping[str, Any] | None = None

@dataclass(frozen=True)
class Plan:
    id: str
    scene_hash: str
    action_id: str
    action: Action
    changed: bool
    view: str
    performance: Performance

@dataclass(frozen=True)
class SpeechRequest:
    text: str
    plan: Plan
    control_report: Mapping[str, Any] | None = None

@dataclass(frozen=True)
class AudioChunk:
    plan_id: str
    sample_start: int  # Relative to this speech request, beginning at zero.
    sample_rate: int
    pcm_f32le: bytes  # Mono, finite IEEE float32, little endian, including planned silence.

@dataclass(frozen=True)
class FaceRequest:
    plan: Plan
    audio: AudioChunk
    global_sample_start: int  # Common run audio clock; no invented wall-clock timing.
    control_report: Mapping[str, Any] | None = None
    audio_complete: bool = False  # True only for an entire completed speech request.

@dataclass(frozen=True)
class FaceFrame:
    plan_id: str
    sample_start: int  # On the common run clock, within the supplied audio chunk.
    sample_rate: int
    image: bytes
    format: Literal["png", "jpeg"]
    controls: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Health:
    ready: bool
    message: str
    model_id: str = ""

class Reasoner(Protocol):
    def health(self) -> Health: ...
    def propose(self, context: Context, cancel: Event) -> Proposal: ...
    def audit(self, context: Context, proposal: Proposal, cancel: Event) -> Audit: ...
    def perform(self, context: Context, action: Action, view: str,
                action_changed: bool, cancel: Event) -> Performance: ...
    def close(self) -> None: ...

class Voice(Protocol):
    def health(self) -> Health: ...
    def synthesize(self, request: SpeechRequest, cancel: Event) -> Iterable[AudioChunk]: ...
    def close(self) -> None: ...

class Face(Protocol):
    def health(self) -> Health: ...
    def render(self, request: FaceRequest, cancel: Event) -> Iterable[FaceFrame]: ...
    def close(self) -> None: ...

@dataclass
class Adapters:
    reasoner: Reasoner
    voice: Voice
    face: Face

    def close(self) -> None:
        for adapter in (self.face, self.voice, self.reasoner):
            try:
                adapter.close()
            except Exception:
                pass
