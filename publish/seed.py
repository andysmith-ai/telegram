"""Seed state.json so a BACKFILL doesn't re-blast the channel.

Only needed if you drop already-published posts into posts/ (they're already on
the channel from the old Zeno path). Marks every current posts/*.md as published
WITHOUT sending anything. Going forward the repo starts empty and only receives
NEW posts, so in the common case you never need this.

    python publish/seed.py            # mark all current posts/*.md as published
"""

import glob
import json
import os

from publish import slug_of  # reuse the slug rule

STATE = "state.json"
POSTS = "posts"


def main() -> int:
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    n = 0
    for path in sorted(glob.glob(os.path.join(POSTS, "*.md"))):
        slug = slug_of(path)
        if slug not in state:
            state[slug] = {"seeded": True}
            n += 1
    json.dump(state, open(STATE, "w"), indent=2, ensure_ascii=False)
    print(f"seeded {n} post(s) as already-published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
