"""Publish new posts from posts/*.md to the Telegram channel.

WHAT'S IN THE FILE IS WHAT PUBLISHES. No image logic here (screenshots / R2 /
og:image live upstream); the `image:` front-matter is a final URL used verbatim.

Idempotency = state.json (slug -> record). CLAIM BEFORE SEND: each post is written
to state.json and pushed to git BEFORE the Telegram call. So a crash or a failed
send can only DROP a post, never DUPLICATE it -- a duplicate storm would spam the
channel and earn the bot a ban. We prefer a missed post over a repeated one; a
dropped post is recorded as `status: failed` and skipped until you remove it.

Order: oldest-first (files sort by their date-prefixed name).

Post file  posts/YYYY-MM-DD-<slug>.md :
    ---
    title: "..."            # heading (required)
    site_url: https://...   # footer link back to the source (optional)
    link: https://...       # LINK post: the outbound URL shown at the top (optional)
    image: https://...      # LINK post preview image, final URL, verbatim (optional)
    ---
    <body markdown>

Env: TELEGRAM_BOT_TOKEN (secret), TG_USERNAME (public channel username, with or
without `@`). The chat id and public permalink are derived from that one value.
In CI `actions/checkout` provides push creds and the workflow sets the git
identity. Flags: --dry-run (no send), --no-push (send but don't touch git;
local testing only).
"""

import glob
import json
import os
import re
import subprocess
import sys

import richmessage
from telegram import Telegram, TelegramError, permalink

STATE = "state.json"
POSTS = "posts"


def _unquote(v: str) -> str:
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


def parse(path: str) -> tuple[dict, str]:
    """Split `--- front-matter --- body` (flat key: value front-matter)."""
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text.strip()
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            fm[k.strip()] = _unquote(v)
    return fm, m.group(2).strip()


def slug_of(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def render(fm: dict, body: str) -> dict:
    """The file -> a Telegram Rich Message payload. Link post iff `link` is set."""
    title = fm.get("title") or slug_of(fm.get("_path", "post"))
    site_url = fm.get("site_url", "")
    if fm.get("link"):
        return richmessage.build_link(title, body, fm["link"], site_url,
                                      image_url=fm.get("image") or None)
    return richmessage.build(title, body, site_url)


def _commit_push(msg: str) -> None:
    """Commit state.json and push. Raises on failure (so we NEVER send having
    failed to persist the claim -- a failed claim just retries next run)."""
    subprocess.run(["git", "add", STATE], check=True, capture_output=True, text=True)
    c = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
    if c.returncode != 0:
        if "nothing to commit" in (c.stdout + c.stderr):
            return
        raise RuntimeError(f"git commit failed: {c.stderr.strip()}")
    subprocess.run(["git", "push"], check=True, capture_output=True, text=True)


def _save(state: dict, slug: str, record: dict, msg: str, push: bool) -> None:
    state[slug] = record
    json.dump(state, open(STATE, "w"), indent=2, ensure_ascii=False)
    if push:
        _commit_push(msg)


def main() -> int:
    dry = "--dry-run" in sys.argv[1:]
    push = "--no-push" not in sys.argv[1:]
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    username = (os.environ.get("TG_USERNAME") or "").strip().lstrip("@") or None
    chat_id = f"@{username}" if username else ""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token and not dry and not username:
        raise RuntimeError("TG_USERNAME is required for Telegram publishing")
    tg = Telegram(token) if (token and not dry) else None

    failed = 0
    for path in sorted(glob.glob(os.path.join(POSTS, "*.md"))):
        slug = slug_of(path)
        if slug in state:
            continue
        fm, body = parse(path)
        fm["_path"] = path
        rich = render(fm, body)

        if tg is None:
            print(f"[dry-run] would post {slug}: {len(rich['blocks'])} blocks")
            continue

        # CLAIM FIRST: persist + push before sending. From here a failure can only
        # drop this post (recorded as failed), never duplicate it.
        _save(state, slug, {"status": "sending"}, f"claim {slug} [skip ci]", push)
        try:
            result = tg.send_rich_message(chat_id, rich, disable_notification=True)
        except TelegramError as e:
            print(f"FAILED {slug}: {e}", file=sys.stderr)
            _save(state, slug, {"status": "failed", "error": str(e)[:300]},
                  f"failed {slug} [skip ci]", push)
            failed += 1
            continue
        mid = result.get("message_id")
        rec = {"message_id": mid, "url": permalink(chat_id, username, mid)}
        _save(state, slug, rec, f"published {slug} [skip ci]", push)
        print(f"posted {slug} -> {rec['url']}")

    if failed:
        print(f"{failed} post(s) failed AFTER claim -> dropped, not retried. "
              f"To re-send, delete their entries from {STATE}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
