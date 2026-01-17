# Building GitHub Desktop for ARM64 (aarch64)

This guide covers building GitHub Desktop on ARM64 hardware, including Apple Silicon Macs running Linux, Raspberry Pi 4/5, AWS Graviton instances, and other ARMv8 systems.

## Table of Contents

- [Supported Hardware](#supported-hardware)
- [Requirements](#requirements)
- [Distribution-Specific Setup](#distribution-specific-setup)
- [Building](#building)
- [Packaging](#packaging)
- [Cross-Compilation](#cross-compilation)
- [Troubleshooting](#troubleshooting)

## Supported Hardware

GitHub Desktop has been tested on the following ARM64 platforms:

| Platform | Status | Notes |
|----------|--------|-------|
| Apple Silicon (M1/M2/M3) with Asahi Linux | Fully supported | Recommended for development |
| Apple Silicon with Fedora Asahi Remix | Fully supported | Best Fedora ARM64 experience |
| Raspberry Pi 4/5 (64-bit OS) | Supported | May be slow for builds |
| AWS Graviton (2/3) | Supported | Good for CI/CD |
| Ampere Altra | Supported | Server-class ARM64 |
| NVIDIA Jetson | Supported | Requires Ubuntu ARM64 |

## Requirements

### Hardware Requirements

- **Processor**: 64-bit ARMv8 or later (aarch64)
- **Memory**: 8 GB RAM minimum (16 GB recommended for faster builds)
- **Storage**: 10 GB free space for build artifacts
- **OS**: 64-bit Linux distribution

### Software Requirements

| Tool | Version | Purpose |
|------|---------|---------|
| Node.js | 18.x or 20.x LTS | JavaScript runtime |
| Yarn | 1.22+ | Package manager |
| Python | 3.8+ | Native module compilation |
| GCC/G++ | 10+ | Native module compilation |
| Git | 2.25+ | Version control |
| FPM | 1.14+ | Package creation (optional) |

## Distribution-Specific Setup

### Fedora Asahi Remix (Apple Silicon)

Fedora Asahi Remix is the recommended distribution for Apple Silicon Macs:

```bash
# Install development tools
sudo dnf groupinstall -y "Development Tools"

# Install all required dependencies
sudo dnf install -y \
  nodejs \
  npm \
  python3 \
  python3-pip \
  gcc-c++ \
  make \
  git \
  libsecret-devel \
  libXScrnSaver-devel \
  rpm-build \
  ruby \
  ruby-devel \
  rubygems

# Install Yarn
sudo npm install -g yarn

# Install FPM for RPM packaging
sudo gem install fpm

# Verify architecture
uname -m  # Should show: aarch64
```

### Ubuntu/Debian ARM64

For Raspberry Pi, AWS Graviton, or other ARM64 systems:

```bash
# Update package lists
sudo apt update

# Install build dependencies
sudo apt install -y \
  build-essential \
  nodejs \
  npm \
  python3 \
  python3-pip \
  git \
  libsecret-1-dev \
  libxss-dev \
  libgconf-2-4 \
  ruby \
  ruby-dev \
  rubygems

# Install Yarn
sudo npm install -g yarn

# Install FPM for DEB packaging
sudo gem install fpm
```

### Raspberry Pi OS (64-bit)

For Raspberry Pi 4/5 with 64-bit Raspberry Pi OS:

```bash
# Enable 64-bit kernel if not already enabled
# Check /boot/config.txt for: arm_64bit=1

# Install Node.js via NodeSource (Raspberry Pi OS repos have old versions)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Install other dependencies
sudo apt install -y \
  build-essential \
  python3 \
  git \
  libsecret-1-dev \
  libxss-dev \
  ruby-dev

# Install Yarn and FPM
sudo npm install -g yarn
sudo gem install fpm
```

## Building

### Clone and Setup

```bash
# Clone the repository
git clone https://github.com/user/github-desktop-linux.git
cd github-desktop-linux

# Verify you're on ARM64
uname -m  # Should output: aarch64

# Install dependencies
yarn install
```

### Development Build

For testing and development:

```bash
# Build development version
yarn build:dev

# Start the application
yarn start

# Or with debug logging
DEBUG=* yarn start
```

### Production Build

For optimized production binaries:

```bash
# Build production bundle
yarn build:prod

# Start production version
yarn start:prod
```

## Packaging

### Create Distribution Packages

After building, create installable packages:

```bash
# Package all formats (AppImage + RPM)
USE_SYSTEM_FPM=true yarn package

# Package specific format only
USE_SYSTEM_FPM=true PACKAGE_FORMAT=rpm yarn package
USE_SYSTEM_FPM=true PACKAGE_FORMAT=AppImage yarn package
```

### Output Files

Packages are created in the `dist/` directory:

| File | Size (approx) | Description |
|------|---------------|-------------|
| `GitHubDesktop-linux-arm64-X.X.X.AppImage` | ~140 MB | Portable AppImage |
| `GitHubDesktop-linux-aarch64-X.X.X.rpm` | ~90 MB | Fedora/RHEL RPM |

### Install and Test

```bash
# Install RPM
sudo dnf install ./dist/GitHubDesktop-linux-aarch64-3.5.4.rpm

# Or run AppImage directly
chmod +x dist/GitHubDesktop-linux-arm64-3.5.4.AppImage
./dist/GitHubDesktop-linux-arm64-3.5.4.AppImage

# Launch the installed application
github-desktop
```

## Cross-Compilation

Cross-compiling from x64 to ARM64 is possible but not recommended due to complexity with native Node.js modules.

### From x64 Linux to ARM64

```bash
# Install cross-compilation toolchain (Fedora)
sudo dnf install -y \
  gcc-aarch64-linux-gnu \
  gcc-c++-aarch64-linux-gnu \
  binutils-aarch64-linux-gnu

# Set environment variables
export npm_config_arch=arm64
export npm_config_target_arch=arm64
export CC=aarch64-linux-gnu-gcc
export CXX=aarch64-linux-gnu-g++

# Install and build
yarn install
yarn build:prod
```

**Limitations:**
- Native Node.js modules may fail to cross-compile
- Electron rebuild may have issues
- Testing requires ARM64 hardware or emulation

**Recommendation:** Use native ARM64 builds whenever possible. For CI/CD, consider using ARM64 runners (GitHub Actions has ARM64 runners, AWS has Graviton instances).

## Troubleshooting

### Native Module Build Failures

If native modules fail to compile:

```bash
# Clear node_modules and rebuild
rm -rf node_modules app/node_modules
yarn cache clean
yarn install

# If specific module fails, try rebuilding it
cd app && npx electron-rebuild -f -w keytar
```

### Electron Download Issues

If Electron fails to download for ARM64:

```bash
# Set Electron mirror
export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"

# Or manually specify architecture
export npm_config_arch=arm64
yarn install
```

### Memory Issues on Raspberry Pi

Raspberry Pi may run out of memory during builds:

```bash
# Increase swap space
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile  # Set CONF_SWAPSIZE=4096
sudo dphys-swapfile setup
sudo dphys-swapfile swapon

# Limit webpack memory
export NODE_OPTIONS="--max_old_space_size=2048"
yarn build:prod
```

### FPM/RPM Build Fails

If RPM packaging fails:

```bash
# Use system FPM instead of bundled (x86) version
export USE_SYSTEM_FPM=true

# Verify FPM is installed and working
fpm --version

# If FPM not found, install it
sudo gem install fpm
```

### Wrong Architecture in Built Package

If the package shows wrong architecture:

```bash
# Verify you're building on ARM64
uname -m  # Must show aarch64

# Check the built binary
file dist/desktop-linux-arm64/github-desktop
# Should show: ELF 64-bit LSB executable, ARM aarch64

# Check RPM architecture
rpm -qip dist/GitHubDesktop-linux-aarch64-3.5.4.rpm | grep Architecture
# Should show: aarch64
```

### Git Library Issues (libcurl-gnutls)

If Git operations fail on Fedora/RHEL:

```bash
# The bundled Git requires libcurl-gnutls (Debian/Ubuntu only)
# Use system Git instead
export GITHUB_DESKTOP_USE_SYSTEM_GIT=1
github-desktop
```

## Performance Tips

### Faster Builds on Raspberry Pi

```bash
# Use all available cores
export JOBS=$(nproc)

# Disable source maps for faster builds
export GENERATE_SOURCEMAP=false

# Build with reduced memory usage
NODE_OPTIONS="--max_old_space_size=2048" yarn build:prod
```

### Using ccache

Speed up repeated builds with ccache:

```bash
# Install ccache
sudo dnf install ccache  # Fedora
sudo apt install ccache  # Ubuntu

# Configure npm to use ccache
npm config set cache-prefix "ccache"
export CC="ccache gcc"
export CXX="ccache g++"
```

## CI/CD for ARM64

### GitHub Actions

GitHub Actions supports ARM64 runners. Example workflow:

```yaml
name: Build ARM64
on: push

jobs:
  build-arm64:
    runs-on: ubuntu-24.04-arm  # ARM64 runner
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: yarn install
      - run: yarn build:prod
      - run: USE_SYSTEM_FPM=true yarn package
```

### Self-Hosted ARM64 Runner

For self-hosted ARM64 builds (e.g., on AWS Graviton):

```bash
# Install GitHub Actions runner
mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-arm64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.XXX/actions-runner-linux-arm64-2.XXX.tar.gz
tar xzf actions-runner-linux-arm64.tar.gz
./config.sh --url https://github.com/YOUR/REPO --token YOUR_TOKEN
./run.sh
```

## Additional Resources

- [Linux Setup Guide](setup-linux.md) - General Linux development setup
- [Packaging Documentation](../technical/packaging.md) - Detailed packaging information
- [Known Issues](../known-issues.md) - Linux-specific issues and workarounds
