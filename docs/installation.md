# Installing GitHub Desktop

GitHub Desktop supports Windows, macOS, and Linux.

## Table of Contents

- [Linux](#linux)
- [macOS](#macos)
- [Windows](#windows)
- [Data Directories](#data-directories)
- [Log Files](#log-files)
- [Installer Logs](#installer-logs)

## Linux

### Package Formats

GitHub Desktop for Linux is available in two formats:

| Format | Description | Best For |
|--------|-------------|----------|
| **RPM** | Native package for Fedora, RHEL, CentOS, openSUSE | System-wide installation with package management |
| **AppImage** | Portable executable | Any distribution, no installation required |

### Supported Architectures

| Architecture | CPU Examples |
|--------------|--------------|
| `x86_64` | Intel Core, AMD Ryzen |
| `aarch64` / `arm64` | Apple M1/M2, Raspberry Pi 4, AWS Graviton |

### RPM Installation (Fedora, RHEL, CentOS)

```bash
# Download the RPM for your architecture from the releases page

# Install with dnf (Fedora 22+, RHEL 8+)
sudo dnf install ./GitHubDesktop-linux-aarch64-3.5.4.rpm

# Or install with yum (older systems)
sudo yum localinstall ./GitHubDesktop-linux-x86_64-3.5.4.rpm
```

After installation:
- Launch from applications menu as "GitHub Desktop"
- Or run `github-desktop` from terminal
- CLI available as `github` command

### AppImage Installation (Universal)

AppImages are portable and work on most Linux distributions without installation.

```bash
# Download the AppImage for your architecture

# Make it executable
chmod +x GitHubDesktop-linux-arm64-3.5.4.AppImage

# Run directly
./GitHubDesktop-linux-arm64-3.5.4.AppImage
```

#### Optional: System Integration

To integrate the AppImage with your desktop environment:

```bash
# Using AppImageLauncher (recommended)
# Install AppImageLauncher from your package manager, then run the AppImage

# Manual integration
mkdir -p ~/.local/bin
mv GitHubDesktop-linux-arm64-3.5.4.AppImage ~/.local/bin/github-desktop
```

Create a desktop entry at `~/.local/share/applications/github-desktop.desktop`:

```ini
[Desktop Entry]
Name=GitHub Desktop
Comment=Simple collaboration from your desktop
Exec=/home/YOUR_USERNAME/.local/bin/github-desktop %U
Icon=github-desktop
Type=Application
Categories=Development;RevisionControl;
MimeType=x-scheme-handler/x-github-client;x-scheme-handler/x-github-desktop-auth;x-scheme-handler/x-github-desktop-dev-auth;
StartupWMClass=GitHub Desktop
```

Update the desktop database:
```bash
update-desktop-database ~/.local/share/applications
```

### Dependencies

#### Runtime Dependencies

The following packages are required at runtime:

| Package | Fedora/RHEL | Ubuntu/Debian | Purpose |
|---------|-------------|---------------|---------|
| libsecret | `libsecret` | `libsecret-1-0` | Secure credential storage |
| gnome-keyring | `gnome-keyring` | `gnome-keyring` | Keyring daemon |
| git | `git` | `git` | Git operations (if using system Git) |

**Fedora/RHEL:**
```bash
sudo dnf install libsecret gnome-keyring git
```

**Ubuntu/Debian:**
```bash
sudo apt install libsecret-1-0 gnome-keyring git
```

### Git Configuration

GitHub Desktop includes a bundled Git binary. However, on some distributions (particularly Fedora/RHEL), the bundled Git may fail due to library incompatibilities (`libcurl-gnutls` vs `libcurl-openssl`).

#### Automatic Detection

The app automatically detects library availability:
- If `libcurl-gnutls.so.4` exists → uses bundled Git
- Otherwise → falls back to system Git

#### Manual Override

Force a specific Git version with environment variables:

```bash
# Use system Git (recommended for Fedora/RHEL)
GITHUB_DESKTOP_USE_SYSTEM_GIT=1 github-desktop

# Use bundled Git
GITHUB_DESKTOP_USE_BUNDLED_GIT=1 github-desktop
```

To make permanent, add to `~/.bashrc`:
```bash
export GITHUB_DESKTOP_USE_SYSTEM_GIT=1
```

### Uninstalling

**RPM:**
```bash
sudo dnf remove desktop
# or
sudo rpm -e desktop
```

**AppImage:**
```bash
rm ~/.local/bin/github-desktop
rm ~/.local/share/applications/github-desktop.desktop
update-desktop-database ~/.local/share/applications
```

**Remove user data:**
```bash
rm -rf ~/.config/GitHub\ Desktop
rm -rf ~/.cache/GitHub\ Desktop
```

---

## macOS

Download the `GitHub Desktop.zip`, unpack the application and put it wherever you want.

### System Requirements

- macOS 10.15 (Catalina) or later
- Apple Silicon (M1/M2) or Intel processor

### Installation

1. Download `GitHub Desktop-darwin-arm64.zip` (Apple Silicon) or `GitHub Desktop-darwin-x64.zip` (Intel)
2. Unzip the archive
3. Drag `GitHub Desktop.app` to your Applications folder
4. Launch from Applications or Spotlight

---

## Windows

### System Requirements

- Windows 10 or later (64-bit)
- Windows Server 2016 or later

### Installation Options

**Per-user installation (recommended):**
- Download `GitHubDesktopSetup.exe`
- Run the installer
- GitHub Desktop installs to `%LOCALAPPDATA%\GitHubDesktop`

**Machine-wide installation:**
- Download `GitHubDesktopSetup.msi`
- Run with administrator privileges
- Installs to `%PROGRAMFILES(x86)%\GitHub Desktop Installer`
- All users on the machine can run GitHub Desktop

---

## Data Directories

GitHub Desktop stores user data in platform-specific locations:

### Linux

| Type | Location |
|------|----------|
| Configuration | `~/.config/GitHub Desktop/` |
| Cache | `~/.cache/GitHub Desktop/` |
| Logs | `~/.config/GitHub Desktop/logs/` |

### macOS

| Type | Location |
|------|----------|
| Application Support | `~/Library/Application Support/GitHub Desktop/` |
| Logs | `~/Library/Application Support/GitHub Desktop/logs/` |
| Cache | `~/Library/Caches/com.github.GitHubClient/` |

### Windows

| Type | Location |
|------|----------|
| Application | `%LOCALAPPDATA%\GitHubDesktop\` |
| User Data | `%APPDATA%\GitHub Desktop\` |
| Logs | `%APPDATA%\GitHub Desktop\logs\` |

---

## Log Files

GitHub Desktop generates logs for troubleshooting. Logs are organized by date using the format `YYYY-MM-DD.desktop.production.log`.

### Viewing Logs

**Linux:**
```bash
# View today's log
cat ~/.config/GitHub\ Desktop/logs/$(date +%Y-%m-%d).desktop.production.log

# Follow log in real-time
tail -f ~/.config/GitHub\ Desktop/logs/$(date +%Y-%m-%d).desktop.production.log

# View recent entries
tail -100 ~/.config/GitHub\ Desktop/logs/*.log
```

**macOS:**
```bash
cat ~/Library/Application\ Support/GitHub\ Desktop/logs/$(date +%Y-%m-%d).desktop.production.log
```

**Windows (PowerShell):**
```powershell
Get-Content "$env:APPDATA\GitHub Desktop\logs\$(Get-Date -Format 'yyyy-MM-dd').desktop.production.log"
```

---

## Installer Logs

Problems with installation or updates are tracked in separate log files.

### Linux

AppImage logs: Check terminal output when running the AppImage directly.

RPM installation logs:
```bash
# DNF transaction history
sudo dnf history info last

# RPM verbose install
sudo rpm -ivh --verbose GitHubDesktop-linux-*.rpm
```

### macOS

Installer logs are located at:
- `~/Library/Caches/com.github.GitHubClient.ShipIt/ShipIt_stderr.log`

Check the end of the file for recent activity.

### Windows

- Initial installation: `%LOCALAPPDATA%\SquirrelSetup.log`
- Updates: `%LOCALAPPDATA%\GitHubDesktop\SquirrelSetup.log`

Look for mentions of `GitHubDesktop.exe` in the log.
