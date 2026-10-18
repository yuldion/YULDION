# YULDION core development

- Keep the core headless and importable without model/GPU/framework dependencies.
- Keep learned model implementations in explicitly selected adapters. Do not
  scan, modify, stop or restart adjacent AI-Theatre experiments/training jobs.
- Do not auto-download weights, install model runtimes, rent pods or publish to
  GitHub. Those operations require task-specific scope.
- Preserve immutable goals/relationship, evidence-gated action changes, first-line
  planning and actual output lineage. Never substitute test doubles for live acting.
- Test with `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
- Keep all identity assets, private configs, model weights and runs out of Git.
- Report real GPU/perceptual validation separately from passing core contracts.
