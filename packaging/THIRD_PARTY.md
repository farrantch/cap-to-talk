# Bundled components

Cap To Talk is distributed under the MIT license in the adjacent LICENSE file.

The desktop application also contains Python, Qt for Python (PySide6/Shiboken),
Qt libraries and plugins (LGPLv3), NumPy, Requests, RapidFuzz, SoundDevice/PortAudio,
Keyring, TOML Kit, and their dependencies. macOS builds include PyObjC;
Linux builds include Python Xlib.

Dependency license files and version information are copied into
licenses/dependencies when building. Python's license is included when supplied
by the build interpreter. Components keep their respective licenses.

The application uses a directory bundle with dynamically loaded Qt libraries.
Source code and licensing information for Qt and Qt for Python are available at:
- https://code.qt.io/
- https://download.qt.io/official_releases/qt/
- https://download.qt.io/official_releases/QtForPython/
- https://www.qt.io/licensing/open-source-lgpl-obligations

Cap To Talk source and build instructions:
https://github.com/farrantch/cap-to-talk

No AI model weights, provider credentials, personal settings, or vocabulary
files are included in the application bundle.

The app's Licenses button opens these notices. The Qt and PySide source versions
match the versions in dependencies/versions.json. Use the corresponding release
from the Qt and Qt for Python source download pages above. To modify the app or
replace a library, build from source with the desired dependency version and the
packaging recipes in this repository. Modified binaries may need to be signed
with your own identity when installed on macOS or Windows.
