#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_env="${project_dir}/.venv"
app_bin="${python_env}/bin/cap-to-talk"
status_bin="${python_env}/bin/cap-to-talk-status"
state_dir="${XDG_STATE_HOME:-${HOME}/.local/state}/cap-to-talk"
runtime_dir="${XDG_RUNTIME_DIR:-/tmp}"
lock_file="${runtime_dir}/cap-to-talk-${UID}.lock"
legacy_lock_file="${runtime_dir}/caps-talk-${UID}.lock"
pid_file="${runtime_dir}/cap-to-talk-${UID}.pid"
keyboard_state=""
app_pid=""
status_pid=""
cleaned_up=false

mkdir -p "${state_dir}"

exec 9>"${lock_file}"
if ! flock -n 9; then
    echo "Cap To Talk is already running." >&2
    exit 0
fi
exec 8>"${legacy_lock_file}"
if ! flock -n 8; then
    echo "Cap To Talk is already running." >&2
    exit 0
fi
printf '%s\n' "$$" >"${pid_file}"

[[ -x "${app_bin}" ]] || {
    echo "Python environment not found. Run ./install.sh first." >&2
    exit 1
}
[[ "${XDG_SESSION_TYPE:-}" == "x11" ]] || {
    echo "Cap To Talk requires an X11 desktop session." >&2
    exit 1
}
[[ -n "${DISPLAY:-}" ]] || {
    echo "The X11 DISPLAY variable is not set." >&2
    exit 1
}

# shellcheck disable=SC2317,SC2329 # Invoked by cleanup.
restore_keyboard() {
    [[ -n "${keyboard_state}" && -f "${keyboard_state}" ]] || return 0
    xkbcomp "${keyboard_state}" "${DISPLAY}" >/dev/null 2>&1 || true
    rm -f -- "${keyboard_state}"
    keyboard_state=""
}

# shellcheck disable=SC2317,SC2329 # Invoked by the EXIT trap.
cleanup() {
    [[ "${cleaned_up}" == false ]] || return 0
    cleaned_up=true
    [[ -z "${app_pid}" ]] || kill "${app_pid}" 2>/dev/null || true
    [[ -z "${status_pid}" ]] || kill "${status_pid}" 2>/dev/null || true
    restore_keyboard
    rm -f -- "${pid_file}"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Check the selected pipeline before changing the keyboard.
"${app_bin}" check --services-only --wait-seconds 30 || exit 1
read -r ptt_keycode hotkey <<<"$("${python_env}/bin/python" -c '
from cap_to_talk.config import load_settings
settings = load_settings()
print(settings.ptt_keycode, settings.hotkey)
')"

keyboard_state="$(mktemp "${runtime_dir}/cap-to-talk-keyboard.XXXXXX.xkb")"
xkbcomp -xkb "${DISPLAY}" "${keyboard_state}" >/dev/null 2>&1
if [[ "${hotkey:-auto}" == auto || "${hotkey}" == caps_lock ]]; then
    setxkbmap -option caps:none
    xmodmap -e 'clear Lock'
    xmodmap -e "keycode ${ptt_keycode} = NoSymbol"
fi
# The X11 adapter disables repeat for its selected key and restores it on exit.

"${status_bin}" >>"${state_dir}/status.log" 2>&1 &
status_pid="$!"
"${app_bin}" run >>"${state_dir}/cap-to-talk.log" 2>&1 &
app_pid="$!"

set +e
wait "${app_pid}"
exit_status="$?"
set -e
app_pid=""
exit "${exit_status}"
