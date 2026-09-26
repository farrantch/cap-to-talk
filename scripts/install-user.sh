#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
config_root="${XDG_CONFIG_HOME:-${HOME}/.config}"
config_dir="${config_root}/caps-talk"
legacy_cap_config_dir="${config_root}/cap-to-talk"
legacy_voice_config_dir="${config_root}/voice-dictate"
autostart_dir="${config_root}/autostart"
state_dir="${XDG_STATE_HOME:-${HOME}/.local/state}/caps-talk"
bin_dir="${HOME}/.local/bin"

python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' \
    || { echo "Python 3.12 or newer is required." >&2; exit 1; }

python3 -m venv "${project_dir}/.venv"
"${project_dir}/.venv/bin/python" -m pip install --upgrade pip
"${project_dir}/.venv/bin/python" -m pip uninstall --yes cap-to-talk \
    >/dev/null 2>&1 || true
legacy_metadata_dir="${project_dir}/src/cap_to_talk.egg-info"
if [[ -d "${legacy_metadata_dir}" ]]; then
    rm -rf -- "${legacy_metadata_dir}"
fi
"${project_dir}/.venv/bin/python" -m pip install --editable "${project_dir}"

mkdir -p "${config_dir}" "${autostart_dir}" "${state_dir}" "${bin_dir}"

link_command() {
    local command_name="$1"
    local source="${project_dir}/.venv/bin/${command_name}"
    local destination="${bin_dir}/${command_name}"
    if [[ -e "${destination}" || -L "${destination}" ]]; then
        if [[ ! -L "${destination}" || "$(readlink "${destination}")" != "${source}" ]]; then
            echo "Refusing to replace existing command: ${destination}" >&2
            exit 1
        fi
    fi
    ln -sfn "${source}" "${destination}"
}

link_command caps-talk
link_command caps-talk-status
link_command cap-to-talk
link_command cap-to-talk-status

install_if_missing() {
    local destination="$1"
    shift
    local source
    [[ ! -e "${destination}" ]] || return 0
    for source in "$@"; do
        if [[ -f "${source}" ]]; then
            install -m 0644 "${source}" "${destination}"
            return 0
        fi
    done
}

install_if_missing \
    "${config_dir}/hotwords.txt" \
    "${legacy_cap_config_dir}/hotwords.txt" \
    "${legacy_voice_config_dir}/hotwords.txt" \
    "${project_dir}/config/hotwords.example.txt"
install_if_missing \
    "${config_dir}/master-hotwords.txt" \
    "${legacy_cap_config_dir}/master-hotwords.txt" \
    "${legacy_voice_config_dir}/master-hotwords.txt" \
    "${project_dir}/config/master-hotwords.example.txt"
install_if_missing \
    "${config_dir}/config.toml" \
    "${legacy_cap_config_dir}/config.toml" \
    "${project_dir}/config/config.example.toml"

escaped_project_dir="${project_dir//|/\\|}"
sed "s|@PROJECT_DIR@|${escaped_project_dir}|g" \
    "${project_dir}/autostart/caps-talk.desktop.in" \
    >"${autostart_dir}/caps-talk.desktop"

for legacy_desktop in \
    "${autostart_dir}/cap-to-talk.desktop" \
    "${autostart_dir}/capslock-voice-dictation.desktop"; do
    if [[ -f "${legacy_desktop}" ]] \
        && grep -Fq "${project_dir}" "${legacy_desktop}"; then
        rm -f -- "${legacy_desktop}"
    fi
done

printf 'Installed the commands, configuration, and desktop autostart entry.\n'
