# GitHub Desktop for Linux

[![Version](https://img.shields.io/badge/version-3.5.4-blue.svg)](https://github.com/desktop/desktop/releases/tag/release-3.5.4)
[![Electron](https://img.shields.io/badge/electron-38.2.0-blue.svg)](https://www.electronjs.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An unofficial Linux fork of [GitHub Desktop](https://desktop.github.com/), the open-source [Electron](https://www.electronjs.org/)-based GitHub app. Written in [TypeScript](https://www.typescriptlang.org) using [React](https://reactjs.org/).

<picture>
  <source
    srcset="https://user-images.githubusercontent.com/634063/202742848-63fa1488-6254-49b5-af7c-96a6b50ea8af.png"
    media="(prefers-color-scheme: dark)"
  />
  <img
    width="1072"
    src="https://user-images.githubusercontent.com/634063/202742985-bb3b3b94-8aca-404a-8d8a-fd6a6f030672.png"
    alt="A screenshot of the GitHub Desktop application showing changes being viewed and committed with two attributed co-authors"
  />
</picture>

## Features

This fork includes all features from the official GitHub Desktop v3.5.4:

- **Copilot Commit Messages** - AI-powered commit message generation via context menu
- **Attribute Co-authors** - Add co-authors to commits
- **Conflict Resolution** - Built-in merge conflict editor
- **Branch Management** - Create, rename, delete branches
- **Pull Request Integration** - View and create PRs from the app
- **Stashing** - Stash and restore changes
- **Rebase Support** - Interactive rebase workflow
- **Image Diff** - View image changes with various diff modes
- **Syntax Highlighting** - For diffs in many languages

### Linux-Specific Features

- **AppImage and portable tarball packages** for x64 and ARM64
- **Bundled Git with libcurl** - Works on all distros out of the box
- **GNOME/GTK integration** - Native look and feel
- **Keyring integration** - Secure credential storage via libsecret

## Installation

### Download

| Architecture | AppImage | Tarball |
|--------------|----------|---------|
| x86_64 (AMD/Intel) | [Download](../../releases) | [Download](../../releases) |
| ARM64 (aarch64) | [Download](../../releases) | [Download](../../releases) |

### AppImage (Recommended)

AppImages are portable and work on most Linux distributions without installation:

```bash
# Make it executable
chmod +x GitHubDesktop-linux-x64-3.5.4.AppImage

# Run directly
./GitHubDesktop-linux-x64-3.5.4.AppImage
```

For desktop integration, use [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher) or manually create a `.desktop` entry:

```bash
mkdir -p ~/.local/bin
mv GitHubDesktop-linux-x64-3.5.4.AppImage ~/.local/bin/github-desktop

cat > ~/.local/share/applications/github-desktop.desktop << 'EOF'
[Desktop Entry]
Name=GitHub Desktop
Exec=$HOME/.local/bin/github-desktop %U
Icon=github-desktop
Type=Application
Categories=Development;
MimeType=x-scheme-handler/x-github-client;x-scheme-handler/x-github-desktop-auth;
EOF

update-desktop-database ~/.local/share/applications/
```

### Portable Tarball

The tarball works on any Linux distribution without requiring root or a package manager:

```bash
# Extract the tarball
tar -xzf GitHubDesktop-linux-x64-3.5.4.tar.gz

# Run the application
cd desktop-linux-x64
./desktop

# Or run from anywhere
/path/to/desktop-linux-x64/desktop
```

## System Requirements

### Minimum Requirements

- **OS**: Linux kernel 4.15+ (glibc 2.28+)
- **Desktop**: GNOME, KDE, XFCE, or other GTK-compatible environment
- **Display**: X11 or Wayland
- **Memory**: 2 GB RAM minimum, 4 GB recommended
- **Storage**: 500 MB free space

### Runtime Dependencies

The following packages are required at runtime:

| Package | Fedora/RHEL | Ubuntu/Debian | Purpose |
|---------|-------------|---------------|---------|
| `libsecret` | `libsecret` | `libsecret-1-0` | Credential storage |
| `gnome-keyring` | `gnome-keyring` | `gnome-keyring` | Keyring daemon |
| `git` | `git` | `git` | Git operations (optional, bundled Git included) |

Install on Fedora:
```bash
sudo dnf install libsecret gnome-keyring git
```

Install on Ubuntu/Debian:
```bash
sudo apt install libsecret-1-0 gnome-keyring git
```

## Git Configuration

GitHub Desktop ships with a bundled Git binary and a bundled `libcurl-gnutls.so.4`, so it works out of the box on all Linux distributions.

If you prefer to use your system Git instead:

```bash
GITHUB_DESKTOP_USE_SYSTEM_GIT=1 github-desktop
```

To make this permanent, add to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
export GITHUB_DESKTOP_USE_SYSTEM_GIT=1
```

## Known Issues

### Linux-Specific Issues

#### OAuth Authentication Requires Protocol Handler

GitHub Desktop uses `x-github-desktop-auth://` URLs for OAuth callbacks. Ensure your desktop environment is configured to handle these URLs (the AppImage should register this automatically).

If authentication doesn't work after browser redirect:
1. Check that the `.desktop` file is properly installed
2. Run `update-desktop-database ~/.local/share/applications/` (for local installs)
3. Try running the app from terminal to see any error messages

#### Wayland Compatibility

GitHub Desktop runs on Wayland through XWayland. Some features may behave differently:
- Window positioning may not persist correctly
- Drag and drop between windows may not work

#### High DPI Scaling

If the UI appears too small or too large:
```bash
# Force specific scale factor
GDK_SCALE=2 github-desktop

# Or let GTK auto-detect
GDK_DPI_SCALE=1.5 github-desktop
```

## Building from Source

### Prerequisites

#### Fedora / RHEL

```bash
sudo dnf install -y \
  nodejs \
  npm \
  yarn \
  python3 \
  gcc-c++ \
  make \
  libsecret-devel \
  libXScrnSaver-devel \
  rpm-build \
  git
```

#### Ubuntu / Debian

```bash
sudo apt install -y \
  nodejs \
  npm \
  yarnpkg \
  python3 \
  build-essential \
  libsecret-1-dev \
  libxss-dev \
  libgconf-2-4 \
  git
```

### Build Steps

```bash
# Clone the repository
git clone https://github.com/user/github-desktop-linux.git
cd github-desktop-linux

# Install dependencies
yarn install

# Build for production
yarn build:prod

# Package AppImage
PACKAGE_FORMAT=AppImage yarn package
```

### Build Outputs

After building, packages are created in the `dist/` directory:

| File | Description |
|------|-------------|
| `GitHubDesktop-linux-x64-X.X.X.AppImage` | AppImage for x64 |
| `GitHubDesktop-linux-arm64-X.X.X.AppImage` | AppImage for ARM64 |
| `GitHubDesktop-linux-x64-X.X.X.tar.gz` | Portable tarball for x64 |
| `GitHubDesktop-linux-arm64-X.X.X.tar.gz` | Portable tarball for ARM64 |

### Development Mode

```bash
# Start in development mode with hot reload
yarn start

# Run tests
yarn test

# Run linting
yarn lint
```

## Data Directories

GitHub Desktop stores data in the following locations:

| Type | Location |
|------|----------|
| Configuration | `~/.config/GitHub Desktop/` |
| Application data | `~/.config/GitHub Desktop/` |
| Logs | `~/.config/GitHub Desktop/logs/` |
| Cache | `~/.cache/GitHub Desktop/` |

### Log Files

Logs are stored by date: `~/.config/GitHub Desktop/logs/YYYY-MM-DD.desktop.production.log`

To view recent logs:
```bash
tail -f ~/.config/GitHub\ Desktop/logs/$(date +%Y-%m-%d).desktop.production.log
```

## CLI Usage

GitHub Desktop includes a command-line interface:

```bash
# Open current directory in GitHub Desktop
github

# Open a specific path
github open /path/to/repo

# Clone a repository
github clone https://github.com/owner/repo
github clone owner/repo  # Shorthand for GitHub repos

# Clone and checkout specific branch
github clone -b branch-name owner/repo

# Show help
github --help
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GITHUB_DESKTOP_USE_SYSTEM_GIT=1` | Force use of system Git instead of bundled Git |
| `GITHUB_DESKTOP_DISABLE_HARDWARE_ACCELERATION=1` | Disable GPU acceleration |
| `GDK_SCALE=2` | Set UI scale factor |
| `GDK_DPI_SCALE=1.5` | Set DPI scale factor |

## Troubleshooting

### Application Won't Start

1. **Check logs**: `cat ~/.config/GitHub\ Desktop/logs/*.log | tail -50`
2. **Try disabling GPU acceleration**: `GITHUB_DESKTOP_DISABLE_HARDWARE_ACCELERATION=1 github-desktop`
3. **Run from terminal** to see error output: `/opt/GitHub\ Desktop/github-desktop`

### Authentication Issues

1. **Clear stored credentials**:
   ```bash
   secret-tool search service github.com
   # Then delete with secret-tool clear
   ```
2. **Check keyring is running**: `gnome-keyring-daemon --status`

### Git Operations Fail

1. **Check Git version**: `git --version` (minimum 2.25 recommended)
2. **Try system Git**: `GITHUB_DESKTOP_USE_SYSTEM_GIT=1 github-desktop`
3. **Check Git config**: `git config --list --show-origin`

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for development guidelines.

### Key Documentation

- [Setup Guide](docs/contributing/setup.md) - Development environment setup
- [Linux Setup](docs/contributing/setup-linux.md) - Linux-specific setup
- [Architecture](docs/technical/packaging.md) - Packaging and build system

## Upstream

This is a fork of [GitHub Desktop](https://github.com/desktop/desktop). See also:
- [Official GitHub Desktop](https://desktop.github.com)
- [shiftkey/desktop](https://github.com/shiftkey/desktop) - Another popular Linux fork

## License

**[MIT](LICENSE)**

The MIT license grant is not for GitHub's trademarks, which include the logo designs. GitHub reserves all trademark and copyright rights in and to all GitHub trademarks. GitHub's logos include, for instance, the stylized Invertocat designs that include "logo" in the file title in the following folder: [logos](app/static/logos).

GitHub® and its stylized versions and the Invertocat mark are GitHub's Trademarks or registered Trademarks. When using GitHub's logos, be sure to follow the GitHub [logo guidelines](https://github.com/logos).
