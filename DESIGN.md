# Telegram channel — design & handoff

## What this repo is
The **@andysmith_ai** Telegram channel's post store **plus** its CI publisher.
Push a post into `posts/`; a GitHub Action publishes the ones not yet published
(oldest-first), then commits `state.json`.

**The file is the source of truth: what's in the file is what publishes.** There
is **no image logic in this repo** — no screenshots, no R2 minting, no og:image.
The `image:` field is a final URL used verbatim; the upstream producer bakes the
Telegram-ready image URL into the file.

## Where it sits (the bigger picture)
Part of a **per-platform** social-publishing split:

- **Blog** — `sm-th/andysmith.ai` (11ty). Source of truth, handwritten / translated
  from Zulip `#blog` by the Zeno researcher pipeline (`sm-th/researcher`).
- **Social = one repo per platform** — `andysmith-ai/telegram`, `.../threads`,
  `.../x` — each with its own posts and its own CI publisher.
- **Telegram is 1:1 with the blog FOR NOW** (the English post reposted), but it's a
  standalone repo so it can diverge later.
- **Threads / X hold DIFFERENT posts** — audience-tuned derivatives a future
  "content factory" writes. See each repo's `DESIGN.md`.

## Why publishing moved out of Zeno
Previously Zeno's publisher called the Telegram API directly. Now:
- **The API call moves to CI** (this repo, on push).
- **Zeno becomes a content producer**: it commits the post file here (and the blog
  post to the blog repo) and replies into the Zulip thread with the **commit/PR
  link here** — not the `t.me` URL (only known after CI runs). *(Producer cutover
  is TODO, below.)*

## Post contract — `posts/YYYY-MM-DD-<slug>.md`
```
---
title: "..."             # heading (required)
site_url: https://...    # footer link back to the source (optional)
link: https://...        # LINK post only: the outbound URL shown at the top
image: https://...       # LINK post preview image, FINAL url, verbatim (optional)
---
<body markdown>          # post text; inline body images pass through unchanged too
```
- No `link:` → a normal post (`richmessage.build`): heading + body + footer.
- With `link:` → a link post (`richmessage.build_link`): heading, the URL (as the
  caption under `image:` if present, else its own line), commentary, footer.
- `slug` = the filename without `.md`; it's the `state.json` key and must be stable.

## CI flow (`.github/workflows/publish.yml`)
`on: push` (main, `posts/**`) → `python publish/publish.py`. For each `posts/*.md`
whose slug isn't in `state.json`, **oldest-first**:
1. **claim first** — write the slug to `state.json` and `git commit`+`push` it
   (`[skip ci]`) BEFORE any Telegram call;
2. `sendRichMessage`, then record `{message_id, url}` and push again.
`concurrency: telegram-publish` → never two publishers at once.

**Why claim-first:** a crash or a failed send can then only DROP a post (recorded
`status: failed`, skipped until you delete the entry), never DUPLICATE it — a
duplicate storm would spam the channel and get the bot banned. Prefer a missed
post over a repeated one. (`--dry-run` = no send; `--no-push` = send without git.)

## First run / seed (do NOT re-spam the channel)
The repo starts **empty** → only NEW posts arrive → **no seed needed**. Only if you
**backfill** already-published posts into `posts/` (they're already on the channel
from the old Zeno path) run `python publish/seed.py` first to mark them published
without sending.

## Reuse / provenance
`publish/richmessage.py` + `publish/telegram.py` are vendored **verbatim** from
`sm-th/researcher` (`publisher/publisher/`): the proven Bot API 10.1 rich builder
+ client. **stdlib only** — the workflow needs no `pip install`. Rendering was
verified in that session (headings/paragraphs/links/photos).

## One-time setup
- Repo **secret**: `TELEGRAM_BOT_TOKEN`.
- Repo **variable**: `TG_USERNAME` = `andysmith_ai`; the publisher derives chat id
  `@andysmith_ai` and the public permalink from it.
- The bot must be an **admin** of the channel.

## Local test
```
python publish/publish.py --dry-run     # no token -> prints what it would post
```

## TODO (next session)
- **Producer cutover in Zeno** (`sm-th/researcher`): remove the direct Telegram post
  from `publisher/publisher/__main__.py` (its `richmessage`/`telegram` usage becomes
  dead); instead have the pipeline commit the post file into THIS repo and reply the
  commit/PR link into the Zulip thread. Touch points: `src/publisher/*`,
  `src/boot.clj` (the `on-published` handoff builds the thread reply).
- **Image URL**: decide what the producer bakes into `image:` — the R2 `.jpg`
  rendition once R2 is active (see the researcher's `docs/publisher.md`); until then
  omit it (link posts publish without a photo).
- **Threads / X** publishers — same reconcile+state shape, different platform adapter.
