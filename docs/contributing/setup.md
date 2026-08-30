# Development setup

> [!NOTE]
> The Linux application lives in [`native/`](../../native/README.md) and is a Qt 6 /
> Kirigami app, not part of the Electron build described below. See
> [The Qt application](#the-qt-application) for its setup; the rest of this guide covers
> the TypeScript/Electron tree, which is kept as the behavioural reference.

## The Qt application

```bash
# Debian or Ubuntu 24.10+ / Fedora / Arch: see native/README.md for the full table
sudo apt install python3-pyside6.qtquick python3-pyside6.qtdbus \
  qml6-module-org-kde-kirigami qml6-module-qtquick-controls breeze-icon-theme git

cd native
PYTHONPATH=. python3 -m pytest tests -q     # unit, git integration and QML smoke tests
PYTHONPATH=. python3 -m github_desktop      # run it
```

There is no build step: the app is Python plus the QML under
`native/github_desktop/ui/qml`. Run `python3 -m pytest tests -q` in `native/` before
opening a pull request that touches it. The QML tests fall back to a Kirigami stub where
KDE Frameworks 6 is not installed, so they run anywhere Qt does — but if you are changing
QML, install the real Kirigami so you are testing what users get.

## Prerequisites

Use the versions pinned by the repository. At the time of writing these are:

- Node.js 22.19.0 (`.node-version` and `.nvmrc`)
- Python 3.9 (`.python-version` and `.tool-versions`)
- Git with submodule support
- Native build tools for the host platform
- A system `yarn` command to bootstrap the vendored Yarn 1.21.1 configured by `.yarnrc`

The broad `engines` ranges in `package.json` are not the development toolchain. Prefer the checked-in version files and CI configuration.

Choose the platform prerequisites:

- [Linux](setup-linux.md)
- [macOS](setup-macos.md)
- [Windows](setup-windows.md)
- [ARM64 and Linux cross-compilation](building-arm64.md)

## Clone

Clone this fork and initialize all submodules:

```bash
git clone --recurse-submodules https://github.com/goshitsarch-eng/github-desktop-linux.git
cd github-desktop-linux
```

For an existing clone:

```bash
git submodule update --init --recursive
```

## Install dependencies

```bash
yarn
```

The post-install script installs root and app dependencies, applies supported patches, and builds native dependencies. Do not use `sudo yarn`.

## Build and run

```bash
yarn build:dev
yarn start
```

`build:dev` compiles webpack bundles and assembles a development application. `start` launches the development build and watches applicable source changes. Changes that affect the assembled main-process package or native resources may require another `yarn build:dev`.

For a production build:

```bash
yarn build:prod
yarn start:prod
```

Generated files are written to `out/` and `dist/`; both can be recreated.

## Tests and validation

```bash
yarn test             # Application unit tests
yarn test:script      # Tests under script/
yarn test:eslint      # Custom ESLint rule tests
yarn lint             # Prettier check plus source lint
yarn markdownlint     # Markdown checks
yarn validate-changelog
```

`script/test.mjs` accepts test file or directory arguments supported by the Node test runner. This repository does not define `test:coverage`, and Jest-style `--grep` examples do not apply.

## Debugging

Start the development app, then use **View > Toggle Developer Tools**. Development builds attempt to install React Developer Tools and axe DevTools.

For environment and native-build failures, see [contributor troubleshooting](troubleshooting.md). For application runtime problems, see [known issues](../known-issues.md).

## Next steps

- Read the [architecture overview](../technical/architecture.md).
- Read the [build and packaging pipeline](../technical/packaging.md).
- Review the [style guide](styleguide.md) and [linting guide](linting.md).
- Follow the repository [contribution guide](../../.github/CONTRIBUTING.md) before opening a pull request.
