"""Lazy, inference-only CosyVoice3 port. No private runtime patches or assets."""
from pathlib import Path
import importlib.util
import math
import struct
from yuldion.types import AudioChunk, Health


class CosyVoice:
    def __init__(self, options):
        self.options = dict(options)
        self.model = None
        self.checkpoint = Path(options['checkpoint'])
        self.reference = Path(options['reference'])
        self.model_id = options.get('model_id', 'cosyvoice3-unverified')

    def health(self):
        ready = ((self.checkpoint / 'cosyvoice3.yaml').is_file()
                 and self.reference.is_file()
                 and importlib.util.find_spec('cosyvoice') is not None)
        return Health(ready, 'Local files/package check only; inference and quality unverified', self.model_id)

    def synthesize(self, request, cancel):
        performance = request.plan.performance
        if not performance.delivery.strip():
            raise ValueError('Generated delivery is required')
        if '<|endofprompt|>' in performance.delivery:
            raise ValueError('Delivery must not contain model protocol delimiters')
        if type(performance.pause_ms) is not int or not 0 <= performance.pause_ms <= 10000:
            raise ValueError('pause_ms must be an integer in 0..10000')
        # Breath support is checkpoint-specific; do not silently ignore or fake it.
        if performance.breath:
            raise ValueError('Verified breath-token support is not implemented for this adapter')
        if cancel.is_set():
            return
        if self.model is None:
            if not self.health().ready:
                raise RuntimeError('CosyVoice files/package are not ready')
            from cosyvoice.cli.cosyvoice import CosyVoice3
            self.model = CosyVoice3(str(self.checkpoint), load_trt=False,
                                   fp16=bool(self.options.get('fp16', True)))
        if cancel.is_set():
            return
        sr = int(self.model.sample_rate)
        instruction = performance.delivery.strip() + '<|endofprompt|>'
        iterator = self.model.inference_instruct2(
            request.text, instruction, str(self.reference), stream=True,
            speed=1.0, text_frontend=False)
        offset = 0
        try:
            for item in iterator:
                if cancel.is_set():
                    return
                tensor = item['tts_speech'].detach().float().cpu()
                if len(tensor.shape) != 2 or tensor.shape[0] != 1:
                    raise ValueError('Expected CosyVoice mono tensor [1, samples]')
                samples = tensor.reshape(-1).tolist()
                if not samples:
                    continue
                if len(samples) > 4000000 or not all(math.isfinite(x) for x in samples):
                    raise ValueError('Invalid CosyVoice audio chunk')
                yield AudioChunk(request.plan.id, offset, sr,
                                 struct.pack('<%df' % len(samples), *samples))
                offset += len(samples)
            if not offset:
                raise RuntimeError('CosyVoice produced no audio')
            # Exactly one trailing planned pause; never prepend a style or old recording.
            remaining = round(sr * performance.pause_ms / 1000)
            while remaining and not cancel.is_set():
                count = min(remaining, sr)
                yield AudioChunk(request.plan.id, offset, sr, bytes(count * 4))
                offset += count
                remaining -= count
        finally:
            close = getattr(iterator, 'close', None)
            if close:
                close()

    def close(self):
        self.model = None


def create_voice(options):
    return CosyVoice(options)
