# Contributing

Thanks for helping improve this unofficial GitHub Desktop for Linux fork.

## Project scope

This repository maintains Linux builds and integration around the upstream [GitHub Desktop source](https://github.com/desktop/desktop). Good contributions include Linux packaging, ARM64, desktop integration, protocol handling, documentation, reproducible Linux bugs, and carefully selected upstream sync work.

A feature or bug that affects official Windows/macOS GitHub Desktop and is unrelated to this fork may belong in the [upstream issue tracker](https://github.com/desktop/desktop/issues). GitHub.com account and service issues belong with [GitHub Support](https://support.github.com/).

All participants must follow the [Code of Conduct](../CODE_OF_CONDUCT.md).

## Before opening an issue

1. Install an asset from this repository's latest release.
2. Read the [installation guide](../docs/installation.md) and [known issues](../docs/known-issues.md).
3. Search open and closed issues.
4. Remove secrets and sensitive paths from logs.
5. Use the appropriate issue form and fill in every relevant environment field.

Security vulnerabilities must follow the [security policy](../SECURITY.md), not the public issue tracker.

## Propose a change

For substantial changes, open an issue first so maintainers can discuss scope and avoid duplicate work. Keep pull requests focused; avoid mixing upstream synchronization, dependency upgrades, formatting, and feature work unless they are inseparable.

## Set up the repository

Start with the [development setup guide](../docs/contributing/setup.md). Linux contributors should also read [Linux setup](../docs/contributing/setup-linux.md), and ARM64 contributors should read [ARM64 builds](../docs/contributing/building-arm64.md).

Create a branch from the repository's default branch and make small, descriptive commits. Do not commit generated `out/`, `dist/`, dependency directories, credentials, or private logs.

## Validate changes

Run checks relevant to the change. A typical source change should run:

```bash
yarn test
yarn test:script
yarn lint
```

Documentation changes should run:

```bash
yarn markdownlint
```

Packaging changes should include the exact build command and manually tested artifact/architecture in the pull request. Cross-platform behavior should be called out when it was not tested.

## Open a pull request

Complete the pull request template, link the issue when one exists, explain user-visible behavior and risks, and include screenshots for UI changes. Add tests for behavior changes when practical and update documentation when commands, dependencies, environment variables, package outputs, or workflows change.

By contributing, you agree that your contribution is licensed under the repository's [MIT License](../LICENSE).
