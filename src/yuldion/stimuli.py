"""Complete JSONL records only. Poll at safe speech checkpoints, never invent silence."""
import json
from pathlib import Path
from .errors import YuldionError
from .types import Observation

class FileStimuli:
    def __init__(self, path: Path):
        self.path = path
        self.seen = set()

    def __call__(self, segment):
        if not self.path.exists():
            return []
        results = []
        try:
            for line in self.path.read_text(encoding="utf-8").split("\n")[:-1]:
                if not line.strip():
                    continue
                data = json.loads(line)
                if set(data) - {"id", "kind", "text", "after_segment"}:
                    raise ValueError("Unknown stimulus fields")
                after = data.get("after_segment", 0)
                if type(after) is not int or after < 0:
                    raise ValueError("after_segment must be a nonnegative integer")
                observation = Observation(data["id"], data["kind"], data["text"])
                if observation.id not in self.seen and after <= segment:
                    results.append(observation)
                    self.seen.add(observation.id)
        except (ValueError, TypeError, KeyError) as error:
            raise YuldionError(f"자극 기록 오류: {error}") from error
        return results
