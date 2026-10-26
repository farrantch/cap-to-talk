#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
asr_model="qwen3-asr-0.6b:q8"
rewrite_model="qwen3:4b-instruct"
assume_yes=false
start_app=true
install_packages=true
enable_autostart=false
install_local_services=true

usage() {
    cat <<'EOF'
Usage: ./install.sh [options]

Options:
  -y, --yes                   Skip the confirmation prompt
      --autostart             Start Cap To Talk automatically at desktop login
      --no-start              Install without starting Cap To Talk
      --skip-system-packages  Do not use apt-get
      --skip-local-services   Do not install OpenASR, Ollama, or local models
  -h, --help                  Show this help
EOF
}

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
    local index

    for ((index = 1; index <= attempts; index++)); do
        if curl -fsS "${url}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

run_official_installer() {
    local name="$1"
    local url="$2"
    local installer
    installer="$(mktemp)"
    trap 'rm -f -- "${installer:-}"' RETURN
    curl -fsSL "${url}" -o "${installer}"
    printf 'Running the %s installer downloaded from %s\n' "${name}" "${url}"
    sh "${installer}"
    rm -f -- "${installer}"
    trap - RETURN
}

while (($#)); do
    case "$1" in
        -y|--yes) assume_yes=true ;;
        --autostart) enable_autostart=true ;;
        --no-start) start_app=false ;;
        --skip-system-packages) install_packages=false ;;
        --skip-local-services) install_local_services=false ;;
        -h|--help) usage; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
    shift
done

[[ "${EUID}" -ne 0 ]] || fail "Run as your normal desktop user, not root."
[[ "$(uname -s)" == "Linux" ]] || fail "Linux/X11 is required."
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
    fail "Wayland is not supported. Log into an X11 session and rerun."
fi

cat <<'EOF'
Cap To Talk will:
  • install missing Ubuntu/Debian desktop packages (with sudo)
  • create a Python virtual environment inside this checkout
EOF

if [[ "${install_local_services}" == true ]]; then
    cat <<'EOF'
  • install OpenASR and Ollama from their official installers if missing
  • download roughly 3.5 GB of local models
  • add a namespaced OpenASR user service
EOF
else
    printf '  • use AI providers configured in ~/.config/cap-to-talk/config.toml\n'
fi

if [[ "${enable_autostart}" == true ]]; then
    printf '  • start Cap To Talk automatically at desktop login\n'
else
    printf '  • configure Cap To Talk for on-demand use (the default)\n'
fi

cat <<'EOF'

Existing glossary files are preserved. Shared OpenASR and Ollama installations
are never removed by Cap To Talk.
EOF

if [[ "${assume_yes}" != true ]]; then
    read -r -p "Continue? [y/N] " answer
    [[ "${answer}" =~ ^[Yy]$ ]] || exit 0
fi

if [[ "${install_packages}" == true && -x "$(command -v apt-get || true)" ]]; then
    packages=(
        curl
        libnotify-bin
        libportaudio2
        python3-tk
        python3-venv
        util-linux
        x11-xkb-utils
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
        log "Installing system packages"
        command -v sudo >/dev/null 2>&1 || fail "sudo is required."
        sudo apt-get update
        sudo apt-get install -y "${missing_packages[@]}"
    fi
fi

required_commands=(
    curl
    flock
    notify-send
    python3
    setxkbmap
    xdotool
    xkbcomp
    xmodmap
    xprintidle
    xset
)
if [[ "${install_local_services}" == true ]]; then
    required_commands+=(systemctl)
fi
for command_name in "${required_commands[@]}"; do
    command -v "${command_name}" >/dev/null 2>&1 \
        || fail "Required command not found: ${command_name}"
done
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' \
    || fail "Python 3.12 or newer is required."

export PATH="${HOME}/.local/bin:${PATH}"
if [[ "${install_local_services}" == true ]]; then
    if ! command -v openasr >/dev/null 2>&1; then
        log "Installing OpenASR"
        run_official_installer "OpenASR" "https://dl.openasr.org/install.sh"
    fi
    openasr_bin="$(command -v openasr || true)"
    [[ -n "${openasr_bin}" ]] || fail "OpenASR was not found after installation."

    log "Preparing the OpenASR model"
    "${openasr_bin}" pull "${asr_model}"

    systemd_user_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
    mkdir -p "${systemd_user_dir}"
    legacy_service_file="${systemd_user_dir}/caps-talk-openasr.service"
    if [[ -f "${legacy_service_file}" ]]; then
        systemctl --user disable --now caps-talk-openasr.service \
            2>/dev/null || true
        rm -f -- "${legacy_service_file}"
    fi
    escaped_openasr_bin="${openasr_bin//|/\\|}"
    sed "s|@OPENASR_BIN@|${escaped_openasr_bin}|g" \
        "${project_dir}/systemd/cap-to-talk-openasr.service.in" \
        >"${systemd_user_dir}/cap-to-talk-openasr.service"
    systemctl --user daemon-reload

    if ! wait_for_url http://127.0.0.1:8080/health 2; then
        log "Starting the Cap To Talk OpenASR service"
        systemctl --user enable --now cap-to-talk-openasr.service
    fi

    if ! command -v ollama >/dev/null 2>&1; then
        log "Installing Ollama"
        run_official_installer "Ollama" "https://ollama.com/install.sh"
    fi

    if ! wait_for_url http://127.0.0.1:11434/api/tags 2; then
        log "Starting Ollama"
        if systemctl list-unit-files ollama.service --no-legend 2>/dev/null \
            | grep -q ollama.service; then
            sudo systemctl enable --now ollama.service
        else
            state_dir="${XDG_STATE_HOME:-${HOME}/.local/state}/cap-to-talk"
            mkdir -p "${state_dir}"
            nohup ollama serve >"${state_dir}/ollama.log" 2>&1 &
        fi
    fi
    wait_for_url http://127.0.0.1:11434/api/tags 30 \
        || fail "Ollama did not become ready."

    log "Preparing the cleanup model"
    ollama pull "${rewrite_model}"
fi

log "Installing Cap To Talk"
if [[ "${enable_autostart}" == true ]]; then
    "${project_dir}/scripts/install-user.sh" --autostart
else
    "${project_dir}/scripts/install-user.sh"
fi

if [[ "${install_local_services}" == true ]]; then
    wait_for_url http://127.0.0.1:8080/health 60 \
        || fail "OpenASR did not become ready. Check its user service."
fi

if [[ "${start_app}" == true && "${XDG_SESSION_TYPE:-}" == "x11" \
    && -n "${DISPLAY:-}" ]]; then
    nohup "${project_dir}/scripts/start.sh" >/dev/null 2>&1 &
    printf '\nInstalled. Cap To Talk is starting; hold Caps Lock to try it.\n'
else
    if [[ "${enable_autostart}" == true ]]; then
        printf '\nInstalled. It will start automatically in your next X11 session.\n'
    else
        printf '\nInstalled. Start it on demand with ./scripts/start.sh.\n'
    fi
fi
