#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${repo_root}/docker/local-network/compose.yaml"
compose=(docker compose -f "${compose_file}")

command="${1:-help}"
case "${command}" in
  config)
    "${compose[@]}" config --quiet
    ;;
  up)
    "${compose[@]}" up -d --build
    ;;
  down)
    "${compose[@]}" down --remove-orphans
    ;;
  reset)
    "${compose[@]}" down --volumes --remove-orphans
    ;;
  status)
    "${compose[@]}" ps
    ;;
  test)
    cleanup() {
      "${compose[@]}" ps --all > \
        "${repo_root}/artifacts/local-network/docker-compose-ps.log" 2>&1 || true
      "${compose[@]}" logs --no-color > \
        "${repo_root}/artifacts/local-network/docker-compose.log" 2>&1 || true
      "${compose[@]}" down --volumes --remove-orphans || true
    }
    mkdir -p "${repo_root}/artifacts/local-network"
    trap cleanup EXIT
    "${compose[@]}" config --quiet
    "${compose[@]}" up -d --build
    python3 "${repo_root}/scripts/dev/local_network_acceptance.py" 2>&1 | \
      tee "${repo_root}/artifacts/local-network/acceptance.log"
    ;;
  help|*)
    cat <<'EOF'
JUNCA isolated local network commands

  bash scripts/dev/local-network.sh config  Validate Compose configuration
  bash scripts/dev/local-network.sh up      Build and start three validators
  bash scripts/dev/local-network.sh status  Show service status
  bash scripts/dev/local-network.sh down    Stop services and preserve state
  bash scripts/dev/local-network.sh reset   Stop services and delete local state
  bash scripts/dev/local-network.sh test    Run finality, quorum-loss and recovery acceptance
EOF
    ;;
esac
