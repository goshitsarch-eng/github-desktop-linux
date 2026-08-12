# Linux development setup

Install the pinned Node.js and Python versions from the [main setup guide](setup.md), plus a C/C++ toolchain and native headers used by Electron modules.

## Debian and Ubuntu

```bash
sudo apt update
sudo apt install -y \
  build-essential \
  git \
  libsecret-1-dev \
  libxss-dev \
  python3
```

The Linux release workflow uses Ubuntu 22.04 and additionally installs `libfuse2` to exercise AppImage packaging.

## Fedora and RHEL-family systems

```bash
sudo dnf groupinstall -y "Development Tools"
sudo dnf install -y \
  git \
  libsecret-devel \
  libXScrnSaver-devel \
  python3
```

Package names can vary by distribution release. Use `pkg-config --libs libsecret-1` to verify the Secret Service development files.

## Node.js, Python, and Yarn

Use a version manager if distribution packages do not provide Node.js 22.19.0 and Python 3.9. The repository's `.yarnrc` redirects `yarn` to `vendor/yarn-1.21.1.js`; a bootstrap `yarn` command must still be available on `PATH`.

Verify from the repository root:

```bash
node --version
python3 --version
yarn --version
```

## Build

```bash
git submodule update --init --recursive
yarn
yarn build:dev
yarn start
```

Build a production application and AppImage with:

```bash
yarn build:prod
PACKAGE_FORMAT=AppImage yarn package
```

The assembled app is written to `dist/desktop-linux-<architecture>/`; the AppImage is written to `dist/GitHubDesktop-linux-<architecture>-<version>.AppImage`.

## Other local package formats

`script/package.ts` also supports:

```bash
PACKAGE_FORMAT=deb yarn package
PACKAGE_FORMAT=rpm yarn package
```

These paths use `electron-installer-debian` and `electron-installer-redhat` and may require packaging tools beyond the core development dependencies. They are available for local experimentation, but the current Linux release workflow publishes only AppImages and tarballs. Test locally built system packages in a disposable environment before distributing them.

## Tests

```bash
yarn test
yarn test:script
yarn lint
yarn markdownlint
```

For ARM64, see [building for ARM64](building-arm64.md). For failures, see [contributor troubleshooting](troubleshooting.md).
