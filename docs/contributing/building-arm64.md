# Building Linux for ARM64

The Linux release workflow cross-compiles `arm64` on an Ubuntu 22.04 x64 runner. Native ARM64 builds are also possible when all dependencies support the host.

## Native ARM64 build

After installing the dependencies from [Linux setup](setup-linux.md):

```bash
uname -m
git submodule update --init --recursive
npm_config_arch=arm64 TARGET_ARCH=arm64 yarn
npm_config_arch=arm64 TARGET_ARCH=arm64 yarn build:prod
npm_config_arch=arm64 TARGET_ARCH=arm64 \
  PACKAGE_FORMAT=AppImage yarn package
```

`uname -m` should report `aarch64` or `arm64`. Production builds can require several gigabytes of memory and disk space; no specific ARM board is guaranteed by the project.

## Cross-compile on Ubuntu 22.04 x64

The checked-in `.github/workflows/linux-release.yml` is the authoritative example. It adds the Ubuntu arm64 repositories and installs:

- `gcc-aarch64-linux-gnu`
- `g++-aarch64-linux-gnu`
- `libsecret-1-dev:arm64`
- `libxss-dev:arm64`
- `libcurl3-gnutls:arm64`

It then uses the same environment for dependency installation and production build:

```bash
export npm_config_arch=arm64
export TARGET_ARCH=arm64
export CC=aarch64-linux-gnu-gcc
export CXX=aarch64-linux-gnu-g++

yarn
yarn build:prod
PACKAGE_FORMAT=AppImage yarn package
```

Do not substitute `npm_config_target_arch` for `TARGET_ARCH`: `script/build.ts` reads `TARGET_ARCH` when passing the architecture to `electron-packager`, while package and distribution helpers read `npm_config_arch`.

## Portable Git library

The release workflow copies `/usr/lib/aarch64-linux-gnu/libcurl-gnutls.so.4` into:

```text
dist/desktop-linux-arm64/resources/app/git/lib/
```

A local portable build intended for other machines should reproduce that step before creating its tarball. AppImage generation and native Node modules may fail if host and target libraries are mixed.

## Outputs

```text
dist/desktop-linux-arm64/
dist/GitHubDesktop-linux-arm64-<version>.AppImage
```

The release workflow separately archives the assembled directory as `GitHubDesktop-linux-arm64-<version>.tar.gz`.

## Troubleshooting

- Delete generated dependency/build directories with `yarn clean-slate` only when a normal reinstall is insufficient; it reinstalls dependencies immediately.
- Confirm native binaries with `file` before packaging.
- Compare environment variables and apt repositories with the current release workflow rather than copying old commands.
- Prefer a native ARM64 machine if a dependency cannot be cross-compiled.

See [contributor troubleshooting](troubleshooting.md) for general setup problems.
