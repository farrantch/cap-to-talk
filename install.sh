#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
asr_model="qwen3-asr-0.6b:q8"
rewrite_model="qwen3:4b-instruct"

log() {
    printf '\n==> %s\n' "$*"
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

wait_for_url() {
    local url="$1"
    local attempts="${2:-30}"

    for ((i = 1; i <= attempts; i++)); do
        if curl -fsS "${url}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done

    return 1
}

if [[ "${EUID}" -eq 0 ]]; then
    fail "Run this installer as your normal desktop user, not as root."
fi

if [[ "$(uname -s)" != "Linux" ]]; then
    fail "Cap to Talk currently supports Linux/X11 only."
fi

if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
    fail "This session is Wayland. Log into an X11 session and rerun the installer."
fi

if command -v apt-get >/dev/null 2>&1; then
    packages=(
        curl
        libnotify-bin
        libportaudio2
        python3-tk
        python3-venv
        x11-xserver-utils
        xdotool
        xprintidle
    )
    missing_packages=()

    for package in "${packages[@]}"; do
        if ! dpkg-query -W -f='${Status}' "${package}" 2>/dev/null \
            | grep -q 'install ok installed'; then
            missing_packages+=("${package}")
        fi
    done

    if ((${#missing_packages[@]})); then
        log "Installing Ubuntu/Debian packages"
        sudo apt-get update
        sudo apt-get install -y "${missing_packages[@]}"
    else
        log "System packages are already installed"
    fi
else
    log "Skipping system packages (apt-get was not found)"
    printf '%s\n' \
        "Install these equivalents with your package manager:" \
        "curl, libnotify, PortAudio, Tk, Python venv, xdotool, xprintidle, and X11 utilities."
fi

command -v curl >/dev/null 2>&1 || fail "curl is required."

export PATH="${HOME}/.local/bin:${PATH}"

if ! command -v openasr >/dev/null 2>&1; then
    log "Installing OpenASR"
    curl -fsSL https://dl.openasr.org/install.sh | sh
fi

openasr_bin="$(command -v openasr || true)"
[[ -n "${openasr_bin}" ]] || fail "OpenASR was not found after installation."

log "Downloading the OpenASR model (if needed)"
"${openasr_bin}" pull "${asr_model}"

systemd_user_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
mkdir -p "${systemd_user_dir}"
escaped_openasr_bin="${openasr_bin//|/\\|}"
sed "s|@OPENASR_BIN@|${escaped_openasr_bin}|g" \
    "${project_dir}/systemd/openasr.service.in" \
    >"${systemd_user_dir}/openasr.service"

log "Starting OpenASR"
systemctl --user daemon-reload
systemctl --user enable --now openasr.service

if ! command -v ollama >/dev/null 2>&1; then
    log "Installing Ollama"
    curl -fsSL https://ollama.com/install.sh | sh
fi

if ! wait_for_url http://127.0.0.1:11434/api/tags 2; then
    log "Starting Ollama"

    if systemctl list-unit-files ollama.service --no-legend 2>/dev/null \
        | grep -q ollama.service; then
        sudo systemctl enable --now ollama.service
    else
        nohup ollama serve >/tmp/ollama.log 2>&1 &
    fi
fi

wait_for_url http://127.0.0.1:11434/api/tags 30 \
    || fail "Ollama did not become ready. Check /tmp/ollama.log or the ollama service."

log "Downloading the cleanup model (if needed)"
ollama pull "${rewrite_model}"

log "Installing Cap to Talk"
"${project_dir}/scripts/install-user.sh"

wait_for_url http://127.0.0.1:8080/health 60 \
    || fail "OpenASR did not become ready. Run: systemctl --user status openasr.service"

if [[ "${XDG_SESSION_TYPE:-}" == "x11" && -n "${DISPLAY:-}" ]]; then
    if ! pgrep -f "${project_dir}/src/cap_to_talk.py" >/dev/null; then
        nohup "${project_dir}/scripts/start.sh" \
            >/tmp/cap-to-talk.log 2>&1 &
    fi

    printf '\nCap to Talk is installed and starting. Hold Caps Lock to try it.\n'
else
    printf '\nCap to Talk is installed. Log into an X11 session to use it.\n'
fi
