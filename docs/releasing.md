# Building and releasing desktop apps

The project version is currently `0.3.0b1`. The desktop UI and installer recipes
are implemented; real macOS/Windows validation and signing accounts are still
needed before a public beta.

## Local builds

Install the project and build tools in a virtual environment:

```bash
python -m pip install -e ".[dev,desktop,packaging]"
python packaging/build_desktop.py bundle
python packaging/build_desktop.py smoke
python packaging/build_desktop.py package
python packaging/build_desktop.py checksums
```

Build on the target operating system. Outputs are:

| Target | Bundle | Installer |
| --- | --- | --- |
| Linux | `dist/CapToTalk/` | `dist/installers/*.deb` |
| Windows | `dist/CapToTalk/` | `dist/installers/*-setup.exe` |
| macOS | `dist/Cap To Talk.app` | `dist/installers/*.dmg` |

The Linux recipe targets Ubuntu 24.04+ and uses `dpkg-deb`. Build on Ubuntu 24.04
to keep the declared glibc requirement accurate. The Windows recipe needs
[Inno Setup](https://jrsoftware.org/isinfo.php). Mac disk images use `hdiutil`.
Mac architectures have separate artifacts.

The smoke test opens and closes an offscreen settings window, using a temporary
configuration directory. It loads the bundled native SDK and credential backend
without grabbing keys, accessing stored keys, recording, or contacting providers.
This checks packaging; it does not replace interactive tests.

The bundle includes the Python runtime, Qt, app dependencies, component notices,
and a dependency-version manifest. It excludes personal settings, API keys,
vocabulary files, and model weights. See [third-party notices](../packaging/THIRD_PARTY.md).
[PyInstaller](https://pyinstaller.org/en/stable/operating-mode.html) builds each
platform separately.

## GitHub test builds

Pull requests generate unsigned test builds. You can also run **Actions >
Desktop builds > Run workflow** after the workflow is in the default branch.
Leave **signed** unchecked for initial testers.

The workflow builds on Ubuntu 24.04, Windows 2025, macOS 15 Apple Silicon, and
macOS 15 Intel. It runs tests, lint, dependency auditing, and packaged smoke
checks, then uploads installers and SHA-256 checksums as artifacts for 14 days.

Unsigned test artifacts are explicitly named `unsigned-test`. They are for
testers who understand OS installation prompts. They do not create a GitHub release.
Selecting **signed** exercises the same signing path used for release candidates.

## macOS signing and notarization

Configure these GitHub repository secrets before signed builds:

| Secret | Value |
| --- | --- |
| `MACOS_CERTIFICATE_BASE64` | Base64-encoded Developer ID Application certificate/private key export (.p12) |
| `MACOS_CERTIFICATE_PASSWORD` | Password for that export |
| `MACOS_CODESIGN_IDENTITY` | Full Developer ID Application signing identity |
| `MACOS_NOTARY_KEY_BASE64` | Base64-encoded App Store Connect API private key (.p8) |
| `MACOS_NOTARY_KEY_ID` | API key ID |
| `MACOS_NOTARY_ISSUER` | Issuer ID |

The build imports the identity into a temporary keychain, signs the app with
PyInstaller's hardened-runtime support and PyObjC's required JIT entitlement,
restores the original keychain search
list, and deletes the temporary identity. It submits the disk image using
`notarytool`, then staples and validates the ticket. Temporary certificate and
notarization files are removed.

The callback entitlement follows [PyObjC's signing guidance](https://pyobjc.readthedocs.io/en/latest/notes/codesigning.html).

An [Apple Developer ID](https://developer.apple.com/developer-id/) identity and
notarization credentials must come from the project owner's account. Do not
commit these credentials.

## Windows signing

The workflow uses Azure Artifact Signing with GitHub OIDC. Configure an Azure
signing account and certificate profile, grant the signing role to an application,
and configure federated credentials for the repository/tag or manual-build branch.
Follow the [official action's setup](https://github.com/Azure/artifact-signing-action).

Repository secrets:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

Repository variables:

- `AZURE_SIGNING_ENDPOINT`
- `AZURE_SIGNING_ACCOUNT`
- `AZURE_SIGNING_PROFILE`

The workflow signs the executable and bundled native libraries before compiling
the installer, signs the installer afterward, verifies the application and
installer signatures, and only then computes checksums. An alternative signing
service can replace these two signing steps. A new signed application can still
receive SmartScreen prompts while reputation develops; see
[Microsoft's signing guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options).

## Draft release

1. Finish real desktop checks from [desktop integration validation](desktop.md#validation-and-release-work),
   including installing on a clean machine, choosing providers, saving keys,
   granting/denying permissions, and quitting during recording/processing.
2. Update both version declarations in `pyproject.toml` and
   `src/cap_to_talk/__init__.py`, plus release notes and the changelog.
3. Commit the reviewed changes and create a matching tag, such as `v0.3.0b1`.
4. Push the tag. Tag builds require signing; missing credentials fail the build.
5. After every platform succeeds, the workflow verifies the checksums again and
   creates a **draft prerelease** with all four installers, combined checksums,
   and the release notes.
6. Review the draft downloads and testing results, then publish the prerelease.

Linux packages use checksums; Mac and Windows packages additionally use platform
signing. A failed platform, invalid checksum, or signing failure prevents the
draft-release job. Manual builds do not publish anything.

The first workflow deliberately creates prereleases. Promote a tested beta
through GitHub's release editor when it is ready. The app links to the releases
page for updates.
