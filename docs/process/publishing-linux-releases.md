# Publishing Linux releases

The automated Linux release workflow is defined in `.github/workflows/linux-release.yml`.

## Trigger

Pushing a tag matching `v*` or `release-*` starts the workflow. Before tagging:

1. Update and validate the canonical version in `app/package.json`.
2. Confirm the intended commit passes CI.
3. Review user-facing changes and release notes.
4. Create and push an annotated tag using the repository's established naming convention.

Only maintainers with release permissions should create release tags.

## Build matrix

GitHub Actions builds `x64` and `arm64` on Ubuntu 22.04. ARM64 uses the cross-compiler and target libraries documented in [Building Linux for ARM64](../contributing/building-arm64.md).

For each architecture, the workflow:

1. installs dependencies;
2. creates a production application;
3. bundles the target `libcurl-gnutls.so.4` for portable Git;
4. archives `dist/desktop-linux-<architecture>/` as a tarball; and
5. packages an AppImage.

The release job downloads all four artifacts and creates a non-draft GitHub Release with generated release notes.

## Published assets

```text
GitHubDesktop-linux-x64-<version>.AppImage
GitHubDesktop-linux-arm64-<version>.AppImage
GitHubDesktop-linux-x64-<version>.tar.gz
GitHubDesktop-linux-arm64-<version>.tar.gz
```

DEB and RPM scripts exist for local packaging but are not uploaded by this workflow.

## Post-release checks

- Confirm all four files are attached to the expected tag.
- Download each asset from the release rather than using a job workspace copy.
- Smoke-test startup and architecture where hardware is available.
- Confirm the AppImage and tarball contain bundled Git and its libcurl library.
- Record or fix any failed architecture before announcing the release.

Do not manually replace an asset under an existing tag without explaining the replacement; immutable tags and auditable workflow output are preferable.
