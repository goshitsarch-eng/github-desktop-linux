# Contributor troubleshooting

This page covers development and build failures. For installed application problems, use [known issues](../known-issues.md).

## Wrong tool versions

From the repository root, compare output with `.node-version`, `.python-version`, and `.yarnrc`:

```bash
node --version
python3 --version
yarn --version
```

Use the exact pinned Node.js version before investigating native module failures.

## Missing submodule content

License, gitignore, emoji, or static-resource build errors often indicate uninitialized submodules:

```bash
git submodule update --init --recursive
```

## Native module compilation fails

Install the platform build tools and Linux headers documented in the platform setup guide. On Linux, verify:

```bash
pkg-config --libs libsecret-1
pkg-config --libs xscrnsaver
```

Do not install random global copies of `node-gyp` or `electron-rebuild`; use the dependencies and post-install flow pinned by this repository.

## Dependencies are inconsistent

First retry `yarn`. If generated dependencies are irreparably stale, the repository provides:

```bash
yarn clean-slate
```

This removes `out`, root `node_modules`, and `app/node_modules`, then reinstalls. Preserve uncommitted source changes and expect downloads/build time.

## Electron download fails

Check proxy, certificate, and network configuration. Prefer configuring the standard npm/Electron proxy settings used by your organization. Mirrors change the binary trust source and should only be used when you understand and trust that source.

## Production build runs out of memory

`compile:prod` already sets Node's old-space limit to 4096 MB. Close memory-intensive processes or build on a machine with more available memory rather than lowering that value.

## AppImage will not run

The build host may need FUSE 2 compatibility (`libfuse2` on the Ubuntu release runner). For runtime diagnosis, compare with the [AppImage known issue](../known-issues.md#appimage-reports-a-fuse-error).

## Packaging does not produce the expected format

Set exactly one supported `PACKAGE_FORMAT` value: `AppImage`, `deb`, or `rpm`. AppImage uses electron-builder; DEB/RPM use separate installer packages and may need extra host tools. See [packaging](../technical/packaging.md).

## Tests do not accept an option

Tests run through `script/test.mjs` and Node's test runner. Use a file/directory argument or supported Node test options. There is no `test:coverage` script and no documented Jest-style `--grep` support.

If the failure persists, open a bug report with the host OS/architecture, exact commands, tool versions, and complete relevant error output.
