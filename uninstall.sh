#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
config_root="${XDG_CONFIG_HOME:-${HOME}/.config}"
config_dir="${config_root}/cap-to-talk"
autostart_file="${config_root}/autostart/cap-to-talk.desktop"
service_file="${config_root}/systemd/user/cap-to-talk-openasr.service"
state_dir="${XDG_STATE_HOME:-${HOME}/.local/state}/cap-to-talk"
runtime_dir="${XDG_RUNTIME_DIR:-/tmp}"
pid_file="${runtime_dir}/cap-to-talk-${UID}.pid"
bin_dir="${HOME}/.local/bin"
purge=false
assume_yes=false

while (($#)); do
    case "$1" in
        --purge) purge=true ;;
        -y|--yes) assume_yes=true ;;
        -h|--help)
            echo "Usage: ./uninstall.sh [--purge] [--yes]"
            echo "--purge also deletes personal configuration and logs."
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

if [[ "${purge}" == true && "${assume_yes}" != true ]]; then
    read -r -p "Delete personal glossaries, configuration, and logs? [y/N] " answer
    [[ "${answer}" =~ ^[Yy]$ ]] || purge=false
fi

if [[ -f "${pid_file}" ]]; then
    pid="$(<"${pid_file}")"
    if [[ "${pid}" =~ ^[0-9]+$ ]] \
        && [[ -r "/proc/${pid}/cmdline" ]] \
        && tr '\0' ' ' <"/proc/${pid}/cmdline" | grep -Fq "${project_dir}"; then
        kill "${pid}" 2>/dev/null || true
    fi
fi

systemctl --user disable --now cap-to-talk-openasr.service 2>/dev/null || true
rm -f -- "${autostart_file}" "${service_file}" "${pid_file}"
systemctl --user daemon-reload 2>/dev/null || true

for command_name in cap-to-talk cap-to-talk-status; do
    command_link="${bin_dir}/${command_name}"
    expected_target="${project_dir}/.venv/bin/${command_name}"
    if [[ -L "${command_link}" \
        && "$(readlink "${command_link}")" == "${expected_target}" ]]; then
        rm -f -- "${command_link}"
    fi
done

venv_dir="${project_dir}/.venv"
if [[ -d "${venv_dir}" && "${venv_dir}" == "${project_dir}/.venv" ]]; then
    rm -rf -- "${venv_dir}"
fi

if [[ "${purge}" == true ]]; then
    [[ "${config_dir}" == */cap-to-talk ]] && rm -rf -- "${config_dir}"
    [[ "${state_dir}" == */cap-to-talk ]] && rm -rf -- "${state_dir}"
fi

echo "Cap To Talk was uninstalled. Shared OpenASR/Ollama files were preserved."
