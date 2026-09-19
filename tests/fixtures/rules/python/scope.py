"""KLC-108 step-2 fixture (AC-2) — module-scope names beside a function whose
body declares the exact local forms AC-2 names: an assignment target (`out`),
a second assignment target (`d`) and a nested `def helper(): ...` whose own
body declares a THIRD, doubly-nested local (`nested`) — the doubly-nested
case D-001/F-007 say a plain (non-`stopBy: end`) `inside` clause would miss.
"""

MAX_SIZE = 1024


class Config:
    DEFAULT = 1

    def method(self):
        return self.DEFAULT


def run(argv):
    out = []
    d = {}

    def helper():
        nested = 1
        return nested

    out.append(helper())
    return out, d
