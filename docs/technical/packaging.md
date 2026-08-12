# Building and packaging

See [application architecture](architecture.md) for the runtime source map. This page describes how source becomes an executable and release asset.

## 1. Compile with webpack

`yarn compile:dev` and `yarn compile:prod` use the configurations under `app/`:

- `app/webpack.common.ts`
- `app/webpack.development.ts`
- `app/webpack.production.ts`

Webpack transpiles TypeScript, React, and SCSS and emits bundles such as `main.js`, `renderer.js`, `crash.js`, `highlighter.js`, and `cli.js` into `out/`. Build-time constants come from `app/app-info.ts`.

## 2. Assemble the application

`yarn build:dev` or `yarn build:prod` runs compilation and `script/build.ts`. The build script:

- recreates `dist/`;
- copies platform and common static resources;
- installs only runtime external dependencies into `out/`;
- copies dugite's bundled Git and Desktop credential helper;
- generates application and third-party license metadata; and
- runs `electron-packager` for the host platform and `TARGET_ARCH`.

The Linux assembled directory is:

```text
dist/desktop-linux-<architecture>/
```

`app/package.json` is the canonical application version.

## 3. Package for distribution

`yarn package` invokes `script/package.ts` and packages the already assembled application.

### Linux

Use `PACKAGE_FORMAT` to select one format:

```bash
PACKAGE_FORMAT=AppImage yarn package
PACKAGE_FORMAT=deb yarn package
PACKAGE_FORMAT=rpm yarn package
```

Without `PACKAGE_FORMAT`, the script attempts all three.

| Format | Implementation | Typical output |
| --- | --- | --- |
| AppImage | `script/package-electron-builder.ts` and `electron-builder-linux.yml` | `GitHubDesktop-linux-<arch>-<version>.AppImage` |
| DEB | `script/package-debian.ts` | `GitHubDesktop-linux-<debian-arch>-<version>.deb` |
| RPM | `script/package-redhat.ts` | `GitHubDesktop-linux-<rpm-arch>-<version>.rpm` |

DEB/RPM support is local packaging functionality. The current `.github/workflows/linux-release.yml` uploads only AppImages and tarballs.

### macOS

`electron-packager` creates the application bundle. `script/package.ts` compresses it into `GitHub Desktop-<architecture>.zip`. Publishable CI builds additionally require signing and notarization credentials.

### Windows

`electron-winstaller` creates architecture-specific Squirrel `.exe` and MSI installers plus NuGet packages. Publishable workflow runs can use Azure Code Signing credentials.

## 4. Linux release workflow

A tag matching `v*` or `release-*` starts `.github/workflows/linux-release.yml`. For each `x64` and `arm64` target, it:

1. checks out recursive submodules;
2. installs Node.js 22.19.0, Python 3.11 in CI, and Linux build dependencies;
3. installs ARM64 cross-toolchains and target libraries when needed;
4. runs `yarn`, then `yarn build:prod`, with `npm_config_arch`, `TARGET_ARCH`, `CC`, and `CXX`;
5. copies target `libcurl-gnutls.so.4` into bundled Git;
6. creates a tarball from the assembled directory;
7. creates an AppImage with `PACKAGE_FORMAT=AppImage`; and
8. attaches both architectures' artifacts to a GitHub Release.

Python 3.11 in CI is an implementation detail of that workflow; contributor version files currently pin Python 3.9.

## Generated content

- `out/`: webpack output and temporary assembled resources
- `dist/`: packaged applications and release artifacts
- `dist/bundle-size.json`: renderer/main bundle-size metadata generated during packaging

These directories are generated and should not be edited manually.
