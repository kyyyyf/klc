#!/usr/bin/env python3
"""fact_verify.py — deprecated shim.

The scope of this skill widened to cover ASSUMPTION and HYPOTHESIS
items as well as FACT. The live implementation is now
`items_verify.py`. This shim re-execs the new name so callers do not
break immediately; it will be removed two releases after the
alignment work lands.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    sys.stderr.write(
        "fact_verify.py is deprecated; use items_verify.py\n"
    )
    target = Path(__file__).with_name("items_verify.py")
    os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
