#!/usr/bin/env python
"""Print the actions/cache key for the source files: a hash over the input sha256s recorded in
the committed latest silver artifact (ADR-0015 item 2). The landing manifest is git-ignored,
so the committed artifact is the only committed record of what was downloaded.

    python scripts/source_cache_key.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR  # noqa: E402


def main() -> int:
    d = ARTIFACTS_DIR / "silver"
    art = json.loads((d / json.loads((d / "latest.json").read_text())["path"]).read_text())
    joined = "\n".join(f"{k}:{v['sha256']}" for k, v in sorted(art["inputs"].items()))
    print("sources-" + hashlib.sha256(joined.encode()).hexdigest()[:16])
    return 0


if __name__ == "__main__":
    sys.exit(main())
