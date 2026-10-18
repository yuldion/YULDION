# RunPod execution

This repository does not contact RunPod or start/stop rented resources. Development
of this skeleton did not use or modify the currently training voice/face jobs.

1. Use an isolated checkout and virtual environment on the chosen GPU server.
   Do not install into or modify an active training environment.
2. Install the selected model adapters and their explicitly pinned GPU dependencies.
   Put approved model weights/identity assets on the operator's persistent storage.
3. Create a private configuration outside tracked examples with the selected
   adapter entrypoints/checkpoints. Point output_dir at a durable run directory.
4. Validate configuration and inspect adapter readiness before actual inference.

```bash
cd /workspace/YULDION
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
# Install your selected adapters separately, after training results are accepted.
yuldion validate --config /workspace/private/hamlet.local.json
yuldion doctor --config /workspace/private/hamlet.local.json
YULDION_PYTHON="$PWD/.venv/bin/python" bash scripts/runpod.sh \
  /workspace/private/hamlet.local.json 300
```

The launcher performs no model downloads, dependency installations, training or
RunPod API operations. It invokes the foreground engine under GNU timeout (Linux),
sends SIGINT at the limit and SIGKILL ten seconds later if still stuck. The limit
includes the foreground run process; it is not a cost cap, remote-service kill
confirmation or automatic pod shutdown. The resource owner remains responsible
for rented GPU lifetime and preserving outputs before removing compute.

Do not assume `/workspace` is persistent merely from its name. Configure actual
mounted storage and verify preservation under the current project's storage rules.
Weights/private identity data and generated output never belong in the public
GitHub repository. Model licenses are independent from YULDION's code license.
