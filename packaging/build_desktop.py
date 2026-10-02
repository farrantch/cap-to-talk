"""Build native desktop bundles, installers, and release checksums."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
VERSION = PROJECT["project"]["version"]
SIGNED = os.environ.get("REQUIRE_SIGNING", "").lower() == "true"


def run(*arguments: str | Path, **kwargs) -> None:
    subprocess.run([str(item) for item in arguments], check=True, **kwargs)


def collect_notices() -> None:
    destination = ROOT / "build" / "desktop-notices"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    pending = list(PROJECT["project"]["dependencies"])
    pending += PROJECT["project"]["optional-dependencies"]["desktop"]
    visited = set()
    from PySide6.QtCore import qVersion

    manifest = [
        {"name": "Python", "version": platform.python_version()},
        {"name": "Qt", "version": qVersion()},
    ]
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        name = requirement.name.lower().replace("_", "-")
        if name in visited:
            continue
        visited.add(name)
        distribution = importlib.metadata.distribution(requirement.name)
        manifest.append(
            {"name": distribution.metadata["Name"], "version": distribution.version}
        )
        pending.extend(distribution.requires or [])
        for item in distribution.files or []:
            if any(
                part.lower().startswith(("license", "copying", "notice"))
                for part in item.parts
            ):
                source = Path(distribution.locate_file(item))
                if source.is_file():
                    target = destination / name / str(item).replace("\\", "/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    python_license = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copyfile(python_license, destination / "PYTHON-LICENSE.txt")
    (destination / "versions.json").write_text(json.dumps(manifest, indent=2) + "\n")


@contextmanager
def macos_identity():
    certificate = os.environ.get("MACOS_CERTIFICATE_BASE64", "")
    identity = os.environ.get("MACOS_CODESIGN_IDENTITY", "")
    if SIGNED and not (
        certificate and identity and os.environ.get("MACOS_CERTIFICATE_PASSWORD")
    ):
        raise RuntimeError(
            "Signed Mac builds require the Developer ID certificate, "
            "password, and identity."
        )
    if not certificate:
        yield
        return
    with tempfile.TemporaryDirectory(prefix="cap-to-talk-signing-") as folder:
        folder = Path(folder)
        certificate_path = folder / "developer.p12"
        certificate_path.write_bytes(base64.b64decode(certificate, validate=True))
        certificate_path.chmod(0o600)
        keychain = folder / "build.keychain-db"
        password = os.urandom(24).hex()
        original = subprocess.check_output(
            ["security", "list-keychains", "-d", "user"], text=True
        )
        previous = [
            line.strip().strip('"') for line in original.splitlines() if line.strip()
        ]
        try:
            run("security", "create-keychain", "-p", password, keychain)
            run("security", "set-keychain-settings", "-lut", "21600", keychain)
            run("security", "unlock-keychain", "-p", password, keychain)
            run(
                "security",
                "import",
                certificate_path,
                "-P",
                os.environ["MACOS_CERTIFICATE_PASSWORD"],
                "-k",
                keychain,
                "-T",
                "/usr/bin/codesign",
            )
            run(
                "security",
                "set-key-partition-list",
                "-S",
                "apple-tool:,apple:,codesign:",
                "-s",
                "-k",
                password,
                keychain,
            )
            run("security", "list-keychains", "-d", "user", "-s", keychain, *previous)
            yield
        finally:
            run("security", "list-keychains", "-d", "user", "-s", *previous)
            subprocess.run(["security", "delete-keychain", str(keychain)], check=False)


def bundle() -> None:
    collect_notices()
    arguments = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST),
        "--workpath",
        str(ROOT / "build" / "desktop-pyinstaller"),
        str(ROOT / "packaging" / "desktop.spec"),
    ]
    if sys.platform == "darwin":
        with macos_identity():
            run(*arguments, cwd=ROOT)
        run("codesign", "--verify", "--deep", "--strict", DIST / "Cap To Talk.app")
    else:
        run(*arguments, cwd=ROOT)


def notarize(dmg: Path) -> None:
    names = ("MACOS_NOTARY_KEY_BASE64", "MACOS_NOTARY_KEY_ID", "MACOS_NOTARY_ISSUER")
    values = [os.environ.get(name, "") for name in names]
    if not all(values):
        if SIGNED:
            raise RuntimeError(
                "Signed Mac releases require App Store Connect API "
                "notarization credentials."
            )
        return
    if not os.environ.get("MACOS_CODESIGN_IDENTITY"):
        raise RuntimeError("Notarization requires a Developer ID signed bundle.")
    with tempfile.TemporaryDirectory(prefix="cap-to-talk-notary-") as folder:
        key = Path(folder) / "notary.p8"
        key.write_bytes(base64.b64decode(values[0], validate=True))
        key.chmod(0o600)
        run(
            "xcrun",
            "notarytool",
            "submit",
            dmg,
            "--key",
            key,
            "--key-id",
            values[1],
            "--issuer",
            values[2],
            "--wait",
        )
    run("xcrun", "stapler", "staple", dmg)
    run("xcrun", "stapler", "validate", dmg)


def package() -> None:
    output = DIST / "installers"
    output.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        architecture = platform.machine()
        dmg = output / f"cap-to-talk-{VERSION}-macos-{architecture}.dmg"
        with tempfile.TemporaryDirectory(prefix="cap-to-talk-dmg-") as folder:
            staging = Path(folder)
            shutil.copytree(
                DIST / "Cap To Talk.app", staging / "Cap To Talk.app", symlinks=True
            )
            (staging / "Applications").symlink_to("/Applications")
            run(
                "hdiutil",
                "create",
                "-volname",
                "Cap To Talk",
                "-srcfolder",
                staging,
                "-format",
                "UDZO",
                "-ov",
                dmg,
            )
        notarize(dmg)
    elif sys.platform == "win32":
        compiler = shutil.which("ISCC.exe")
        if compiler is None:
            program_files = Path(
                os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")
            )
            candidates = sorted(program_files.glob("Inno Setup */ISCC.exe"))
            compiler = str(candidates[-1]) if candidates else None
        if compiler is None:
            raise RuntimeError("Install Inno Setup and add ISCC.exe to PATH.")
        run(
            compiler,
            f"/DAppVersion={VERSION}",
            f"/DBundleDir={DIST / 'CapToTalk'}",
            f"/DOutputDir={output}",
            ROOT / "packaging" / "windows.iss",
        )
    elif sys.platform == "linux":
        architecture = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
        deb_version = VERSION.replace("b", "~beta")
        with tempfile.TemporaryDirectory(prefix="cap-to-talk-deb-") as folder:
            staging = Path(folder)
            shutil.copytree(
                DIST / "CapToTalk", staging / "opt/cap-to-talk", symlinks=True
            )
            control = staging / "DEBIAN"
            control.mkdir()
            (control / "control").write_text(
                f"Package: cap-to-talk\nVersion: {deb_version}\n"
                f"Architecture: {architecture}\n"
                "Maintainer: Chase Farrant\nSection: sound\nPriority: optional\n"
                "Depends: libc6 (>= 2.39), libegl1, libopengl0, libxcb-cursor0, "
                "libxkbcommon-x11-0, libportaudio2, xdotool, "
                "xprintidle, libnotify-bin, "
                "x11-xkb-utils, x11-xserver-utils\nRecommends: gnome-keyring\n"
                "Homepage: https://github.com/farrantch/cap-to-talk\n"
                "Description: Push-to-talk dictation with configurable AI providers\n"
                " Desktop settings and global dictation for X11 sessions.\n"
            )
            applications = staging / "usr/share/applications"
            applications.mkdir(parents=True)
            (applications / "cap-to-talk.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Cap To Talk\n"
                "Comment=Push-to-talk dictation\nExec=/opt/cap-to-talk/CapToTalk\n"
                "Icon=cap-to-talk\nTerminal=false\nCategories=AudioVideo;Audio;Accessibility;\n"
            )
            icons = staging / "usr/share/pixmaps"
            icons.mkdir(parents=True)
            shutil.copyfile(ROOT / "docs/assets/icon.png", icons / "cap-to-talk.png")
            run(
                "dpkg-deb",
                "--build",
                "--root-owner-group",
                staging,
                output / f"cap-to-talk-{VERSION}-linux-{architecture}.deb",
            )
    else:
        raise RuntimeError("Unsupported build platform.")


def smoke() -> None:
    if sys.platform == "darwin":
        executable = DIST / "Cap To Talk.app/Contents/MacOS/CapToTalk"
    else:
        executable = (
            DIST
            / "CapToTalk"
            / ("CapToTalk.exe" if sys.platform == "win32" else "CapToTalk")
        )
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    run(executable, "--smoke-test", env=environment, timeout=45)


def checksums() -> None:
    folder = DIST / "installers"
    artifacts = sorted(
        item for item in folder.iterdir() if item.suffix in (".deb", ".dmg", ".exe")
    )
    if not artifacts:
        raise RuntimeError("No installers were built.")
    lines = []
    for artifact in artifacts:
        with artifact.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        lines.append(f"{digest}  {artifact.name}")
    (folder / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("bundle", "package", "smoke", "checksums", "validate-tag")
    )
    args = parser.parse_args()
    if args.command == "validate-tag":
        tag = os.environ.get("RELEASE_TAG", "")
        if tag != f"v{VERSION}":
            raise SystemExit(f"Tag must match pyproject.toml: v{VERSION}")
        Version(VERSION)
    else:
        globals()[args.command]()


if __name__ == "__main__":
    main()
