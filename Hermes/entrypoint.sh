#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${HERMES_HOME}"

if [ ! -f "${HERMES_HOME}/config.yaml" ]; then
  cp /etc/hermes-bootstrap/config.yaml "${HERMES_HOME}/config.yaml"
fi

exec "$@"
