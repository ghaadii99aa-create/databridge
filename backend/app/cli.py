"""Maintenance commands.

    python -m app.cli seed      # create the shared demo data if missing (idempotent)
    python -m app.cli cleanup   # remove expired visitor data and orphans now
"""
from __future__ import annotations

import json
import sys

from app.db import session_factory


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in ("seed", "cleanup"):
        print(__doc__)
        return 2
    from app.services import demo

    with session_factory()() as session:
        result = demo.seed(session) if args[0] == "seed" else demo.cleanup(session)
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
