project('github-desktop',
  version: '3.5.4',
  meson_version: '>= 1.0.0',
)

python = import('python').find_installation('python3')

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
