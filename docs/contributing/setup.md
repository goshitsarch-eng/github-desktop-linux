# Development setup

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
