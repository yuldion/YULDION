"""Checkpoint each successful realization; resume only the failed/unstarted line."""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
import uuid
from .acting_score import select_reasoner
from .adapters.chat_reasoner import ChatReasoner
from .adapters.unconfigured import Unconfigured
from .engine import Engine,normalized
from .errors import failure_record
from .events import Journal,canonical
from .preparation import save
from .types import Adapters,Action,Performance,Plan
from .vocal import vocal_delivery


def restore(engine, record, extend=False):
    if record.get('status') not in (('completed',) if extend else ('failed','cancelled')):raise ValueError('Resume requires a failed/cancelled performance')
    if record.get('preparation_sha256')!=engine.config.preparation['document_sha256'] or record.get('review_sha256')!=engine.config.review['sha256']:
        raise ValueError('Preparation/review changed; cannot resume old performance')
    if record.get('scene_hash')!=engine.scene_hash:raise ValueError('Scene changed')
    for index,row in enumerate(record['plans']):
        score=engine.config.preparation['acting_score'][index];p=row['plan']
        if row['segment']!=index or row['script']!=engine.config.execution_script[index] or p['scene_hash']!=engine.scene_hash or p['view']!=score['meaning'] or p['action']!=score['action']:
            raise ValueError('Saved performance prefix differs from reviewed score')
        performance=Performance(**p['performance'])
        if vocal_delivery(performance.vocal,row['script'])!=performance.delivery:raise ValueError('Saved vocal controls differ from rendered directions')
        if type(performance.pause_ms) is not int or not 0<=performance.pause_ms<=10000 or type(performance.breath) is not bool:raise ValueError('Invalid saved pause/breath')
        canonical(performance)
        if any(not isinstance(p[key],str) or not p[key] for key in ('id','action_id')):raise ValueError('Invalid saved plan identifiers')
        plan=Plan(p['id'],p['scene_hash'],p['action_id'],Action(**p['action']),p['changed'],p['view'],performance)
        if type(plan.changed) is not bool or not isinstance(plan.performance.motor,dict) or not plan.performance.motor:raise ValueError('Invalid saved plan')
        if plan.changed!=(score['transition']['decision']!='retain'):raise ValueError('Saved action transition differs from score')
        if engine.plan and not plan.changed and plan.action_id!=engine.plan.action_id:raise ValueError('Retained action ID changed')
        engine.plan=plan;engine.prior_views.append(plan.view)
        if plan.changed and score['transition']['decision']=='change':engine.discoveries.append(normalized(score['transition']['discovery']))
    return len(record['plans'])


def run_plans(config, options, directory, segments=None, resume_from=None, on_plan=None, extend_from=None):
    count=len(config.execution_script) if segments is None else segments
    if type(count) is not int or not 1<=count<=len(config.execution_script):raise ValueError('Invalid segment count')
    reasoner=select_reasoner(config,ChatReasoner(options))
    engine=Engine(config,Adapters(reasoner,Unconfigured('voice'),Unconfigured('face')))
    record={'status':'started','mode':'reviewed_score_performance','scene_hash':engine.scene_hash,
        'preparation_sha256':config.preparation['document_sha256'],'review_sha256':config.review['sha256'],
        'voice_face_loaded':False,'media_status':'not_run','human_approved':False,'plans':[],'calls':[],
        'next_segment':0,'requested_segments':count}
    if resume_from and extend_from:raise ValueError('Choose resume or extension')
    extending=extend_from is not None
    resume_from=extend_from or resume_from
    start=0
    if resume_from:
        old=json.loads(resume_from.read_text());start=restore(engine,old,extending)
        if count<start or (count<=old.get('requested_segments',0) if extending else count!=old.get('requested_segments')):raise ValueError('Resume must keep original segment scope')
        record['plans']=deepcopy(old['plans']);reasoner.calls.extend(deepcopy(old['calls']))
        record['resumed_from_sha256']=sha256(resume_from.read_bytes()).hexdigest();record['next_segment']=start
    output=directory/'result.json'
    with output.open('x',encoding='utf-8') as handle:handle.write(canonical(record)+'\n')
    journal=Journal(directory,'plan-'+uuid.uuid4().hex)
    index=start
    try:
        journal.emit('reviewed_score.loaded',preparation_sha256=record['preparation_sha256'],review=config.review)
        if resume_from:journal.emit('planning.restored',completed_segments=start,source_sha256=record['resumed_from_sha256'],speech_emitted=False)
        for index in range(start,count):
            fragment=config.execution_script[index]
            plan=engine.make_plan(fragment,index,journal)
            row={'segment':index,'script':fragment,'plan':asdict(plan)}
            record['plans'].append(row);record['next_segment']=index+1;record['calls']=reasoner.calls
            save(output,record)
            if on_plan:on_plan(row)
        record['status']='completed'
    except BaseException as error:
        record['status']='cancelled' if isinstance(error,KeyboardInterrupt) else 'failed'
        record['error_type']=type(error).__name__;record['failure']=failure_record(error)
        if isinstance(error,ValueError) and reasoner.calls and 'response' in reasoner.calls[-1]:
            reasoner.calls[-1]['validation_error']=str(error)
        record['failed_stage']={'stage':'performance','segment':index,'line_id':config.preparation['acting_score'][index]['line_id']}
        raise
    finally:
        record['calls']=reasoner.calls;save(output,record);journal.close();reasoner.close()
    return record
