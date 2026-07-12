#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  ./setup.sh
fi
exec .venv/bin/python -m kerberus.main
