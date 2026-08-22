# Known issues

This page covers common problems in the unofficial Linux GTK 4 builds. Start with the [installation guide](installation.md), then search this repository's [issues](https://github.com/goshitsarch-eng/github-desktop-linux/issues) before filing a report.

## Browser sign-in does not return to the app

Production authentication uses `x-github-desktop-auth://`. The meson/tarball desktop file registers that scheme; some environments still need a manual default:

```bash
xdg-mime query default x-scheme-handler/x-github-desktop-auth
```

If the result is empty or names another application, follow [desktop menu and browser sign-in setup](installation.md#desktop-menu-and-browser-sign-in). Confirm that the `Exec` path is absolute and still points to `github-desktop`.

Development builds also use `x-github-desktop-dev-auth`. The shipped desktop file lists both handlers.

## Missing GTK 4 or libadwaita

The app will not start without PyGObject, GTK 4, and libadwaita. Install the packages listed under [runtime requirements](installation.md#runtime-requirements) and retry `github-desktop` from a terminal so import errors are visible.

## Credentials are not saved or the keyring repeatedly unlocks

Install `libsecret` / `gir1.2-secret-1` and a Secret Service provider such as GNOME Keyring. Verify that the keyring daemon starts and unlocks with the desktop login session. Configuration is desktop- and distribution-specific; consult the distribution's keyring/PAM documentation rather than editing PAM files blindly.

When reporting this issue, include the desktop environment, display manager, installed Secret Service provider, and whether another application can save a secret.

## Git is not found

The native app uses **system Git**. Install `git` and confirm `git --version` works in a terminal. If Git is installed in a non-standard location, put that directory on `PATH` before launching `github-desktop`.

## Wayland drag and drop does not work

Cross-application drag and drop can fail when one app is X11 and the other is native Wayland. Try an X11 desktop session or launch with:

```bash
GDK_BACKEND=x11 github-desktop
```

Repository operations remain available through the application menus and the `github` helper.

## UI scaling is incorrect

Prefer the desktop environment's display scaling first. GitHub Desktop also has **Preferences → Appearance** zoom (Ctrl+0 / Ctrl+= / Ctrl+−) for the application chrome.

## Find logs

Use **Help → Show logs in your File Manager**. On a default Linux configuration, logs are under:

```text
~/.local/share/github-desktop/logs/
```

Settings live under `~/.config/github-desktop/`. Before attaching logs publicly, review them for repository names, paths, usernames, remote URLs, and other sensitive data.

## Report a problem

Use the [Linux bug report form](https://github.com/goshitsarch-eng/github-desktop-linux/issues/new?template=bug_report.yaml) and include the release, asset filename, distribution, architecture, desktop/session type, reproduction steps, and sanitized logs.

If the same problem occurs in an official Windows or macOS GitHub Desktop release, search the [upstream issue tracker](https://github.com/desktop/desktop/issues). GitHub.com service and account issues belong with [GitHub Support](https://support.github.com/).
