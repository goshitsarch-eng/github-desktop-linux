# Install GitHub Desktop for Linux

This is the installation guide for the unofficial Linux releases from `goshitsarch-eng/github-desktop-linux`. GitHub, Inc. does not publish or support these packages.

The Linux UI is a **native GTK 4 + libadwaita** application. Releases publish a meson prefix tarball (`GitHubDesktop-linux-native-<version>.tar.gz`) that installs under `/usr`.

## Choose a release

Open the [latest release](https://github.com/goshitsarch-eng/github-desktop-linux/releases/latest) and download:

```text
GitHubDesktop-linux-native-<version>.tar.gz
```

The archive contains a `usr/` tree (`bin/github-desktop`, the `github` CLI helper, the desktop file, icons, and the Python package).

### Verify the source

Download only from this repository's [Releases page](https://github.com/goshitsarch-eng/github-desktop-linux/releases). Review the release tag and, when GitHub displays an asset digest, compare it with the downloaded file. The current workflow does not attach a separate checksum or signature file, so do not trust checksums copied from comments or third-party download sites.

## Runtime requirements

Install GTK 4, libadwaita, PyGObject, Git, and a Secret Service provider before launching.

| Purpose | Debian/Ubuntu | Fedora/RHEL |
| --- | --- | --- |
| Python GObject / GTK 4 / Adwaita | `python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-4.0`, `gir1.2-adw-1` | `python3-gobject`, `gtk4`, `libadwaita` |
| Secret Service | `gir1.2-secret-1`, `gnome-keyring` | `libsecret`, `gnome-keyring` |
| Git | `git` | `git` |

```bash
# Debian or Ubuntu
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
  gir1.2-secret-1 gnome-keyring git

# Fedora or RHEL
sudo dnf install python3-gobject gtk4 libadwaita libsecret gnome-keyring git
```

The native app uses **system Git**. A graphical Linux session is required.

## Install the release tarball

The tarball is built with `--prefix=/usr`. Extract it at the filesystem root (or another prefix if you adjust `PATH` and Python's package path yourself):

```bash
sudo tar -C / -xzf GitHubDesktop-linux-native-<version>.tar.gz
github-desktop
```

That installs:

- `/usr/bin/github-desktop` — GTK 4 application
- `/usr/bin/github` — command-line helper
- `/usr/share/applications/io.github.desktop.GitHubDesktop.desktop`
- `/usr/share/icons/hicolor/scalable/apps/io.github.desktop.GitHubDesktop.svg`

Then refresh desktop and icon caches if your environment does not pick the new files up immediately:

```bash
sudo gtk4-update-icon-cache -f /usr/share/icons/hicolor
sudo update-desktop-database /usr/share/applications
```

## Install from a source checkout (meson)

```bash
cd native
meson setup build --prefix=/usr
meson compile -C build
sudo meson install -C build
github-desktop
```

For a user prefix:

```bash
cd native
meson setup build --prefix="$HOME/.local"
meson compile -C build
meson install -C build
```

Ensure `~/.local/bin` is on `PATH`. Python must be able to import `github_desktop` from the prefix's site-packages directory.

## Run from a source checkout without installing

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

## Desktop menu and browser sign-in

A meson or tarball install already ships `io.github.desktop.GitHubDesktop.desktop` with:

```text
MimeType=x-scheme-handler/x-github-client;x-scheme-handler/x-github-desktop-auth;x-scheme-handler/x-github-desktop-dev-auth;
```

Register it if the desktop environment does not pick it up after install:

```bash
update-desktop-database "$HOME/.local/share/applications"  # user prefix
# or
sudo update-desktop-database /usr/share/applications
xdg-mime default io.github.desktop.GitHubDesktop.desktop x-scheme-handler/x-github-client
xdg-mime default io.github.desktop.GitHubDesktop.desktop x-scheme-handler/x-github-desktop-auth
```

Confirm registration:

```bash
xdg-mime query default x-scheme-handler/x-github-desktop-auth
```

It should print `io.github.desktop.GitHubDesktop.desktop`. Development builds use `x-github-desktop-dev-auth` as well; that handler is listed on the same desktop file.

## Command-line helper

After a prefix install, `github` is on `PATH` next to `github-desktop`:

```bash
github                         # Open the current directory
github open /path/to/repo
github clone owner/repository
github --help
```

## Environment variables

| Variable | Behavior |
| --- | --- |
| `GITHUB_DESKTOP_OFFLINE=1` | Skip Central stats and changelog network calls |
| `GITHUB_DESKTOP_PREVIEW_FEATURES=1` | Enable available preview features |
| `XDG_CONFIG_HOME` | Override the base configuration location |

Appearance is **System**, **Light**, or **Dark** in Preferences → Appearance.

## Data and logs

The native app follows XDG locations:

| Data | Default location |
| --- | --- |
| Settings and account data | `~/.config/github-desktop/` |
| Logs | `~/.local/share/github-desktop/logs/` |
| Cache | `~/.cache/github-desktop/` |

**Help → Show logs in your File Manager** is the preferred way to find logs.

Locations can differ if XDG environment variables are customized.

## Update

Quit the app, then either extract the new prefix tarball over `/` or reinstall with meson. Application data under `~/.config/github-desktop/` is retained. Back it up before a major upgrade if it is important.

## Uninstall

Remove the files you installed. After a `/usr` prefix tarball or `meson install`:

```bash
sudo rm -f /usr/bin/github-desktop /usr/bin/github
sudo rm -f /usr/share/applications/io.github.desktop.GitHubDesktop.desktop
sudo rm -f /usr/share/icons/hicolor/scalable/apps/io.github.desktop.GitHubDesktop.svg
sudo rm -rf "$(python3 -c 'import site; print(site.getsitepackages()[0])')/github_desktop"
sudo update-desktop-database /usr/share/applications
```

Those commands preserve user data. To reset the app completely, first back up anything needed, then:

```bash
rm -rf "$HOME/.config/github-desktop" \
  "$HOME/.local/share/github-desktop" \
  "$HOME/.cache/github-desktop"
```

## Troubleshooting

See [known issues](known-issues.md) for OAuth, keyring, and graphics problems. When reporting a reproducible Linux problem, use this repository's [bug report form](https://github.com/goshitsarch-eng/github-desktop-linux/issues/new?template=bug_report.yaml).
