"""python -m github_desktop"""

from __future__ import annotations

import os
import sys

# Allow running from a source checkout without installation.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    try:
        from github_desktop.ui.application import run
    except ImportError as exc:  # pragma: no cover - depends on the install
        print(
            f"GitHub Desktop needs PySide6 (Qt 6 for Python): {exc}\n"
            "Install it with your distribution's package manager "
            "(python3-pyside6 on Fedora, python3-pyside6.qtquick on Debian "
            "and Ubuntu, pyside6 on Arch) or with `pip install PySide6`.",
            file=sys.stderr,
        )
        return 1

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
