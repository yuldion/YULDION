"""Exercise actual planning/supervision with immutable saved model responses.
No API calls, new interpretation, voice or face adapter loading.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import time
from unittest.mock import patch
from yuldion.config import load_config
from yuldion.pipeline import model_options
from yuldion.planning import run_plans
from yuldion.preparation import save
from yuldion.errors import InferenceFailure
from yuldion.inference import generate as real_generate
from yuldion.tools.inspector.server import supervised_worker,paths,read


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source-run',type=Path,required=True)
    p.add_argument('--prefix-result',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--fault-line',type=int,default=18)
    p.add_argument('--delay',type=float,default=0.5)
    p.add_argument('--live-api',action='store_true')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    source=paths(args.source_run);original=read(source['performance'])
    config=load_config(Path(source['reviewed_config']));options=model_options(config)
    prefix=read(args.prefix_result)
    if not len(prefix['plans'])<args.fault_line<=len(original['plans']):raise ValueError('Fault must follow prefix')
    responses={}
    for call in original['calls']:
        if call.get('operation')=='perform' and 'response' in call and not call.get('validation_error'):
            payload=json.loads(call['request'][1]['content'])
            responses[payload['context']['script']['id']]=call
    report={'mode':'live_api_fault_injection' if args.live_api else 'saved_real_model_response_replay','status':'running','api_calls':0,
            'analysis_reused':True,'review_reused':True,'voice_face_loaded':False,
            'injected_fault_line':args.fault_line,'source_result_sha256':sha256(Path(source['performance']).read_bytes()).hexdigest(),
            'events':[],'attempt_requests':[]}
    def event(kind,**values):
        report['events'].append({'event':kind,**values});save(args.output/'verification.json',report)
    injected=False
    def run(_,out,previous):
        nonlocal injected
        job={**source,'performance':str(out/'plans/result.json'),'status':'running','stage':'plan'}
        save(out/'job.json',job);(out/'plans').mkdir()
        failed=Path(paths(previous)['performance']) if previous else None
        requests=[];report['attempt_requests'].append(requests)
        def replay(options,messages):
            nonlocal injected
            payload=json.loads(messages[1]['content']);sid=payload['context']['script']['id'];line=int(sid.split(':')[1])+1
            requests.append(line);event('line_requested',line=line,attempt=len(report['attempt_requests']))
            time.sleep(args.delay)
            live=None
            if args.live_api:
                report['api_calls']+=1
                live=real_generate(options,messages)
                event('api_response_received',line=line,reported_model=live[1].get('reported_model'))
            if line==args.fault_line and not injected:
                injected=True
                if live:save(args.output/'discarded_fault_response.json',{'line':line,'response':live[0],'receipt':live[1],'reason':'Intentional post-response connection fault; not committed as a plan'})
                event('injected_connection_failure',line=line)
                raise InferenceFailure('connection')
            if live:return live
            call=responses[sid]
            return deepcopy(call['response']),{'replay':True,'source_result_sha256':report['source_result_sha256'],
                'source_response_sha256':sha256(json.dumps(call['response'],sort_keys=True).encode()).hexdigest()}
        try:
            with patch('yuldion.adapters.chat_reasoner.generate',side_effect=replay):
                run_plans(config,options,out/'plans',len(config.execution_script),
                    resume_from=failed if failed else None,
                    extend_from=None if failed else args.prefix_result,
                    on_plan=lambda row:event('line_committed',line=row['segment']+1))
            job['status']='finished';return 0
        except InferenceFailure:
            job['status']='failed';return 2
        finally:save(out/'job.json',job)
    code=supervised_worker('unchanged-reviewed-config',args.output,run=run)
    final=read(paths(args.output)['performance'])
    first=read(args.output/'attempt-1/plans/result.json')
    checks={'one_fault':sum(e['event']=='injected_connection_failure' for e in report['events'])==1,
            'resumed_at_failed_line':len(report['attempt_requests'])==2 and report['attempt_requests'][1][0]==args.fault_line,
            'prefix_unchanged':final['plans'][:len(prefix['plans'])]==prefix['plans'],
            'successful_before_fault_unchanged':final['plans'][:len(first['plans'])]==first['plans'],
            'completed_whole':code==0 and final['status']=='completed' and len(final['plans'])==len(config.execution_script),
            'same_analysis_review':final['preparation_sha256']==original['preparation_sha256'] and final['review_sha256']==original['review_sha256']}
    report.update(status='passed' if all(checks.values()) else 'failed',checks=checks,completed_lines=len(final['plans']))
    save(args.output/'verification.json',report)
    print(json.dumps({'status':report['status'],'checks':checks},ensure_ascii=False))
    return 0 if report['status']=='passed' else 2

if __name__=='__main__':raise SystemExit(main())
