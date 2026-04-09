#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPOS_DIR="${ROOT_DIR}/repos"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

clone_repo() {
  local name="$1"
  local url="$2"
  local branch="${3:-}"
  local dest="${REPOS_DIR}/${name}"

  if [[ -d "${dest}/.git" ]]; then
    echo "repo exists: ${name}"
    return
  fi

  echo "cloning ${name}"
  if [[ -n "${branch}" ]]; then
    git clone --branch "${branch}" --single-branch "${url}" "${dest}"
  else
    git clone "${url}" "${dest}"
  fi
}

copy_if_missing() {
  local src="$1"
  local dest="$2"
  if [[ -e "${dest}" ]]; then
    echo "exists: ${dest}"
    return
  fi
  cp "${src}" "${dest}"
  echo "created: ${dest}"
}

need_cmd git
need_cmd docker

mkdir -p "${REPOS_DIR}"

copy_if_missing "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
copy_if_missing "${ROOT_DIR}/Hermes/.env.example" "${ROOT_DIR}/Hermes/.env"

clone_repo "llama-cpp-turboquant" "https://github.com/TheTom/llama-cpp-turboquant.git" "feature/turboquant-kv-cache"
clone_repo "llama.cpp" "https://github.com/ggml-org/llama.cpp.git"
clone_repo "turboquant_plus" "https://github.com/TheTom/turboquant_plus.git"
clone_repo "hermes-agent" "https://github.com/NousResearch/hermes-agent.git"
clone_repo "pi-mono" "https://github.com/badlogic/pi-mono.git"
clone_repo "whisper.cpp" "https://github.com/ggml-org/whisper.cpp.git"
clone_repo "amd-strix-halo-toolboxes" "https://github.com/kyuz0/amd-strix-halo-toolboxes.git"

echo
echo "bootstrap complete"
echo "next:"
echo "  1. edit .env"
echo "  2. edit Hermes/.env"
echo "  3. docker compose up -d --build"
