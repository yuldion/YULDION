"""Whole-script preparation followed by connected acting plans, without media backends."""
import argparse
from dataclasses import asdict
import getpass
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import uuid
from .config import load_config
from .pipeline import model_options, write_new
from .providers import authentication_ready
from .preparation import prepare, bind_config


def provenance(config_path):
    root=Path(__file__).resolve().parent
    names=('preparation.py','preparation_cli.py','engine.py','config.py','types.py','capabilities.py','face_capabilities.py','streaming.py',
           'tools/inspector/server.py','inference.py','review.py','planning.py','vocal.py','acting_score.py','adapters/chat_reasoner.py','tools/action_verbs/core.py')
    return {'config_sha256':sha256(config_path.read_bytes()).hexdigest(),
            'source_sha256':{name:sha256((root/name).read_bytes()).hexdigest() for name in names}}


def main(argv):
    parser=argparse.ArgumentParser(prog='yuldion pipeline')
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('prepare','review','plan','bind'):
        sub=commands.add_parser(name)
        sub.add_argument('--config',type=Path,required=True)
        if name=='bind':
            sub.add_argument('--preparation',type=Path,required=True)
            sub.add_argument('--bound-config',type=Path,required=True)
            sub.add_argument('--allow-draft',action='store_true',required=True)
            continue
        sub.add_argument('--output-dir',type=Path,required=True)
        sub.add_argument('--prompt-api-key',action='store_true')
        sub.add_argument('--resume-from',type=Path)
        if name in ('prepare','review'):sub.add_argument('--bound-config',type=Path,required=True)
        if name=='prepare':
            sub.add_argument('--allow-draft',action='store_true',required=True)
            sub.add_argument('--max-calls',type=int,default=128)
            sub.add_argument('--max-seconds',type=float,default=600)
        if name=='plan':
            sub.add_argument('--segments',type=int,help='Number of consecutive source lines; default all')
            sub.add_argument('--extend-from',type=Path)
    args=parser.parse_args(argv)
    temporary_key=None
    try:
        if args.command=='bind':
            bind_config(args.config,args.preparation,args.bound_config,args.allow_draft)
            return 0
        if args.output_dir.exists():raise FileExistsError('Use a fresh output directory')
        if args.command in ('prepare','review') and args.bound_config.exists():raise FileExistsError('Use a fresh bound config path')
        config=load_config(args.config)
        options=model_options(config)
        if args.command=='prepare' and config.preparation:raise ValueError('Prepare from the original scene config')
        if args.command in ('review','plan') and (not config.preparation or not config.preparation.get('acting_score')):
            raise ValueError('Completed linked preparation required')
        if args.command=='plan':
            if not config.review:raise ValueError('Semantic review must pass before acting')
            if args.segments is not None and not 1<=args.segments<=len(config.execution_script):raise ValueError('Invalid segment count')
        if args.prompt_api_key and options['provider']!='openai':raise ValueError('Key prompt is for OpenAI only')
        if not authentication_ready(options):
            if not args.prompt_api_key:raise ValueError('API key required')
            value=getpass.getpass('OpenAI API key (not saved): ').strip()
            if not value:raise ValueError('Empty API key')
            temporary_key=options['api_key_env'];os.environ[temporary_key]=value
        args.output_dir.mkdir(parents=True,exist_ok=False)
        if args.command=='prepare':
            document=args.output_dir/'preparation.json'
            try:
                prepare(config,options,document,args.max_calls,args.max_seconds,resume_from=args.resume_from,
                    observe=lambda step:print(json.dumps({'stage':step['task'],'status':step['status']},ensure_ascii=False),flush=True))
            finally:
                if document.exists():
                    saved=json.loads(document.read_text())
                    write_new(args.output_dir/'manifest.json',{**provenance(args.config),'status':saved['status'],
                        'preparation_sha256':sha256(document.read_bytes()).hexdigest(),
                        'provider':options['provider'],'model':options['model'],'voice_face_loaded':False,
                        'human_approved':False,'backup_status':'unverified'})
            bind_config(args.config,document,args.bound_config,allow_draft=True)
            print('전체 대본 분석 저장 완료. 의미 검수는 별도 단계입니다.')
            return 0
        if args.command=='review':
            from .review import run_review,bind_review
            raw=json.loads(args.config.read_text());document=Path(raw['preparation']['path'])
            if not document.is_absolute():document=args.config.resolve().parent/document
            review_path=args.output_dir/'review.json'
            try:record=run_review(document,options,review_path,args.resume_from)
            finally:
                if review_path.exists():
                    r=json.loads(review_path.read_text())
                    write_new(args.output_dir/'manifest.json',{**provenance(args.config),'status':r['status'],
                        'preparation_sha256':r['preparation_sha256'],'review_sha256':sha256(review_path.read_bytes()).hexdigest(),
                        'voice_face_loaded':False,'human_approved':False,'backup_status':'unverified'})
            if record['status']!='passed':
                print('의미 검수: 수정 필요. 연기 실행은 차단했습니다.')
                return 3
            bind_review(args.config,review_path,args.bound_config)
            print('모델 의미 검수 통과. 사람의 수행 검증은 미수행입니다.')
            return 0
        from .planning import run_plans
        output=args.output_dir/'result.json'
        try:
            run_plans(config,options,args.output_dir,args.segments,args.resume_from,extend_from=args.extend_from,
                on_plan=lambda row:print(json.dumps(row,ensure_ascii=False),flush=True))
        finally:
            if output.exists():
                record=json.loads(output.read_text())
                write_new(args.output_dir/'manifest.json',{**provenance(args.config),
                    'preparation_sha256':record['preparation_sha256'],'review_sha256':record['review_sha256'],
                    'result_sha256':sha256(output.read_bytes()).hexdigest(),'status':record['status'],
                    'failure':record.get('failure'),'next_segment':record['next_segment'],
                    'voice_face_loaded':False,'backup_status':'unverified'})
        return 0
    except KeyboardInterrupt:return 130
    except Exception as error:
        from .errors import failure_record
        print('Pipeline failed: '+json.dumps(failure_record(error),ensure_ascii=False),file=sys.stderr)
        return 2
    finally:
        if temporary_key is not None:os.environ.pop(temporary_key,None)
