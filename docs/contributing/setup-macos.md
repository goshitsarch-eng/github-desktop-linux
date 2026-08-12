# macOS development dependencies

macOS support is inherited from upstream and is useful when changing cross-platform application code. Linux release packages must still be built and tested on Linux.

Install:

- Node.js 22.19.0 from `.node-version` (for example with `nvm install`)
- Python 3.9 from `.python-version` (for example with `pyenv`)
- A bootstrap Yarn command; `.yarnrc` selects vendored Yarn 1.21.1
- Xcode and its command-line tools
- Git

```bash
xcode-select --install
node --version
python3 --version
yarn --version
```

Then return to the [main development setup](setup.md). Production signing and notarization require Apple credentials and are configured by CI environment variables; they are not required for ordinary development builds.
