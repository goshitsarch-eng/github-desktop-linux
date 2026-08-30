"""Qt 6 / Kirigami user interface.

Importing this package must stay cheap and Qt-free: the store pulls
``ui.syntax`` in from worker threads, and the CLI never builds a UI at all.
The Qt entry point lives in :mod:`github_desktop.ui.application`.
"""
