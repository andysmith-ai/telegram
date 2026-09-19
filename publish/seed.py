"""Seed sibling state files so a BACKFILL doesn't re-blast the channel.

Only needed if you drop already-published posts into posts/ (they're already on
the channel from the old Zeno path). Marks every current posts/*.md as published
WITHOUT sending anything. Going forward the repo starts empty and only receives
NEW posts, so in the common case you never need this.

    python publish/seed.py            # mark all current posts/*.md as published
"""

import glob
import json
import os

from publish import POSTS, slug_of, state_path


def main() -> int:
    n = 0
    for path in sorted(glob.glob(os.path.join(POSTS, "*.md"))):
        slug = slug_of(path)
        sp = state_path(slug)
        if not os.path.exists(sp):
            os.makedirs(os.path.dirname(sp), exist_ok=True)
            with open(sp, "w", encoding="utf-8") as f:
                json.dump({"seeded": True}, f, indent=2, ensure_ascii=False)
                f.write("\n")
            n += 1
    print(f"seeded {n} post(s) as already-published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
