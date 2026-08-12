# Windows development dependencies

Windows support is inherited from upstream and is useful when changing cross-platform application code. Linux release packages must still be built and tested on Linux.

Install:

- Node.js 22.19.0 from `.node-version`
- Python 3.9 from `.python-version`
- A bootstrap Yarn command; `.yarnrc` selects vendored Yarn 1.21.1
- Git
- Visual Studio 2022 Build Tools with the **Desktop development with C++** workload and a supported Windows SDK

Use a regular PowerShell or Developer PowerShell session. Verify:

```powershell
node --version
python --version
yarn --version
git --version
```

Then return to the [main development setup](setup.md). Do not apply old `msvs_version` settings for Visual Studio 2017/2019 unless a current build error specifically requires custom node-gyp configuration.
