"""Typed vocal controls, rendered into the existing voice-adapter style contract."""
import re

PACE={'slow':'느리게','even':'고르게','brisk':'빠르게','variable':'속도 변화'}
VOLUME={'soft':'부드러운 강도','conversational':'대화 강도','firm':'분명한 강도','variable':'강도 변화'}
PITCH={'low':'낮은 음역','middle':'중간 음역','high':'높은 음역','variable':'음역 변화'}


def vocal_delivery(vocal, script):
    if not isinstance(vocal,dict) or set(vocal)!={'pace','volume','pitch','articulation','stress'}:
        raise ValueError('vocal requires pace, volume, pitch, articulation and stress')
    for key,choices in (('pace',PACE),('volume',VOLUME),('pitch',PITCH)):
        if not isinstance(vocal[key],str) or vocal[key] not in choices:raise ValueError('Invalid vocal '+key)
    articulation=vocal['articulation']
    normalize=lambda value:re.sub(r'\W','',value.casefold())
    if not isinstance(articulation,str) or not articulation.strip() or normalize(articulation)==normalize(script):
        raise ValueError('Articulation must describe physical speech, not repeat dialogue')
    if not isinstance(vocal['stress'],list) or len(vocal['stress'])>12 or any(not isinstance(q,str) or not q.strip() or q not in script for q in vocal['stress']):
        raise ValueError('Stress must quote current words exactly')
    return '속도: '+PACE[vocal['pace']]+'; 강도: '+VOLUME[vocal['volume']]+'; 음역: '+PITCH[vocal['pitch']]+'; 발음: '+articulation+'; 강조: '+', '.join(vocal['stress'])
