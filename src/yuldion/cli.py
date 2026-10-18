from __future__ import annotations
import argparse
from dataclasses import asdict
from pathlib import Path
import json
import signal
import sys
from threading import Event
from . import __version__
from .config import load_adapters, load_config
from .engine import Engine
from .errors import Cancelled, YuldionError
from .events import canonical
from .stimuli import FileStimuli

def main(argv=None):
    parser = argparse.ArgumentParser(prog="yuldion", description="YULDION · 화면 없는 AI 배우 핵심 엔진")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [("validate", "설정 구조 검사 · 모델 코드 실행 없음"),
                            ("doctor", "명시된 어댑터의 연결 상태 검사"),
                            ("run", "모델 어댑터를 사용한 실제 실행")]:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--config", type=Path, required=True)
        if name == "run":
            sub.add_argument("--events", type=Path, help="상대의 실제 텍스트 자극 JSONL")
            sub.add_argument("--max-seconds", type=float, default=300)
            sub.add_argument("--json-events", action="store_true", help="표준 출력에 실제 이벤트 JSONL")
    sub = commands.add_parser("inspect", help="저장된 이벤트 원문 확인 · 재추론 없음")
    sub.add_argument("journal", type=Path)
    args = parser.parse_args(argv)
    adapters = None
    try:
        if args.command == "inspect":
            for line in args.journal.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                print(canonical(event))
            return 0
        config = load_config(args.config)
        if args.command == "validate":
            print(f"설정 유효 · {len(config.script)}개 발화 조각 · 모델 로드/추론 없음")
            for role, spec in config.adapters.items():
                print(f"  {role}: {spec['kind']}")
            return 0
        adapters = load_adapters(config)
        if args.command == "doctor":
            healthy = True
            for role in ("reasoner", "voice", "face"):
                health = getattr(adapters, role).health()
                print(canonical({"role": role, **asdict(health)}))
                healthy = healthy and health.ready
            return 0 if healthy else 2
        cancel = Event()
        previous = {}
        def stop(*_):
            cancel.set()
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, stop)
        def observe(event):
            if args.json_events:
                print(canonical(event), flush=True)
            else:
                print(f"[{event['sequence']:04d}] {event['type']}", flush=True)
        try:
            directory = Engine(config, adapters, cancel).run(observe,
                FileStimuli(args.events) if args.events else None, args.max_seconds)
            print(f"실행 완료: {directory}", file=sys.stderr)
            return 0
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    except Cancelled as error:
        print(str(error), file=sys.stderr)
        return 130
    except (YuldionError, OSError, ValueError, TypeError) as error:
        print(f"YULDION: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"YULDION adapter failure ({type(error).__name__}): {error}", file=sys.stderr)
        return 1
    finally:
        if adapters is not None:
            adapters.close()
