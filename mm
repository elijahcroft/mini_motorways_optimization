#!/usr/bin/env bash
# Run minimotor from its own venv, building the venv on first use.
#   ./mm                       -> the overlay panel
#   ./mm solve boards/x.json   -> anything main.py takes
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py="$here/.venv/bin/python"

if [ ! -x "$py" ]; then
    echo "setting up $here/.venv ..." >&2
    python3 -m venv "$here/.venv"
    "$here/.venv/bin/pip" install -q -e "$here"
fi

if [ $# -eq 0 ]; then
    exec "$py" "$here/main.py" overlay --now
fi
exec "$py" "$here/main.py" "$@"
