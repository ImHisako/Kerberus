#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
if command -v go >/dev/null 2>&1; then
  mkdir -p build/native
  (cd native && go build -trimpath -o ../build/native/kerberus-native .)
else
  echo "Avviso: Go non trovato; messaggi vocali e trasporto nativo non saranno disponibili." >&2
fi
echo "Kerberus installato. Avvia con ./start.sh"
