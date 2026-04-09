#!/usr/bin/env bash
set -euo pipefail

exec node /opt/src/pi-mono/packages/coding-agent/dist/cli.js "$@"
