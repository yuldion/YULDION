"""CPU-only port for a separately prepared B/v10/v30/v36 face runtime.

No renderer, weights, video replay, GPU setup or live quality claim is supplied.
Preserved v30 needs a complete utterance: the engine marks audio_complete=True.
This is delayed utterance rendering, not low-latency streaming v30.
"""
from copy import deepcopy
from hashlib import sha256
from importlib import import_module
import json
import math
import struct
from threading import Lock

from yuldion.types import AudioChunk, FaceFrame, Health

PROFILE_ID = "hamlet-b-v10-v30-v36"
COMPONENTS = frozenset({
    "portrait_identity", "liveportrait", "musetalk", "whisper", "speech_blend",
    "eyes_v10", "joint_v09", "brow_v30", "brow_transport_v29", "head_neck_v36",
})
PROFILE = {
    "profile_id": PROFILE_ID, "fps": 25, "width": 512, "height": 512,
    "format": "png", "eye_compositor": "v09_existing",
    "brow_context": "complete_utterance",
    "motor_schema": "hamlet.motor.v1",
    "trajectory_replay": False,
}
LIMITS = {
    "head.pitch_deg": 3., "head.yaw_deg": 6., "head.roll_deg": 3.,
    "expression.brow_inner": .025, "expression.glabella": .025,
}
UNSUPPORTED = (
    "gaze.focus", "gaze.hold", "gaze.blink", "expression.smile",
    "expression.jaw_open", "expression.au", "neck.pitch_deg", "neck.yaw_deg",
    "neck.roll_deg", "shoulders.left", "shoulders.right",
)
MAX_PCM_BYTES = 16 * 1024 * 1024


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def _leaves(value, prefix=""):
    if not isinstance(value, dict) or not value:
        raise ValueError("Motor groups must be nonempty dictionaries")
    for key, child in value.items():
        if not isinstance(key, str) or not key or "." in key:
            raise ValueError("Motor keys must be nonempty undotted strings")
        path = prefix + "." + key if prefix else key
        if isinstance(child, dict):
            yield from _leaves(child, path)
        else:
            yield path, child


def _number(value, name, limit):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > limit:
        raise ValueError("Outside reviewed numeric range: " + name)
    return float(value)


def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("Gaze needs one explicit [X,Y,Z] point in metres")
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        raise ValueError("Nonfinite gaze point")
    if value[2] <= 0:
        raise ValueError("Gaze target must be in front of the registered camera plane")
    # Exact eye-distance/angle/occlusion checks belong to the calibrated runtime.
    return [float(x) for x in value]


def verify_manifest(manifest, expected=None):
    if not isinstance(manifest, dict):
        raise ValueError("Prepared face manifest required")
    for key, value in PROFILE.items():
        if type(manifest.get(key)) is not type(value) or manifest[key] != value:
            raise ValueError("Face profile mismatch: " + key)
    hashes = manifest.get("components_sha256")
    if not isinstance(hashes, dict) or set(hashes) != COMPONENTS:
        raise ValueError("Explicit hashes for every preserved face component required")
    for value in hashes.values():
        if (not isinstance(value, str) or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError("Invalid component SHA-256")
    if manifest.get("asset_verification") != "sha256_readback":
        raise ValueError("Prepared backend must report asset hash readback")
    if expected is not None:
        verify_manifest(expected)
        if any(manifest[key] != expected[key] for key in (*PROFILE, "components_sha256")):
            raise ValueError("Prepared runtime differs from configured component hashes")
    return deepcopy(manifest)


def sample_positions(start, end, sample_rate):
    """Global 25fps integer clock; no per-chunk restart or accumulated rounding."""
    k = (start * 25 + sample_rate - 1) // sample_rate
    while (position := k * sample_rate // 25) < end:
        yield position
        k += 1


class HamletFace:
    def __init__(self, options):
        allowed = {"enabled", "backend_factory", "backend_options", "manifest",
                   "target_positions_m", "allow_experimental"}
        if not isinstance(options, dict) or set(options) - allowed:
            raise ValueError("Unknown Hamlet face options")
        self.options = deepcopy(options)
        for key in ("enabled", "allow_experimental"):
            if key in options and type(options[key]) is not bool:
                raise ValueError(key + " must be boolean")
        positions = self.options.get("target_positions_m", {})
        if not isinstance(positions, dict):
            raise ValueError("Explicit named gaze target mapping required")
        self.targets = {}
        for name, point in positions.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Invalid gaze target name")
            self.targets[name] = _point(point)
        if "manifest" in options:
            verify_manifest(options["manifest"])
        self.backend = None
        self._context = None
        self._last_end = 0
        self._last_frame = -1
        self._rate = None
        self._closed = False
        self._broken = False
        self._needs_reset = True
        self._lock = Lock()
        self._receipt = None

    def health(self):
        factory = self.options.get("backend_factory")
        configured = (self.options.get("enabled") is True
                      and isinstance(factory, str) and factory.count(":") == 1
                      and all(factory.split(":")) and "manifest" in self.options
                      and not self._closed and not self._broken)
        return Health(configured,
                      "Configured only; completed utterance and prepared "
                      "backend required. GPU/render/effects unverified.", PROFILE_ID)

    def capabilities(self):
        controls = {
            key: {"status": "experimental", "transport": "current motor -> " + key,
                  "effect_verified": False} for key in LIMITS
        }
        controls["gaze.target_m"] = {
            "status": "experimental", "transport": "one common world target, metres",
            "effect_verified": False,
        }
        controls["gaze.target"] = {
            "status": "experimental" if self.targets else "unsupported",
            "transport": "explicit target_positions_m lookup; never semantic inference",
            "effect_verified": False,
        }
        for key in UNSUPPORTED:
            controls[key] = {"status": "unsupported", "transport": "none",
                             "effect_verified": False}
        return {"schema_version": 1, "model_id": PROFILE_ID,
                "audio_context": "utterance", "controls": controls}

    def _compile(self, motor):
        requested = dict(_leaves(motor))
        if "gaze.target" in requested and "gaze.target_m" in requested:
            raise ValueError("Specify one shared gaze target, not two")
        delivered = {}
        for key, value in requested.items():
            if key in LIMITS:
                delivered[key] = _number(value, key, LIMITS[key])
            elif key == "gaze.target_m":
                delivered[key] = _point(value)
            elif key == "gaze.target":
                if not isinstance(value, str) or value not in self.targets:
                    raise ValueError("Unmapped semantic gaze target; no camera fallback")
                delivered["gaze.target_m"] = deepcopy(self.targets[value])
            else:
                raise ValueError("Unsupported motor path: " + key)
        if not self.options.get("allow_experimental", False):
            raise ValueError("Face motor transport requires experimental opt-in")
        return requested, delivered

    @staticmethod
    def _pcm(audio):
        if (not isinstance(audio, AudioChunk) or type(audio.sample_rate) is not int
                or not 8000 <= audio.sample_rate <= 192000
                or type(audio.sample_start) is not int or audio.sample_start < 0):
            raise ValueError("Invalid audio clock")
        raw = audio.pcm_f32le
        if not isinstance(raw, bytes) or not raw or len(raw) % 4 or len(raw) > MAX_PCM_BYTES:
            raise ValueError("Expected bounded nonempty mono f32le PCM")
        if any(not math.isfinite(x) for (x,) in struct.iter_unpack("<f", raw)):
            raise ValueError("Nonfinite PCM")
        return len(raw) // 4

    def declare_utterance(self, plan, audio, global_sample_start):
        """Caller explicitly declares complete PCM, never an inferred chunk end.

        Optional explicit offline API. Engine callers instead use
        FaceRequest.audio_complete=True; no separate registration is required.
        """
        if not self._lock.acquire(False):
            raise RuntimeError("One face inference/context owner required")
        try:
            self._declare(plan, audio, global_sample_start)
        finally:
            self._lock.release()

    def _declare(self, plan, audio, global_sample_start):
        if self._closed or self._broken:
            raise RuntimeError("Face port closed or failed")
        self._pcm(audio)
        self._compile(dict(plan.performance.motor))
        if (audio.plan_id != plan.id or audio.sample_start != 0
                or type(global_sample_start) is not int
                or global_sample_start < self._last_end):
            raise ValueError("Complete utterance must start at relative zero on a future run span")
        if self._rate is not None and self._rate != audio.sample_rate:
            raise ValueError("Run sample rate changed")
        self._context = {
            "plan_id": plan.id, "plan_sha256": _digest(plan.performance.motor),
            "global_sample_start": global_sample_start,
            "sample_rate": audio.sample_rate, "pcm_f32le": audio.pcm_f32le,
            "pcm_sha256": sha256(audio.pcm_f32le).hexdigest(),
        }
        # A new utterance resets offline audio features, not continuous eye/joint
        # registration. Only a run start, missing samples or interruption resets
        # the visual temporal state.
        self._needs_reset = self._needs_reset or global_sample_start > self._last_end

    def _packet(self, request):
        count = self._pcm(request.audio)
        if request.audio.plan_id != request.plan.id:
            raise ValueError("Audio/face plan mismatch")
        requested, delivered = self._compile(dict(request.plan.performance.motor))
        context = self._context
        if context is None or context["plan_id"] != request.plan.id:
            raise ValueError("Complete utterance unavailable; streaming v30 is unsupported")
        if context["plan_sha256"] != _digest(request.plan.performance.motor):
            raise ValueError("Motor changed after complete-utterance declaration")
        start = request.global_sample_start
        relative = request.audio.sample_start
        if (type(start) is not int or start < self._last_end
                or start != context["global_sample_start"] + relative
                or request.audio.sample_rate != context["sample_rate"]):
            raise ValueError("Face request overlaps, reorders or changes the sample clock")
        if context["pcm_f32le"][relative*4:(relative+count)*4] != request.audio.pcm_f32le:
            raise ValueError("Chunk differs from declared original PCM")
        metadata = {
            "profile_id": PROFILE_ID, "motor_schema": PROFILE["motor_schema"],
            "plan_id": request.plan.id, "global_sample_start": start,
            "relative_sample_start": relative, "sample_count": count,
            "sample_rate": context["sample_rate"],
            "pcm_sha256": sha256(request.audio.pcm_f32le).hexdigest(),
            "utterance_pcm_sha256": context["pcm_sha256"],
            "utterance_global_sample_start": context["global_sample_start"],
            "utterance_sample_count": len(context["pcm_f32le"]) // 4,
            "requested_motor": deepcopy(dict(request.plan.performance.motor)),
            "delivered_motor": delivered,
            "frame_samples": list(sample_positions(start, start+count, context["sample_rate"])),
            "missing_audio_span": [self._last_end, start] if start > self._last_end else None,
            "reset_temporal_state": self._needs_reset or start > self._last_end,
            "brow_composition": "v30_prediction_plus_explicit_residual_no_clipping",
            "unrequested_motor_policy": "retain_current_state_no_invented_expression",
            "joint_policy": "v09_from_current_head_no_saved_trajectory",
        }
        return {
            **metadata, "request_sha256": _digest(metadata),
            "pcm_f32le": request.audio.pcm_f32le,
            "utterance_pcm_f32le": context["pcm_f32le"],
        }, requested

    def _attach(self):
        if not self.health().ready:
            raise RuntimeError("Explicit enabled face configuration/manifest required")
        if self.backend is None:
            module, name = self.options["backend_factory"].split(":")
            backend = getattr(import_module(module), name)(
                deepcopy(self.options.get("backend_options", {})))
            try:
                for method in ("describe", "health", "render_packet", "input_receipt", "close"):
                    if not callable(getattr(backend, method, None)):
                        raise ValueError("Prepared face backend lacks " + method)
                verify_manifest(backend.describe(), self.options["manifest"])
                if not backend.health().ready:
                    raise RuntimeError("Face backend must be prepared separately")
            except BaseException:
                if callable(getattr(backend, "close", None)):
                    backend.close()
                raise
            self.backend = backend
        verify_manifest(self.backend.describe(), self.options["manifest"])
        if not self.backend.health().ready:
            raise RuntimeError("Prepared face backend is no longer ready")

    @staticmethod
    def _image(image, format):
        # Lightweight encoded header validation, not full pixel decoding.
        if (format != "png" or not isinstance(image, bytes)
                or not 33 <= len(image) <= 16*1024*1024
                or image[:8] != b"\x89PNG\r\n\x1a\n"
                or image[8:16] != b"\0\0\0\rIHDR"
                or struct.unpack(">II", image[16:24]) != (512, 512)):
            raise ValueError("Prepared face must emit 512x512 PNG bytes")

    def render(self, request, cancel):
        if cancel.is_set():
            return
        if not self._lock.acquire(False):
            raise RuntimeError("One face inference owner required")
        iterator = None
        started = False
        try:
            if self._closed or self._broken:
                raise RuntimeError("Face port closed or failed")
            if type(request.audio_complete) is not bool:
                raise ValueError("audio_complete must be an explicit boolean")
            if request.audio_complete:
                self._declare(request.plan, request.audio, request.global_sample_start)
            packet, requested = self._packet(request)
            self._receipt = {
                "plan_id": request.plan.id, "sample_start": request.global_sample_start,
                "status": "requested", "request_sha256": packet["request_sha256"],
                "frames": 0, "effect_verified": False,
            }
            self._attach()
            if cancel.is_set():
                self._receipt["status"] = "cancelled"
                return
            iterator = iter(self.backend.render_packet(deepcopy(packet), cancel))
            started = True
            expected = packet["frame_samples"]
            index = 0
            for part in iterator:
                if cancel.is_set():
                    self._receipt["status"] = "cancelled"
                    return
                ack = self._ack(packet)
                if (not isinstance(part, dict) or index >= len(expected)
                        or type(part.get("sample_start")) is not int
                        or part["sample_start"] != expected[index]
                        or part["sample_start"] <= self._last_frame
                        or part.get("request_sha256") != packet["request_sha256"]):
                    raise ValueError("Invalid frame sample/hash; missing frames cannot be hidden")
                self._image(part.get("image"), part.get("format"))
                applied = part.get("applied_state")
                if (not isinstance(applied, dict) or not applied
                        or not set(packet["delivered_motor"]).issubset(applied)
                        or part.get("application_status") != "applied"):
                    raise ValueError("Renderer must report actual applied state")
                _digest(applied)  # finite, serializable; not a visual correctness test.
                for key in packet["delivered_motor"]:
                    if key == "gaze.target_m":
                        _point(applied[key])
                    else:
                        _number(applied[key], key, LIMITS[key])
                controls = {
                    "requested_motor": deepcopy(dict(request.plan.performance.motor)),
                    "delivered_motor": deepcopy(packet["delivered_motor"]),
                    "applied_plan_id": request.plan.id, "applied_state": deepcopy(applied),
                    "trajectory_replayed": False, "unsupported": [],
                    "experimental": list(requested), "effect_verified": False,
                    "delivery_verified": True,
                    "application_evidence": "backend_reported_not_pixel_verified",
                    "request_sha256": packet["request_sha256"],
                    "missing_audio_span": packet["missing_audio_span"],
                    "temporal_state_reset": ack.get("temporal_state_reset") is True,
                    "utterance_context": "complete", "visual_validation": "not_run",
                    "clock": "original_pcm_samples_not_speaker_or_display_time",
                }
                self._last_frame = part["sample_start"]
                index += 1
                self._receipt.update(status="rendering", frames=index)
                yield FaceFrame(request.plan.id, part["sample_start"],
                                request.audio.sample_rate, part["image"], "png", controls)
            if cancel.is_set():
                self._receipt["status"] = "cancelled"
                return
            if index != len(expected):
                raise ValueError("Backend omitted scheduled frames without an engine drop")
            self._ack(packet)  # Also require acknowledgement for a frame-free chunk.
            self._last_end = packet["global_sample_start"] + packet["sample_count"]
            self._rate = packet["sample_rate"]
            self._needs_reset = False
            self._receipt["status"] = "completed"
        except GeneratorExit:
            if self._receipt:
                self._receipt["status"] = "consumer_closed"
            raise
        except Exception:
            if self._receipt:
                self._receipt["status"] = "failed"
            if started:
                self._broken = True  # no uncertain partially advanced-state retry.
            raise
        finally:
            try:
                if iterator is not None and callable(getattr(iterator, "close", None)):
                    iterator.close()
            finally:
                if self._receipt and self._receipt["status"] != "completed":
                    self._needs_reset = True
                    if started:
                        self._broken = True
                self._lock.release()

    def _ack(self, packet):
        ack = self.backend.input_receipt()
        if (not isinstance(ack, dict)
                or ack.get("request_sha256") != packet["request_sha256"]
                or ack.get("trajectory_replayed") is not False
                or (packet["reset_temporal_state"] and ack.get("temporal_state_reset") is not True)):
            raise ValueError("Missing current PCM/motor acknowledgement or temporal reset")
        return ack

    def control_receipt(self, request):
        if (self._receipt is None or self._receipt["plan_id"] != request.plan.id
                or self._receipt["sample_start"] != request.global_sample_start):
            return {"plan_id": request.plan.id, "status": "not_reported",
                    "effect_verified": False}
        return deepcopy(self._receipt)

    def close(self):
        if not self._lock.acquire(False):
            raise RuntimeError("Cannot close while face inference owns the context")
        try:
            if self.backend is not None:
                self.backend.close()
                self.backend = None
            self._context = None
            self._closed = True
        finally:
            self._lock.release()


def create_face(options):
    return HamletFace(options)
