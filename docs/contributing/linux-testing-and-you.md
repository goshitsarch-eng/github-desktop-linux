# Testing Linux releases

Test assets attached to this repository's [Releases page](https://github.com/goshitsarch-eng/github-desktop-linux/releases). The current workflow publishes x64 and arm64 AppImages and tarballs; DEB/RPM packaging is available only for local builds.

## Before testing

1. Read the [installation guide](../installation.md).
2. Choose the asset matching `uname -m`.
3. Preserve a copy of important application data.
4. Never test an untrusted third-party package with access to valuable credentials or repositories.

## Suggested checks

- Start the package from a terminal and from a desktop menu.
- Sign in through the browser and confirm the OAuth callback returns to Desktop.
- Add, clone, fetch, commit, push, and pull a disposable repository.
- Confirm credentials persist after restart.
- Test external editor and shell integration used by your desktop.
- For tarballs, test the packaged `github` helper.
- Record distribution, desktop environment, X11/Wayland session, architecture, package, and release tag.

Report problems through this repository's [Linux bug report form](https://github.com/goshitsarch-eng/github-desktop-linux/issues/new?template=bug_report.yaml). Include sanitized logs and state whether the problem is new compared with the previous release.

To test local source or packaging changes, complete [Linux development setup](setup-linux.md) and document the exact build command in the pull request.
