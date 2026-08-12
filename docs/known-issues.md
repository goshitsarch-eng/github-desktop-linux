# Table of Contents

- [Linux](#linux)
  - [Bundled Git fails with libcurl-gnutls error](#bundled-git-fails-with-libcurl-gnutls-error)
  - [OAuth authentication doesn't complete after browser redirect](#oauth-authentication-doesnt-complete-after-browser-redirect)
  - [Application shows black screen on launch](#application-shows-black-screen-on-launch)
  - [Keyring unlock prompt on every launch](#keyring-unlock-prompt-on-every-launch)
  - [Wayland drag and drop issues](#wayland-drag-and-drop-issues)
  - [High DPI scaling issues](#high-dpi-scaling-issues)
  - [Tray icon not showing](#tray-icon-not-showing)
- [macOS](#macos)
  - ['The username or passphrase you entered is not correct' error after signing into account](#the-username-or-passphrase-you-entered-is-not-correct-error-after-signing-into-account)
  - [Checking for updates triggers a 'Could not create temporary directory: Permission denied' message](#checking-for-updates-triggers-a-could-not-create-temporary-directory-permission-denied-message)
- [Windows](#windows)
  - [Window is hidden after detaching secondary monitor](#window-is-hidden-after-detaching-secondary-monitor)
  - [Certificate revocation check fails](#certificate-revocation-check-fails)
  - [Using a repository configured with Folder Redirection](#using-a-repository-configured-with-folder-redirection)
  - [Enable Mandatory ASLR triggers cygheap errors](#enable-mandatory-aslr-triggers-cygheap-errors)
  - [I get a black screen when launching Desktop](#i-get-a-black-screen-when-launching-desktop)
  - [Failed to open CA file after an update](#failed-to-open-ca-file-after-an-update)
  - [Authentication errors due to modified registry entries](#authentication-errors-due-to-modified-registry-entries)

# Known Issues

This document outlines acknowledged issues with GitHub Desktop, including workarounds if known.

## What should I do if...

### I have encountered an issue listed here?

Some known issues have a workaround that users have reported addresses the issue. Please try the workaround for yourself to confirm it addresses the issue.

### I have additional questions about an issue listed here?

Each known issue links off to an existing GitHub issue. If you have additional questions or feedback, please comment on the issue.

### My issue is not listed here?

Please check the [open](https://github.com/desktop/desktop/labels/bug) and [closed](https://github.com/desktop/desktop/issues?q=is%3Aclosed+label%3Abug) bugs in the issue tracker for the details of your bug. If you can't find it, or if you're not sure, open a [new issue](https://github.com/desktop/desktop/issues/new?template=bug_report.md).

---

## Linux

### OAuth authentication doesn't complete after browser redirect

**Symptoms:**

After signing in through the browser and authorizing GitHub Desktop, the browser shows a page with `x-github-desktop-auth://` URL but the desktop app doesn't log you in.

**Cause:**

Linux desktop environments handle custom protocol URLs differently than macOS/Windows. The desktop entry file must be properly registered to handle the `x-github-desktop-auth://` protocol.

**Workaround:**

1. **Verify the .desktop file is installed:**
   ```bash
   ls ~/.local/share/applications/desktop.desktop
   # or for system-wide RPM install
   ls /usr/share/applications/desktop.desktop
   ```

2. **Check protocol handler registration:**
   ```bash
   xdg-mime query default x-scheme-handler/x-github-desktop-auth
   ```
   Should return `desktop.desktop`

3. **Manually register the handler:**
   ```bash
   xdg-mime default desktop.desktop x-scheme-handler/x-github-desktop-auth
   xdg-mime default desktop.desktop x-scheme-handler/x-github-client
   update-desktop-database ~/.local/share/applications
   ```

4. **For AppImage users**, create a desktop entry manually at `~/.local/share/applications/github-desktop.desktop`:
   ```ini
   [Desktop Entry]
   Name=GitHub Desktop
   Exec=/path/to/GitHubDesktop-linux-arm64-3.5.4.AppImage %U
   Type=Application
   Categories=Development;
   MimeType=x-scheme-handler/x-github-client;x-scheme-handler/x-github-desktop-auth;
   ```
   Then run: `update-desktop-database ~/.local/share/applications`

5. **As a last resort**, copy the auth URL from the browser and run:
   ```bash
   github-desktop "x-github-desktop-auth://oauth?code=YOUR_CODE_HERE"
   ```

---

### Application shows black screen on launch

**Symptoms:**

The application window opens but displays only a black screen.

**Cause:**

Electron's hardware acceleration may not work correctly with certain GPU drivers (especially on older hardware, VMs, or with nouveau/mesa drivers).

**Workaround:**

Disable hardware acceleration:

```bash
# One-time
GITHUB_DESKTOP_DISABLE_HARDWARE_ACCELERATION=1 github-desktop

# Permanent - add to ~/.bashrc
export GITHUB_DESKTOP_DISABLE_HARDWARE_ACCELERATION=1
```

Or create a modified desktop entry with this environment variable.

---

### Keyring unlock prompt on every launch

**Symptoms:**

Every time you launch GitHub Desktop, you're prompted to unlock your keyring or enter your password.

**Cause:**

The GNOME Keyring daemon isn't properly integrated with your login session, or you're using a desktop environment that doesn't automatically unlock the keyring.

**Workaround:**

1. **Ensure gnome-keyring is properly configured for PAM:**

   Edit `/etc/pam.d/login` (or the appropriate PAM config for your display manager) and ensure these lines exist:
   ```
   auth       optional     pam_gnome_keyring.so
   session    optional     pam_gnome_keyring.so auto_start
   ```

2. **For KDE/SDDM users:**

   Install `gnome-keyring` and configure it to start with your session:
   ```bash
   mkdir -p ~/.config/autostart
   cp /etc/xdg/autostart/gnome-keyring-*.desktop ~/.config/autostart/
   ```

3. **Check keyring daemon is running:**
   ```bash
   gnome-keyring-daemon --status
   ```

4. **Use seahorse to manage keyrings:**
   ```bash
   sudo dnf install seahorse  # Fedora
   sudo apt install seahorse  # Ubuntu
   seahorse  # Open and check your keyrings
   ```

---

### Wayland drag and drop issues

**Symptoms:**

- Cannot drag files from the file manager into GitHub Desktop
- Cannot drag commits or branches between windows
- Drag and drop operations fail silently

**Cause:**

GitHub Desktop runs under XWayland (X11 compatibility layer) on Wayland, which has limitations with drag and drop operations across the Wayland/X11 boundary.

**Workaround:**

1. **Run under X11 session:**

   Log out and select "GNOME on Xorg" or equivalent at your login screen.

2. **Force X11 for this application only:**
   ```bash
   GDK_BACKEND=x11 github-desktop
   ```

3. **Use alternative methods:**
   - Use the CLI to open repositories: `github open /path/to/repo`
   - Use keyboard shortcuts instead of drag and drop

---

### High DPI scaling issues

**Symptoms:**

- UI appears too small or too large
- Fonts are blurry
- Window elements are misaligned

**Cause:**

Electron's auto-detection of DPI scaling may not work correctly on all display configurations, especially with mixed DPI setups.

**Workaround:**

Set scaling manually with environment variables:

```bash
# Force 2x scaling
GDK_SCALE=2 github-desktop

# Or use fractional scaling (may cause blurriness)
GDK_DPI_SCALE=1.5 github-desktop

# Or set Electron's own scale factor
ELECTRON_FORCE_WINDOW_SCALE_FACTOR=2 github-desktop
```

For permanent fix, modify your desktop entry or add to `~/.bashrc`.

---

### Tray icon not showing

**Symptoms:**

No system tray icon appears, or the icon appears but is invisible/broken.

**Cause:**

GNOME removed the system tray by default. Some desktop environments require additional extensions or packages.

**Workaround:**

1. **GNOME:** Install AppIndicator extension:
   ```bash
   # Fedora
   sudo dnf install gnome-shell-extension-appindicator

   # Ubuntu
   sudo apt install gnome-shell-extension-appindicator
   ```
   Then enable it in GNOME Extensions app.

2. **KDE:** Should work by default. Check System Tray settings.

3. **XFCE:** Ensure the notification area plugin is added to your panel.

---

## macOS

### 'The username or passphrase you entered is not correct' error after signing into account

Related issue: [#3263](https://github.com/desktop/desktop/issues/3263)

This seems to be caused by the Keychain being in an invalid state, affecting applications that try to use the keychain to store or retrieve credentials. This has been reported from macOS High Sierra 10.13 (17A365) to macOS Mojave 10.14.5 (18F132).

**Workaround:**

- Open `Keychain Access.app`
- Right-click on the `login` keychain and try locking it
- Right-click on the `login` keychain and try unlocking it
- Sign into your GitHub account again

### Checking for updates triggers a 'Could not create temporary directory: Permission denied' message

Related issue: [#4115](https://github.com/desktop/desktop/issues/4115)

This issue seems to be caused by missing permissions for the `~/Library/Caches/com.github.GitHubClient.ShipIt` folder. This is a directory that Desktop uses to create and unpack temporary files as part of updating the application.

**Workaround:**

 - Close Desktop
 - Open Finder and navigate to `~/Library/Caches/`
 - Context-click `com.github.GitHubClient.ShipIt` and select **Get Info**
 - Expand the **Sharing & Permissions** section
 - If you do not see the "You can read and write" message, add yourself with
   the "Read & Write" permissions
 - Start Desktop again and check for updates

### GitHub Desktop prompts admin password to install helper tool very frequently

Related issue: [#13956](https://github.com/desktop/desktop/issues/13956)

Users who use macOS' Migration Assistant to keep their stuff intact when moving to a new computer might run into this problem because the Migration Assistant changes the owner of the `/Applications/GitHub Desktop.app` folder to `root`.

Since GitHub Desktop is able to auto-update by changing the contents of the `/Applications/GitHub Desktop.app` folder, it needs to be able to write to it. If the owner of the folder is not the current user, the user will be prompted for an admin password every time GitHub Desktop tries to update itself.

**Workaround:** you need to restore the ownership and permissions of the application folder to the current user. If your app is located in `/Applications/GitHub Desktop.app`, you can probably do this by just running the following commands in Terminal:

```sh
sudo chown -R ${USER}:staff /Applications/GitHub\ Desktop.app
chmod -R g+w /Applications/GitHub\ Desktop.app
```

---

## Windows

### Window is hidden after detaching secondary monitor

Related issue: [#2107](https://github.com/desktop/desktop/issues/2107)

This is related to Desktop tracking the window position between launches, but not changes to your display configuration such as removing the secondary monitor where Desktop was positioned.

**Workaround:**

 - Remove `%APPDATA%\GitHub Desktop\window-state.json`
 - Restart Desktop

### Certificate revocation check fails

Related issue: [#3326](https://github.com/desktop/desktop/issues/3326)

If you are using Desktop on a corporate network, you may encounter an error like this:

```
fatal: unable to access 'https://github.com/owner/name.git/': schannel: next InitializeSecurityContext failed: Unknown error (0x80092012) - The revocation function was unable to check revocation for the certificate.
```

GitHub Desktop by default uses the Windows Secure Channel (SChannel) APIs to validate the certificate received from a server. Some networks will block the attempts by Windows to check the revocation status of a certificate, which then causes the whole operation to error.

**Workaround:**

**We do not recommend setting this config value for normal Git usage**. This is intended to be an "escape hatch" for situations where the network administrator has restricted the normal usage of SChannel APIs on Windows that Git is trying to use.

Run this command in your Git shell to disable the revocation check:

```shellsession
$ git config --global http.schannelCheckRevoke false
```

### Using a repository configured with Folder Redirection

Related issue: [#2972](https://github.com/desktop/desktop/issues/2972)

[Folder Redirection](https://docs.microsoft.com/en-us/previous-versions/windows/it-pro/windows-server-2008-R2-and-2008/cc753996(v%3dws.11)) is a feature of Windows for administrators to ensure files and folders are managed on a network server, instead.

**Not supported** as Git is not able to resolve the working directory correctly:

```shellsession
2017-09-21T23:16:05.933Z - error: [ui] `git -c credential.helper= lfs clone --recursive --progress --progress -- https://github.com/owner/name.git \\harvest\Redirected\andrewd\My Documents\GitHub\name` exited with an unexpected code: 2.
Cloning into '\\harvest\Redirected\andrewd\My Documents\GitHub\name'...
remote: Counting objects: 4, done.
remote: Compressing objects:  33% (1/3)
remote: Compressing objects:  66% (2/3)
remote: Compressing objects: 100% (3/3)
remote: Compressing objects: 100% (3/3), done.
remote: Total 4 (delta 1), reused 4 (delta 1), pack-reused 0
fatal: unable to get current working directory: No such file or directory
warning: Clone succeeded, but checkout failed.
You can inspect what was checked out with 'git status'
and retry the checkout with 'git checkout -f HEAD'

Error(s) during clone:
git clone failed: exit status 128
```

### Enable Mandatory ASLR triggers cygheap errors

Related issue: [#3096](https://github.com/desktop/desktop/issues/3096)

Windows 10 Fall Creators Edition (version 1709 or later) added enhancements to the Enhanced Mitigation Experience Toolkit, one being to enable Mandatory ASLR. This setting affects the embedded Git shipped in Desktop, and produces errors that look like this:

```
      1 [main] sh (2072) C:\Users\bdorrans\AppData\Local\GitHubDesktop\app-1.0.4\resources\app\git\usr\bin\sh.exe: *** fatal error - cygheap base mismatch detected - 0x2E07408/0x2EC7408.
This problem is probably due to using incompatible versions of the cygwin DLL.
Search for cygwin1.dll using the Windows Start->Find/Search facility
and delete all but the most recent version.  The most recent version *should*
reside in x:\cygwin\bin, where 'x' is the drive on which you have
installed the cygwin distribution.  Rebooting is also suggested if you
are unable to find another cygwin DLL.
```

Enabling Mandatory ASLR affects the MSYS2 core library, which is relied upon by Git for Windows to emulate process forking.

**Not supported:** this is an upstream limitation of MSYS2, and it is recommended that you either disable Mandatory ASLR or explicitly allow all executables under `<Git>\usr\bin` which depend on MSYS2.

### I get a black screen when launching Desktop

Related issue: [#3921](https://github.com/desktop/desktop/issues/3921)

Electron enables hardware accelerated graphics by default, but some graphics cards have issues with hardware acceleration which means the application will launch successfully but it will be a black screen.

**Workaround:** if you set the `GITHUB_DESKTOP_DISABLE_HARDWARE_ACCELERATION` environment variable to any value and launch Desktop again it will disable hardware acceleration on launch, so the application is usable. Here are the steps to set the environment variable in PowerShell:

1. Open PowerShell
2. Run the command `$env:GITHUB_DESKTOP_DISABLE_HARDWARE_ACCELERATION=1`
3. Launch GitHub Desktop

### Failed to open CA file after an update

Related issue: [#4832](https://github.com/desktop/desktop/issues/4832)

A recent upgrade to Git for Windows changed how it uses `http.sslCAInfo`.

An example of this error:

> fatal: unable to access 'https://github.com/\<owner>/\<repo>.git/': schannel: failed to open CA file 'C:/Users/\<account>/AppData/Local/GitHubDesktop/app-1.2.2/resources/app/git/mingw64/bin/curl-ca-bundle.crt': No such file or directory

This is occurring because some users have an existing Git for Windows installation that created a special config at `C:\ProgramData\Git\config`, and this config may contain an `http.sslCAInfo` entry, which is inherited by Desktop.

There's two problems with this current state:

 - Desktop doesn't need custom certificates for its Git operations - it uses SChannel by default, which uses the Windows Certificate Store to verify server certificates
 - this `http.sslCAInfo` config value may resolve to a location or file that doesn't exist in Desktop's Git installation

**Workaround:**

1. Verify that you have the problem configuration by checking the output of this command:

```
> git config -l --show-origin
```

You should have an entry that looks like this:

```
file:"C:\ProgramData/Git/config" http.sslcainfo=[some value here]
```

2. Open `C:\ProgramData\Git\config` (requires elevated privileges) and remove the corresponding lines that look like this:

```
[http]
sslCAInfo = [some value here]
```

### Authentication errors due to modified registry entries

Related issue: [#2623](https://github.com/desktop/desktop/issues/2623)

If either the user or an application has modified the `Command Processor` registry entries it can cause GitHub Desktop to throw an `Authentication failed` error. To check if these registry entries have been modified open the Registry Editor (regedit.exe) and navigate to the following locations:

`HKEY_CURRENT_USER\Software\Microsoft\Command Processor\`
`HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Command Processor\`

Check to see if there is an `Autorun` value in either of those location. If there is, deleting that value should resolve the `Authentication failed` error.

### "Not enough resources" error when signing in

Related issue: [#15217](https://github.com/desktop/desktop/issues/15217)

If you see an error that says "Not enough resources are available to process this command" when signing in to GitHub Desktop, it's likely that you have too many credentials stored in Windows Credentials Manager.

**Workaround:** open the Credential Manager application, click on Windows Credentials and go through the list to see if there are some you can delete.
