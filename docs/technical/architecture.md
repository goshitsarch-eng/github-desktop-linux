# Application architecture

GitHub Desktop for Linux is a **native GTK 4 + libadwaita** application (`native/`) that preserves the GitHub Desktop feature set. The TypeScript/Electron tree remains as the upstream-compatible behavioral reference.

## Repository map

| Path | Purpose |
| --- | --- |
| `native/` | GTK 4 + libadwaita rewrite (the Linux application) |
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

### Native GTK 4 application

`native/github_desktop/ui/application.py` is an `Adw.Application` (id `io.github.desktop.GitHubDesktop`). It is single-instance, handles `x-github-client://`, `x-github-desktop-auth://`, and `x-github-desktop-dev-auth://` URLs, and dispatches the `github` CLI (`open` / `clone`). Appearance is System, Light, or Dark via `Adw.StyleManager`. Git is invoked as a subprocess (`native/github_desktop/git/`). GitHub REST + OAuth live in `native/github_desktop/github/`. Tokens use libsecret with a 0600 file fallback.

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
