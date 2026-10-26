#!/usr/bin/env bash
# Install Cap To Talk and its local models on macOS:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/farrantch/cap-to-talk/main/install-macos.sh)"

set -euo pipefail

repo="farrantch/cap-to-talk"
asr_model="qwen3-asr-0.6b:q8"
rewrite_model="qwen3:4b-instruct"
app_name="Cap To Talk.app"
agent_label="io.github.farrantch.cap-to-talk.openasr"
agent_file="${HOME}/Library/LaunchAgents/${agent_label}.plist"
config_dir="${HOME}/Library/Application Support/cap-to-talk"
log_dir="${HOME}/Library/Logs/cap-to-talk"
ollama_app_bin="/Applications/Ollama.app/Contents/Resources/ollama"
assume_yes=false
start_app=true
install_local_services=true
uninstall=false
dmg=""
tag=""

usage() {
    cat <<'EOF'
Usage: install-macos.sh [options]

Options:
  -y, --yes                  Skip the confirmation prompt
      --no-start             Install without opening Cap To Talk
      --skip-local-services  Do not install OpenASR, Ollama, or local models
      --version TAG          Install a specific release, such as v0.3.0b1
      --dmg PATH             Install from a local disk image instead of a release
      --uninstall            Remove the app and its OpenASR login service
  -h, --help                 Show this help
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

quit_app() {
    # SIGTERM lets a running copy restore the Caps Lock mapping before it exits.
    pkill -x CapToTalk 2>/dev/null || return 0
    local index
    for ((index = 1; index <= 20; index++)); do
        pgrep -x CapToTalk >/dev/null 2>&1 || return 0
        sleep 0.25
    done
    fail "Quit Cap To Talk, then rerun the installer."
}

stop_agent() {
    local index
    launchctl bootout "gui/${UID}/${agent_label}" 2>/dev/null || return 0
    for ((index = 1; index <= 20; index++)); do
        launchctl print "gui/${UID}/${agent_label}" >/dev/null 2>&1 || return 0
        sleep 0.25
    done
}

while (($#)); do
    case "$1" in
        -y|--yes) assume_yes=true ;;
        --no-start) start_app=false ;;
        --skip-local-services) install_local_services=false ;;
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
        -h|--help) usage; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
    shift
done

[[ "$(uname -s)" == "Darwin" ]] || fail "This installer is for macOS. On Linux, use ./install.sh."
[[ "${EUID}" -ne 0 ]] || fail "Run as your normal user, not root."
macos_major="$(sw_vers -productVersion | cut -d. -f1)"
((macos_major >= 15)) || fail "macOS 15 or newer is required."
case "$(uname -m)" in
    arm64) arch="arm64" ;;
    x86_64) arch="x86_64" ;;
    *) fail "Unsupported architecture: $(uname -m)" ;;
esac

apps_dir="/Applications"
if [[ ! -w "${apps_dir}" ]]; then
    apps_dir="${HOME}/Applications"
fi
app_path="${apps_dir}/${app_name}"

if [[ "${uninstall}" == true ]]; then
    cat <<EOF
This removes ${app_path} and the Cap To Talk OpenASR login service.
Settings, vocabulary, saved keys, models, OpenASR, and Ollama are kept.
EOF
    confirm
    quit_app
    stop_agent
    rm -f -- "${agent_file}"
    rm -rf -- "${app_path}"
    printf '\nUninstalled. Settings remain in %s\n' "${config_dir}"
    exit 0
fi

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

work_dir="$(mktemp -d)"
mount_dir="${work_dir}/mount"
cleanup() {
    if [[ -d "${mount_dir}" ]]; then
        hdiutil detach "${mount_dir}" -quiet 2>/dev/null || true
    fi
    rm -rf -- "${work_dir}"
}
trap cleanup EXIT

if [[ -z "${dmg}" ]]; then
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
fi
[[ -f "${dmg}" ]] || fail "Disk image not found: ${dmg}"

log "Installing ${app_name}"
quit_app
mkdir -p "${apps_dir}" "${mount_dir}"
hdiutil attach "${dmg}" -nobrowse -readonly -noautoopen -mountpoint "${mount_dir}" \
    >/dev/null
[[ -d "${mount_dir}/${app_name}" ]] || fail "The disk image does not contain ${app_name}."
rm -rf -- "${app_path}"
ditto "${mount_dir}/${app_name}" "${app_path}"
hdiutil detach "${mount_dir}" -quiet
xattr -dr com.apple.quarantine "${app_path}" 2>/dev/null || true

log "Preparing settings and vocabulary"
mkdir -p "${config_dir}"
for name in config.toml hotwords.txt master-hotwords.txt; do
    destination="${config_dir}/${name}"
    [[ ! -e "${destination}" ]] || continue
    example="${name%.*}.example.${name##*.}"
    curl -fsSL -o "${destination}.download" \
        "https://raw.githubusercontent.com/${repo}/${tag:-main}/config/${example}"
    mv -- "${destination}.download" "${destination}"
done

if [[ "${install_local_services}" == true ]]; then
    export PATH="${HOME}/.local/bin:${PATH}"
    mkdir -p "${log_dir}" "$(dirname -- "${agent_file}")"

    if ! command -v openasr >/dev/null 2>&1; then
        log "Installing OpenASR"
        curl -fsSL https://dl.openasr.org/install.sh -o "${work_dir}/openasr-install.sh"
        printf 'Running the OpenASR installer downloaded from https://dl.openasr.org/install.sh\n'
        sh "${work_dir}/openasr-install.sh"
    fi
    openasr_bin="$(command -v openasr || true)"
    [[ -n "${openasr_bin}" ]] || fail "OpenASR was not found after installation."

    log "Preparing the OpenASR model"
    "${openasr_bin}" pull "${asr_model}"

    if launchctl print "gui/${UID}/${agent_label}" >/dev/null 2>&1 \
        || ! wait_for_url http://127.0.0.1:8080/health 2; then
        log "Starting OpenASR at login"
        stop_agent
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

    ollama_bin="$(command -v ollama || true)"
    if [[ -z "${ollama_bin}" && -x "${ollama_app_bin}" ]]; then
        ollama_bin="${ollama_app_bin}"
    fi
    if [[ -z "${ollama_bin}" ]]; then
        log "Installing Ollama"
        curl -fsSL https://ollama.com/install.sh -o "${work_dir}/ollama-install.sh"
        printf 'Running the Ollama installer downloaded from https://ollama.com/install.sh\n'
        sh "${work_dir}/ollama-install.sh"
        ollama_bin="$(command -v ollama || echo "${ollama_app_bin}")"
    fi
    [[ -x "${ollama_bin}" ]] || fail "Ollama was not found after installation."

    if ! wait_for_url http://127.0.0.1:11434/api/tags 2; then
        log "Starting Ollama"
        if [[ -d /Applications/Ollama.app ]]; then
            open -a Ollama --args hidden
        else
            nohup "${ollama_bin}" serve >"${log_dir}/ollama.log" 2>&1 &
        fi
    fi
    wait_for_url http://127.0.0.1:11434/api/tags 60 || fail "Ollama did not become ready."

    log "Preparing the cleanup model"
    "${ollama_bin}" pull "${rewrite_model}"

    wait_for_url http://127.0.0.1:8080/health 60 \
        || fail "OpenASR did not become ready. Check ${log_dir}/openasr.log."
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
