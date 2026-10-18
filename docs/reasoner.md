# Actual interpretation model port

`yuldion.adapters.chat_reasoner:create_reasoner` sends the current unspoken line,
immutable scene premises and actual evidence to an explicitly configured chat-completions
model. It implements propose/audit/perform. No fixed Hamlet appraisal, style prefix,
future script, voice weights or face runtime is loaded. Audit may use the same model
and is not independent verification. Human approval is never inferred.

The runtime endpoint/model ID must be configured privately. No server is started,
no model downloaded and no paid resource provisioned by this adapter.
A first-line-only probe can run independently of missing voice/face adapters:

```bash
PYTHONPATH=src python3 -m yuldion.reasoner_probe \
  --scene-config examples/hamlet.json \
  --model-config private/reasoner.local.json \
  --output private/first-line-result.local.json
```

Use the same endpoint/model/api_key_env shape as the optional tool's model configuration.
The scene goal and relationship in the example are authored provisional premises;
the model generates a new interpretation and intention conditioned on those premises.
The probe saves input, raw model responses, usage, timing, interpretation, action
and grounding audit. It does not synthesize speech or render faces. On failure it
preserves a failure status; no canned interpretation is substituted. JSON parse or
network failures do not preserve a provider response body. The full actor engine's
additional action/continuity gates remain responsible for actual performance runs.
Motor values require agreement with the selected face backend; unconstrained JSON
alone does not guarantee a usable pose or gaze direction.

Local tests use test-only responses. Real inference requires an available endpoint
and is verified separately from these tests. A bounded local Qwen3-8B Q4_K_M /
llama.cpp b11718 first-line rerun on 2026-10-18 completed quote checks and same-model
audit with grounded=true; this is not independent human validation or evidence of
performance quality. The voice/face adapters were not loaded in that probe.

## Text-first grounding

The reasoner first calls `read_text` with **only the current script ID and words**.
It receives no authored situation, goal, relationship or later lines in that call.
The model returns brief exact quotes, their proposed readings and what the words
alone do not establish. These are inspectable analysis outputs, not hidden thoughts.

A separate propose call receives those readings and the scene as secondary context.
It must return `textual_support` connecting an exact observed quote to an interpretation
and an explicit explanation of its link to the single desired change selected by the action.
Python validates exact quote attribution, nonempty support explanations and rejects a view
that only copies the whole line. It does not require repeated intention strings or prove
semantic agreement; the audit and human review assess that.
The normal engine action/continuity gates remain unchanged. A following audit call
receives both the original text reading and support; its verdict is recorded unchanged.
Semantic entailment is still a fallible model/human judgment, not proven by JSON checks.
The raw reading and support are retained in first-line probe output and model-call records.

For the textual proposal call, authored scene goal/given explanations and scene
observations are withheld to prevent direct copying; target/relationship constraints
and prior action/evidence remain available. Full immutable scene premises return
in audit/perform. Text-only reading requires at least two distinct short quotations.
The first proposal's structured basis is constrained to the current script ID and
verbatim reuse of a prepared scene goal as the desired change is rejected. These
mechanical checks still do not establish semantic correctness.

`request_timeout_seconds` defaults to 60 and can be configured between 1 and 180
seconds for slower local inference. The actual text-grounded run used 120 seconds
per call, with an external 360-second probe bound and owned-server cleanup.
The selected quotes were “To die” and “to sleep”; the model generated “Consider the
possibility of death as a resolution to suffering” as the desired change. “Suffering”
is an inferred reading, not a directly quoted fact; “No more” was not separately
analyzed by this response. Human review remains necessary. Prior failures were retained,
including invalid quotations, goal copying, redundant support checks and a timeout.
