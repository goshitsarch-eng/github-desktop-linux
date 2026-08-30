# Application architecture

GitHub Desktop for Linux is a **native Qt 6 + Kirigami** application (`native/`) that preserves the GitHub Desktop feature set. The TypeScript/Electron tree remains as the upstream-compatible behavioral reference.

## Repository map

| Path | Purpose |
| --- | --- |
| `native/` | Qt 6 + Kirigami rewrite (the Linux application) |
| `app/src/main-process/` | Electron main process (legacy reference) |
| `app/src/ui/` | React components (legacy reference) |
| `app/src/lib/` | Shared models, Git operations, API clients, state, and utilities |
| `app/src/cli/` | Implementation behind the packaged `github` helper |
| `app/test/` | Application tests |
| `app/styles/` | SCSS application styles |
| `app/static/` | Shared and platform-specific runtime resources |
| `script/` | Build, test, package, release, and validation scripts |
| `vendor/` | Vendored tools and local packages |
| `docs/` | User and contributor documentation |

## Runtime processes

### Native Qt 6 application

`native/github_desktop/ui/application.py` is a `QApplication` (id
`io.github.desktop.GitHubDesktop`) that loads the QML tree in
`native/github_desktop/ui/qml`. Single-instance behaviour is a `QLocalServer` keyed on
the application id: a second launch hands its argv over that socket and exits, which is
what makes `github open` and the protocol handlers reach the window already on screen. It
handles `x-github-client://`, `x-github-desktop-auth://`, and `x-github-desktop-dev-auth://`
URLs, and dispatches the `github` CLI (`open` / `clone`). Git is invoked as a subprocess
(`native/github_desktop/git/`); GitHub REST and OAuth live in
`native/github_desktop/github/`.

Appearance is System, Light, or Dark. System reads `QStyleHints.colorScheme`, which Plasma,
GNOME and the freedesktop appearance portal all drive, and Kirigami takes its palette from
the platform theme so the app follows the user's Breeze colour scheme.

Tokens go to KWallet over D-Bus, then to the Secret Service via `secret-tool`, then to a
`0600` file (`native/github_desktop/keyring.py`).

#### Layering

| Layer | Where | Responsibility |
| --- | --- | --- |
| Git and GitHub | `github_desktop/git`, `github_desktop/github` | Subprocess and API calls |
| State | `github_desktop/store.py` | One observable store; `emit()` on every change |
| Bridge | `github_desktop/ui/bridge.py` | Store state as QML properties and list models |
| Interface | `github_desktop/ui/qml` | Kirigami views, dialogs, shared components |

Nothing outside `ui/` imports Qt. The store runs unchanged under pytest and in the CLI, and
marshals onto the GUI thread through `github_desktop/mainloop.py` when one exists. The list
models in `ui/models.py` take a fresh snapshot on each store change and diff it, so a
refresh emits `dataChanged` rather than resetting the view and losing selection or scroll
position. Text that a dialog or a diff shows lives in `ui/dialogs.py` and `ui/diff_view.py`
rather than in QML, so the parity tests can read it without a window.

### Legacy Electron (reference)

`app/src/main-process/main.ts` starts Electron, enforces a single application instance, creates windows and menus, registers protocol handlers, dispatches CLI actions, initializes logging, and applies security filters to web requests.

On Linux, protocol URLs are accepted as command-line arguments. Production builds accept `x-github-desktop-auth://` and development builds accept `x-github-desktop-dev-auth://`; both accept `x-github-client://`.

### Renderer

The renderer contains the React user interface, application state, repository models, GitHub API interactions, and user workflows. Communication with privileged main-process functionality uses Electron IPC modules.

### Git and credentials

Git operations are wrapped by modules under `app/src/lib/git/` and executed through `dugite`. Production builds copy dugite's bundled Git into the application. Credential prompts use the Desktop trampoline and credential helper; Linux credential storage uses Secret Service through `keytar`/`libsecret`.

### Command-line helper

`app/src/cli/main.ts` implements `github open` and `github clone`. The shell wrapper in `app/static/linux/github` locates the packaged Electron binary and runs the compiled CLI with `ELECTRON_RUN_AS_NODE=1`.

## Build outputs

Webpack creates main, renderer, crash, syntax-highlighter, and CLI bundles in `out/`. `script/build.ts` then copies static resources and Git, installs runtime dependencies, generates license data, and invokes `electron-packager`. Platform packaging scripts turn the assembled app in `dist/` into release artifacts.

See [Building and packaging](packaging.md) for commands and workflow details.
