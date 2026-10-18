from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import importlib
import json
from .adapters.unconfigured import Unconfigured
from .errors import YuldionError
from .types import Adapters, Scene

ROLES = ("reasoner", "voice", "face")
METHODS = {"reasoner": ("propose", "audit", "perform"), "voice": ("synthesize",), "face": ("render",)}

@dataclass(frozen=True)
class Config:
    scene: Scene
    script: tuple[str, ...]
    adapters: dict
    output_dir: Path

def load_config(path: Path) -> Config:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1:
            raise ValueError("schema_version must be 1")
        if not isinstance(raw.get("scene"), dict):
            raise ValueError("scene must be an object")
        scene = Scene(**raw["scene"])
        if not all(isinstance(value, str) and value.strip() for value in vars(scene).values()):
            raise ValueError("Every scene field must be a nonempty string")
        script = raw.get("script")
        if not isinstance(script, list) or not script or not all(isinstance(s, str) and s.strip() for s in script):
            raise ValueError("script must be an explicit nonempty array of speech fragments")
        adapters = raw.get("adapters")
        if not isinstance(adapters, dict) or set(adapters) != set(ROLES):
            raise ValueError("adapters must declare reasoner, voice and face separately")
        for role, spec in adapters.items():
            if not isinstance(spec, dict) or spec.get("kind") not in ("unconfigured", "python"):
                raise ValueError(f"Invalid adapter: {role}")
            if spec["kind"] == "python":
                entrypoint = spec.get("entrypoint", "")
                if not isinstance(entrypoint, str) or len(entrypoint.split(":")) != 2 or not all(entrypoint.split(":")):
                    raise ValueError(f"{role}: entrypoint must be installed_module:factory")
                if not isinstance(spec.get("options", {}), dict):
                    raise ValueError(f"{role}: options must be an object")
        output = raw.get("output_dir", "outputs")
        if not isinstance(output, str) or not output:
            raise ValueError("output_dir must be a path string")
        output_dir = Path(output).expanduser()
        if not output_dir.is_absolute():
            output_dir = path.resolve().parent / output_dir
        return Config(scene, tuple(script), deepcopy(adapters), output_dir)
    except (OSError, ValueError, TypeError) as error:
        raise YuldionError(f"설정 오류: {error}") from error

def load_adapters(config: Config) -> Adapters:
    loaded = {}
    try:
        for role in ROLES:
            spec = config.adapters[role]
            if spec["kind"] == "unconfigured":
                adapter = Unconfigured(role)
            else:
                module, factory = spec["entrypoint"].split(":")
                # Explicit opt-in plugin execution. No pip installs, weight downloads or training.
                adapter = getattr(importlib.import_module(module), factory)(deepcopy(spec.get("options", {})))
                loaded[role] = adapter
                for method in ("health", "close", *METHODS[role]):
                    if not callable(getattr(adapter, method, None)):
                        raise TypeError(f"{role} adapter lacks {method}()")
            loaded[role] = adapter
        return Adapters(**loaded)
    except Exception as error:
        for adapter in loaded.values():
            try:
                adapter.close()
            except Exception:
                pass
        raise YuldionError(f"어댑터 로드 실패: {error}") from error
