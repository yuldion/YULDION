"""Explicit port for a live audio + motor + gaze renderer, never a trajectory player."""
from importlib import import_module
from yuldion.types import FaceFrame, Health

REQUIRED = frozenset({'received_audio', 'generated_motor', 'generated_gaze', 'no_trajectory_replay'})


class ControlledFace:
    def __init__(self, options):
        self.options = dict(options)
        self.backend = None
        self.last_sample = -1

    def health(self):
        # No import/factory/GPU access from doctor. Backend readiness needs explicit validation.
        configured = (self.options.get('enabled') is True
                      and isinstance(self.options.get('backend_factory'), str)
                      and self.options['backend_factory'].count(':') == 1)
        return Health(configured, 'Configuration check only; live backend and GPU unverified',
                      self.options.get('model_id', 'face-unverified'))

    def _load(self):
        module, factory = self.options['backend_factory'].split(':')
        backend = getattr(import_module(module), factory)(dict(self.options.get('backend_options', {})))
        try:
            if not REQUIRED.issubset(set(backend.capabilities)):
                raise ValueError('Face backend lacks live audio/motor/gaze or forbids no replay guarantee')
            if not backend.health().ready:
                raise RuntimeError('Face backend is not ready')
            if not callable(getattr(backend, 'render', None)):
                raise ValueError('Face backend must implement render')
        except Exception:
            backend.close()
            raise
        self.backend = backend

    def render(self, request, cancel):
        if cancel.is_set():
            return
        if self.backend is None:
            self._load()
        if cancel.is_set():
            return
        iterator = iter(self.backend.render(request, cancel))
        try:
            for frame in iterator:
                if cancel.is_set():
                    return
                if not isinstance(frame, FaceFrame):
                    raise ValueError('Face backend must return FaceFrame')
                if frame.plan_id != request.plan.id or frame.sample_rate != request.audio.sample_rate:
                    raise ValueError('Face backend changed plan or clock')
                end = request.global_sample_start + len(request.audio.pcm_f32le) // 4
                if not request.global_sample_start <= frame.sample_start < end or frame.sample_start <= self.last_sample:
                    raise ValueError('Invalid face sample position')
                receipt = frame.controls
                if (receipt.get('requested_motor') != dict(request.plan.performance.motor)
                        or receipt.get('applied_plan_id') != request.plan.id
                        or receipt.get('trajectory_replayed') is not False
                        or not isinstance(receipt.get('applied_state'), dict)
                        or not receipt['applied_state']):
                    raise ValueError('Missing live motor/plan/application receipt')
                self.last_sample = frame.sample_start
                yield frame
        finally:
            close = getattr(iterator, 'close', None)
            if close:
                close()

    def close(self):
        if self.backend is not None:
            self.backend.close()
            self.backend = None


def create_face(options):
    return ControlledFace(options)
