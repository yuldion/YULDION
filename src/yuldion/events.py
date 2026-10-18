"""Append-only event journal, plus independent subscribers for future UIs/transports."""
from dataclasses import asdict, is_dataclass
from pathlib import Path
from threading import Lock
from typing import Callable
import json
import time

def jsonable(value):
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Not JSON-serializable: {type(value).__name__}")

def canonical(value) -> str:
    return json.dumps(value, default=jsonable, ensure_ascii=False, sort_keys=True, allow_nan=False)

class Journal:
    def __init__(self, directory: Path, run_id: str):
        self.run_id = run_id
        self.path = directory / "events.jsonl"
        self._file = self.path.open("x", encoding="utf-8")
        self._start = time.monotonic()
        self._sequence = 0
        self._lock = Lock()
        self._listeners: list[Callable] = []

    def subscribe(self, callback: Callable) -> None:
        self._listeners.append(callback)

    def emit(self, event_type: str, **payload):
        with self._lock:
            self._sequence += 1
            event = {"schema_version": 1, "run_id": self.run_id, "sequence": self._sequence,
                     "elapsed_s": time.monotonic() - self._start, "type": event_type, "payload": payload}
            self._file.write(canonical(event) + "\n")
            self._file.flush()
        for listener in tuple(self._listeners):
            try:
                listener(event)
            except Exception:
                # An observer must not stop the actor or corrupt the authoritative journal.
                pass
        return event

    def close(self):
        self._file.close()
