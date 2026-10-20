"""Port for the preserved v66 B runtime; no model imports or resource startup.

A selected private factory attaches an explicitly prepared, exclusively owned B
runtime. This module never imports adjacent experiments, loads weights, builds
engines, downloads assets, starts services, or rents/stops compute.
"""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
from importlib import import_module
import json
import math
import re
import struct
import sys
from threading import Lock
from yuldion.types import AudioChunk, Health

MODEL_ID = 'hamlet-B-cosyvoice3-v66-l4'
# B is an observed runtime/reference configuration, not a newly trained checkpoint.
PROFILE = {
    'profile_id': MODEL_ID,
    'core': 'CosyVoice3-0.5B-base',
    'weights_sha256': {
        'llm.pt': '69f43bd545131c30e98947fb360ea8b4dc9916d8e83dded7757c7ea4f5a24970',
        'flow.pt': 'a6fab32a7825e5b0bc855ddd948f8db9370b0a786fbc249caa4595e95b608e4b',
        'hift.pt': 'b279d7641eb97ae55b3b540cfba4f953c26492a2df758328a89a4d007ab87a65'},
    'reference_sha256': '5ff5176b363445b9dc8fc8d7ba1cdae0d9866c7e75cb17c30939b681fc1fbd46',
    'reference_conditioning': {'acoustic_context_seconds': 3,
        'full_speaker_embedding_supplied': True, 'full_llm_fields_retained': True,
        'frontend_auxiliary_provider': 'CPUExecutionProvider'},
    'gpu': 'NVIDIA L4', 'torch': '2.8.0.dev20250319+cu128',
    'transformers': '4.51.3', 'sample_rate': 24000,
    'runtime_sources_sha256': {
        'b_runtime.py': '01015e97a02aa7a7cc9dc3e3c8fd420993e421826959f064ddd6aedfee601ca2',
        'profiling.py': 'ec6c75ee7d0d7e01008a9f74f67a91ac36e7050d699f8eb3fe51355a8a5afaa1',
        'decode_candidate.py': 'a7f685523c1a0f020c0a2eedb468a109a9d3795c92fc9717e8a8780eb1b6f6e7',
        'lm_candidate.py': 'bfa76a09283dfe2900e533c19022f0e2f43326aaeca316369f0ee4890654d63a',
        'linear_cache.py': '604caa292ea97464cc28d1e0b7dd00ab5204dac346192c27bf5fa04d8165f7b9',
        'trt_candidate.py': 'b1bc1a2f4f5cb348d6ede55b66565250017cf258f7b5719a4d49438e9e584770'},
}
PRESET = {'core': 'base', 'acoustics': 'current', 'reference': 'vtl',
          'seed': 5901, 'first_hop_tokens': 25, 'speed': 1.0,
          'engine': 'trt', 'precision': 'fp32', 'fast_lm': True,
          'decode_mode': 'graph_audio', 'optimized': True,
          'max_hop': 50, 'hop_policy': 'bridge'}
VOCAL = {'pace': {'slow', 'even', 'brisk', 'variable'},
         'volume': {'soft', 'conversational', 'firm', 'variable'},
         'pitch': {'low', 'middle', 'high', 'variable'}}


def profile():
    return deepcopy(PROFILE)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             allow_nan=False).encode()).hexdigest()


def verify_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError('B runtime must return an identity manifest')
    for key, expected in PROFILE.items():
        if manifest.get(key) != expected:
            raise ValueError('B identity mismatch: ' + key)
    if manifest.get('asset_verification') != 'sha256_readback':
        raise ValueError('B assets require explicit SHA256 readback')
    if manifest.get('prepared_request') != PRESET:
        raise ValueError('B prepared streaming configuration mismatch')
    return deepcopy(manifest)


def readback_manifest(weights, reference, runtime_sources, environment):
    """Explicit setup-time hash readback, never invoked by health/factory.

    Caller supplies private paths and observed runtime environment. Returned
    metadata excludes those paths. This checks files, not the tensors in GPU RAM.
    """
    from pathlib import Path
    def digest_file(path):
        h = sha256()
        with Path(path).open('rb') as f:
            for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
                h.update(block)
        return h.hexdigest()
    if set(weights) != set(PROFILE['weights_sha256']):
        raise ValueError('B weight file set differs')
    if set(runtime_sources) != set(PROFILE['runtime_sources_sha256']):
        raise ValueError('B runtime source set differs')
    required = {'gpu', 'torch', 'transformers', 'sample_rate', 'reference_conditioning'}
    if set(environment) != required:
        raise ValueError('Observed B environment fields are required')
    result = {**deepcopy(PROFILE), **deepcopy(environment),
              'weights_sha256': {k: digest_file(v) for k, v in weights.items()},
              'reference_sha256': digest_file(reference),
              'runtime_sources_sha256': {k: digest_file(v) for k, v in runtime_sources.items()},
              'asset_verification': 'sha256_readback', 'prepared_request': deepcopy(PRESET)}
    return verify_manifest(result)


class BVoice:
    """Lazy attachment to a prepared runtime; effects require separate evaluation."""
    def __init__(self, options):
        allowed = {'backend_factory', 'backend_options', 'allow_experimental'}
        if set(options) - allowed:
            raise ValueError('Unknown B adapter option')
        self.options = deepcopy(options)
        factory = options.get('backend_factory', '')
        if not isinstance(factory, str) or factory.count(':') != 1:
            raise ValueError('Explicit prepared B backend_factory is required')
        if type(options.get('allow_experimental', False)) is not bool:
            raise ValueError('allow_experimental must be boolean')
        self.backend = None
        self.manifest = None
        self._lock = Lock()
        self._receipts = OrderedDict()
        self._closed = False

    def health(self):
        if self._closed:
            return Health(False, 'B adapter closed', MODEL_ID)
        if self.backend is None:
            return Health(True, 'Factory configured only; B attachment/inference unverified', MODEL_ID)
        result = self.backend.health()
        return Health(result.ready, result.message, MODEL_ID)

    def capabilities(self):
        controls = {
            'delivery': ('supported', 'exact generated instruction to B prompt; no style added'),
            'pace': ('experimental', 'natural-language instruction; numeric speed fixed at 1'),
            'volume': ('experimental', 'natural-language instruction; no gain processing'),
            'pitch': ('experimental', 'natural-language instruction; no pitch processing'),
            'articulation': ('experimental', 'natural-language instruction; no phoneme overrides'),
            'stress': ('experimental', 'up to two exact unique source spans -> strong markup'),
            'pause_ms': ('supported', 'additional trailing zero PCM once after native completion'),
            'breath': ('unsupported', 'native spontaneous breath only; no requested breath control')}
        return {'schema_version': 1, 'model_id': MODEL_ID,
                'controls': {k: {'status': status, 'transport': route, 'effect_verified': False}
                             for k, (status, route) in controls.items()}}

    def _compile(self, request):
        p = request.plan.performance
        text, instruction = request.text, p.delivery
        if not isinstance(text, str) or not 0 < len(text) <= 900 or any(c in text for c in '<>[]'):
            raise ValueError('B requires bounded original dialogue without control tags')
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) >= 500:
            raise ValueError('B requires generated instruction shorter than 500 characters')
        if any(c in instruction for c in '<>[]'):
            raise ValueError('Instruction must not inject model control delimiters')
        if type(p.pause_ms) is not int or not 0 <= p.pause_ms <= 10000:
            raise ValueError('Invalid additional trailing pause_ms')
        if type(p.breath) is not bool or p.breath:
            raise ValueError('Requested breath is unsupported by B')
        vocal = p.vocal if p.vocal is not None else {}
        if not isinstance(vocal, dict) or set(vocal) - {'pace', 'volume', 'pitch', 'articulation', 'stress'}:
            raise ValueError('Unknown B vocal field')
        for key, choices in VOCAL.items():
            if key in vocal and (not isinstance(vocal[key], str) or vocal[key] not in choices):
                raise ValueError('Invalid B vocal ' + key)
        if 'articulation' in vocal and (not isinstance(vocal['articulation'], str) or not vocal['articulation'].strip()):
            raise ValueError('Invalid B articulation')
        if set(vocal) - {'stress'}:
            from yuldion.vocal import vocal_delivery
            if vocal_delivery(vocal, text) != instruction:
                raise ValueError('B structured vocal controls differ from generated delivery')
        spans = vocal.get('stress', [])
        if not isinstance(spans, list) or len(spans) > 2:
            raise ValueError('B supports at most two stress spans')
        ranges = []
        for span in spans:
            if not isinstance(span, str) or not span.strip():
                raise ValueError('Invalid stress span')
            matches = list(re.finditer(r'(?<!\w)' + re.escape(span) + r'(?!\w)', text))
            if len(matches) != 1:
                raise ValueError('B stress requires one exact unique whole source span')
            ranges.append((matches[0].start(), matches[0].end()))
        ranges.sort()
        if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
            raise ValueError('Overlapping stress spans')
        active = [k for k in vocal if k != 'stress' or spans]
        if active and not self.options.get('allow_experimental', False):
            raise ValueError('Experimental B controls require explicit opt-in: ' + ', '.join(active))
        rendered = text
        for start, end in reversed(ranges):
            rendered = rendered[:start] + '<strong>' + rendered[start:end] + '</strong>' + rendered[end:]
        q = {**PRESET, 'text': rendered, 'instruction': instruction}
        requested = {'delivery': instruction, **deepcopy(vocal), 'pause_ms': p.pause_ms, 'breath': p.breath}
        fingerprint = _digest({'text': text, 'requested': requested})
        return q, requested, fingerprint

    def _attach(self):
        if self._closed:
            raise RuntimeError('B adapter closed')
        if self.backend is not None:
            verify_manifest(self.backend.describe())
            if not self.backend.health().ready:
                raise RuntimeError('Prepared B backend is no longer ready')
            return
        module, name = self.options['backend_factory'].split(':')
        backend = getattr(import_module(module), name)(deepcopy(self.options.get('backend_options', {})))
        try:
            for method in ('describe', 'health', 'stream', 'input_receipt', 'close'):
                if not callable(getattr(backend, method, None)):
                    raise ValueError('Prepared B backend lacks ' + method)
            manifest = verify_manifest(backend.describe())
            if not backend.health().ready:
                raise RuntimeError('B must be explicitly prepared before attachment')
        except BaseException:
            if callable(getattr(backend, 'close', None)):
                backend.close()
            raise
        self.backend, self.manifest = backend, manifest

    def synthesize(self, request, cancel):
        if cancel.is_set():
            return
        q, requested, fingerprint = self._compile(request)
        if not self._lock.acquire(False):
            raise RuntimeError('B supports only one inference owner')
        if request.plan.id in self._receipts:
            self._lock.release()
            raise ValueError('B plan ID has already been submitted; no automatic replay')
        record = {'plan_id': request.plan.id, 'status': 'started', 'request_sha256': fingerprint,
                  'model_id': MODEL_ID, 'controls': {}, 'effect_verified': False,
                  'scope': 'backend input acknowledgement and PCM; not perceptual validation',
                  'native_samples': 0, 'added_pause_samples': 0}
        self._receipts[request.plan.id] = record
        self._receipts.move_to_end(request.plan.id)
        while len(self._receipts) > 64:
            self._receipts.popitem(last=False)
        iterator = None
        offset = 0
        try:
            self._attach()
            if cancel.is_set():
                record['status'] = 'cancelled'
                return
            iterator = iter(self.backend.stream(deepcopy(q), cancel))
            for part in iterator:
                if cancel.is_set():
                    record['status'] = 'cancelled'
                    return
                if not isinstance(part, dict) or part.get('sample_start') != offset or type(part.get('sample_start')) is not int:
                    raise ValueError('B backend PCM sample positions must be contiguous')
                sr, raw = part.get('sample_rate'), part.get('pcm_f32le')
                if type(sr) is not int or sr != PROFILE['sample_rate']:
                    raise ValueError('B sample rate differs from preserved profile')
                if not isinstance(raw, bytes) or not raw or len(raw) % 4 or len(raw) > 16*1024*1024:
                    raise ValueError('B backend must return bounded mono f32le PCM')
                if any(not math.isfinite(x) or abs(x) >= 1 for (x,) in struct.iter_unpack('<f', raw)):
                    raise ValueError('B backend returned nonfinite or clipped PCM')
                # An acknowledgement is evidence of backend input, never acoustic effect.
                ack = self.backend.input_receipt()
                if not isinstance(ack, dict) or ack.get('request_sha256') != _digest(q):
                    raise ValueError('B backend did not acknowledge the actual model request')
                for key, value in requested.items():
                    delivered = q['instruction'] if key == 'delivery' else (
                        {'instruction': q['instruction'], 'requested_value': deepcopy(value)}
                        if key in VOCAL or key == 'articulation' else (
                        {'spans': deepcopy(value), 'model_text': q['text']} if key == 'stress' else None))
                    active = not ((key == 'stress' and value == []) or (key == 'pause_ms' and value == 0) or (key == 'breath' and value is False))
                    if not active:
                        delivered = None
                    record['controls'][key] = {'requested': deepcopy(value), 'active': active, 'delivered_value': delivered,
                        'delivery_verified': active and key not in {'pause_ms', 'breath'}, 'effect_verified': False,
                        'status': self.capabilities()['controls'][key]['status']}
                count = len(raw)//4
                record['native_samples'] += count
                yield AudioChunk(request.plan.id, offset, sr, raw)
                offset += count
            if cancel.is_set():
                record['status'] = 'cancelled'
                return
            if not offset:
                raise RuntimeError('B produced no native audio')
            remaining = round(PROFILE['sample_rate'] * requested['pause_ms']/1000)
            while remaining:
                if cancel.is_set():
                    record['status'] = 'cancelled'
                    return
                count = min(remaining, PROFILE['sample_rate'])
                record['added_pause_samples'] += count
                yield AudioChunk(request.plan.id, offset, PROFILE['sample_rate'], bytes(count*4))
                offset += count
                remaining -= count
            record['controls']['pause_ms'] = {'requested': requested['pause_ms'], 'active': requested['pause_ms'] != 0,
                'delivered_value': {'additional_trailing_samples': record['added_pause_samples'],
                                    'sample_rate': PROFILE['sample_rate']},
                'delivery_verified': requested['pause_ms'] != 0, 'effect_verified': False, 'status': 'supported'}
            record['controls']['breath'] = {'requested': False, 'active': False, 'delivered_value': None,
                'delivery_verified': False, 'effect_verified': False, 'status': 'unsupported'}
            record['status'] = 'completed'
        except GeneratorExit:
            record['status'] = 'consumer_closed'
            raise
        except BaseException:
            record['status'] = 'failed'
            raise
        finally:
            try:
                if iterator is not None and callable(getattr(iterator, 'close', None)):
                    iterator.close()
            finally:
                self._lock.release()

    def control_receipt(self, request):
        _, _, fingerprint = self._compile(request)
        record = self._receipts.get(request.plan.id)
        if record is None:
            return {'plan_id': request.plan.id, 'status': 'not_reported', 'effect_verified': False}
        if record['request_sha256'] != fingerprint:
            raise ValueError('B plan ID reused for different voice controls')
        return deepcopy(record)

    def close(self):
        if not self._lock.acquire(False):
            raise RuntimeError('Cancel and drain the owned B request before close')
        try:
            self._closed = True
            if self.backend is not None:
                self.backend.close()
                self.backend = None
        finally:
            self._lock.release()


class PreparedV66Backend:
    """Facade for already-prepared v66 components in a dedicated inference worker.

    It does not construct, patch, warm or close the supplied model. The selected
    factory owns preparation and supplies asset/environment readback. Cancellation
    drains native inference without emitting late PCM, so cleanup can block until
    the native utterance finishes. No shared training/process termination.
    """
    def __init__(self, voice, engine, lm_candidate, decoder, profiler, manifest):
        self.voice, self.engine, self.lm = voice, engine, lm_candidate
        self.decoder, self.profiler = decoder, profiler
        self.manifest = verify_manifest(manifest)
        self._lock = Lock()
        self._ack = None
        self.closed = False
        self.broken = False

    def describe(self):
        return deepcopy(self.manifest)

    def health(self):
        ready = (not self.closed and not self.broken and self.decoder.ready and 'fp32' in self.engine.engines
                 and len(self.decoder.graphs) == 353)
        return Health(bool(ready), 'Prepared B component flags; live output not revalidated', MODEL_ID)

    def stream(self, q, cancel):
        if cancel.is_set():
            return
        if not self.health().ready or not self._lock.acquire(False):
            raise RuntimeError('B runtime unavailable or already active')
        iterator = None
        try:
            if {k: q.get(k) for k in PRESET} != PRESET:
                raise ValueError('B runtime preset changed')
            self.engine.compiled = self.engine.engines['fp32']
            self.engine.precision, self.engine.requested = 'fp32', 'trt'
            self.lm.enabled = True
            self.profiler.begin(True, 50, 'bridge')
            self.decoder.begin('graph_audio', False)
            native = {k: q[k] for k in ('text', 'instruction', 'core', 'acoustics', 'reference', 'seed', 'first_hop_tokens')}
            self._ack = None
            iterator = iter(self.voice.stream(native))
            for part in iterator:
                self._ack = {'request_sha256': _digest(q), 'scope': 'native Voice.stream yielded audio'}
                if cancel.is_set():
                    continue  # Drain native thread/cache cleanup, discard late audio.
                x = memoryview(part['array'])
                if x.ndim != 1 or x.format != 'f' or not x.c_contiguous or sys.byteorder != 'little':
                    raise ValueError('Native B requires contiguous little-endian float32')
                yield {'pcm_f32le': x.tobytes(), 'sample_rate': part['sr'],
                       'sample_start': part['start_sample'], 'generation_arrival_s': part['arrival_s']}
        except Exception:
            self.broken = True
            raise
        finally:
            try:
                if iterator is not None:
                    # Consumer cancellation must not leave CosyVoice's worker/cache in flight.
                    for _ in iterator:
                        pass
                    close = getattr(iterator, 'close', None)
                    if close:
                        close()
            except BaseException:
                self.broken = True
                raise
            finally:
                self._lock.release()

    def input_receipt(self):
        return deepcopy(self._ack)

    def close(self):
        if not self._lock.acquire(False):
            raise RuntimeError('B runtime is still draining')
        try:
            self.closed = True  # Detach only; component/model/process owner handles teardown.
        finally:
            self._lock.release()


def create_voice(options):
    return BVoice(options)
