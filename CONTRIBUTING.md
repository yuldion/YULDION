# Contributing

Run `PYTHONPATH=src python3 -m unittest discover -s tests -v` before submitting
engine changes. Core tests require no GPU, network, model weights or real identity
assets. Test adapters belong in tests only and must not be shipped as actual actors.

Keep backend dependencies in separate optional adapter packages. Document their
input/output contract, selected model identity, cancellation behavior, actual
sample clock, control units and known perceptual limitations. A contract test is
not evidence of natural acting, likeness, realtime performance or user approval.

Do not commit private configuration, recordings, model weights, credentials or
generated outputs. GitHub publishing is a separate user-authorized action.
