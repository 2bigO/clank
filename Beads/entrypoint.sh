#!/usr/bin/env bash
set -euo pipefail

state_root="${HOME:-/var/lib/beads}"
port="${BEADS_DOLT_SERVER_PORT:-3308}"
data_dir="${state_root}/dolt"
log_path="${state_root}/dolt-sql-server.log"

mkdir -p "${state_root}" "${data_dir}"

dolt sql-server --host 0.0.0.0 --port "${port}" --data-dir "${data_dir}" >"${log_path}" 2>&1 &
server_pid=$!

cleanup() {
  kill "${server_pid}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 60); do
  if nc -z 127.0.0.1 "${port}"; then
    break
  fi
  sleep 1
done

mysql --protocol=TCP -h 127.0.0.1 -P "${port}" -u root <<'SQL'
CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED BY '';
GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;
SQL

wait "${server_pid}"
