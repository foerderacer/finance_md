"""Allow ``python -m finance_md``."""

from __future__ import annotations

import sys

from finance_md.cli import main

if __name__ == "__main__":
    sys.exit(main())
