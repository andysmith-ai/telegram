"""Publish new posts from posts/*.md to the Telegram channel.

WHAT'S IN THE FILE IS WHAT PUBLISHES. No image logic here (screenshots / R2 /
og:image live upstream); the `image:` front-matter is a final URL used verbatim.

Idempotency = a sibling state file per post: posts/<slug>.state.json. CLAIM
BEFORE SEND: each post's state file is written and pushed to git BEFORE the
Telegram call. So a crash or a failed send can only DROP a post, never DUPLICATE
it -- a duplicate storm would spam the channel and earn the bot a ban. We prefer
a missed post over a repeated one; a dropped post is recorded as `status: failed`
and skipped until you remove its sibling state file.

Order: oldest-first (files sort by their date-prefixed name).

Post file  posts/YYYY-MM-DD-<slug>.md :
    ---
    title: "..."            # heading (required)
    site_url: https://...   # footer link back to the source (optional)
    link: https://...       # LINK post: the outbound URL shown at the top (optional)
    image: https://...      # LINK post preview image, final URL, verbatim (optional)
    ---
    <body markdown>

Sibling state file posts/YYYY-MM-DD-<slug>.state.json :
    {"status": "sending"}                  # claim before send
    {"status": "failed", "error": "..."}   # send failed, no auto-retry
    {"message_id": 123, "url": "..."}      # success

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

POSTS = "posts"
ROOT_STATE = "state.json"


def _unquote(v: str) -> str:
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


def parse(path: str) -> tuple[dict, str]:
    """Split `--- front-matter --- body` (flat key: value front-matter)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
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


def state_path(slug: str, root: str = ".") -> str:
    """Sibling state file path for a post slug."""
    return os.path.join(root, POSTS, f"{slug}.state.json")


def load_state(slug: str, root: str = ".") -> dict | None:
    """Load a post's sibling state file, or None if it doesn't exist."""
    path = state_path(slug, root)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _commit_push(msg: str, paths: list[str], max_push_retries: int = 5) -> None:
    """Commit the given paths and push.

    If the push fails because origin advanced since checkout (non-fast-forward),
    fetch and rebase onto origin/main before retrying. This keeps a safely-
    claimed post from being abandoned when parallel producers advance main
    between the workflow checkout and the state commit. Raises on failure (so
    we NEVER send having failed to persist the claim -- a failed claim just
    retries next run).
    """
    subprocess.run(["git", "add", *paths], check=True, capture_output=True, text=True)
    c = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
    if c.returncode != 0:
        if "nothing to commit" in (c.stdout + c.stderr):
            return
        raise RuntimeError(f"git commit failed: {c.stderr.strip()}")

    stderr = ""
    for attempt in range(max_push_retries):
        p = subprocess.run(["git", "push"], capture_output=True, text=True)
        if p.returncode == 0:
            return
        stderr = p.stderr
        err = stderr.lower()
        if "non-fast-forward" in err or "fetch first" in err or "rejected" in err:
            subprocess.run(["git", "fetch", "origin"], check=True,
                           capture_output=True, text=True)
            r = subprocess.run(["git", "rebase", "origin/main"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                subprocess.run(["git", "rebase", "--abort"], check=False,
                               capture_output=True, text=True)
                raise RuntimeError(f"git rebase failed: {r.stderr.strip()}")
            continue
        break
    raise RuntimeError(f"git push failed: {stderr.strip()}")


def save_state(slug: str, record: dict, msg: str, push: bool, root: str = ".") -> None:
    """Write a sibling state file and optionally commit + push it."""
    path = state_path(slug, root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
        f.write("\n")
    if push:
        _commit_push(msg, [path])


def _migrate_root_state(push: bool, root: str = ".") -> None:
    """One-time migration from the legacy root state.json map to sibling files.

    Existing records are copied verbatim, so an already-published post stays
    skipped and never reposts. The legacy file is removed once all entries are
    written to their sibling state files.
    """
    legacy = os.path.join(root, ROOT_STATE)
    if not os.path.exists(legacy):
        return
    with open(legacy, encoding="utf-8") as f:
        state = json.load(f)
    migrated = []
    for slug, record in state.items():
        path = state_path(slug, root)
        if os.path.exists(path):
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
            f.write("\n")
        migrated.append(path)
    os.remove(legacy)
    if push and migrated:
        _commit_push("migrate root state.json to sibling state files [skip ci]",
                     migrated + [legacy])


def _legacy_slugs(root: str = ".") -> set[str]:
    """Return slugs recorded in a legacy root state.json without mutating files."""
    legacy = os.path.join(root, ROOT_STATE)
    if not os.path.exists(legacy):
        return set()
    with open(legacy, encoding="utf-8") as f:
        return set(json.load(f).keys())


def _post_paths(root: str = ".") -> list[str]:
    """All post files, oldest-first. State files are ignored."""
    return sorted(glob.glob(os.path.join(root, POSTS, "*.md")))


def main(argv: list[str] | None = None, root: str = ".") -> int:
    argv = argv if argv is not None else sys.argv[1:]
    dry = "--dry-run" in argv
    push = "--no-push" not in argv
    username = (os.environ.get("TG_USERNAME") or "").strip().lstrip("@") or None
    chat_id = f"@{username}" if username else ""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token and not dry and not username:
        raise RuntimeError("TG_USERNAME is required for Telegram publishing")
    tg = Telegram(token) if (token and not dry) else None

    # Dry-run must not create, delete, or commit anything, but it still needs to
    # treat legacy root state entries as already-published.
    if dry:
        legacy_published = _legacy_slugs(root)
    else:
        legacy_published = set()
        _migrate_root_state(push, root)

    failed = 0
    for path in _post_paths(root):
        slug = slug_of(path)
        if slug in legacy_published or load_state(slug, root) is not None:
            continue
        fm, body = parse(path)
        fm["_path"] = path
        rich = render(fm, body)

        if tg is None:
            print(f"[dry-run] would post {slug}: {len(rich['blocks'])} blocks")
            continue

        # CLAIM FIRST: persist + push before sending. From here a failure can only
        # drop this post (recorded as failed), never duplicate it.
        save_state(slug, {"status": "sending"}, f"claim {slug} [skip ci]", push, root)
        try:
            result = tg.send_rich_message(chat_id, rich, disable_notification=True)
        except TelegramError as e:
            print(f"FAILED {slug}: {e}", file=sys.stderr)
            save_state(slug, {"status": "failed", "error": str(e)[:300]},
                       f"failed {slug} [skip ci]", push, root)
            failed += 1
            continue
        mid = result.get("message_id")
        rec = {"message_id": mid, "url": permalink(chat_id, username, mid)}
        save_state(slug, rec, f"published {slug} [skip ci]", push, root)
        print(f"posted {slug} -> {rec['url']}")

    if failed:
        print(f"{failed} post(s) failed AFTER claim -> dropped, not retried. "
              f"To re-send, delete their sibling state file.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
