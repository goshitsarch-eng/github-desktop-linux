"""python -m github_desktop"""

from __future__ import annotations

import os
import sys

# Allow running from a source checkout without installation.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    from github_desktop.ui.application import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
