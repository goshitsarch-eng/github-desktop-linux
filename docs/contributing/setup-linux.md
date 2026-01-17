# Setting Up Development Dependencies on Linux

This guide covers setting up a complete development environment for building GitHub Desktop on Linux.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Distribution-Specific Setup](#distribution-specific-setup)
- [Node.js Setup](#nodejs-setup)
- [Yarn Setup](#yarn-setup)
- [Python Setup](#python-setup)
- [Native Dependencies](#native-dependencies)
- [Building for ARM64](#building-for-arm64)
- [Troubleshooting](#troubleshooting)

## Prerequisites

You will need to install these tools on your machine:

| Tool | Version | Purpose |
|------|---------|---------|
| Node.js | 18.x or 20.x LTS | JavaScript runtime |
| Yarn | 1.22+ | Package manager |
| Python | 3.8+ | Native module compilation |
| Git | 2.25+ | Version control |
| GCC/G++ | 10+ | Native module compilation |
| Make | 4.0+ | Build tool |

## Distribution-Specific Setup

### Fedora 38+ / RHEL 9+ / CentOS Stream 9+

```bash
# Enable development tools
sudo dnf groupinstall -y "Development Tools"

# Install all dependencies
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

# Install Yarn globally
sudo npm install -g yarn

# Install FPM for packaging (optional, for building RPMs)
sudo gem install fpm
```

### Ubuntu 22.04+ / Debian 12+

```bash
# Update package lists
sudo apt update

# Install build essentials
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

# Install Yarn globally
sudo npm install -g yarn

# Install FPM for packaging (optional, for building DEBs)
sudo gem install fpm
```

### Arch Linux / Manjaro

```bash
# Install dependencies
sudo pacman -S --needed \
  base-devel \
  nodejs \
  npm \
  yarn \
  python \
  git \
  libsecret \
  libxss \
  ruby

# Install FPM for packaging
gem install fpm
```

### openSUSE Tumbleweed / Leap

```bash
# Install development pattern
sudo zypper install -t pattern devel_basis

# Install dependencies
sudo zypper install \
  nodejs \
  npm \
  python3 \
  git \
  libsecret-devel \
  libXScrnSaver-devel \
  rpm-build \
  ruby \
  ruby-devel

# Install Yarn
sudo npm install -g yarn

# Install FPM
sudo gem install fpm
```

## Node.js Setup

### Using System Package Manager

Most distributions include Node.js in their repositories. Check the version:

```bash
node --version  # Should be 18.x or 20.x
npm --version   # Should be 8.x or 10.x
```

### Using NodeSource (Recommended for Latest LTS)

For the latest LTS version:

```bash
# Fedora/RHEL/CentOS
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo dnf install -y nodejs

# Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

### Using nvm (Node Version Manager)

For managing multiple Node.js versions:

```bash
# Install nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash

# Restart shell or source profile
source ~/.bashrc

# Install Node.js LTS
nvm install --lts
nvm use --lts

# Verify
node --version
```

## Yarn Setup

GitHub Desktop uses a local version of Yarn bundled in `vendor/yarn-1.21.1.js`, but you need a system-level Yarn to bootstrap.

### Install via npm

```bash
sudo npm install -g yarn
yarn --version  # Should be 1.22+
```

### Install via Package Manager

**Fedora:**
```bash
sudo dnf install yarnpkg
```

**Ubuntu/Debian:**
```bash
curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | sudo apt-key add -
echo "deb https://dl.yarnpkg.com/debian/ stable main" | sudo tee /etc/apt/sources.list.d/yarn.list
sudo apt update && sudo apt install yarn
```

## Python Setup

Python 3 is required for building native Node.js modules.

```bash
# Check Python version
python3 --version  # Should be 3.8+

# Ensure pip is installed
python3 -m pip --version

# Set Python for node-gyp (if needed)
npm config set python python3
```

## Native Dependencies

### Electron Dependencies

GitHub Desktop uses Electron, which requires several native libraries:

| Library | Package (Fedora) | Package (Ubuntu) | Purpose |
|---------|------------------|------------------|---------|
| libsecret | `libsecret-devel` | `libsecret-1-dev` | Credential storage via keytar |
| libXScrnSaver | `libXScrnSaver-devel` | `libxss-dev` | Screen saver extension |
| GConf | (not needed) | `libgconf-2-4` | Legacy GNOME config (Ubuntu only) |

### Verify Installation

```bash
# Check for libsecret
pkg-config --libs libsecret-1

# Check for libXScrnSaver
pkg-config --libs xscrnsaver

# If pkg-config fails, the development headers are missing
```

## Building for ARM64

### Native ARM64 Build

If you're building on an ARM64 system (e.g., Apple Silicon with Linux, Raspberry Pi 4, AWS Graviton):

```bash
# Verify architecture
uname -m  # Should show aarch64

# Clone and build
git clone https://github.com/your-fork/github-desktop-linux.git
cd github-desktop-linux

# Install dependencies
yarn install

# Build production
yarn build:prod

# Package
USE_SYSTEM_FPM=true yarn package
```

### Cross-Compilation (x64 → ARM64)

Cross-compiling from x64 to ARM64 requires additional setup:

```bash
# Fedora: Install cross-compilation toolchain
sudo dnf install -y \
  gcc-aarch64-linux-gnu \
  gcc-c++-aarch64-linux-gnu \
  binutils-aarch64-linux-gnu

# Set environment for cross-compilation
export npm_config_arch=arm64
export npm_config_target_arch=arm64

# Build
yarn install
yarn build:prod
yarn package
```

**Note:** Cross-compilation of native Node modules can be challenging. Native ARM64 builds are recommended when possible.

## Building the Application

### Clone the Repository

```bash
git clone https://github.com/your-fork/github-desktop-linux.git
cd github-desktop-linux
```

### Install Dependencies

```bash
# Using system Yarn to bootstrap
yarn install

# Or using the bundled Yarn
node vendor/yarn-1.21.1.js install
```

This will:
- Install all npm dependencies
- Run postinstall scripts
- Compile native modules

### Development Build

```bash
# Start in development mode with hot reload
yarn start

# Or with verbose logging
DEBUG=* yarn start
```

### Production Build

```bash
# Build optimized production bundle
yarn build:prod
```

### Run Tests

```bash
# Run all tests
yarn test

# Run specific test file
yarn test -- --grep "test name"

# Run with coverage
yarn test:coverage
```

### Lint Code

```bash
# Run ESLint
yarn lint

# Fix auto-fixable issues
yarn lint:fix
```

### Package for Distribution

```bash
# Build all package formats (AppImage, RPM)
USE_SYSTEM_FPM=true yarn package

# Build specific format
USE_SYSTEM_FPM=true PACKAGE_FORMAT=rpm yarn package
USE_SYSTEM_FPM=true PACKAGE_FORMAT=AppImage yarn package
```

Build outputs appear in `dist/`:
- `GitHubDesktop-linux-arm64-X.X.X.AppImage`
- `GitHubDesktop-linux-aarch64-X.X.X.rpm`

## Project Structure

```
github-desktop-linux/
├── app/                    # Application source
│   ├── src/
│   │   ├── cli/           # CLI entry point
│   │   ├── lib/           # Shared libraries
│   │   ├── main-process/  # Electron main process
│   │   └── ui/            # React UI components
│   ├── static/            # Static assets
│   └── test/              # Tests
├── docs/                   # Documentation
├── script/                 # Build scripts
│   ├── build.ts           # Production build
│   ├── package.ts         # Packaging
│   └── electron-builder-linux.yml
├── vendor/                 # Vendored dependencies
├── out/                    # Compiled output (gitignored)
└── dist/                   # Distribution packages (gitignored)
```

## Troubleshooting

### `gyp ERR! find Python`

Node-gyp can't find Python:

```bash
# Set Python path
npm config set python /usr/bin/python3

# Or set environment variable
export PYTHON=/usr/bin/python3
```

### `Error: Cannot find module 'node-gyp'`

Install node-gyp globally:

```bash
sudo npm install -g node-gyp
```

### Native Module Compilation Fails

Missing development headers:

```bash
# Fedora
sudo dnf install libsecret-devel libXScrnSaver-devel

# Ubuntu
sudo apt install libsecret-1-dev libxss-dev
```

### `EACCES: permission denied` Errors

Don't run npm/yarn with sudo. Fix npm permissions:

```bash
mkdir -p ~/.npm-global
npm config set prefix '~/.npm-global'
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc
source ~/.bashrc
```

### Electron Download Fails

If Electron download times out or fails:

```bash
# Set mirror
export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"

# Or download manually and set cache
export ELECTRON_CACHE=~/.cache/electron
```

### RPM Build Fails with FPM

If FPM (used by electron-builder) fails:

```bash
# Use system FPM instead of bundled
export USE_SYSTEM_FPM=true

# Install FPM if not present
sudo gem install fpm

# Verify FPM works
fpm --version
```

### ARM64 RPM Shows Wrong Architecture

Ensure you're building on native ARM64:

```bash
uname -m  # Should show aarch64, not x86_64
```

## Back to Setup

Once you've installed the necessary dependencies, head back to the [main setup page](setup.md) to finish getting set up.

## Additional Resources

- [Working with Packages](working-with-packages.md) - npm/yarn usage
- [Tooling Guide](tooling.md) - Development tools
- [Linting Guide](linting.md) - Code style
- [Testing Guide](../process/testing.md) - Testing practices
