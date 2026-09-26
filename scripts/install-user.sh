#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
config_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/voice-dictate"
autostart_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart"

python3 -m venv "${project_dir}/.venv"
"${project_dir}/.venv/bin/python" -m pip install --upgrade pip
"${project_dir}/.venv/bin/python" -m pip install \
    -r "${project_dir}/requirements.txt"

mkdir -p "${config_dir}" "${autostart_dir}"

if [[ ! -e "${config_dir}/hotwords.txt" ]]; then
    install -m 0644 \
        "${project_dir}/config/hotwords.example.txt" \
        "${config_dir}/hotwords.txt"
fi

if [[ ! -e "${config_dir}/master-hotwords.txt" ]]; then
    install -m 0644 \
        "${project_dir}/config/master-hotwords.example.txt" \
        "${config_dir}/master-hotwords.txt"
fi

escaped_project_dir="${project_dir//|/\\|}"
sed "s|@PROJECT_DIR@|${escaped_project_dir}|g" \
    "${project_dir}/autostart/capslock-voice-dictation.desktop.in" \
    >"${autostart_dir}/capslock-voice-dictation.desktop"

chmod +x "${project_dir}/scripts/start.sh"

echo "Installed the Python environment and desktop autostart entry."
echo "Log out and back in, or run: ${project_dir}/scripts/start.sh"
