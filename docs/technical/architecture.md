# Application architecture

GitHub Desktop for Linux is an Electron application written primarily in TypeScript and React. It retains the cross-platform upstream application and adds Linux build, protocol, CLI, and packaging support.

## Repository map

| Path | Purpose |
| --- | --- |
| `app/src/main-process/` | Electron main process, windows, menus, protocols, updates, and native integration |
| `app/src/ui/` | React components and application views |
| `app/src/lib/` | Shared models, Git operations, API clients, state, and utilities |
| `app/src/cli/` | Implementation behind the packaged `github` helper |
| `app/test/` | Application tests |
| `app/styles/` | SCSS application styles |
| `app/static/` | Shared and platform-specific runtime resources |
| `script/` | Build, test, package, release, and validation scripts |
| `vendor/` | Vendored tools and local packages |
| `docs/` | User and contributor documentation |

## Runtime processes

### Main process

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
