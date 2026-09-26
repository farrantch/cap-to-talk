#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${VOICE_PYTHON:-${project_dir}/.venv/bin/python}"

sleep "${VOICE_STARTUP_DELAY:-2}"

if [[ ! -x "${python_bin}" ]]; then
    echo "Python environment not found: ${python_bin}" >&2
    echo "Run ./install.sh first." >&2
    exit 1
fi

# Start the optional status overlay once.
if ! pgrep -f "${project_dir}/src/status_ui.py" >/dev/null; then
    nohup "${python_bin}" "${project_dir}/src/status_ui.py" \
        >/tmp/voice-status.log 2>&1 &
    sleep 0.5
fi

# Turn Caps Lock into a push-to-talk key under X11.
setxkbmap -option caps:none
xmodmap -e 'clear Lock'
xmodmap -e 'keycode 66 = NoSymbol'
xset -r 66

# Give the local transcription service up to 30 seconds to become healthy.
for _ in {1..30}; do
    if curl -sf http://127.0.0.1:8080/health >/dev/null; then
        break
    fi
    sleep 1
done

exec "${python_bin}" "${project_dir}/src/cap_to_talk.py"
