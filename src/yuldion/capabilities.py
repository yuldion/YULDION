"""Declare transport support separately from measured acoustic effects."""
from copy import deepcopy
from .errors import ContractError

FIELDS=('delivery','pace','volume','pitch','articulation','stress','pause_ms','breath')
STATUSES={'supported','experimental','unsupported','unknown'}


def inspect_controls(voice,request):
    method=getattr(voice,'capabilities',None)
    declaration=method() if callable(method) else {'schema_version':1,'controls':{}}
    if not isinstance(declaration,dict) or declaration.get('schema_version')!=1 or not isinstance(declaration.get('controls'),dict):
        raise ContractError('Invalid voice capability declaration')
    requested={'delivery':request.plan.performance.delivery,**(request.plan.performance.vocal or {}),
               'pause_ms':request.plan.performance.pause_ms,'breath':request.plan.performance.breath}
    controls={};unsupported=[]
    for field,value in requested.items():
        if field not in FIELDS:raise ContractError('Unknown requested voice control')
        item=declaration['controls'].get(field,{'status':'unknown','transport':'undeclared','effect_verified':False})
        if not isinstance(item,dict) or item.get('status') not in STATUSES or not isinstance(item.get('transport',''),str) or type(item.get('effect_verified',False)) is not bool:
            raise ContractError('Invalid voice control capability')
        active=not ((field=='pause_ms' and value==0) or (field=='breath' and value is False) or (field=='stress' and value==[]))
        controls[field]={'requested':deepcopy(value),'active':active,'status':item['status'],
                         'declared_transport':item.get('transport',''),'declared_effect_verified':item.get('effect_verified',False),
                         'delivered_value':None,'delivery_verified':False,'effect_verified':False}
        if active and item['status']=='unsupported':unsupported.append(field)
    return {'schema_version':1,'plan_id':request.plan.id,'controls':controls,'unsupported':unsupported,
            'scope':'preflight declaration only; no delivery or acoustic effect established'}


def control_receipt(voice,request):
    method=getattr(voice,'control_receipt',None)
    if not callable(method):return {'plan_id':request.plan.id,'status':'not_reported','effect_verified':False}
    result=method(request)
    if not isinstance(result,dict) or result.get('plan_id')!=request.plan.id:
        raise ContractError('Voice control receipt must identify the requested plan')
    return deepcopy(result)
