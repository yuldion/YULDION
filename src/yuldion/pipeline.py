"""Selectable interpretation pipeline; no training or implicit model provisioning."""
import argparse
import getpass
import os
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from . import __version__
from .config import load_config
from .providers import provider_options, validate_provider, authentication_ready


def write_new(path, value):
    with path.open('x',encoding='utf-8') as handle:
        handle.write(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def model_options(config):
    spec=config.adapters['reasoner']
    if spec.get('entrypoint')!='yuldion.adapters.chat_reasoner:create_reasoner':
        raise ValueError('Pipeline requires the built-in chat reasoner; other adapters use yuldion run')
    return validate_provider(spec['options'])


def main(argv=None):
    arguments=list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in ('prepare','review','plan','bind'):
        from .preparation_cli import main as ordered_main
        return ordered_main(arguments)
    parser=argparse.ArgumentParser(prog='yuldion pipeline',description='OpenAI / local interpretation pipeline')
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('prepare',help='전체 대본을 원래 순서대로 분석하고 배우 설정에 연결')
    commands.add_parser('review',help='준비된 분석의 근거·시간 순서·전환을 검수; 새 해석 생성 없음')
    commands.add_parser('bind',help='수정한 분석 문서를 새 설정에 연결; 모델 호출 없음')
    commands.add_parser('plan',help='전체 분석 기반으로 첫 대사부터 연속 연기 계획 생성; 미디어 로드 없음')
    init=commands.add_parser('init',help='장면 복사·제공자 선택; 모델/네트워크 실행 없음')
    init.add_argument('--scene',type=Path,required=True)
    init.add_argument('--provider',choices=('openai','local'),required=True)
    init.add_argument('--config',type=Path,required=True)
    init.add_argument('--model')
    init.add_argument('--endpoint')
    init.add_argument('--api-key-env',default='OPENAI_API_KEY')
    init.add_argument('--output-dir',default='../outputs')
    for name in ('check','interpret','run'):
        sub=commands.add_parser(name,help={'check':'설정·키 존재 검사; 통신/모델 로드 없음',
              'interpret':'첫 대사만 실제 해석; 음성/얼굴 로드 없음',
              'run':'연결한 음성·얼굴까지 배우 엔진 실행'}[name])
        sub.add_argument('--config',type=Path,required=True)
        if name in ('interpret','run'):
            sub.add_argument('--diagnostic-unprepared','--diagnostic-reanalyse',dest='diagnostic_unprepared',action='store_true',help='Explicit legacy diagnostic without whole-script preparation')
            sub.add_argument('--prompt-api-key',action='store_true',help='OpenAI 키가 없으면 숨김 입력; 파일 저장 없음')
        if name=='interpret':
            sub.add_argument('--output-dir',type=Path)
            sub.add_argument('--focus-index',type=int,default=0,help='분석할 script 배열 인덱스; 0부터 시작')
            sub.add_argument('--context',choices=('current-line','full-script'),default='current-line',
                             help='현재 구절만 또는 설정의 대본 전체를 준비 맥락으로 제공')
        if name=='run':
            sub.add_argument('--max-seconds',type=float,default=300)
            sub.add_argument('--events',type=Path)
    serve=commands.add_parser('serve-local',help='명시한 GGUF로 독립 llama.cpp 서버 전경 실행')
    serve.add_argument('--model-path',type=Path,required=True)
    serve.add_argument('--binary',default='llama-server')
    serve.add_argument('--model-id',default='yuldion-qwen3-8b')
    serve.add_argument('--port',type=int,default=8080)
    serve.add_argument('--gpu-layers',type=int,default=0)
    serve.add_argument('--context-size',type=int,default=4096)
    serve.add_argument('--threads',type=int,default=4)
    args=parser.parse_args(argv)
    temporary_key=None
    try:
        if args.command=='init':
            load_config(args.scene)  # Structural validation only; never load plugins.
            raw=json.loads(args.scene.read_text(encoding='utf-8'))
            raw['adapters']['reasoner']={'kind':'python',
                'entrypoint':'yuldion.adapters.chat_reasoner:create_reasoner',
                'options':provider_options(args.provider,args.model,args.endpoint,args.api_key_env)}
            raw['output_dir']=args.output_dir
            # Private parent creation only; never overwrite an existing config.
            args.config.parent.mkdir(parents=True,exist_ok=True)
            write_new(args.config,raw)
            print('설정 생성 완료 · 키 값 저장/모델 로드/네트워크 호출 없음')
            return 0
        if args.command=='serve-local':
            if not args.model_path.is_file():raise ValueError('Existing GGUF model file required')
            if not 1024<=args.port<=65535 or not 1<=args.threads<=64 or not 0<=args.gpu_layers<=999 or not 4096<=args.context_size<=131072:
                raise ValueError('Invalid server resource option')
            binary=shutil.which(args.binary)
            if binary is None:raise ValueError('Install llama.cpp or provide --binary')
            command=[binary,'-m',str(args.model_path.resolve()),'--host','127.0.0.1',
                '--port',str(args.port),'--alias',args.model_id,'-c',str(args.context_size),'-np','1',
                '-t',str(args.threads),'-tb',str(args.threads),'-ngl',str(args.gpu_layers),
                '--jinja','--reasoning','off']
            return subprocess.run(command,check=False).returncode
        config=load_config(args.config)
        if args.command in ('interpret','run') and not config.preparation and not args.diagnostic_unprepared:
            raise ValueError('Whole-script preparation required; use pipeline prepare first')
        if args.command=='interpret' and not args.diagnostic_unprepared:
            raise ValueError('interpret is an explicit reanalysis diagnostic; use plan for prepared performance')
        options=model_options(config)
        ready=authentication_ready(options)
        if args.command=='check':
            print(json.dumps({'provider':options['provider'],'model':options['model'],
                'configuration_valid':True,'authentication_present':ready,
                'connectivity':'not_tested','inference':'not_run',
                'voice_configured':config.adapters['voice']['kind']!='unconfigured',
                'face_configured':config.adapters['face']['kind']!='unconfigured'},ensure_ascii=False,indent=2))
            return 0 if ready else 2
        if getattr(args,'prompt_api_key',False) and options['provider']!='openai':
            raise ValueError('--prompt-api-key is only for the OpenAI provider')
        if not ready and getattr(args,'prompt_api_key',False):
            value=getpass.getpass('OpenAI API key (not saved): ').strip()
            if not value:raise ValueError('Empty API key')
            temporary_key=options['api_key_env']
            os.environ[temporary_key]=value
            ready=True
        if args.command=='interpret' and not 0<=args.focus_index<len(config.script):
            raise ValueError('Invalid focus index')
        if not ready:
            raise ValueError('Set the configured API key environment variable before inference')
        if args.command=='run':
            from .cli import main as actor_main
            command=['run','--config',str(args.config),'--max-seconds',str(args.max_seconds),'--json-events']
            if args.events:command+=['--events',str(args.events)]
            return actor_main(command)
        # Explicit, interpretation-only execution. Never call load_adapters().
        from .reasoner_probe import run_probe
        run_id='interpret-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
        directory=args.output_dir or config.output_dir/run_id
        directory.mkdir(parents=True,exist_ok=False)
        snapshot={'scene':asdict(config.scene),'script':list(config.script) if args.context=='full-script' else [config.script[args.focus_index]],
                  'context_mode':args.context,'focus_index':args.focus_index,'reasoner':options}
        write_new(directory/'input.json',snapshot)
        result=run_probe(config,options,directory/'result.json',args.context,args.focus_index)
        input_hash=sha256((directory/'input.json').read_bytes()).hexdigest()
        code_dir=Path(__file__).resolve().parent
        source_hashes={name:sha256((code_dir/name).read_bytes()).hexdigest() for name in
            ('pipeline.py','providers.py','inference.py','reasoner_probe.py','adapters/chat_reasoner.py','types.py','config.py')}
        code_commit=None
        checkout=code_dir.parents[1]
        if (checkout/'.git').exists():
            try:
                code_commit=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],
                    text=True,stderr=subprocess.DEVNULL,timeout=3).strip()
            except (OSError,subprocess.SubprocessError):pass
        write_new(directory/'manifest.json',{'run_id':run_id,'package_version':__version__,'python_version':sys.version.split()[0],
            'provider':options['provider'],'requested_model':options['model'],
            'reported_models':sorted({c['receipt'].get('reported_model','') or '' for c in result['calls']}),
            'code_commit':code_commit,'source_sha256':source_hashes,
            'model_weights_sha256':'not_supplied',
            'status':result['status'],'context_mode':args.context,'input_sha256':input_hash,
            'result_sha256':sha256((directory/'result.json').read_bytes()).hexdigest(),
            'voice_face_loaded':False,'human_approved':False,'backup_status':'unverified'})
        print(json.dumps({'run_id':run_id,'status':result['status'],
                          'output_dir':str(directory),'proposal':result.get('proposal'),
                          'audit':result.get('audit')},ensure_ascii=False,indent=2))
        return 130 if result['status']=='cancelled' else (0 if result['status']=='completed' else 2)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        # Never echo HTTP bodies, headers, credentials or private script data.
        print('Pipeline failed ('+type(error).__name__+'); check configuration, authentication and output paths.',file=sys.stderr)
        return 2
    finally:
        if temporary_key is not None:os.environ.pop(temporary_key,None)

if __name__=='__main__':
    raise SystemExit(main())
