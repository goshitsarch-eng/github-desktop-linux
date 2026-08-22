# Native GTK 4 GitHub Desktop

This directory is a **full rewrite** of GitHub Desktop for Linux using **GTK 4** and **libadwaita**, with light, dark, and system appearance. It keeps feature parity with the Electron app in this repository (version 3.5.4): Git workflows, GitHub.com / Enterprise auth, PRs, diffs, stashing, rebase / merge / cherry-pick / squash, Copilot commit messages, secret scanning errors, the `github` CLI, and `x-github-client://` protocol handlers.

## Requirements

- Python 3.10+
- GTK 4 and libadwaita 1.5+
- PyGObject (`python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`)
- Git
- Optional: `gir1.2-secret-1` (GNOME Keyring / libsecret)

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
  gir1.2-secret-1 git
```

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
PYTHONPATH=. python3 -m pytest tests -q
# GTK widget tests (needs a display or Xvfb):
xvfb-run -a env GTK_A11Y=none PYTHONPATH=. python3 -m pytest tests/test_gtk_smoke.py -q
```

## Install (meson)

```bash
cd native
meson setup build
meson install -C build
```

Appearance is **System**, **Light**, or **Dark** in Preferences → Appearance (Adwaita `StyleManager`).
