"""Preflight exact motor leaf paths without inventing physical gaze coordinates."""
from copy import deepcopy
from .capabilities import STATUSES
from .errors import ContractError


def motor_leaves(value,prefix=''):
    if not isinstance(value,dict):raise ContractError('Motor controls must be dictionaries')
    for key,child in value.items():
        if not isinstance(key,str) or not key or '.' in key:raise ContractError('Motor keys must be nonempty undotted strings')
        path=prefix+'.'+key if prefix else key
        if isinstance(child,dict):yield from motor_leaves(child,path)
        else:yield path,child


def inspect_motor(face,plan):
    method=getattr(face,'capabilities',None)
    caps=method() if callable(method) else {'schema_version':1,'controls':{}}
    if not isinstance(caps,dict) or caps.get('schema_version')!=1 or not isinstance(caps.get('controls'),dict):
        raise ContractError('Invalid face capability declaration')
    audio_context=caps.get('audio_context','chunk')
    if audio_context not in ('chunk','utterance'):raise ContractError('Invalid face audio context')
    controls={};unsupported=[]
    for path,value in motor_leaves(dict(plan.performance.motor)):
        item=caps['controls'].get(path,{'status':'unknown','transport':'undeclared','effect_verified':False})
        if not isinstance(item,dict) or item.get('status') not in STATUSES or not isinstance(item.get('transport',''),str) or type(item.get('effect_verified',False)) is not bool:
            raise ContractError('Invalid face motor capability')
        controls[path]={'requested':deepcopy(value),'active':True,'status':item['status'],
            'declared_transport':item.get('transport',''),'declared_effect_verified':item.get('effect_verified',False),
            'delivered_value':None,'delivery_verified':False,'effect_verified':False}
        if item['status']=='unsupported':unsupported.append(path)
    return {'schema_version':1,'plan_id':plan.id,'audio_context':audio_context,'controls':controls,'unsupported':unsupported,
            'scope':'declared support only; application and visual effects unverified'}
