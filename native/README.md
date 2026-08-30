# Native Qt 6 / Kirigami GitHub Desktop

This directory is the Linux application: a **Qt 6 + Kirigami** rewrite of GitHub Desktop
that uses the KDE frameworks, follows the Plasma colour scheme, and keeps feature parity
with the Electron app in this repository (version 3.5.4) — Git workflows, GitHub.com and
Enterprise auth, pull requests, diffs, stashing, rebase / merge / cherry-pick / squash,
Copilot commit messages, secret scanning errors, the `github` CLI, and
`x-github-client://` protocol handlers.

## Requirements

- Python 3.10+
- Qt 6 and PySide6 (Qt 6 for Python)
- Kirigami, from KDE Frameworks 6
- Git
- Optional: KWallet or a Secret Service provider for token storage

| Component | Debian / Ubuntu | Fedora | Arch |
| --- | --- | --- | --- |
| PySide6 | `python3-pyside6.qtquick`, `python3-pyside6.qtdbus` | `python3-pyside6` | `pyside6` |
| Kirigami | `qml6-module-org-kde-kirigami` | `kf6-kirigami` | `kirigami` |
| Qt Quick Controls | `qml6-module-qtquick-controls` | `qt6-qtquickcontrols2` | `qt6-declarative` |
| Icons | `breeze-icon-theme` | `breeze-icon-theme` | `breeze-icons` |

```bash
# Debian / Ubuntu (24.10 or newer for KDE Frameworks 6)
sudo apt install python3-pyside6.qtquick python3-pyside6.qtdbus \
  qml6-module-org-kde-kirigami qml6-module-qtquick-controls breeze-icon-theme git

# Fedora
sudo dnf install python3-pyside6 kf6-kirigami qt6-qtquickcontrols2 breeze-icon-theme git

# Arch
sudo pacman -S pyside6 kirigami qt6-declarative breeze-icons git
```

If PySide6 is not packaged for your distribution, `pip install PySide6` works; Kirigami
must come from the distribution, because it is a QML module rather than a Python one.

## Run from a source checkout

```bash
cd native
PYTHONPATH=. python3 -m github_desktop
```

CLI helper:

```bash
PYTHONPATH=. python3 -m github_desktop.cli --help
PYTHONPATH=. python3 -m github_desktop.cli open /path/to/repo
PYTHONPATH=. python3 -m github_desktop.cli clone desktop/desktop
```

## Tests

```bash
cd native
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest tests -q
```

Everything runs headless. The QML smoke tests use the real Kirigami when it is installed
and otherwise fall back to `tests/qmlstub`, a stand-in that is enough to instantiate the
UI and catch a broken binding — see `tests/kirigami_stub.py` for what that does and does
not prove. CI runs both: the Ubuntu job against the stub, and a Fedora container job
against the real module.

## Install (meson)

```bash
cd native
meson setup build --prefix=/usr
meson install -C build
```

## How it fits together

| Layer | Where | What it does |
| --- | --- | --- |
| Git and GitHub | `github_desktop/git`, `github_desktop/github` | Runs `git`, talks to the API |
| State | `github_desktop/store.py` | One observable store; `emit()` on every change |
| Bridge | `github_desktop/ui/bridge.py` | Exposes that state to QML as properties and models |
| Interface | `github_desktop/ui/qml` | Kirigami views, dialogs and shared components |

Nothing below `ui/` imports Qt: the store runs unchanged under pytest and in the `github`
CLI, and marshals onto the GUI thread through `github_desktop/mainloop.py` when there is
one. Dialog wording lives in `ui/dialogs.py` and diff presentation in `ui/diff_view.py`,
so the parity tests can check them without a window.

Appearance is **System**, **Light**, or **Dark** in Settings → Appearance. System follows
the desktop's own colour scheme through `QStyleHints.colorScheme`, which Plasma, GNOME and
the freedesktop appearance portal all drive; the other two override it for this
application only.

## Credential storage

Tokens go to the first backend that answers:

1. **KWallet** over D-Bus — the native store on a Plasma session.
2. **Secret Service**, through libsecret's `secret-tool` helper, when it is installed.
3. A `0600` JSON file under the config directory, so the app still works on a session
   with no keyring at all.
