#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_env="${project_dir}/.venv"
app_bin="${python_env}/bin/cap-to-talk"
status_bin="${python_env}/bin/cap-to-talk-status"
state_dir="${XDG_STATE_HOME:-${HOME}/.local/state}/cap-to-talk"
runtime_dir="${XDG_RUNTIME_DIR:-/tmp}"
lock_file="${runtime_dir}/cap-to-talk-${UID}.lock"
pid_file="${runtime_dir}/cap-to-talk-${UID}.pid"
keyboard_state=""
app_pid=""
status_pid=""
cleaned_up=false

mkdir -p "${state_dir}"

exec 9>"${lock_file}"
if ! flock -n 9; then
    echo "Cap to Talk is already running." >&2
    exit 0
fi
printf '%s\n' "$$" >"${pid_file}"

[[ -x "${app_bin}" ]] || {
    echo "Python environment not found. Run ./install.sh first." >&2
    exit 1
}
[[ "${XDG_SESSION_TYPE:-}" == "x11" ]] || {
    echo "Cap to Talk requires an X11 desktop session." >&2
    exit 1
}
[[ -n "${DISPLAY:-}" ]] || {
    echo "The X11 DISPLAY variable is not set." >&2
    exit 1
}

wait_for_url() {
    local url="$1"
    local attempts="${2:-30}"
    local index
    for ((index = 1; index <= attempts; index++)); do
        curl -fsS "${url}" >/dev/null 2>&1 && return 0
        sleep 1
    done
    return 1
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

runtime_settings_output="$("${python_env}/bin/python" -c '
from cap_to_talk.config import load_settings
settings = load_settings()
print(settings.asr_health_url)
print(settings.ollama_health_url)
print(settings.ptt_keycode)
')"
mapfile -t runtime_settings <<<"${runtime_settings_output}"
[[ "${#runtime_settings[@]}" -eq 3 ]] || exit 1
asr_health_url="${runtime_settings[0]}"
ollama_health_url="${runtime_settings[1]}"
ptt_keycode="${runtime_settings[2]}"

wait_for_url "${asr_health_url}" || {
    echo "OpenASR is not ready. Run: ${app_bin} check" >&2
    exit 1
}
if ! wait_for_url "${ollama_health_url}" 2; then
    echo "Ollama is not ready; cleanup will fall back to raw transcripts." >&2
fi

keyboard_state="$(mktemp "${runtime_dir}/cap-to-talk-keyboard.XXXXXX.xkb")"
xkbcomp -xkb "${DISPLAY}" "${keyboard_state}" >/dev/null 2>&1
setxkbmap -option caps:none
xmodmap -e 'clear Lock'
xmodmap -e "keycode ${ptt_keycode} = NoSymbol"
xset -r "${ptt_keycode}"

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
