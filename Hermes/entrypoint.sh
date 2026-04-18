#!/usr/bin/env bash
set -euo pipefail

export HOME="${HOME:-/workspace}"
export XDG_STATE_HOME="${XDG_STATE_HOME:-${HOME}/.local/state}"

mkdir -p "${HERMES_HOME}"
mkdir -p "${XDG_STATE_HOME}"
cp /etc/hermes-bootstrap/config.yaml "${HERMES_HOME}/config.yaml"

exec "$@"
