"""Verify every platform artifact before preparing a GitHub release."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

root = Path("release-assets")
destination = root / "files"
destination.mkdir(exist_ok=True)
expected = {
    "linux-amd64": ".deb",
    "windows-x64": ".exe",
    "macos-arm64": ".dmg",
    "macos-x86_64": ".dmg",
}
combined = []
for platform, suffix in expected.items():
    folder = root / f"cap-to-talk-{platform}-release"
    installers = list(folder.glob(f"*{suffix}"))
    if len(installers) != 1:
        raise RuntimeError(f"Expected one installer for {platform}.")
    installer = installers[0]
    checksum_file = folder / "SHA256SUMS.txt"
    checksums = dict(
        (filename, digest)
        for digest, filename in (
            line.split("  ", 1) for line in checksum_file.read_text().splitlines()
        )
    )
    with installer.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if checksums.get(installer.name) != actual:
        raise RuntimeError(f"Checksum mismatch: {installer.name}")
    shutil.copyfile(installer, destination / installer.name)
    combined.append(f"{actual}  {installer.name}")
(destination / "SHA256SUMS.txt").write_text("\n".join(sorted(combined)) + "\n")
