"""Loopback observer: resume the failed stage; never repeat completed analysis."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from threading import Lock
import uuid


def read(path):
    if path is None:return None
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return None


def paths(directory):
    if directory is None:return {}
    job=read(directory/'job.json') or {}
    if job.get('active_attempt'):return paths(Path(job['active_attempt']))
    return {'analysis':job.get('analysis',str(directory/'analysis/preparation.json')),
            'prepared_config':job.get('prepared_config',str(directory/'prepared.local.json')),
            'review':job.get('review',str(directory/'review/review.json')),
            'reviewed_config':job.get('reviewed_config',str(directory/'reviewed.local.json')),
            'performance':job.get('performance',str(directory/'plans/result.json'))}


def snapshot(directory, process=None):
    value={'status':'not_started','phase':'input','analysis_status':'not_started','structure_status':'not_started',
        'review_status':'not_started','performance_status':'not_started','media_status':'not_run',
        'steps':[],'acting_score':[],'calls':0,'plans':[],'source_lines':[],'runtime_calls':[],
        'review_issues':[],'failure':None,'failed_stage':None,'voice_face_loaded':False,'can_start':True,'next_action':'전체 분석 시작'}
    if directory is None:return value
    value['recovery_verification']=read(directory/'verification.json')
    p=paths(directory);doc=read(p['analysis']);review=read(p['review']);performance=read(p['performance'])
    if doc:
        value.update(status=doc['status'],analysis_status='completed' if doc['status']=='draft_complete' else doc['status'],
            phase=doc.get('phase','whole_script_analysis'),steps=doc['steps'],acting_score=doc.get('acting_score',[]),
            calls=len(doc['calls']),source_lines=doc['source']['lines'],failure=doc.get('failure'))
        value['next_action']='분석 실패 단계 재개'
        if doc.get('failure'):value['failed_stage']=doc['calls'][-1]['task'] if doc.get('calls') else {'stage':'analysis'}
        if doc['status']=='draft_complete':
            from ...preparation import validate_document
            try:
                validate_document(doc,doc['source']['script'],doc['source']['character'],True)
                value['structure_status']='passed'
            except (ValueError,KeyError,TypeError):value['structure_status']='failed'
            value.update(status='awaiting_review',phase='semantic_review',next_action='완료된 분석 의미 검수')
    if review:
        value.update(review_status=review['status'],review_issues=review.get('issues',[]),failure=review.get('failure'))
        if review['status']=='needs_revision':value.update(status='needs_revision',can_start=False,next_action='검수 지적 수정 필요')
        elif review['status']=='passed':value.update(status='ready',phase='ready_for_performance',next_action='검수된 계획으로 연기 지시 생성')
        elif review['status'] in ('failed','cancelled'):value.update(status='failed',failed_stage={'stage':'semantic_review'},next_action='실패한 의미 검수만 재개')
        else:value.update(status='running',can_start=False)
    if performance:
        reviewed=performance.get('review_sha256') and review and review.get('status')=='passed'
        value['performance_status']=performance['status'] if reviewed else 'legacy_unreviewed'
        if reviewed:
            value.update(status=performance['status'],phase='performance_realization',plans=performance['plans'],
                runtime_calls=[c['operation'] for c in performance['calls']],failure=performance.get('failure'),failed_stage=performance.get('failed_stage'))
            value['next_action']='실패한 연기 지시만 재개'
            if performance['status']=='completed':
                value.update(phase='completed',can_start=False,next_action='연기 지시 완료 · 실제 미디어 미실행')
                if len(performance['plans'])<len(value['source_lines']):
                    value.update(can_start=True,next_action='독백 끝까지 이어서 생성')
    if process and process.poll() is None:value.update(status='running',can_start=False)
    job=read(directory/'job.json') or {}
    value['automatic_recoveries']=job.get('recoveries',[])
    value['recovery_attempt']=job.get('attempt',1)
    if job.get('status')=='recovering':value.update(status='recovering',can_start=False)
    if job.get('status')=='failed' and not value['failure']:
        value.update(status='failed',failure=job.get('failure',{'type':'WorkerFailure','retryable':False}),failed_stage={'stage':job.get('stage','setup')})
    if value['structure_status']=='failed':value.update(status='failed',can_start=False,next_action='분석 구조 오류 수정 필요')
    return value


def worker(config, directory, resume=None):
    from ...pipeline import main as pipeline
    from ...preparation import save
    old=paths(resume) if resume else {}
    olddoc=read(old.get('analysis'))
    if olddoc:
        from ...config import load_config
        from ...preparation import source_for
        if olddoc.get('source')!=source_for(load_config(Path(config))):raise ValueError('Original scene/script changed; cannot reuse another preparation')
    job={'status':'running','analysis':str(directory/'analysis/preparation.json'),
         'prepared_config':str(directory/'prepared.local.json'),'review':str(directory/'review/review.json'),
         'reviewed_config':str(directory/'reviewed.local.json'),'performance':str(directory/'plans/result.json')}
    if olddoc and olddoc.get('status')=='draft_complete':
        job['analysis']=old['analysis']
        if Path(old['prepared_config']).is_file():job['prepared_config']=old['prepared_config']
        else:
            from ...preparation import bind_config
            bind_config(Path(config),Path(job['analysis']),Path(job['prepared_config']),True)
    job['stage']='setup'
    save(directory/'job.json',job)
    def invoke(command):
        job['stage']=command[0];save(directory/'job.json',job)
        result=pipeline(command)
        job['exit_code']=result
        if result:job['status']='needs_revision' if result==3 else 'failed'
        save(directory/'job.json',job)
        return result
    try:
        if not olddoc or olddoc.get('status')!='draft_complete':
            command=['prepare','--config',config,'--output-dir',str(directory/'analysis'),
                '--bound-config',job['prepared_config'],'--allow-draft','--max-calls','160','--max-seconds','900']
            if olddoc and olddoc.get('status') in ('failed','cancelled'):command+=['--resume-from',old['analysis']]
            result=invoke(command)
            if result:return result
        oldreview=read(old.get('review'))
        same_review=oldreview and olddoc and olddoc.get('status')=='draft_complete'
        if same_review and oldreview.get('status')=='needs_revision':
            job['review']=old['review'];save(directory/'job.json',job);return 3
        if same_review and oldreview.get('status')=='passed':
            job['review']=old['review']
            from ...review import bind_review
            bind_review(Path(job['prepared_config']),Path(job['review']),Path(job['reviewed_config']))
            save(directory/'job.json',job)
        else:
            command=['review','--config',job['prepared_config'],'--output-dir',str(directory/'review'),
                '--bound-config',job['reviewed_config']]
            if same_review and oldreview.get('status') in ('failed','cancelled'):command+=['--resume-from',old['review']]
            result=invoke(command)
            if result:return result
        previous=read(old.get('performance'))
        target=len(olddoc['source']['lines']) if olddoc else len(read(job['analysis'])['source']['lines'])
        if previous and previous.get('status') in ('failed','cancelled'):
            target=previous['requested_segments']
        command=['plan','--config',job['reviewed_config'],'--output-dir',str(directory/'plans'),'--segments',str(target)]
        previous=read(old.get('performance'))
        if same_review and oldreview.get('status')=='passed' and previous and previous.get('review_sha256') and previous.get('status') in ('failed','cancelled'):
            command+=['--resume-from',old['performance']]
        if same_review and oldreview.get('status')=='passed' and previous and previous.get('status')=='completed' and len(previous.get('plans',[]))<target:
            command+=['--extend-from',old['performance']]
        return invoke(command)
    except BaseException as error:
        from ...errors import failure_record
        job['status']='failed';job['failure']=failure_record(error)
        raise
    finally:
        if job['status'] not in ('failed','needs_revision'):job['status']='finished'
        save(directory/'job.json',job)


def recovery_failure(directory):
    """Retry only recorded inference/response-format failures, never semantic findings."""
    p=paths(directory)
    for name in ('performance','review','analysis'):
        record=read(p.get(name))
        if not record:continue
        if record.get('status')=='needs_revision':return None
        if record.get('status') not in ('failed','cancelled'):continue
        if record.get('status')=='cancelled':return None
        failure=record.get('failure',{})
        if failure.get('retryable'):return failure
        calls=record.get('calls',[])
        if failure.get('category')=='validation' and calls and calls[-1].get('response') and calls[-1].get('validation_error'):
            return failure
        return None
    return None


def supervised_worker(config,directory,resume=None,run=worker,sleep=time.sleep):
    """One start, bounded automatic stage recovery, and full-script completion."""
    from ...preparation import save
    previous=resume
    history=[]
    for attempt in range(3):
        current=directory/('attempt-'+str(attempt+1))
        current.mkdir(parents=True,exist_ok=False)
        control={'status':'running','active_attempt':str(current),'attempt':attempt+1,'recoveries':history}
        save(directory/'job.json',control)
        try:code=run(config,current,previous)
        except Exception:code=2
        p=paths(current);performance=read(p.get('performance'));analysis=read(p.get('analysis'))
        if code==0 and performance and analysis and len(performance.get('plans',[]))<len(analysis['source']['lines']):
            # Finish an older limited failed run without changing its resume scope,
            # then extend the completed prefix to the rest in the same start.
            extra=current/'finish-whole';extra.mkdir()
            control['active_attempt']=str(extra);save(directory/'job.json',control)
            try:code=run(config,extra,current)
            except Exception:code=2
            current=extra
        if code==0:
            control.update(status='finished',exit_code=0);save(directory/'job.json',control);return 0
        failure=recovery_failure(current)
        if not failure or attempt==2:
            control.update(status='needs_revision' if code==3 else 'failed',exit_code=code,
                           failure=failure or (read(current/'job.json') or {}).get('failure'),
                           recovery_exhausted=bool(failure))
            save(directory/'job.json',control);return code
        delay=min(30,max(1,failure.get('retry_after_seconds') or 2**attempt))
        history.append({'attempt':attempt+1,'failure':failure,'delay_seconds':delay})
        control.update(status='recovering',recoveries=history);save(directory/'job.json',control)
        sleep(delay);previous=current
    return 2


class SessionKey:
    """Observer-lifetime credential; never serialized or exposed by state responses."""
    def __init__(self):self._value=''
    def set(self,value):
        if not isinstance(value,str):raise ValueError('Invalid credential')
        self._value=value.strip()
    def available(self):return bool(self._value)
    def apply(self,env,name):
        if self._value:env[name]=self._value
    def clear(self):self._value=''


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8794);parser.add_argument('--resume',type=Path);parser.add_argument('--worker',type=Path)
    args=parser.parse_args(argv)
    if args.worker:return supervised_worker(str(args.config),args.worker,args.resume)
    from ...config import load_config
    from ...pipeline import model_options
    config=load_config(args.config);options=model_options(config)
    if config.preparation:raise ValueError('Start observer with original scene config')
    if not 1024<=args.port<=65535:raise ValueError('Invalid port')
    credentials=SessionKey()
    token=secrets.token_urlsafe(32);lock=Lock();state={'directory':None,'process':None}
    from ...preparation import source_for
    candidates=sorted(config.output_dir.glob('visual-whole-*'),key=lambda p:p.stat().st_mtime,reverse=True)
    for candidate in candidates:
        doc=read(paths(candidate).get('analysis'))
        if doc and doc.get('source')==source_for(config):state['directory']=candidate;break
    origins={f'http://127.0.0.1:{args.port}',f'http://localhost:{args.port}'};hosts={url.removeprefix('http://') for url in origins}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,data,kind='application/json; charset=utf-8'):
            raw=data.encode() if isinstance(data,str) else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(raw)))
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.headers.get('Host') not in hosts:return self.send(403,{'error':'host'})
            if self.path=='/':return self.send(200,Path(__file__).with_name('index.html').read_text().replace('__CSRF_TOKEN__',token),'text/html; charset=utf-8')
            if self.path=='/state':
                value=snapshot(state['directory'],state['process']);value.update(input_script=list(config.script),provider=options['provider'],model=options['model'],session_key_available=credentials.available())
                return self.send(200,value)
            return self.send(404,{})
        def do_POST(self):
            if self.headers.get('Host') not in hosts or self.headers.get('Origin') not in origins or not hmac.compare_digest(self.headers.get('X-Yuldion-Token',''),token):return self.send(403,{'error':'origin/token'})
            if self.path not in ('/start','/key','/key/clear','/verify-live'):return self.send(404,{})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=16384:raise ValueError()
                payload=json.loads(self.rfile.read(size))
                if self.path=='/key/clear':
                    if payload!={}:raise ValueError()
                    with lock:credentials.clear()
                    return self.send(200,{'cleared':True})
                if set(payload)!={'api_key'} or not isinstance(payload['api_key'],str):raise ValueError()
                with lock:
                    if payload['api_key'].strip():credentials.set(payload['api_key'])
                    if self.path=='/key':return self.send(200,{'session_key_available':credentials.available()})
                    view=snapshot(state['directory'],state['process'])
                    if self.path=='/verify-live':
                        if state['process'] and state['process'].poll() is None:return self.send(409,{'error':'작업 진행 중'})
                        if view['review_status']!='passed' or len(view['plans'])<12:return self.send(409,{'error':'검수된 12줄 이상의 기존 결과가 필요합니다.'})
                    elif not view['can_start']:return self.send(409,{'error':view['next_action']})
                    env=os.environ.copy()
                    if options['provider']=='openai':
                        credentials.apply(env,options['api_key_env'])
                        key=env.get(options['api_key_env'],'')
                        if not key:return self.send(400,{'error':'API 키를 숨김 입력해 주세요.'})
                        env[options['api_key_env']]=key
                    if not env.get('SSL_CERT_FILE') and Path('/etc/ssl/cert.pem').is_file():env['SSL_CERT_FILE']='/etc/ssl/cert.pem'
                    directory=config.output_dir/('visual-whole-'+uuid.uuid4().hex[:12]);directory.mkdir(parents=True,exist_ok=False)
                    command=[sys.executable,'-m','yuldion.tools.inspector.server','--config',str(args.config.resolve()),'--worker',str(directory)]
                    observed=directory
                    if self.path=='/verify-live':
                        previous=read(paths(state['directory'])['performance'])
                        prefix={**previous,'status':'completed','requested_segments':12,'next_segment':12,'plans':previous['plans'][:12]}
                        from ...preparation import save
                        save(directory/'prefix.json',prefix)
                        observed=directory/'verification'
                        save(directory/'job.json',{'active_attempt':str(observed),'status':'running'})
                        command=[sys.executable,str(Path(__file__).resolve().parents[4]/'tools/verify_recovery.py'),'--source-run',str(state['directory']),'--prefix-result',str(directory/'prefix.json'),'--output',str(observed),'--fault-line','18','--delay','0','--live-api']
                    elif state['directory']:command+=['--resume',str(state['directory'])]
                    with (directory/'worker.log').open('xb') as log:
                        process=subprocess.Popen(command,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
                    state.update(directory=observed,process=process)
                return self.send(200,{'started':True})
            except (ValueError,TypeError):return self.send(400,{'error':'요청 형식 오류'})
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'YULDION observer: http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    finally:
        credentials.clear();server.server_close()

if __name__=='__main__':raise SystemExit(main())
