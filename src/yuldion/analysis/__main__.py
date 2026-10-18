import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
from .core import (prepare, validate, prompt, review, markdown, digest,
                   next_task, submit, human_input, rewind)
from .model import generate


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, state):
    descriptor, name = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(state, indent=2, ensure_ascii=False)+'\n')
            handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


@contextmanager
def locked(path):
    # Single-writer guard; retained lock file contains no script or credentials.
    with path.with_name(path.name+'.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main(argv=None):
    parser = argparse.ArgumentParser(description='YULDION · 한 항목씩 확인·확정하는 대본 분석')
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('init','status','propose','input','review','rewind','export','prompt'):
        sub = commands.add_parser(command)
        sub.add_argument('--state', type=Path, required=True)
        if command == 'init': sub.add_argument('--script',type=Path,required=True)
        if command == 'propose':
            group = sub.add_mutually_exclusive_group(required=True)
            group.add_argument('--model-config',type=Path)
            group.add_argument('--proposal-file',type=Path,help='외부 모델/사람이 작성한 제안 가져오기; 추론 실행 아님')
        if command == 'input': sub.add_argument('--text-file',type=Path,required=True)
        if command == 'review':
            group = sub.add_mutually_exclusive_group(required=True)
            group.add_argument('--approve',action='store_true')
            group.add_argument('--reject',action='store_true')
            sub.add_argument('--edited',type=Path)
        if command == 'rewind': sub.add_argument('--index',type=int,required=True)
        if command in ('export','prompt'): sub.add_argument('--output',type=Path,required=True)
    args = parser.parse_args(argv)
    try:
        with locked(args.state):
            if args.command == 'init':
                state = prepare(read(args.script))
                with args.state.open('x',encoding='utf-8') as handle:
                    handle.write(json.dumps(state,indent=2,ensure_ascii=False)+'\n')
                print('초기화 완료 · 모델 호출 없음')
                return 0
            state = read(args.state); validate(state)
            if args.command == 'status':
                print(json.dumps({'next':next_task(state),'pending':state['pending'],
                                  'approved_count':len(state['reviews'])},indent=2,ensure_ascii=False))
                return 0
            if args.command in ('export','prompt'):
                content = markdown(state) if args.command == 'export' else json.dumps(prompt(state),indent=2,ensure_ascii=False)
                with args.output.open('x',encoding='utf-8') as handle: handle.write(content+'\n')
                return 0
            if args.command == 'propose':
                messages = prompt(state)
                if args.proposal_file:
                    answer, receipt = read(args.proposal_file), {'origin':'imported_proposal','inference_executed':False}
                else:
                    answer, receipt = generate(read(args.model_config),messages)
                try:
                    submit(state,answer,{**receipt,'prompt_sha256':digest(messages)})
                except (ValueError, KeyError, TypeError):
                    state['history'].append({'event':'invalid_model_proposal',
                        'answer':answer,'receipt':receipt,'prompt_sha256':digest(messages)})
                    save(args.state,state)
                    raise
            elif args.command == 'input':
                human_input(state,args.text_file.read_text(encoding='utf-8'))
            elif args.command == 'review':
                review(state,args.approve,read(args.edited) if args.edited else None)
            elif args.command == 'rewind': rewind(state,args.index)
            save(args.state,state)
            print(json.dumps({'next':next_task(state),'pending':state['pending']},indent=2,ensure_ascii=False))
        return 0
    except (ValueError,KeyError,TypeError,OSError) as error:
        # Never echo provider bodies/headers or private prompts on failures.
        print('대본 분석 실패 ('+type(error).__name__+'): 입력·현재 단계·모델 설정을 확인하세요.',file=sys.stderr)
        return 2
    except Exception as error:
        print('모델/분석 오류 ('+type(error).__name__+') · 미확정 상태 유지',file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
