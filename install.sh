#!/usr/bin/env bash
# Install, update, or uninstall Cap To Talk on Linux (X11) or macOS 15+:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/farrantch/cap-to-talk/main/install.sh)"

set -euo pipefail

repo="farrantch/cap-to-talk"
asr_model="qwen3-asr-0.6b:q8"
rewrite_model="qwen3:4b-instruct"
assume_yes=false
start_app=true
enable_autostart=false
install_packages=true
install_local_services=true
uninstall=false
purge=false
dmg=""
tag=""
original_args=("$@")

usage() {
    cat <<'EOF'
Usage: install.sh [options]

Installs or updates Cap To Talk, OpenASR, Ollama, and the local models.

Options:
  -y, --yes                   Skip the confirmation prompt
      --no-start              Do not start Cap To Talk afterwards
      --skip-local-services   Do not install OpenASR, Ollama, or local models
      --autostart             Linux: start Cap To Talk at desktop login
      --skip-system-packages  Linux: do not install packages with apt-get
      --version TAG           macOS: install a specific release, such as v0.3.0b1
      --dmg PATH              macOS: install from a local disk image
      --uninstall             Remove Cap To Talk; settings, saved keys, models,
                              OpenASR, and Ollama are kept
      --purge                 With --uninstall, also delete settings and logs
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

confirm() {
    local answer
    [[ "${assume_yes}" != true ]] || return 0
    [[ -r /dev/tty ]] || fail "No terminal is available for confirmation; rerun with --yes."
    read -r -p "Continue? [y/N] " answer </dev/tty
    [[ "${answer}" =~ ^[Yy]$ ]] || exit 0
}

run_official_installer() {
    local name="$1"
    local url="$2"
    shift 2
    curl -fsSL "${url}" -o "${work_dir}/${name}-install.sh"
    printf 'Running the %s installer downloaded from %s\n' "${name}" "${url}"
    env "$@" sh "${work_dir}/${name}-install.sh"
}

while (($#)); do
    case "$1" in
        -y|--yes) assume_yes=true ;;
        --no-start) start_app=false ;;
        --skip-local-services) install_local_services=false ;;
        --autostart) enable_autostart=true ;;
        --skip-system-packages) install_packages=false ;;
        --version)
            (($# >= 2)) || fail "--version requires a release tag."
            tag="$2"
            shift
            ;;
        --dmg)
            (($# >= 2)) || fail "--dmg requires a path."
            dmg="$2"
            shift
            ;;
        --uninstall) uninstall=true ;;
        --purge) purge=true ;;
        -h|--help) usage; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
    shift
done

case "$(uname -s)" in
    Darwin) os="macos" ;;
    Linux) os="linux" ;;
    *) fail "This installer supports Linux and macOS. On Windows, use the installer from https://github.com/${repo}/releases." ;;
esac
[[ "${EUID}" -ne 0 ]] || fail "Run as your normal user, not root."
[[ "${purge}" == false || "${uninstall}" == true ]] || fail "--purge requires --uninstall."

# A checkout is used in place; a downloaded copy of this script has none.
script_dir=""
if [[ -f "${BASH_SOURCE[0]:-}" ]]; then
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
fi
checkout=""
if [[ -n "${script_dir}" ]] && grep -qs '^name = "cap-to-talk"' "${script_dir}/pyproject.toml"; then
    checkout="${script_dir}"
fi

work_dir="$(mktemp -d)"
mount_dir="${work_dir}/mount"
cleanup() {
    if [[ -d "${mount_dir}" ]]; then
        hdiutil detach "${mount_dir}" -quiet 2>/dev/null || true
    fi
    rm -rf -- "${work_dir}"
}
trap cleanup EXIT

# Settings, local models, and services shared by both platforms.

seed_settings() {
    local name destination example
    log "Preparing settings and vocabulary"
    mkdir -p "${config_dir}"
    for name in config.toml hotwords.txt master-hotwords.txt; do
        destination="${config_dir}/${name}"
        [[ ! -e "${destination}" ]] || continue
        example="${name%.*}.example.${name##*.}"
        if [[ -n "${checkout}" ]]; then
            install -m 0644 "${checkout}/config/${example}" "${destination}"
        else
            curl -fsSL -o "${destination}.download" \
                "https://raw.githubusercontent.com/${repo}/${tag:-main}/config/${example}"
            mv -- "${destination}.download" "${destination}"
        fi
    done
}

install_openasr() {
    export PATH="${HOME}/.local/bin:${PATH}"
    if ! command -v openasr >/dev/null 2>&1; then
        log "Installing OpenASR"
        run_official_installer OpenASR https://dl.openasr.org/install.sh
    fi
    openasr_bin="$(command -v openasr || true)"
    [[ -n "${openasr_bin}" ]] || fail "OpenASR was not found after installation."

    log "Preparing the OpenASR model"
    "${openasr_bin}" pull "${asr_model}"
}

install_ollama() {
    local app_bin="/Applications/Ollama.app/Contents/Resources/ollama"
    ollama_bin="$(command -v ollama || true)"
    if [[ -z "${ollama_bin}" && -x "${app_bin}" ]]; then
        ollama_bin="${app_bin}"
    fi
    if [[ -z "${ollama_bin}" ]]; then
        log "Installing Ollama"
        if [[ "${os}" == macos ]]; then
            # Start Ollama below by path; the installer's start can run before
            # macOS registers the new app by name.
            run_official_installer Ollama https://ollama.com/install.sh OLLAMA_NO_START=1
        else
            run_official_installer Ollama https://ollama.com/install.sh
        fi
        ollama_bin="$(command -v ollama || echo "${app_bin}")"
    fi
    [[ -x "${ollama_bin}" ]] || fail "Ollama was not found after installation."

    if ! wait_for_url http://127.0.0.1:11434/api/tags 2; then
        log "Starting Ollama"
        if [[ "${os}" == macos && -d /Applications/Ollama.app ]]; then
            open /Applications/Ollama.app --args hidden
        elif [[ "${os}" == linux ]] \
            && systemctl list-unit-files ollama.service --no-legend 2>/dev/null \
            | grep -q ollama.service; then
            sudo systemctl enable --now ollama.service
        else
            mkdir -p "${log_dir}"
            nohup "${ollama_bin}" serve >"${log_dir}/ollama.log" 2>&1 &
        fi
    fi
    wait_for_url http://127.0.0.1:11434/api/tags 60 || fail "Ollama did not become ready."

    log "Preparing the cleanup model"
    "${ollama_bin}" pull "${rewrite_model}"
}

wait_for_openasr() {
    wait_for_url http://127.0.0.1:8080/health 60 \
        || fail "OpenASR did not become ready. Check ${openasr_log_hint}."
}

# macOS: the release app, with OpenASR as a LaunchAgent.

macos_setup() {
    agent_label="io.github.farrantch.cap-to-talk.openasr"
    agent_file="${HOME}/Library/LaunchAgents/${agent_label}.plist"
    config_dir="${XDG_CONFIG_HOME:-${HOME}/Library/Application Support}/cap-to-talk"
    log_dir="${HOME}/Library/Logs/cap-to-talk"
    openasr_log_hint="${log_dir}/openasr.log"
    app_name="Cap To Talk.app"
    apps_dir="/Applications"
    if [[ ! -w "${apps_dir}" ]]; then
        apps_dir="${HOME}/Applications"
    fi
    app_path="${apps_dir}/${app_name}"
    case "$(uname -m)" in
        arm64) arch="arm64" ;;
        x86_64) arch="x86_64" ;;
        *) fail "Unsupported architecture: $(uname -m)" ;;
    esac
    macos_major="$(sw_vers -productVersion | cut -d. -f1)"
    ((macos_major >= 15)) || fail "macOS 15 or newer is required."
}

macos_quit_app() {
    # SIGTERM lets a running copy restore the Caps Lock mapping before it exits.
    pkill -x CapToTalk 2>/dev/null || return 0
    local index
    for ((index = 1; index <= 20; index++)); do
        pgrep -x CapToTalk >/dev/null 2>&1 || return 0
        sleep 0.25
    done
    fail "Quit Cap To Talk, then rerun the installer."
}

macos_stop_agent() {
    local index
    launchctl bootout "gui/${UID}/${agent_label}" 2>/dev/null || return 0
    for ((index = 1; index <= 20; index++)); do
        launchctl print "gui/${UID}/${agent_label}" >/dev/null 2>&1 || return 0
        sleep 0.25
    done
}

macos_download_release() {
    local releases_url dmg_url release_url expected actual
    log "Finding the Cap To Talk release"
    releases_url="https://api.github.com/repos/${repo}/releases?per_page=20"
    if [[ -n "${tag}" ]]; then
        releases_url="https://api.github.com/repos/${repo}/releases/tags/${tag}"
    fi
    curl -fsSL "${releases_url}" -o "${work_dir}/releases.json" \
        || fail "Could not read releases from GitHub."
    # The list is newest first and includes prereleases.
    dmg_url="$(grep -Eo "https://[^\"]+/cap-to-talk-[^\"/]+-macos-${arch}\\.dmg" \
        "${work_dir}/releases.json" | head -n 1 || true)"
    [[ -n "${dmg_url}" ]] || fail "No macOS ${arch} download was found in ${tag:-the releases}."
    release_url="${dmg_url%/*}"
    tag="${release_url##*/}"
    dmg="${work_dir}/${dmg_url##*/}"

    log "Downloading Cap To Talk ${tag}"
    curl -fL --progress-bar -o "${dmg}" "${dmg_url}"
    curl -fsSL -o "${work_dir}/SHA256SUMS.txt" "${release_url}/SHA256SUMS.txt"
    expected="$(awk -v name="${dmg_url##*/}" '$2 == name { print $1 }' \
        "${work_dir}/SHA256SUMS.txt")"
    actual="$(shasum -a 256 "${dmg}" | awk '{ print $1 }')"
    [[ -n "${expected}" && "${expected}" == "${actual}" ]] \
        || fail "Checksum verification failed for ${dmg_url##*/}."
    printf 'Checksum verified.\n'
}

macos_install() {
    printf 'Cap To Talk will:\n'
    if [[ -n "${dmg}" ]]; then
        printf '  • install %s from %s\n' "${app_name}" "${dmg}"
    else
        printf '  • download %s (%s) from GitHub releases\n' "${tag:-the newest release}" "${arch}"
    fi
    printf '  • install it into %s\n' "${apps_dir}"
    if [[ "${install_local_services}" == true ]]; then
        cat <<'EOF'
  • install OpenASR and Ollama from their official installers if missing
  • download roughly 3.5 GB of local models
  • start OpenASR at login with a user LaunchAgent
EOF
    fi
    cat <<'EOF'

Existing settings and vocabulary files are preserved. Beta builds are not signed
by Apple, so the installer clears the download quarantine flag on the app.
EOF
    confirm

    [[ -n "${dmg}" ]] || macos_download_release
    [[ -f "${dmg}" ]] || fail "Disk image not found: ${dmg}"

    log "Installing ${app_name}"
    macos_quit_app
    mkdir -p "${apps_dir}" "${mount_dir}"
    hdiutil attach "${dmg}" -nobrowse -readonly -noautoopen -mountpoint "${mount_dir}" \
        >/dev/null
    [[ -d "${mount_dir}/${app_name}" ]] || fail "The disk image does not contain ${app_name}."
    rm -rf -- "${app_path}"
    ditto "${mount_dir}/${app_name}" "${app_path}"
    hdiutil detach "${mount_dir}" -quiet
    xattr -dr com.apple.quarantine "${app_path}" 2>/dev/null || true

    seed_settings

    if [[ "${install_local_services}" == true ]]; then
        install_openasr
        if launchctl print "gui/${UID}/${agent_label}" >/dev/null 2>&1 \
            || ! wait_for_url http://127.0.0.1:8080/health 2; then
            log "Starting OpenASR at login"
            macos_stop_agent
            mkdir -p "${log_dir}" "$(dirname -- "${agent_file}")"
            cat >"${agent_file}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${agent_label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${openasr_bin}</string>
        <string>serve</string>
        <string>--model</string>
        <string>${asr_model%%:*}</string>
        <string>--addr</string>
        <string>127.0.0.1:8080</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${log_dir}/openasr.log</string>
    <key>StandardErrorPath</key>
    <string>${log_dir}/openasr.log</string>
</dict>
</plist>
EOF
            plutil -lint "${agent_file}" >/dev/null
            launchctl bootstrap "gui/${UID}" "${agent_file}"
        fi
        install_ollama
        wait_for_openasr
    fi

    if [[ "${start_app}" == true ]]; then
        open "${app_path}"
    fi

    cat <<EOF

Installed ${app_path}.

Next steps:
  1. In Cap To Talk, click Start dictation. macOS asks for Accessibility and
     Input Monitoring: enable Cap To Talk in both lists under System Settings >
     Privacy & Security, then quit and reopen Cap To Talk.
  2. Click Start dictation again, focus a text field, hold Caps Lock, speak,
     and release. Allow microphone access when asked.

Beta updates are unsigned, so macOS asks for these permissions again after
each update. Rerun this installer to update.
EOF
}

macos_uninstall() {
    cat <<EOF
This removes ${app_path} and the Cap To Talk OpenASR login service.
Saved keys, models, OpenASR, and Ollama are kept.
EOF
    if [[ "${purge}" == true ]]; then
        printf 'Settings, vocabulary, and logs are deleted.\n'
    else
        printf 'Settings and vocabulary are kept.\n'
    fi
    confirm
    macos_quit_app
    macos_stop_agent
    rm -f -- "${agent_file}"
    rm -rf -- "${app_path}"
    if [[ "${purge}" == true ]]; then
        rm -rf -- "${config_dir}" "${log_dir}"
    fi
    printf '\nUninstalled Cap To Talk.\n'
}

# Linux: a Python environment in a checkout, with OpenASR as a systemd user service.

linux_setup() {
    config_root="${XDG_CONFIG_HOME:-${HOME}/.config}"
    config_dir="${config_root}/cap-to-talk"
    data_root="${XDG_DATA_HOME:-${HOME}/.local/share}"
    state_dir="${XDG_STATE_HOME:-${HOME}/.local/state}/cap-to-talk"
    log_dir="${state_dir}"
    bin_dir="${HOME}/.local/bin"
    managed_dir="${data_root}/cap-to-talk"
    autostart_file="${config_root}/autostart/cap-to-talk.desktop"
    menu_file="${data_root}/applications/cap-to-talk.desktop"
    service_file="${config_root}/systemd/user/cap-to-talk-openasr.service"
    openasr_log_hint="journalctl --user -u cap-to-talk-openasr.service"
}

linux_install_packages() {
    local packages=(
        curl
        git
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
    local missing=()
    local package
    [[ "${install_packages}" == true && -x "$(command -v apt-get || true)" ]] || return 0
    for package in "${packages[@]}"; do
        if ! dpkg-query -W -f='${Status}' "${package}" 2>/dev/null \
            | grep -q 'install ok installed'; then
            missing+=("${package}")
        fi
    done
    if ((${#missing[@]})); then
        log "Installing system packages"
        command -v sudo >/dev/null 2>&1 || fail "sudo is required."
        sudo apt-get update
        sudo apt-get install -y "${missing[@]}"
    fi
}

linux_desktop_entry() {
    cat <<EOF
[Desktop Entry]
Type=Application
Name=Cap To Talk
Comment=Hold Caps Lock to dictate into the active X11 window
Exec=${project_dir}/scripts/start.sh
TryExec=${project_dir}/scripts/start.sh
Icon=${project_dir}/docs/assets/icon.png
Terminal=false
Categories=Utility;Accessibility;Audio;
Keywords=dictation;speech;voice;transcription;
EOF
}

linux_owns() {
    [[ -f "$1" ]] && grep -Fq "Exec=${project_dir}/scripts/start.sh" "$1"
}

linux_link_command() {
    local source="${project_dir}/.venv/bin/$1"
    local destination="${bin_dir}/$1"
    if [[ -e "${destination}" || -L "${destination}" ]]; then
        if [[ ! -L "${destination}" || "$(readlink "${destination}")" != "${source}" ]]; then
            fail "Refusing to replace existing command: ${destination}"
        fi
    fi
    ln -sfn "${source}" "${destination}"
}

linux_install() {
    [[ "${XDG_SESSION_TYPE:-}" != wayland ]] \
        || fail "Wayland is not supported. Log into an X11 session and rerun."

    if [[ -z "${CAP_TO_TALK_CONFIRMED:-}" ]]; then
        printf 'Cap To Talk will:\n'
        if [[ "${install_packages}" == true ]]; then
            printf '  • install missing Ubuntu/Debian desktop packages (with sudo)\n'
        fi
        if [[ -z "${checkout}" ]]; then
            printf '  • download Cap To Talk into %s\n' "${managed_dir}"
        fi
        printf '  • create a Python environment and an applications-menu launcher\n'
        if [[ "${install_local_services}" == true ]]; then
            cat <<'EOF'
  • install OpenASR and Ollama from their official installers if missing
  • download roughly 3.5 GB of local models
  • start OpenASR at login with a systemd user service
EOF
        fi
        if [[ "${enable_autostart}" == true ]]; then
            printf '  • start Cap To Talk automatically at desktop login\n'
        fi
        printf '\nExisting settings and vocabulary files are preserved.\n'
        confirm
    fi

    linux_install_packages

    if [[ -z "${checkout}" ]]; then
        command -v git >/dev/null 2>&1 || fail "git is required."
        if [[ -d "${managed_dir}/.git" ]]; then
            log "Updating ${managed_dir}"
            git -C "${managed_dir}" pull --ff-only
        else
            log "Downloading Cap To Talk"
            git clone "https://github.com/${repo}.git" "${managed_dir}"
        fi
        CAP_TO_TALK_CONFIRMED=1 exec bash "${managed_dir}/install.sh" "${original_args[@]}"
    fi
    project_dir="${checkout}"

    local required_commands=(
        curl flock notify-send python3 setxkbmap xdotool xkbcomp xmodmap xprintidle xset
    )
    if [[ "${install_local_services}" == true ]]; then
        required_commands+=(systemctl)
    fi
    local command_name
    for command_name in "${required_commands[@]}"; do
        command -v "${command_name}" >/dev/null 2>&1 \
            || fail "Required command not found: ${command_name}"
    done
    python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' \
        || fail "Python 3.12 or newer is required."

    if [[ "${install_local_services}" == true ]]; then
        install_openasr
        mkdir -p "$(dirname -- "${service_file}")"
        cat >"${service_file}" <<EOF
[Unit]
Description=Cap To Talk local OpenASR server
Documentation=https://github.com/${repo}

[Service]
ExecStart=${openasr_bin} serve --model ${asr_model%%:*} --addr 127.0.0.1:8080
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF
        systemctl --user daemon-reload
        if ! wait_for_url http://127.0.0.1:8080/health 2; then
            log "Starting OpenASR at login"
            systemctl --user enable --now cap-to-talk-openasr.service
        fi
        install_ollama
    fi

    log "Installing Cap To Talk"
    python3 -m venv "${project_dir}/.venv"
    "${project_dir}/.venv/bin/python" -m pip install --upgrade pip
    "${project_dir}/.venv/bin/python" -m pip install --editable "${project_dir}"
    mkdir -p "${state_dir}" "${bin_dir}" "$(dirname -- "${menu_file}")"
    linux_link_command cap-to-talk
    linux_link_command cap-to-talk-status
    seed_settings
    linux_desktop_entry >"${menu_file}"
    if [[ "${enable_autostart}" == true ]]; then
        mkdir -p "$(dirname -- "${autostart_file}")"
        {
            linux_desktop_entry
            printf 'X-GNOME-Autostart-enabled=true\n'
        } >"${autostart_file}"
    elif linux_owns "${autostart_file}"; then
        rm -f -- "${autostart_file}"
    fi

    if [[ "${install_local_services}" == true ]]; then
        wait_for_openasr
    fi

    if [[ "${start_app}" == true && "${XDG_SESSION_TYPE:-}" == x11 && -n "${DISPLAY:-}" ]]; then
        nohup "${project_dir}/scripts/start.sh" >/dev/null 2>&1 &
        printf '\nInstalled. Cap To Talk is starting; hold Caps Lock to try it.\n'
    else
        printf '\nInstalled. Start Cap To Talk from your applications menu.\n'
    fi
    if [[ "${enable_autostart}" == true ]]; then
        printf 'It also starts automatically at desktop login.\n'
    fi
}

linux_uninstall() {
    local pid_file pid command_name command_link
    project_dir="${checkout:-${managed_dir}}"
    printf 'This removes Cap To Talk from %s and its OpenASR user service.\n' "${project_dir}"
    printf 'Saved keys, models, OpenASR, and Ollama are kept.\n'
    if [[ "${purge}" == true ]]; then
        printf 'Settings, vocabulary, and logs are deleted.\n'
    else
        printf 'Settings and vocabulary are kept.\n'
    fi
    confirm

    pid_file="${XDG_RUNTIME_DIR:-/tmp}/cap-to-talk-${UID}.pid"
    if [[ -f "${pid_file}" ]]; then
        pid="$(<"${pid_file}")"
        if [[ "${pid}" =~ ^[0-9]+$ && -r "/proc/${pid}/cmdline" ]] \
            && tr '\0' ' ' <"/proc/${pid}/cmdline" | grep -Fq "${project_dir}"; then
            kill "${pid}" 2>/dev/null || true
        fi
        rm -f -- "${pid_file}"
    fi

    systemctl --user disable --now cap-to-talk-openasr.service 2>/dev/null || true
    rm -f -- "${service_file}"
    systemctl --user daemon-reload 2>/dev/null || true
    for command_link in "${autostart_file}" "${menu_file}"; do
        if linux_owns "${command_link}"; then
            rm -f -- "${command_link}"
        fi
    done
    for command_name in cap-to-talk cap-to-talk-status; do
        command_link="${bin_dir}/${command_name}"
        if [[ -L "${command_link}" \
            && "$(readlink "${command_link}")" == "${project_dir}/.venv/bin/${command_name}" ]]; then
            rm -f -- "${command_link}"
        fi
    done
    if [[ "${project_dir}" == "${managed_dir}" ]]; then
        rm -rf -- "${managed_dir}"
    else
        rm -rf -- "${project_dir}/.venv"
    fi
    if [[ "${purge}" == true ]]; then
        rm -rf -- "${config_dir}" "${state_dir}"
    fi
    printf '\nUninstalled Cap To Talk.\n'
}

if [[ "${os}" == macos ]]; then
    macos_setup
    if [[ "${uninstall}" == true ]]; then macos_uninstall; else macos_install; fi
else
    linux_setup
    if [[ "${uninstall}" == true ]]; then linux_uninstall; else linux_install; fi
fi
