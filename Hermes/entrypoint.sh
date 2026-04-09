#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${HERMES_HOME}"

cp /etc/hermes-bootstrap/config.yaml "${HERMES_HOME}/config.yaml"

exec "$@"
