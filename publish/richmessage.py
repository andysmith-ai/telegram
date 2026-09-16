"""Build a Telegram Rich Message (Bot API 10.1) from an English post.

The title becomes a size-1 heading, the Markdown body becomes content blocks
(paragraphs with inline bold/code/italic/links, inline images as photo blocks,
headings, lists, quotes, code fences), and a footer holds the site link as
visible linked text.

Vendored verbatim from sm-th/researcher (publisher/publisher/richmessage.py).
NOTE: image URLs pass through UNCHANGED -- this repo does no image logic (no
screenshot / R2 minting / og:image); whatever URL is in the post file is what
Telegram gets. The upstream producer bakes the final, Telegram-ready image URL
(e.g. the .jpg rendition) into the file.
"""

import re

# A Markdown image `![alt](url)` or a bare <img src="url">. The captured URL is
# whichever group matched.
_IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)|<img[^>]+src=[\"']([^\"']+)[\"']")

# Inline spans, left-to-right: link | bold | code | italic.
_INLINE = re.compile(
    r"\[([^\]]+)\]\(([^)\s]+)\)"            # 1,2  [text](url)
    r"|\*\*([^*]+)\*\*"                      # 3    **bold**
    r"|`([^`]+)`"                            # 4    `code`
    r"|(?<![\w*])\*([^*\n]+)\*(?![\w*])"     # 5    *italic*
)
_HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_LIST = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")
_FENCE = re.compile(r"^```")
_SPACER = " "  # a one-space paragraph renders as a blank line between blocks


def _img_url(m: "re.Match") -> str:
    return m.group(1) or m.group(2)


def _inline_rich(text: str):
    """Inline Markdown -> a RichText value: a plain string when there's no
    formatting, else a list of strings and entity dicts."""
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out.append(text[pos:m.start()])
        if m.group(1) is not None:
            out.append({"type": "url", "text": m.group(1), "url": m.group(2)})
        elif m.group(3) is not None:
            out.append({"type": "bold", "text": m.group(3)})
        elif m.group(4) is not None:
            out.append({"type": "code", "text": m.group(4)})
        else:
            out.append({"type": "italic", "text": m.group(5)})
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    if not out:
        return text
    return out[0] if len(out) == 1 and isinstance(out[0], str) else out


def _para(text: str) -> dict:
    return {"type": "paragraph", "text": _inline_rich(text)}


def _photo(url: str) -> dict:
    return {"type": "photo", "photo": {"type": "photo", "media": url}}


def _footer_block(site_url: str, site_disp: str) -> dict:
    return {"type": "footer", "text": [{"type": "url", "text": site_disp, "url": site_url}]}


def _content_blocks(body: str) -> list:
    """Parse the Markdown body into rich blocks."""
    lines = body.split("\n")
    out: list = []
    buf: list = []
    i, n = 0, len(lines)

    def flush():
        if not buf:
            return
        text = " ".join(s.strip() for s in buf).strip()
        buf.clear()
        if not text:
            return
        last = 0
        for m in _IMG.finditer(text):
            pre = text[last:m.start()].strip()
            if pre:
                out.append(_para(pre))
            out.append(_photo(_img_url(m)))
            last = m.end()
        rest = text[last:].strip()
        if rest:
            out.append(_para(rest))

    while i < n:
        line = lines[i]
        if not line.strip():
            flush(); i += 1; continue
        if _FENCE.match(line.strip()):
            flush()
            lang = line.strip()[3:].strip()
            code = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i]); i += 1
            i += 1
            block = {"type": "pre", "text": "\n".join(code)}
            if lang:
                block["language"] = lang
            out.append(block); continue
        m = _HEAD.match(line)
        if m:
            flush()
            out.append({"type": "heading", "text": _inline_rich(m.group(2).strip()),
                        "size": min(6, len(m.group(1)) + 2)})
            i += 1; continue
        if _QUOTE.match(line):
            flush()
            q = []
            while i < n and _QUOTE.match(lines[i]):
                q.append(_QUOTE.match(lines[i]).group(1)); i += 1
            out.append({"type": "blockquote", "blocks": [_para(" ".join(q).strip())]})
            continue
        if _LIST.match(line):
            flush()
            items = []
            while i < n and _LIST.match(lines[i]):
                items.append(_LIST.match(lines[i]).group(1).strip()); i += 1
            out.append({"type": "list", "items": [{"blocks": [_para(it)]} for it in items]})
            continue
        buf.append(line); i += 1
    flush()
    return out


def _rich_blocks(title: str, body: str, site_url: str, site_disp: str,
                 spacer: bool = True, image_spacer: bool = False) -> list:
    blocks = ([{"type": "heading", "text": title, "size": 1}]
              + _content_blocks(body)
              + [_footer_block(site_url, site_disp)])
    if not spacer:
        return blocks
    spaced = [blocks[0]]
    for prev, b in zip(blocks, blocks[1:]):
        next_to_photo = prev.get("type") == "photo" or b.get("type") == "photo"
        if not next_to_photo or image_spacer:
            spaced.append({"type": "paragraph", "text": _SPACER})
        spaced.append(b)
    return spaced


def _truncate_paragraphs(body: str, budget: int) -> str:
    """Keep whole paragraphs (split on blank lines) up to `budget` chars."""
    paras = re.split(r"\n\s*\n", body)
    kept, total = [], 0
    for p in paras:
        if total + len(p) > budget:
            break
        kept.append(p); total += len(p) + 2
    return "\n\n".join(kept) if kept else body[:budget]


def build(title: str, body: str, site_url: str, max_chars: int = 30000,
          # Telegram spaces paragraphs itself now; the one-space spacer only
          # doubles the gap (ugly empty lines), so it stays off.
          spacer: bool = False) -> dict:
    """Return an InputRichMessage payload {"blocks": [...]} for sendRichMessage."""
    body = body.strip()
    site_disp = re.sub(r"^https?://", "", site_url)
    reserve = len(title) + len(site_disp) + 16
    if len(body) > max(0, max_chars - reserve):
        body = _truncate_paragraphs(body, max(0, max_chars - reserve)).rstrip() + " …"
    return {"blocks": _rich_blocks(title, body, site_url, site_disp, spacer)}


def build_link(title: str, body: str, link_url: str, site_url: str,
               image_url: str | None = None, max_chars: int = 30000) -> dict:
    """Rich message for a link post: title heading, the outbound URL (as the
    caption under the preview image if there is one, else its own line), the
    commentary, then the site footer. Same {"blocks": [...]} shape as build()."""
    body = (body or "").strip()
    reserve = len(title) + len(link_url) + 24
    if len(body) > max(0, max_chars - reserve):
        body = _truncate_paragraphs(body, max(0, max_chars - reserve)).rstrip() + " …"
    site_disp = re.sub(r"^https?://", "", site_url)
    url_rich = {"type": "url", "text": link_url, "url": link_url}
    blocks = [{"type": "heading", "text": title, "size": 1}]
    if image_url:
        blocks.append({"type": "photo",
                       "photo": {"type": "photo", "media": image_url},
                       "caption": {"text": url_rich}})
    else:
        blocks.append({"type": "paragraph", "text": url_rich})
    blocks += _content_blocks(body)
    blocks.append(_footer_block(site_url, site_disp))
    return {"blocks": blocks}
