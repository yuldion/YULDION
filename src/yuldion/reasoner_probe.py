"""First unspoken line only. Never imports or loads voice/face adapters."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from threading import Event
from .adapters.chat_reasoner import ChatReasoner
from .config import load_config
from .events import canonical
from .types import Context, Observation
from hashlib import sha256


def main(argv=None):
    parser=argparse.ArgumentParser(description='First-line reasoning only; no audio/face execution')
    parser.add_argument('--scene-config',type=Path,required=True)
    parser.add_argument('--model-config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    config=load_config(args.scene_config)
    reasoner=ChatReasoner(json.loads(args.model_config.read_text()))
    script=Observation('script:0','authored_script',config.script[0])
    scene=Observation('scene:0','scene',canonical(asdict(config.scene)))
    context=Context(config.scene,sha256(canonical(asdict(config.scene)).encode()).hexdigest(),
                    script,(scene,script),None,None,(),(),(),None,{})
    record={'mode':'actual-model-request; first-line-only', 'input':asdict(context),
            'voice_face_loaded':False,'human_approved':False,'status':'started'}
    with args.output.open('x',encoding='utf-8') as handle:
        try:
            proposal=reasoner.propose(context,Event())
            record['proposal']=asdict(proposal)
            key=(context.scene_hash,context.script.id,context.script.text)
            record['text_reading']=reasoner.readings[key]
            record['textual_support']=reasoner.supports[key]
            record['status']='generated'
            if proposal.decision!='initialize' or not proposal.action or script.id not in proposal.basis:
                raise ValueError('First action must initialize and cite current line')
            if proposal.action.target_id!=config.scene.target_id:
                raise ValueError('Scene target changed')
            record['audit']=asdict(reasoner.audit(context,proposal,Event()))
            record['status']='completed' if record['audit']['grounded'] else 'ungrounded'
        except Exception as error:
            record['status']='failed'
            record['error_type']=type(error).__name__
        finally:
            record['calls']=reasoner.calls
            handle.write(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
            reasoner.close()
    print(json.dumps(record,indent=2,ensure_ascii=False))
    return 0 if record['status']=='completed' else 2

if __name__=='__main__':
    raise SystemExit(main())
