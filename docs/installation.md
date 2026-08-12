# Install GitHub Desktop for Linux

This is the installation guide for the unofficial Linux releases from `goshitsarch-eng/github-desktop-linux`. GitHub, Inc. does not publish or support these packages.

## Choose a release

Open the [latest release](https://github.com/goshitsarch-eng/github-desktop-linux/releases/latest) and choose both an architecture and a format.

| Your system | Release architecture |
| --- | --- |
| 64-bit Intel or AMD (`uname -m` reports `x86_64`) | `x64` |
| 64-bit ARM (`uname -m` reports `aarch64` or `arm64`) | `arm64` |

| Format | Use case |
| --- | --- |
| AppImage | Simplest portable desktop application; recommended for most users |
| `.tar.gz` | Portable directory; useful when AppImage/FUSE is unavailable |

The release workflow currently uploads AppImages and tarballs. Although the source contains DEB and RPM packaging scripts, `.deb` and `.rpm` files are not currently uploaded by that workflow.

### Verify the source

Download only from this repository's [Releases page](https://github.com/goshitsarch-eng/github-desktop-linux/releases). Review the release tag and, when GitHub displays an asset digest, compare it with the downloaded file. The current workflow does not attach a separate checksum or signature file, so do not trust checksums copied from comments or third-party download sites.

## Install an AppImage

The examples use placeholders. Substitute the exact filename you downloaded.

```bash
cd ~/Downloads
chmod +x GitHubDesktop-linux-<architecture>-<version>.AppImage
./GitHubDesktop-linux-<architecture>-<version>.AppImage
```

AppImage mounts itself temporarily and does not require a system installation. If it reports a FUSE error, install your distribution's FUSE 2 compatibility package (often `libfuse2`) or use the tarball.

For a stable location:

```bash
mkdir -p "$HOME/Applications"
mv GitHubDesktop-linux-<architecture>-<version>.AppImage \
  "$HOME/Applications/GitHubDesktop.AppImage"
chmod +x "$HOME/Applications/GitHubDesktop.AppImage"
```

## Install a portable tarball

```bash
mkdir -p "$HOME/Applications/GitHubDesktop"
tar -xzf GitHubDesktop-linux-<architecture>-<version>.tar.gz \
  --strip-components=1 \
  -C "$HOME/Applications/GitHubDesktop"
"$HOME/Applications/GitHubDesktop/desktop"
```

Keep the extracted directory intact because the executable loads Git and application resources from it.

## Desktop menu and browser sign-in

Portable formats do not have a system installer to create a menu entry. Electron attempts protocol registration when the app starts, but Linux desktop environments generally need a registered `.desktop` file with matching MIME handlers for browser authentication to return to the app reliably.

Create the applications directory:

```bash
mkdir -p "$HOME/.local/share/applications"
```

Create `~/.local/share/applications/github-desktop.desktop` with **one** of the following `Exec` lines. Desktop entries do not expand `$HOME`; use your absolute home path.

```ini
[Desktop Entry]
Type=Application
Name=GitHub Desktop
Comment=Simple collaboration from your desktop
Exec=/home/YOUR_USER/Applications/GitHubDesktop.AppImage %U
Terminal=false
Categories=Development;RevisionControl;
MimeType=x-scheme-handler/x-github-client;x-scheme-handler/x-github-desktop-auth;
StartupWMClass=GitHub Desktop
```

For the tarball, use:

```ini
Exec=/home/YOUR_USER/Applications/GitHubDesktop/desktop %U
```

Then register the entry:

```bash
update-desktop-database "$HOME/.local/share/applications"
xdg-mime default github-desktop.desktop x-scheme-handler/x-github-client
xdg-mime default github-desktop.desktop x-scheme-handler/x-github-desktop-auth
```

Confirm registration:

```bash
xdg-mime query default x-scheme-handler/x-github-desktop-auth
```

It should print `github-desktop.desktop`. Development builds use `x-github-desktop-dev-auth` instead of the production authentication scheme.

## Optional command-line helper

The tarball contains the `github` helper. Link it without moving it away from the package:

```bash
mkdir -p "$HOME/.local/bin"
ln -s "$HOME/Applications/GitHubDesktop/resources/app/static/github" \
  "$HOME/.local/bin/github"
```

Ensure `~/.local/bin` is on `PATH`, then run `github --help`. The AppImage does not expose its internal helper as a stable host path; use the tarball if this integration is important.

## Runtime requirements

The application requires a graphical Linux session and the native libraries required by Electron. Credential storage uses Secret Service.

| Purpose | Debian/Ubuntu | Fedora/RHEL |
| --- | --- | --- |
| Secret Service library | `libsecret-1-0` | `libsecret` |
| Keyring daemon (typical choice) | `gnome-keyring` | `gnome-keyring` |
| AppImage FUSE compatibility, if needed | `libfuse2` | Distribution-specific FUSE 2 package |

```bash
# Debian or Ubuntu
sudo apt install libsecret-1-0 gnome-keyring

# Fedora or RHEL
sudo dnf install libsecret gnome-keyring
```

GitHub Desktop includes its own Git distribution; installing system Git does not replace the Git used internally by default. The Linux release workflow also bundles the `libcurl-gnutls` library needed by that Git distribution.

To opt into the Git executable found on the application's `PATH`, launch with:

```bash
GITHUB_DESKTOP_USE_SYSTEM_GIT=1 /absolute/path/to/GitHubDesktop.AppImage
```

Use the corresponding tarball executable path as needed. System Git is an escape hatch for compatibility testing and must provide the features expected by the app.

## Environment variables

| Variable | Behavior |
| --- | --- |
| `GITHUB_DESKTOP_USE_SYSTEM_GIT=1` | Do not select the bundled Git on Linux |
| `GITHUB_DESKTOP_DISABLE_HARDWARE_ACCELERATION=1` | Disable Electron GPU acceleration |
| `GITHUB_DESKTOP_PREVIEW_FEATURES=1` | Enable available preview features |
| `XDG_CONFIG_HOME` | Override the base configuration location used by Electron |

## Data and logs

Electron follows XDG locations by default:

| Data | Default location |
| --- | --- |
| Settings and application data | `~/.config/GitHub Desktop/` |
| Logs | `~/.config/GitHub Desktop/logs/` |
| Cache | `~/.cache/GitHub Desktop/` |

The **Help > Show Logs** menu is the preferred way to find logs. A typical production log is named `YYYY-MM-DD.desktop.production.log`.

```bash
tail -n 100 "$HOME/.config/GitHub Desktop/logs/$(date +%F).desktop.production.log"
```

Locations can differ if XDG environment variables are customized.

## Update

Portable Linux builds do not provide a package-manager update path.

- **AppImage:** quit the app, download the new asset, verify it, and replace the old AppImage while preserving its stable filename.
- **Tarball:** quit the app, extract the new release into a new empty directory, then replace the old application directory. Do not merge new files into an old extracted tree.

Application data is stored separately and is retained during replacement. Back it up before a major upgrade if it is important.

## Uninstall

Remove only the package format you installed:

```bash
rm -f "$HOME/Applications/GitHubDesktop.AppImage"
rm -rf "$HOME/Applications/GitHubDesktop"
rm -f "$HOME/.local/bin/github"
rm -f "$HOME/.local/share/applications/github-desktop.desktop"
update-desktop-database "$HOME/.local/share/applications"
```

Those commands preserve user data. To reset the app completely, first back up anything needed, then remove its configuration and cache manually:

```bash
rm -rf "$HOME/.config/GitHub Desktop" "$HOME/.cache/GitHub Desktop"
```

## Troubleshooting

See [known issues](known-issues.md) for OAuth, keyring, AppImage, graphics, Wayland, and bundled Git problems. When reporting a reproducible Linux packaging problem, use this repository's [bug report form](https://github.com/goshitsarch-eng/github-desktop-linux/issues/new?template=bug_report.yaml).
