#!/usr/bin/env bash
set -euo pipefail

agent_dir="${PI_CODING_AGENT_DIR:-/root/.pi/agent}"

mkdir -p "${agent_dir}" "${agent_dir}/sessions"

cp /etc/pi-bootstrap/models.json "${agent_dir}/models.json"
cp /etc/pi-bootstrap/settings.json "${agent_dir}/settings.json"

exec "$@"
