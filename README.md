# GitHub Desktop for Linux

[![Latest release](https://img.shields.io/github/v/release/goshitsarch-eng/github-desktop-linux)](https://github.com/goshitsarch-eng/github-desktop-linux/releases/latest)
[![Linux release](https://github.com/goshitsarch-eng/github-desktop-linux/actions/workflows/linux-release.yml/badge.svg)](https://github.com/goshitsarch-eng/github-desktop-linux/actions/workflows/linux-release.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An independently maintained, unofficial Linux build of the open-source [GitHub Desktop](https://desktop.github.com/) application.

> [!IMPORTANT]
> This project is not affiliated with, sponsored by, or supported by GitHub, Inc. For problems with these Linux builds, use this repository's [issue tracker](https://github.com/goshitsarch-eng/github-desktop-linux/issues). For GitHub.com account or service problems, contact [GitHub Support](https://support.github.com/).

<picture>
  <source srcset="https://user-images.githubusercontent.com/634063/202742848-63fa1488-6254-49b5-af7c-96a6b50ea8af.png" media="(prefers-color-scheme: dark)">
  <img width="1072" src="https://user-images.githubusercontent.com/634063/202742985-bb3b3b94-8aca-404a-8d8a-fd6a6f030672.png" alt="GitHub Desktop showing a commit with two co-authors">
</picture>

## Download and install

The Linux release workflow publishes AppImages and portable tarballs for:

- **x64**: most Intel and AMD computers
- **arm64**: 64-bit ARM systems

Download the appropriate file from the [latest release](https://github.com/goshitsarch-eng/github-desktop-linux/releases/latest). AppImage is the easiest option for most users.

```bash
chmod +x GitHubDesktop-linux-<architecture>-<version>.AppImage
./GitHubDesktop-linux-<architecture>-<version>.AppImage
```

Replace `<architecture>` with `x64` or `arm64` and `<version>` with the downloaded release version. See the [complete installation guide](docs/installation.md) for tarball installation, desktop menus, browser sign-in, upgrades, dependencies, and uninstalling.

> [!NOTE]
> DEB and RPM packaging code is available for local builds, but the current Linux release workflow does **not** publish `.deb` or `.rpm` files. Only install assets attached to this repository's releases or artifacts you build and verify yourself.

## What is included

- GitHub authentication and GitHub Enterprise Server support
- Repository cloning, creation, publishing, and branch management
- Commit history, diffs, stashing, rebasing, and conflict resolution
- Pull request and issue integrations
- A bundled Git distribution and credential helper
- Linux x64 and arm64 packages
- A `github` command-line helper in packaged builds

Feature behavior primarily follows the [upstream GitHub Desktop project](https://github.com/desktop/desktop). Linux packaging and integration issues belong in this repository.

## Requirements

A modern 64-bit Linux distribution with a graphical desktop is required. Credential storage uses Secret Service (`libsecret`) and normally requires a keyring such as GNOME Keyring. AppImage may require FUSE 2 on some distributions; if unavailable, use the tarball.

See [installation requirements](docs/installation.md#runtime-requirements) and [known issues](docs/known-issues.md).

## Command line

When the packaged `github` helper is on `PATH`:

```bash
github                         # Open the current directory
github open /path/to/repo
github clone owner/repository
github clone --branch topic owner/repository
github --help
```

AppImage and tarball users must create their own launcher or symlink before `github` is available globally. Details are in the [installation guide](docs/installation.md#optional-command-line-helper).

## Documentation

- [Install and update](docs/installation.md)
- [Known issues](docs/known-issues.md)
- [Documentation index](docs/README.md)
- [Development setup](docs/contributing/setup.md)
- [Architecture](docs/technical/architecture.md)
- [Build and packaging pipeline](docs/technical/packaging.md)
- [Contributing](.github/CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## Development quick start

The checked-in version files currently select Node.js 22.19.0, Python 3.9, and vendored Yarn 1.21.1. Clone submodules recursively:

```bash
git clone --recurse-submodules https://github.com/goshitsarch-eng/github-desktop-linux.git
cd github-desktop-linux
yarn
yarn build:dev
yarn start
```

Before opening a pull request, run the relevant checks:

```bash
yarn test
yarn test:script
yarn lint
yarn markdownlint
```

Platform prerequisites and the full workflow are documented in the [development setup guide](docs/contributing/setup.md).

## Upstream and support boundaries

This fork carries Linux-specific build and packaging work on top of [desktop/desktop](https://github.com/desktop/desktop). Search upstream when a problem also occurs in official Windows or macOS GitHub Desktop. Do not ask upstream maintainers to support packages produced here.

## License and trademarks

Source code is available under the [MIT License](LICENSE). The license grant does not grant rights to GitHub trademarks or logos. GitHub® and the Invertocat mark are trademarks of GitHub, Inc.; follow the [GitHub logo guidelines](https://github.com/logos) when reusing branded assets.
