# Architecture and current limits

```text
CLI / Python API
  -> Config (immutable scene + script + three selected adapters)
  -> Engine
       scene/current authored script + observations
       -> Reasoner.propose -> Reasoner.audit
       -> persistent action retain/change gate
       -> Reasoner.perform (same action -> delivery + motor)
       -> Voice.synthesize -> PCM chunk
       -> Face.render (same plan + same audio clock)
       -> journal + output artifacts + technical feedback
```

UI, RunPod API client, training loop and download manager are intentionally absent.
The actor engine is ordinary Python and runs in an operator-prepared local or
RunPod environment. Heavy inference and checkpoint formats belong to adapters.

## Continuity

The scene object is frozen and a canonical scene hash follows every plan.
An action is target-directed (target, desired change, tactic, observable test).
Only a validated first action or grounded, novel, necessary event can create a new
action ID. A phrase is a checkpoint; rejecting an unsupported proposed change
retains the existing action. Exact repeated discoveries and consumed external
events cannot retrigger. A model audit is still fallible about semantic novelty.

Performance validates before action/state commit. No confirmed outcome is inferred
from silence, successful synthesis, RMS or frame count. Observer events and
technical feedback remain separate. Stimuli are currently handled at safe phrase
checkpoints rather than interrupting an in-flight utterance.

## Output lineage and observability

The journal records actual engine requests, returned values, gate decisions,
committed plans, PCM metadata, frame metadata and explicit termination/failure.
It does not reconstruct hidden model thoughts or pretend to be a Python line
debugger. Consumers can subscribe or read JSONL. An optional future UI can consume
this stream without modifying actor logic.

Every chunk/frame references the committed plan. Relative voice sample positions
are converted to one run clock. Non-contiguous PCM, mixed sample rates, nonfinite
audio, mismatched IDs and out-of-chunk/retrograde frames stop the run and preserve
partial records. Source samples are stored unchanged in `.f32le` files with a
JSON format/rate/plan manifest. No framebuffer/device playback is implemented.

## Cancellation and resource ownership

SIGINT/SIGTERM and the engine timer set a cooperative cancellation event. Returned
output after cancellation is discarded. A blocking backend that ignores the
event cannot be forcibly stopped by pure in-process Python; run under the
provided Linux `timeout` wrapper for a process-level bound. Keep backend request
timeouts and resource accounting in each adapter. External service cancellation
needs its actual API; killing a local caller does not prove remote compute stopped.

Each run has a new output directory and cannot reuse the same Engine instance.
Exceptions are journalled without a prerecorded/default-performance fallback.
The CLI closes adapters; applications using the Python API must also own/close
their adapters. No automatic checkpoint promotion, training, pod management or
deletion is implemented.

## Optional authoring tools

`yuldion.tools.action_verbs` is a separate, explicitly invoked rehearsal CLI
(`yuldion-action-verbs`). It has its own human approval workflow and model-server
configuration. Actor core modules never import it or wait for its stage approvals.
Its analysis is one optional acting method, not the definition of the engine's
reasoning process. There is no automatic conversion of its state into an engine
Scene/Plan, and no dependency on the separate script-analyzer repository.
