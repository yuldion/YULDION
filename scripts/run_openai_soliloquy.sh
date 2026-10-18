#!/usr/bin/env bash
# Hidden key prompt; full public-domain soliloquy context; interpretation only.
set -euo pipefail
YULDION_REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
YULDION_RUN_PYTHON="${YULDION_PYTHON:-python3}"
export PYTHONPATH="${YULDION_REPO_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
# Respect a configured CA bundle. On macOS, Python's optional cert bootstrap may
# be missing; use the system CA when available, never disable TLS verification.
if [[ -z "${SSL_CERT_FILE:-}" && -f /etc/ssl/cert.pem ]]; then
  export SSL_CERT_FILE=/etc/ssl/cert.pem
fi
YULDION_RUN_CONFIG="${YULDION_REPO_DIR}/private/openai-soliloquy.local.json"
if [[ ! -e "${YULDION_RUN_CONFIG}" ]]; then
  "${YULDION_RUN_PYTHON}" -m yuldion pipeline init --provider openai \
    --scene "${YULDION_REPO_DIR}/examples/hamlet-soliloquy.json" \
    --config "${YULDION_RUN_CONFIG}"
fi
exec "${YULDION_RUN_PYTHON}" -m yuldion pipeline interpret \
  --config "${YULDION_RUN_CONFIG}" --context full-script --focus-index 1 --prompt-api-key
