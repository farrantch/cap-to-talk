# Build with: python packaging/build_desktop.py bundle
import os
import sys
import tomllib

from packaging.version import Version
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
version = Version(tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"])
hidden = []
if sys.platform == "darwin":
    for package in (
        "objc", "AppKit", "Foundation", "CoreFoundation", "Quartz",
        "ApplicationServices", "AVFoundation", "CoreText", "CoreMedia", "CoreAudio",
    ):
        hidden.extend(collect_submodules(package))
    hidden.append("keyring.backends.macOS")
elif sys.platform == "win32":
    hidden.append("keyring.backends.Windows")
else:
    hidden.append("keyring.backends.SecretService")

data = collect_data_files("cap_to_talk", includes=["assets/*.png"])
data += [
    (str(root / "LICENSE"), "licenses"),
    (str(root / "packaging" / "THIRD_PARTY.md"), "licenses"),
    (str(root / "build" / "desktop-notices"), "licenses/dependencies"),
]
analysis = Analysis(
    [str(root / "packaging" / "desktop_entry.py")],
    pathex=[str(root / "src")], binaries=[], datas=data, hiddenimports=hidden,
    excludes=["tkinter", "pytest", "PySide6.QtQml", "PySide6.QtQuick"],
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True, name="CapToTalk",
    console=False, strip=False, upx=False,
    icon=str(root / "docs" / "assets" / "icon.png") if sys.platform != "linux" else None,
    codesign_identity=os.environ.get("MACOS_CODESIGN_IDENTITY") or None,
    entitlements_file=str(root / "packaging" / "macos-entitlements.plist") if sys.platform == "darwin" else None,
)
directory = COLLECT(
    executable, analysis.binaries, analysis.datas, name="CapToTalk",
    strip=False, upx=False,
)
if sys.platform == "darwin":
    application = BUNDLE(
        directory, name="Cap To Talk.app",
        icon=str(root / "docs" / "assets" / "icon.png"),
        bundle_identifier="io.github.farrantch.cap-to-talk",
        info_plist={
            "CFBundleShortVersionString": version.base_version,
            "CFBundleVersion": version.base_version,
            "LSMinimumSystemVersion": "15.0",
            "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription": "Cap To Talk records your voice while you hold the dictation key.",
        },
    )
