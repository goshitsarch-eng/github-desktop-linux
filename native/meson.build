project('github-desktop',
  version: '3.5.4',
  meson_version: '>= 1.0.0',
)

python = import('python').find_installation('python3')

# The Python package. The Kirigami QML lives inside it (github_desktop/ui/qml)
# and is loaded relative to the module, so there is nothing to install twice.
install_subdir('github_desktop', install_dir: python.get_install_dir())

configure_file(
  input: 'data/io.github.desktop.GitHubDesktop.desktop.in',
  output: 'io.github.desktop.GitHubDesktop.desktop',
  configuration: {
    'bindir': get_option('prefix') / get_option('bindir'),
  },
  install: true,
  install_dir: get_option('datadir') / 'applications',
)

install_data(
  'data/icons/io.github.desktop.GitHubDesktop.svg',
  install_dir: get_option('datadir') / 'icons/hicolor/scalable/apps',
)

install_data('scripts/github-desktop', install_dir: get_option('bindir'), install_mode: 'rwxr-xr-x')
install_data('scripts/github', install_dir: get_option('bindir'), install_mode: 'rwxr-xr-x')

# Register the launcher and the x-github-client:// handler with the session.
# Only the desktop database needs refreshing: the icon is a scalable SVG in
# hicolor, which both Plasma and every other desktop read directly.
meson.add_install_script(
  'sh', '-c',
  'test -n "$DESTDIR" || update-desktop-database -q ' +
  get_option('prefix') / get_option('datadir') / 'applications || true',
)
