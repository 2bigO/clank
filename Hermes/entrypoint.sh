#!/usr/bin/env bash
set -euo pipefail

cp /etc/hermes-bootstrap/config.yaml "${HERMES_HOME}/config.yaml"

exec "$@"
