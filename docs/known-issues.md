# Known issues

This page covers common problems in the unofficial Linux builds. Start with the [installation guide](installation.md), then search this repository's [issues](https://github.com/goshitsarch-eng/github-desktop-linux/issues) before filing a report.

## Browser sign-in does not return to the app

Production authentication uses `x-github-desktop-auth://`. Portable packages need a desktop entry registered for that scheme.

```bash
xdg-mime query default x-scheme-handler/x-github-desktop-auth
```

If the result is empty or names another application, follow [desktop menu and browser sign-in setup](installation.md#desktop-menu-and-browser-sign-in). Confirm that the `Exec` path is absolute and still points to the installed AppImage or tarball executable.

Development builds use `x-github-desktop-dev-auth` instead. Do not register the development scheme to a production build.

## AppImage reports a FUSE error

Some distributions no longer install FUSE 2 compatibility by default. Install the appropriate compatibility package (for example, `libfuse2` on supported Debian/Ubuntu releases) or use the release tarball. Avoid running an untrusted AppImage extraction command copied from third-party sites.

## The window is black or graphics are corrupted

Disable Electron hardware acceleration for one launch:

```bash
GITHUB_DESKTOP_DISABLE_HARDWARE_ACCELERATION=1 \
  "$HOME/Applications/GitHubDesktop.AppImage"
```

Use the corresponding tarball path if needed. If this works, add the environment variable to a wrapper script or desktop entry, for example:

```ini
Exec=env GITHUB_DESKTOP_DISABLE_HARDWARE_ACCELERATION=1 /absolute/path/to/GitHubDesktop.AppImage %U
```

## Credentials are not saved or the keyring repeatedly unlocks

Install `libsecret` and a Secret Service provider such as GNOME Keyring. Verify that the keyring daemon starts and unlocks with the desktop login session. Configuration is desktop- and distribution-specific; consult the distribution's keyring/PAM documentation rather than editing PAM files blindly.

When reporting this issue, include the desktop environment, display manager, installed Secret Service provider, and whether another application can save a secret.

## Git operations fail because a library is missing

Release builds include dugite's Git and copy `libcurl-gnutls.so.4` into the portable Git library directory. If Git still reports a missing shared library:

1. Confirm that the entire tarball directory was preserved, or redownload the AppImage.
2. Confirm the selected asset matches the system architecture.
4. If the bundled library remains incompatible, test system Git:

   ```bash
   GITHUB_DESKTOP_USE_SYSTEM_GIT=1 /absolute/path/to/GitHubDesktop.AppImage
   ```

5. Run from a terminal and attach the exact error and application log to a bug report.

## Wayland drag and drop does not work

Cross-application drag and drop can fail when the app runs through XWayland while the other application is native Wayland. Try an X11 desktop session or launch with:

```bash
GDK_BACKEND=x11 /absolute/path/to/GitHubDesktop.AppImage
```

Repository operations remain available through the application menus and the tarball's `github` helper.

## UI scaling is incorrect

Prefer the desktop environment's display scaling first. For diagnosis, Electron also accepts Chromium switches such as:

```bash
/absolute/path/to/GitHubDesktop.AppImage --force-device-scale-factor=1.5
```

Values that work on one mixed-DPI setup may look poor on another.

## Find logs

Use **Help > Show Logs**. On a default Linux configuration, logs are under:

```text
~/.config/GitHub Desktop/logs/
```

Before attaching logs publicly, review them for repository names, paths, usernames, remote URLs, and other sensitive data.

## Report a problem

Use the [Linux bug report form](https://github.com/goshitsarch-eng/github-desktop-linux/issues/new?template=bug_report.yaml) and include the release, asset filename, distribution, architecture, desktop/session type, reproduction steps, and sanitized logs.

If the same problem occurs in an official Windows or macOS GitHub Desktop release, search the [upstream issue tracker](https://github.com/desktop/desktop/issues). GitHub.com service and account issues belong with [GitHub Support](https://support.github.com/).
