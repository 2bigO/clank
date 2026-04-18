#!/usr/bin/env bash
set -euo pipefail

home_dir="${HOME:-/home/node}"
agent_dir="${home_dir}/.pi/agent"

mkdir -p "${agent_dir}" "${agent_dir}/sessions"

if [[ -f /workspace/host/Pi/models.json ]]; then
  cp /workspace/host/Pi/models.json "${agent_dir}/models.json"
fi

if [[ -f /workspace/host/Pi/settings.json ]]; then
  cp /workspace/host/Pi/settings.json "${agent_dir}/settings.json"
fi

exec "$@"
