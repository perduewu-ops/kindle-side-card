#!/usr/bin/env python3
"""Kindle Side Card PIL renderer.

Design philosophy:
  - ONE font size (28pt body, 28pt bold for headlines)
  - Hierarchy via dividers, inverted bars, spacing, boxes
  - No font-size variation. No glyph gaps.
  - Inspired by Swiss minimalist e-ink dashboards (TRMNL etc.)

Output:
  - 758x1024 grayscale Kindle PIL image for the public daemon path
  - Legacy 540x960 helpers remain where the upstream renderer expects them
"""
from __future__ import annotations
import io
import os
from typing import Iterable, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None

CANVAS_W, CANVAS_H = 540, 960
PADDING = 20
DIVIDER_GRAY = 0x88
INK_BLACK = 0

KINDLE_CANVAS_W, KINDLE_CANVAS_H = 758, 1024

SLOT_RECTS = {
    # v0.6.1: shrunk the top row from 380 → 280 because top widgets only
    # need ~240 px of content; extra read as a weird empty band.
    # v0.6.3: shrunk the bottom row from 340 → 280 to make room for the
    # status/settings bar at the very bottom (60 px tall).
    "top-left":  (0,   0,   270, 280),
    "top-right": (270, 0,   270, 280),
    "middle":    (0,   280, 540, 340),
    "bottom":    (0,   620, 540, 280),
    "full":      (0,   0,   540, 960),
}

KINDLE_SLOT_RECTS = {
    "top-left":  (24,  0,   332, 280),
    "top-right": (403, 0,   333, 280),
    "main":      (24,  288, 710, 666),
    "middle":    (24,  288, 710, 320),
    "bottom":    (24,  628, 710, 326),
    "full":      (0,   0,   758, 1024),
}

# Bottom status/settings bar — inverted black strip at the very bottom of
# the canvas. Left side = passive status (USB / BLE / time). Right side
# = action chips (refresh / sleep / restart) — visually styled as
# tappable, touch dispatch is wired in v0.6.4.
BOTTOM_BAR_Y = 900
BOTTOM_BAR_H = 60
KINDLE_BOTTOM_BAR_Y = 954
KINDLE_BOTTOM_BAR_H = 70

# Set by paint_bottom_bar() on every render. Daemon's touch dispatcher
# reads via get_bottom_bar_hot_zones() so finger taps map to actions.
# Shape: [{"rect": (x0,y0,x1,y1), "action": "sleep"|"settings"|...}]
LAST_BOTTOM_BAR_HOT_ZONES: list = []

def get_bottom_bar_hot_zones() -> list:
    return list(LAST_BOTTOM_BAR_HOT_ZONES)

# ---- font ---------------------------------------------------------------

# Try macOS system fonts first (PingFang has CJK + Latin-1 + box drawing).
# Falls back to whatever's available.
_FONT_PATHS_REGULAR = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]
_FONT_PATHS_BOLD = [
    "/System/Library/Fonts/PingFang.ttc",   # bold via index
    "/System/Library/Fonts/STHeiti Medium.ttc",
]

BODY_SIZE = 28

_font_cache: dict = {}

def font(bold: bool = False):
    """Return the single-size font. v0.6 design decision: one size, period."""
    key = ("bold" if bold else "regular", BODY_SIZE)
    if key in _font_cache:
        return _font_cache[key]
    paths = _FONT_PATHS_BOLD if bold else _FONT_PATHS_REGULAR
    for p in paths:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, BODY_SIZE, index=1 if bold else 0)
                _font_cache[key] = f
                return f
            except Exception:
                continue
    f = ImageFont.load_default()
    _font_cache[key] = f
    return f


# Status/settings bar font — 22 pt. The "one font size" rule applies to
# widget BODY content; the bar is infrastructure chrome (status + action
# chips) and reads cleanest at a smaller-than-body size so left + right
# zones fit without colliding at 540 px wide.
def font_bar():
    key = ("bar", 22)
    if key in _font_cache:
        return _font_cache[key]
    for p in _FONT_PATHS_REGULAR:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, 22, index=0)
                _font_cache[key] = f
                return f
            except Exception:
                continue
    return font()


def font_bar_bold():
    key = ("bar-bold", 22)
    if key in _font_cache:
        return _font_cache[key]
    for p in _FONT_PATHS_BOLD:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, 22, index=1)
                _font_cache[key] = f
                return f
            except Exception:
                continue
    return font(bold=True)


def font_quota_percent():
    key = ("quota-percent", 24)
    if key in _font_cache:
        return _font_cache[key]
    for p in _FONT_PATHS_BOLD:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, 24, index=1)
                _font_cache[key] = f
                return f
            except Exception:
                continue
    return font(bold=True)


# A slightly larger font is only used for ONE thing — the inverted bar's
# type label, which should be assertive. Same rule otherwise.
def font_header():
    key = ("header", 32)
    if key in _font_cache:
        return _font_cache[key]
    for p in _FONT_PATHS_BOLD:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, 32, index=1)
                _font_cache[key] = f
                return f
            except Exception:
                continue
    return font(bold=True)


_DENSE_FONT_PATHS_REGULAR = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Menlo.ttc",
    "/Library/Fonts/Menlo.ttc",
    *_FONT_PATHS_REGULAR,
]
_DENSE_FONT_PATHS_BOLD = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Menlo.ttc",
    "/Library/Fonts/Menlo.ttc",
    *_FONT_PATHS_BOLD,
]


def font_dense(size: int = 13, bold: bool = False):
    key = ("dense-bold" if bold else "dense", size)
    if key in _font_cache:
        return _font_cache[key]
    paths = _DENSE_FONT_PATHS_BOLD if bold else _DENSE_FONT_PATHS_REGULAR
    for p in paths:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, size, index=1 if bold else 0)
                _font_cache[key] = f
                return f
            except Exception:
                continue
    f = ImageFont.load_default()
    _font_cache[key] = f
    return f


# ---- design primitives --------------------------------------------------

def header_bar(d: ImageDraw.ImageDraw, rect, label: str, meta: str = ""):
    """Minimal header: black label text on white + a thin horizontal rule.

    v0.6.1 update: dropped the inverted-bar design — on the middle and
    bottom widgets, which span full canvas width, the inverted bar read
    as a heavy horizontal section divider (the 'horizontal black bars'
    we removed earlier kept reappearing because they were the widget
    headers themselves). This lighter treatment keeps the type label
    visible without the section-divider look."""
    x, y, w, h = rect
    bar_h = 52
    # Label on white background (black text).
    d.text((x + PADDING, y + 14), label.upper(),
           fill=INK_BLACK, font=font_header())
    if meta:
        meta_bbox = d.textbbox((0, 0), meta, font=font())
        meta_w = meta_bbox[2] - meta_bbox[0]
        d.text((x + w - PADDING - meta_w, y + 18), meta,
               fill=DIVIDER_GRAY, font=font())
    # Thin underline (3 px) — gives the label visual weight without a
    # full inverted block.
    d.rectangle((x + PADDING, y + bar_h - 3, x + w - PADDING, y + bar_h),
                fill=INK_BLACK)
    return y + bar_h


def divider(d: ImageDraw.ImageDraw, x1, y, x2, weight: int = 1, gray: int = DIVIDER_GRAY):
    """Horizontal divider. weight 1 = subtle, 2-3 = stronger."""
    for w in range(weight):
        d.line((x1, y + w, x2, y + w), fill=gray)


def body_text(d, x, y, max_w: int, text: str, bold: bool = False) -> int:
    """Draw single line of body text, return next-y. Auto-truncate with '...'
    if too wide. No font-size shrinking (v0.6 single-size rule)."""
    if not text:
        return y
    f = font(bold)
    # Truncate to width.
    truncated = text
    if d.textlength(text, font=f) > max_w:
        while truncated and d.textlength(truncated + "...", font=f) > max_w:
            # Strip one char at a time (UTF-8 aware via Python string).
            truncated = truncated[:-1]
        truncated = (truncated + "...") if truncated != text else text
    d.text((x, y), truncated, fill=INK_BLACK, font=f)
    return y + BODY_SIZE + 8


def wrapped_text(d, x, y, max_w: int, max_h: int, text: str) -> int:
    """Multi-line wrap. Word-aware (preserves Latin word boundaries),
    falls back to per-codepoint for CJK runs. Truncate last visible line
    with '...' if overflows max_h."""
    if not text:
        return y
    f = font()
    line_h = BODY_SIZE + 8

    # Tokenise into atoms we won't break across lines.
    atoms = []
    buf = ""
    def flush():
        nonlocal buf
        if buf: atoms.append(buf); buf = ""
    for ch in text:
        if ch == "\n":
            flush(); atoms.append("\n")
        elif ch.isspace():
            flush(); atoms.append(ch)
        elif ord(ch) >= 0x2E80:    # CJK + fullwidth — break per codepoint
            flush(); atoms.append(ch)
        else:
            buf += ch
    flush()

    lines = []
    cur = ""
    for atom in atoms:
        if atom == "\n":
            lines.append(cur.rstrip()); cur = ""
            continue
        trial = cur + atom
        if d.textlength(trial, font=f) > max_w:
            if cur.strip():
                lines.append(cur.rstrip())
                cur = atom.lstrip()
                # Fallback for atoms that are themselves wider than the
                # line (super-long Latin words) — char-split that atom.
                while cur and d.textlength(cur, font=f) > max_w:
                    lo, hi = 1, len(cur)
                    while lo < hi:
                        mid = (lo + hi + 1) // 2
                        if d.textlength(cur[:mid], font=f) <= max_w:
                            lo = mid
                        else:
                            hi = mid - 1
                    lines.append(cur[:lo])
                    cur = cur[lo:]
            else:
                cur = atom
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.rstrip())

    max_lines = max_h // line_h
    if max_lines < 1: max_lines = 1
    if len(lines) > max_lines:
        last = lines[max_lines - 1]
        while last and d.textlength(last + "...", font=f) > max_w:
            last = last[:-1]
        lines = lines[:max_lines - 1] + [last + "..."]

    for i, line in enumerate(lines):
        d.text((x, y + i * line_h), line, fill=INK_BLACK, font=f)
    return y + len(lines) * line_h


# ---- per-widget painters ------------------------------------------------

def _resolve_widget(slot_name, widget_snapshot):
    for w in widget_snapshot:
        if w.get("slot") == slot_name:
            return w
    return None


def paint_weather(d, rect, data, stale=False):
    x, y, w, h = rect
    next_y = header_bar(d, rect, "WEATHER", data.get("location", "") or "")
    next_y += PADDING

    cur = data.get("current") or {}
    if cur:
        # Combine temp + condition into one line (single-size design — no
        # huge headline, but use bold to emphasise).
        temp = cur.get("temp_c")
        cond = cur.get("condition", "")
        if temp is not None:
            line = f"{temp}°  {cond}".strip()
        else:
            line = cond
        next_y = body_text(d, x + PADDING, next_y, w - 2 * PADDING, line, bold=True)
        next_y += 8

    divider(d, x + PADDING, next_y, x + w - PADDING)
    next_y += 12

    for f in (data.get("forecast") or [])[:2]:
        line = f"{f.get('day','')}  {f.get('high','-')}° / {f.get('low','-')}°  {f.get('condition','')}"
        next_y = body_text(d, x + PADDING, next_y, w - 2 * PADDING, line.strip())


def paint_todo(d, rect, data, stale=False):
    x, y, w, h = rect
    title = data.get("title") or ""
    next_y = header_bar(d, rect, "TODO", title)
    next_y += PADDING
    for it in (data.get("items") or [])[:3]:   # tighter cap with single size
        tag = it.get("tag", "")
        if tag == "overdue":    prefix = "▪"
        elif tag == "today":    prefix = "▶"
        else:                   prefix = "□"
        line = f"{prefix}  {it.get('text','')}"
        next_y = body_text(d, x + PADDING, next_y, w - 2 * PADDING, line, bold=(tag in ("today", "overdue")))


def paint_page_placeholder(d, rect, data, stale=False):
    x, y, w, h = rect
    title = data.get("title") or "PAGE"
    meta = data.get("meta") or ""
    next_y = header_bar(d, rect, title, meta)
    next_y += PADDING
    body = data.get("body") or ""
    if body:
        next_y = wrapped_text(d, x + PADDING, next_y, w - 2 * PADDING, h // 3, body)
        next_y += 20

    label = data.get("label") or title
    f_b = font_header()
    bbox = d.textbbox((0, 0), label, font=f_b)
    label_w = bbox[2] - bbox[0]
    label_h = bbox[3] - bbox[1]
    box_x0 = x + PADDING
    box_x1 = x + w - PADDING
    box_h = 94
    box_y0 = max(next_y + 20, y + (h - box_h) // 2)
    d.rectangle((box_x0, box_y0, box_x1, box_y0 + box_h), outline=INK_BLACK, width=3)
    d.text((box_x0 + (box_x1 - box_x0 - label_w) // 2,
            box_y0 + (box_h - label_h) // 2 - bbox[1]),
           label, fill=INK_BLACK, font=f_b)


def _dense_truncate(d, text: str, max_w: int, fnt) -> str:
    text = str(text or "")
    if d.textlength(text, font=fnt) <= max_w:
        return text
    out = text
    while out and d.textlength(out + "...", font=fnt) > max_w:
        out = out[:-1]
    return (out + "...") if out else "..."


def _dark_page_header(d, rect, title: str, meta: str = "") -> int:
    x, y, w, h = rect
    d.rectangle((x, y, x + w, y + h), fill=INK_BLACK)
    d.text((x, y + 6), title.upper(), fill=255,
           font=font_dense(28, bold=True))
    if meta:
        f_meta = font_dense(10)
        meta_w = d.textlength(meta, font=f_meta)
        d.text((x + w - meta_w, y + 18), meta, fill=160, font=f_meta)
    d.line((x, y + 43, x + w, y + 43), fill=58, width=1)
    return y + 60


def _dark_text(d, x: int, y: int, text: str, fill: int = 238,
               size: int = 13, bold: bool = False, anchor=None) -> None:
    d.text((x, y), str(text or ""), fill=fill,
           font=font_dense(size, bold=bold), anchor=anchor)


def _dark_chip(d, x: int, y: int, text: str, kind: str,
               w: int = 62, h: int = 18) -> None:
    text = str(text or "")
    hot = kind in {"ERR", "STALE", "BLOCK"}
    muted = kind in {"NO ROW", "OFF", "SKIP", "OLD"}
    if hot:
        d.rectangle((x, y, x + w, y + h), fill=255, outline=255)
        fill = 0
    else:
        d.rectangle((x, y, x + w, y + h), outline=150 if muted else 220)
        fill = 165 if muted else 238
    _dark_text(d, x + w - 5, y + 3, text, fill=fill, size=10,
               bold=True, anchor="ra")


def paint_todo_dashboard(d, rect, data, stale=False):
    x, y, w, h = rect
    active = data.get("active_count", 0)
    parsed_at = data.get("parsed_at") or ""

    d.rectangle((x, y, x + w, y + h), fill=255)

    f_title = font_dense(38, bold=True)
    f_meta = font_dense(24, bold=True)
    f_sum = font_dense(24, bold=True)
    f_task = font_dense(24, bold=True)
    f_detail = font_dense(24)

    def text_w(text, fnt=f_task):
        return d.textlength(str(text or ""), font=fnt)

    def clip(text, max_w, fnt=f_task):
        return _dense_truncate(d, text, max_w, fnt)

    def draw_text(tx, ty, text, fnt=f_task, fill=0, anchor=None):
        d.text((tx, ty), str(text or ""), font=fnt, fill=fill, anchor=anchor)

    draw_text(x, y + 9, "TODO", f_title)
    meta = f"{active} Active Tasks" if active else parsed_at
    if meta:
        draw_text(x + w, y + 22, meta, f_meta, anchor="ra")
    d.line((x, y + 70, x + w, y + 70), fill=0, width=4)
    next_y = y + 92

    if data.get("error"):
        draw_text(x, next_y, "TODO PARSE ERR", f_task)
        draw_text(x, next_y + 38, clip(data.get("error"), w, f_detail), f_detail)
        return

    counts = data.get("counts") or {}
    priorities = data.get("priorities") or {}
    cols = [x, x + 160, x + 360, x + 530]
    col_widths = [150, 190, 160, 180]
    row1 = [
        f"{counts.get('blocked', 0)} BLOCKED",
        f"{counts.get('running', 0)} IN PROGRESS",
        f"{counts.get('partial', 0)} PARTIAL",
        f"{counts.get('pending', 0)} PENDING",
    ]
    row2 = [
        f"{priorities.get('P0', 0)} P0",
        f"{priorities.get('P1', 0)} P1",
        f"{priorities.get('P2', 0)} P2",
        f"{priorities.get('P3', 0)} P3",
    ]
    for cx, max_w, value in zip(cols, col_widths, row1):
        draw_text(cx, next_y, clip(value, max_w, f_sum), f_sum)
    next_y += 38
    for cx, max_w, value in zip(cols, col_widths, row2):
        draw_text(cx, next_y, clip(value, max_w, f_sum), f_sum)
    next_y += 47
    d.line((x, next_y, x + w, next_y), fill=0, width=2)
    next_y += 16

    row_h = 84
    state_w = 124
    for task in (data.get("tasks") or [])[:5]:
        task_id = f"#{task.get('id', '')}"
        state = f"{task.get('priority', '')} {task.get('state', '')}".strip()
        title_x = x + 72
        state_x = x + w - state_w
        title = clip(task.get("title") or "", state_x - title_x - 14, f_task)
        nxt = clip(f"Next: {task.get('next', '')}", w - 72, f_detail)

        draw_text(x, next_y + 5, task_id, f_task)
        draw_text(title_x, next_y + 5, title, f_task)

        hot = task.get("state") in {"BLOCK", "PAUSE"}
        if hot:
            d.rectangle((state_x, next_y, x + w, next_y + 37), fill=0, outline=0)
            draw_text(x + w - 8, next_y + 5, state, f_task, fill=255, anchor="ra")
        else:
            d.rectangle((state_x, next_y, x + w, next_y + 37), outline=0, width=2)
            draw_text(x + w - 8, next_y + 5, state, f_task, fill=0, anchor="ra")

        draw_text(title_x, next_y + 45, nxt, f_detail)
        d.line((x, next_y + row_h - 7, x + w, next_y + row_h - 7),
               fill=170, width=1)
        next_y += row_h
        if next_y > y + h - 72:
            break


def paint_agent_live_map(d, rect, data, stale=False):
    x, y, w, h = rect
    lanes = data.get("lanes") or []
    summary = data.get("summary") or {}

    if w >= 740 and h >= 980:
        d.rectangle((x, y, x + w, y + h), fill=255)

        f_title = font_dense(38, bold=True)
        f_meta = font_dense(26, bold=True)
        f_group = font_dense(25, bold=True)
        f_cell = font_dense(24, bold=True)
        f_sum = font_dense(25, bold=True)

        def draw_text(tx, ty, text, fnt=f_cell, fill=0, anchor=None):
            d.text((tx, ty), str(text or ""), font=fnt, fill=fill, anchor=anchor)

        def text_w(text, fnt=f_cell):
            return d.textlength(str(text or ""), font=fnt)

        def clip(text, max_w, fnt=f_cell):
            text = str(text or "")
            if text_w(text, fnt) <= max_w:
                return text
            out = text
            while out and text_w(out, fnt) > max_w:
                out = out[:-1]
            return out

        def status_label(status):
            status = str(status or "NO ROW")
            return "NO" if status == "NO ROW" else status

        margin = 24
        draw_text(x + margin, y + 24, "LIVE AGENTS", f_title)
        draw_text(
            x + w - margin,
            y + 36,
            f"{summary.get('slots', 0)} SLOTS / {summary.get('loaded', 0)} LOADED",
            f_meta,
            anchor="ra",
        )
        d.line((x + margin, y + 79, x + w - margin, y + 79),
               fill=0, width=4)

        cell_w = 222
        cell_h = 37
        gap_x = 10
        start_y = y + 98
        lane_h = 112

        def draw_cell(cx: int, cy: int, name: str, status: str) -> None:
            raw_status = str(status or "NO ROW")
            shown = status_label(raw_status)
            hot = raw_status in {"ERR", "STALE"}
            if hot:
                d.rectangle((cx, cy, cx + cell_w, cy + cell_h),
                            fill=0, outline=0)
                fill = 255
            else:
                d.rectangle((cx, cy, cx + cell_w, cy + cell_h),
                            outline=0, width=2)
                if raw_status in {"NO ROW", "OFF"}:
                    d.rectangle((cx, cy, cx + 8, cy + cell_h), fill=0)
                fill = 0
            sw = text_w(shown, f_cell)
            draw_text(cx + 13, cy + 4,
                      clip(name, cell_w - sw - 26, f_cell),
                      f_cell, fill=fill)
            draw_text(cx + cell_w - 10, cy + 4, shown, f_cell,
                      fill=fill, anchor="ra")

        for lane_idx, lane in enumerate(lanes[:7]):
            lane_y = start_y + lane_idx * lane_h
            draw_text(x + margin, lane_y, lane.get("label") or "", f_group)
            d.line((x + 150, lane_y + 18, x + w - margin, lane_y + 18),
                   fill=0, width=2)
            for i, item in enumerate((lane.get("items") or [])[:6]):
                row = i // 3
                col = i % 3
                draw_cell(
                    x + margin + col * (cell_w + gap_x),
                    lane_y + 32 + row * 41,
                    item.get("name") or "",
                    item.get("status") or "",
                )

        summary_y = y + 894
        d.line((x + margin, summary_y, x + w - margin, summary_y),
               fill=0, width=4)
        draw_text(x + margin, summary_y + 20, "SUMMARY", f_group)
        cols = [x + 24, x + 204, x + 390, x + 574]
        row_a = [
            f"{summary.get('slots', 0)} SLOTS",
            f"{summary.get('loaded', 0)} LOADED",
            f"{summary.get('ok', 0)} OK",
            f"{summary.get('err', 0)} ERR",
        ]
        row_b = [
            f"{summary.get('no_row', 0)} NO ROW",
            f"{summary.get('off', 0)} OFF",
            f"{summary.get('skip', 0)} SKIP",
            f"{summary.get('queue', 0)} QUEUE",
        ]
        for cx, value in zip(cols, row_a):
            draw_text(cx, summary_y + 62, value, f_sum)
        for cx, value in zip(cols, row_b):
            draw_text(cx, summary_y + 102, value, f_sum)
        return

    next_y = _dark_page_header(
        d,
        rect,
        "LIVE AGENTS",
        data.get("meta") or "fixed map",
    )
    _dark_text(
        d, x, next_y - 17,
        "Every slot stays fixed. Problems are reversed; coverage gaps stay dim.",
        fill=160,
        size=9,
    )

    cell_w = 174
    cell_h = 21
    gap = 8
    x0 = x + 108
    lane_h = 68

    def draw_compact_cell(cx: int, cy: int, name: str, status: str) -> None:
        status = str(status or "NO ROW")
        problem = status in {"ERR", "STALE"}
        gap_state = status in {"NO ROW", "OFF"}
        if problem:
            d.rectangle((cx, cy, cx + cell_w, cy + cell_h), fill=255, outline=255)
            fill = 0
        else:
            d.rectangle((cx, cy, cx + cell_w, cy + cell_h),
                        outline=210 if not gap_state else 135)
            fill = 238 if not gap_state else 160
        _dark_text(d, cx + 5, cy + 4,
                   _dense_truncate(d, name, 105, font_dense(10)),
                   fill=fill, size=10)
        _dark_text(d, cx + cell_w - 5, cy + 4, status,
                   fill=fill, size=10, bold=True, anchor="ra")

    for lane in lanes[:7]:
        label = lane.get("label") or ""
        d.rectangle((x - 8, next_y - 5, x + w + 8, next_y + 59), outline=34)
        _dark_text(d, x + 3, next_y + 22, label, fill=255, size=13, bold=True)
        for i, item in enumerate((lane.get("items") or [])[:6]):
            row = i // 3
            col = i % 3
            draw_compact_cell(
                x0 + col * (cell_w + gap),
                next_y + 6 + row * 28,
                item.get("name") or "",
                item.get("status") or "",
            )
        next_y += lane_h

    summary_y = y + h - 100
    d.line((x, summary_y, x + w, summary_y), fill=58, width=1)
    _dark_text(d, x, summary_y + 13, "SUMMARY", fill=255, size=13, bold=True)
    summary = data.get("summary") or {}
    row_a = [
        f"{summary.get('slots', 0)} SLOTS",
        f"{summary.get('loaded', 0)} LOADED",
        f"{summary.get('ok', 0)} OK",
        f"{summary.get('err', 0)} ERR",
        f"{summary.get('stale', 0)} STALE",
        f"{summary.get('no_row', 0)} NO ROW",
    ]
    row_b = [
        f"{summary.get('off', 0)} OFF",
        f"{summary.get('old', 0)} OLD",
        f"{summary.get('skip', 0)} SKIP",
        f"{summary.get('queue', 0)} QUEUE",
        f"{summary.get('alerts_24h', 0)} ALERTS",
        f"{summary.get('ledger', 0)} LEDGER",
    ]
    sx = [x, x + 114, x + 228, x + 342, x + 456, x + 574]
    for cx, value in zip(sx, row_a):
        _dark_text(d, cx, summary_y + 40, value, fill=238, size=12, bold=True)
    for cx, value in zip(sx, row_b):
        _dark_text(d, cx, summary_y + 63, value, fill=160, size=12, bold=True)


def paint_calendar(d, rect, data, stale=False):
    x, y, w, h = rect
    now_iso = data.get("now_iso") or ""
    meta = now_iso[11:16] if len(now_iso) >= 16 else ""
    next_y = header_bar(d, rect, "TODAY", meta)
    next_y += PADDING
    for ev in (data.get("events") or [])[:3]:
        line = f"{ev.get('start','')}   {ev.get('title','')}"
        next_y = body_text(d, x + PADDING, next_y, w - 2 * PADDING, line.strip())


def paint_messages(d, rect, data, stale=False):
    x, y, w, h = rect
    next_y = header_bar(d, rect, "MESSAGES")
    next_y += PADDING - 4
    for m in (data.get("items") or [])[:2]:
        sender = m.get("sender", "")
        preview = m.get("preview", "")
        age = m.get("age", "")
        # sender + age share one line (bold sender, age right-aligned)
        f_bold = font(bold=True)
        d.text((x + PADDING, next_y), sender, fill=INK_BLACK, font=f_bold)
        if age:
            age_w = d.textlength(age, font=font())
            d.text((x + w - PADDING - age_w, next_y + 4), age, fill=DIVIDER_GRAY, font=font())
        next_y += BODY_SIZE + 6
        next_y = body_text(d, x + PADDING, next_y, w - 2 * PADDING, preview)
        divider(d, x + PADDING, next_y + 2, x + w - PADDING)
        next_y += 16


def paint_ai_status(d, rect, data, stale=False):
    x, y, w, h = rect
    session = data.get("session_name", "")
    next_y = header_bar(d, rect, "AI", session)
    next_y += PADDING

    model = data.get("model", "")
    if model:
        next_y = body_text(d, x + PADDING, next_y, w - 2 * PADDING, model, bold=True)

    task = data.get("task", "")
    if task:
        next_y = wrapped_text(d, x + PADDING, next_y, w - 2 * PADDING, BODY_SIZE * 2 + 16, task)
        next_y += 8

    ctx = data.get("context") or {}
    if ctx.get("limit"):
        used, lim = ctx.get("used", 0), ctx["limit"]
        # Inline progress bar.
        bar_y = next_y
        bar_w = w - 2 * PADDING
        d.rectangle((x + PADDING, bar_y, x + PADDING + bar_w, bar_y + 12),
                    outline=INK_BLACK, width=1)
        fill = max(1, min(bar_w, int(bar_w * used / lim))) if used > 0 else 0
        if fill:
            d.rectangle((x + PADDING, bar_y, x + PADDING + fill, bar_y + 12),
                        fill=INK_BLACK)
        next_y = bar_y + 24
        body_text(d, x + PADDING, next_y, w - 2 * PADDING,
                  f"ctx {used // 1000}K / {lim // 1000}K")


def paint_ai_tasks(d, rect, data, stale=False):
    x, y, w, h = rect
    next_y = header_bar(d, rect, "SESSIONS")
    next_y += 12

    cells = [
        (data.get("running", 0), "running"),
        (data.get("waiting", 0), "waiting"),
        (data.get("blocked", 0), "blocked"),
        (data.get("completed_today", 0), "done today"),
    ]
    f_b = font(bold=True)
    f_l = font()
    if w < 350:
        # Narrow slot — stack vertically. Black number box on left + label.
        row_h = (h - (next_y - y) - 20) // 4
        row_h = max(min(row_h, 60), 48)
        box_size = min(row_h - 10, 50)
        for i, (n, label) in enumerate(cells):
            ry = next_y + i * row_h
            # Black number box.
            d.rectangle((x + PADDING, ry, x + PADDING + box_size, ry + box_size),
                        fill=INK_BLACK)
            n_str = str(n)
            n_bbox = d.textbbox((0, 0), n_str, font=f_b)
            nw, nh = n_bbox[2] - n_bbox[0], n_bbox[3] - n_bbox[1]
            d.text((x + PADDING + (box_size - nw) // 2,
                    ry + (box_size - nh) // 2 - 2),
                   n_str, fill=255, font=f_b)
            d.text((x + PADDING + box_size + 16, ry + (box_size - BODY_SIZE) // 2),
                   label, fill=INK_BLACK, font=f_l)
    else:
        cell_w = (w - 3 * PADDING) // 2
        cell_h = 90
        for i, (n, label) in enumerate(cells):
            row, col = i // 2, i % 2
            cx = x + PADDING + col * (cell_w + PADDING)
            cy = next_y + row * (cell_h + 8)
            d.rectangle((cx, cy, cx + 60, cy + 50), fill=INK_BLACK)
            n_str = str(n)
            n_bbox = d.textbbox((0, 0), n_str, font=f_b)
            n_w = n_bbox[2] - n_bbox[0]
            d.text((cx + 30 - n_w // 2, cy + 8), n_str, fill=255, font=f_b)
            d.text((cx + 72, cy + 12), label, fill=INK_BLACK, font=f_l)


# v0.5.1 widget types

def paint_scratch(d, rect, data, stale=False):
    x, y, w, h = rect
    source = data.get("source") or ""
    age = data.get("age") or ""
    meta = f"{source} · {age}".strip(" ·") if source or age else ""
    next_y = header_bar(d, rect, "NOTE", meta)
    next_y += PADDING
    text = data.get("text") or ""
    body_h = h - (next_y - y) - PADDING
    wrapped_text(d, x + PADDING, next_y, w - 2 * PADDING, body_h, text)


def paint_focus(d, rect, data, stale=False):
    x, y, w, h = rect
    next_y = header_bar(d, rect, "FOCUS")
    next_y += 12

    task = data.get("task", "")
    if task:
        next_y = wrapped_text(d, x + PADDING, next_y,
                              w - 2 * PADDING, BODY_SIZE * 2 + 8, task)
        next_y += 8

    big = data.get("big_text", "")
    if big:
        box_w = w - 2 * PADDING
        # Narrower slot → shorter box so we leave room for subtitle + dots
        # without overlapping.
        box_h = 56 if w < 350 else 64
        d.rectangle((x + PADDING, next_y, x + PADDING + box_w, next_y + box_h),
                    outline=INK_BLACK, width=2)
        f_b = font(bold=True)
        bbox = d.textbbox((0, 0), big, font=f_b)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text((x + PADDING + (box_w - tw) // 2, next_y + (box_h - th) // 2 - 4),
               big, fill=INK_BLACK, font=f_b)
        next_y += box_h + 10

    # Subtitle on its OWN line — no longer split with dots (which would
    # overlap on the narrow 270 px top slot).
    subtitle = data.get("subtitle", "")
    if subtitle:
        body_text(d, x + PADDING, next_y, w - 2 * PADDING, subtitle)
        next_y += BODY_SIZE + 6

    # Pomodoro dots on their OWN line below subtitle.
    done = data.get("pomodoros_done", 0)
    planned = data.get("pomodoros_planned", 0)
    if planned:
        dot_str = " ".join(["●" if i < done else "○" for i in range(min(planned, 8))])
        d.text((x + PADDING, next_y), dot_str, fill=DIVIDER_GRAY, font=font())


def paint_now_playing(d, rect, data, stale=False):
    x, y, w, h = rect
    source = data.get("source", "")
    next_y = header_bar(d, rect, "PLAYING", source)
    next_y += 12

    track = data.get("track", "")
    artist = data.get("artist", "")
    # Track may need 2 lines on narrow slots. Use wrapped_text instead of
    # body_text so long titles don't get aggressively "..."-truncated.
    if track:
        max_lines_h = (BODY_SIZE + 8) * 2
        next_y = wrapped_text(d, x + PADDING, next_y,
                              w - 2 * PADDING, max_lines_h, track)
        next_y += 4
    if artist:
        next_y = body_text(d, x + PADDING, next_y, w - 2 * PADDING, artist)
    next_y += 8

    # Progress bar.
    pos = data.get("position_sec", 0)
    dur = data.get("duration_sec", 0)
    bar_w = w - 2 * PADDING
    d.rectangle((x + PADDING, next_y, x + PADDING + bar_w, next_y + 10),
                outline=INK_BLACK, width=1)
    if dur > 0:
        fill = max(1, min(bar_w, int(bar_w * pos / dur))) if pos > 0 else 0
        if fill:
            d.rectangle((x + PADDING, next_y, x + PADDING + fill, next_y + 10), fill=INK_BLACK)
    next_y += 22
    def mmss(s): return f"{s // 60}:{s % 60:02d}"
    # Drop the play/pause glyph on narrow slots to avoid the "▶ ..." ellipsis.
    if w < 350:
        body_text(d, x + PADDING, next_y, w - 2 * PADDING, f"{mmss(pos)} / {mmss(dur)}")
    else:
        state = "▶ playing" if data.get("playing", True) else "❚❚ paused"
        body_text(d, x + PADDING, next_y, w - 2 * PADDING,
                  f"{mmss(pos)} / {mmss(dur)}   {state}")


def paint_git_status(d, rect, data, stale=False):
    x, y, w, h = rect
    repo = data.get("repo_name", "") or ""
    next_y = header_bar(d, rect, "GIT", repo)
    next_y += PADDING - 4

    branch = data.get("branch", "") or "(detached)"
    # Box around branch — single-size design means we lean on the box for emphasis.
    box_w = w - 2 * PADDING
    box_h = 50
    d.rectangle((x + PADDING, next_y, x + PADDING + box_w, next_y + box_h),
                outline=INK_BLACK, width=2)
    f_b = font(bold=True)
    bbox = d.textbbox((0, 0), branch, font=f_b)
    bw = bbox[2] - bbox[0]
    # Truncate branch if too wide for box.
    if bw > box_w - 32:
        trunc = branch
        while trunc and d.textlength(trunc + "...", font=f_b) > box_w - 32:
            trunc = trunc[:-1]
        branch = trunc + "..." if trunc else branch
        bw = d.textlength(branch, font=f_b)
    d.text((x + PADDING + (box_w - bw) // 2, next_y + 8), branch, fill=INK_BLACK, font=f_b)
    next_y += box_h + 12

    parts = []
    if data.get("staged"):    parts.append(f"{data['staged']} staged")
    if data.get("modified"):  parts.append(f"{data['modified']} modified")
    if data.get("untracked"): parts.append(f"{data['untracked']} new")
    if not parts:
        parts.append("clean")
    next_y = body_text(d, x + PADDING, next_y, w - 2 * PADDING, "  ·  ".join(parts))

    ahead, behind = data.get("ahead", 0), data.get("behind", 0)
    if ahead or behind:
        next_y = body_text(d, x + PADDING, next_y, w - 2 * PADDING,
                           f"↑ {ahead}   ↓ {behind}")

    h_str = data.get("last_commit_hash", "")
    msg = data.get("last_commit_msg", "")
    if h_str:
        divider(d, x + PADDING, next_y + 2, x + w - PADDING)
        body_text(d, x + PADDING, next_y + 10, w - 2 * PADDING, f"{h_str}  {msg}")


def paint_system(d, rect, data, stale=False):
    x, y, w, h = rect
    next_y = header_bar(d, rect, "SYSTEM")
    next_y += 12

    cells = []
    if data.get("cpu_pct") is not None:    cells.append((data["cpu_pct"], "CPU"))
    if data.get("memory_pct") is not None: cells.append((data["memory_pct"], "MEM"))
    if data.get("disk_pct") is not None:   cells.append((data["disk_pct"], "DISK"))
    bp = data.get("battery_pct")
    if bp is not None and bp != 255:       cells.append((bp, "BAT"))

    # Narrow slot (270 px top-left/right) — stack vertically, 4 rows of
    # [val  LABEL ─────── bar]. Wide slot (540 px middle/bottom) — keep
    # 2×2 grid because there's room.
    f_b = font(bold=True)
    f_l = font()

    def draw_centered_text(tx: int, center_y: int, text: str, fnt, fill: int) -> None:
        bbox = d.textbbox((0, 0), text, font=fnt)
        ty = int(round(center_y - (bbox[1] + bbox[3]) / 2))
        d.text((tx, ty), text, fill=fill, font=fnt)

    def draw_wifi_icon(cx: int, center_y: int, online: bool) -> None:
        fill = INK_BLACK if online else DIVIDER_GRAY
        dot_y = center_y + 8
        d.ellipse((cx - 2, dot_y - 2, cx + 2, dot_y + 2), fill=fill)
        for radius in (10, 18, 26):
            d.arc(
                (cx - radius, dot_y - radius, cx + radius, dot_y + radius),
                start=215,
                end=325,
                fill=fill,
                width=2,
            )
        if not online:
            d.line((cx - 23, center_y - 13, cx + 23, center_y + 18),
                   fill=INK_BLACK, width=3)

    if w < 350:
        # Vertical stack: each row is a full-width metric.
        show_kindle = isinstance(data.get("kindle_online"), bool)
        row_centers = [next_y + 18, next_y + 68, next_y + 118, next_y + 168]
        row_h = 55 if show_kindle else 60
        for i, (pct, label) in enumerate(cells):
            center_y = row_centers[i] if show_kindle and i < len(row_centers) else next_y + i * row_h + 18
            val = f"{pct}%"
            draw_centered_text(x + PADDING, center_y, val, f_b, INK_BLACK)
            draw_centered_text(x + PADDING + 82, center_y, label, f_l, DIVIDER_GRAY)
            bar_x0 = x + PADDING + 160
            bar_x1 = x + w - PADDING
            bar_y = int(round(center_y - 5))
            d.rectangle((bar_x0, bar_y, bar_x1, bar_y + 10),
                        outline=INK_BLACK, width=1)
            fill = max(1, int((bar_x1 - bar_x0) * pct / 100))
            d.rectangle((bar_x0, bar_y, bar_x0 + fill, bar_y + 10),
                        fill=INK_BLACK)
        if show_kindle:
            row_center = row_centers[len(cells)] if len(cells) < len(row_centers) else next_y + len(cells) * row_h + 18
            online = bool(data.get("kindle_online"))
            draw_centered_text(x + PADDING, row_center, "KNDL",
                               font_bar_bold(), INK_BLACK)
            draw_centered_text(x + PADDING + 82, row_center, "Wi-Fi",
                               f_l, DIVIDER_GRAY)
            draw_wifi_icon(x + PADDING + 186, row_center, online)
            label = "Online" if online else "Offline"
            draw_centered_text(x + PADDING + 220, row_center, label,
                               font_bar_bold(), INK_BLACK)
    else:
        cell_w = (w - 3 * PADDING) // 2
        cell_h = 64
        for i, (pct, label) in enumerate(cells[:4]):
            row, col = i // 2, i % 2
            cx = x + PADDING + col * (cell_w + PADDING)
            cy = next_y + row * (cell_h + 8)
            val = f"{pct}%"
            d.text((cx, cy), val, fill=INK_BLACK, font=f_b)
            d.text((cx + 90, cy + 6), label, fill=DIVIDER_GRAY, font=f_l)
            d.rectangle((cx, cy + 38, cx + cell_w - 8, cy + 46),
                        outline=INK_BLACK, width=1)
            fill = max(1, int((cell_w - 10) * pct / 100))
            d.rectangle((cx, cy + 38, cx + fill, cy + 46), fill=INK_BLACK)

    foot_parts = []
    nd, nu = data.get("net_down_kbps", 0), data.get("net_up_kbps", 0)
    if nd or nu:
        foot_parts.append(f"↓ {nd / 1024:.1f}MB  ↑ {nu / 1024:.1f}MB")
    t = data.get("temp_c")
    if t is not None and t != -32768:
        foot_parts.append(f"{t}°C")
    if foot_parts:
        body_text(d, x + PADDING, y + h - PADDING - BODY_SIZE - 4,
                  w - 2 * PADDING, "  ·  ".join(foot_parts))


def paint_ai_quota(d, rect, data, stale=False):
    x, y, w, h = rect
    next_y = header_bar(d, rect, "AI LIMITS", "used")
    next_y += 10

    rows = []
    for provider in (data.get("providers") or [])[:2]:
        name = str(provider.get("name") or "").strip()
        short = "Claude" if name.lower().startswith("claude") else "Codex"
        for window in (provider.get("windows") or [])[:2]:
            label = str(window.get("label") or "").upper()
            used = window.get("used_pct")
            reset = window.get("reset_seconds")
            rows.append((short, label, used, reset, bool(window.get("available", True))))

    if not rows:
        body_text(d, x + PADDING, next_y, w - 2 * PADDING, "no local quota data")
        return

    f_b = font_bar_bold()
    f_pct = font_quota_percent()
    row_h = 48 if w < 350 else 56
    bar_h = 9
    max_rows = max(1, (y + h - PADDING - next_y) // row_h)

    def reset_label(seconds):
        if not isinstance(seconds, (int, float)):
            return ""
        seconds = max(0, int(seconds))
        if seconds < 3600:
            return f"0h{seconds // 60:02d}m"
        if seconds < 86400:
            return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
        return f"{seconds // 86400}d{(seconds % 86400) // 3600:02d}h"

    def draw_bar(x0, y0, x1, pct):
        d.rectangle((x0, y0, x1, y0 + bar_h), outline=INK_BLACK, width=1)
        if pct > 0:
            fill_w = max(1, int((x1 - x0) * pct / 100))
            d.rectangle((x0, y0, x0 + fill_w, y0 + bar_h), fill=INK_BLACK)

    for i, (provider, label, used, reset, available) in enumerate(rows[:max_rows]):
        ry = next_y + i * row_h
        if isinstance(used, (int, float)):
            pct = max(0, min(100, int(round(float(used)))))
            value = f"{pct}%"
            fill_pct = pct
        else:
            value = "--"
            fill_pct = 0
            available = False

        countdown = reset_label(reset)

        if w >= 320:
            provider_x = x + PADDING
            window_x = provider_x + 115
            reset_x = provider_x + 167
            percent_x = x + w - PADDING
            bar_x0 = provider_x
            bar_y = ry + 31
            value_bbox = d.textbbox((0, 0), value, font=f_pct)
            value_w = value_bbox[2] - value_bbox[0]
            bar_x1 = max(bar_x0 + 80, percent_x - max(value_w + 14, 52))

            d.text((provider_x, ry), provider, fill=INK_BLACK, font=f_b)
            d.text((window_x, ry), label, fill=INK_BLACK, font=f_b)
            if countdown:
                d.text((reset_x, ry), countdown, fill=INK_BLACK, font=f_b)

            draw_bar(bar_x0, bar_y, bar_x1, fill_pct)

            value_y = bar_y + bar_h - value_bbox[3]
            d.text((percent_x - value_w, value_y), value,
                   fill=INK_BLACK if available else DIVIDER_GRAY, font=f_pct)
        else:
            row_label = f"{provider} {label} {countdown}".strip()
            d.text((x + PADDING, ry), row_label, fill=INK_BLACK, font=f_b)
            value_w = d.textlength(value, font=f_b)
            d.text((x + w - PADDING - value_w, ry), value,
                   fill=INK_BLACK if available else DIVIDER_GRAY, font=f_b)

            bar_x0 = x + PADDING
            bar_x1 = x + w - PADDING
            bar_y = ry + 28
            draw_bar(bar_x0, bar_y, bar_x1, fill_pct)


def paint_inbox(d, rect, data, stale=False):
    """Aggregated unread count + per-source breakdown."""
    x, y, w, h = rect
    total = data.get("total", 0)
    next_y = header_bar(d, rect, "INBOX", str(total) if total else "")
    next_y += 16
    f = font()
    f_b = font(bold=True)
    sources = (data.get("sources") or [])[:4]
    if not sources:
        body_text(d, x + PADDING, next_y, w - 2 * PADDING, "all caught up")
        return
    row_h = BODY_SIZE + 14
    for src in sources:
        name = src.get("name", "")
        cnt = src.get("count", 0)
        cnt_str = str(cnt)
        cnt_w = d.textlength(cnt_str, font=f_b)
        d.text((x + PADDING, next_y), name, fill=INK_BLACK, font=f)
        d.text((x + w - PADDING - cnt_w, next_y), cnt_str,
               fill=INK_BLACK if cnt > 0 else DIVIDER_GRAY, font=f_b)
        # Dotted leader between name and count.
        name_w = d.textlength(name, font=f)
        leader_x0 = x + PADDING + name_w + 12
        leader_x1 = x + w - PADDING - cnt_w - 12
        cx = leader_x0
        while cx + 2 < leader_x1:
            d.rectangle((cx, next_y + BODY_SIZE - 4,
                         cx + 2, next_y + BODY_SIZE - 2),
                        fill=DIVIDER_GRAY)
            cx += 8
        next_y += row_h
        if next_y > y + h - PADDING: break


def paint_next_meeting(d, rect, data, stale=False):
    """Single upcoming meeting with prominent countdown."""
    x, y, w, h = rect
    start_in = data.get("start_in", "")
    next_y = header_bar(d, rect, "NEXT", start_in)
    next_y += 12

    title = data.get("title", "")
    if title:
        next_y = wrapped_text(d, x + PADDING, next_y,
                              w - 2 * PADDING, BODY_SIZE * 2 + 8, title)
        next_y += 10

    start_at = data.get("start_at", "")
    if start_at:
        box_w = w - 2 * PADDING
        box_h = 50
        d.rectangle((x + PADDING, next_y, x + PADDING + box_w, next_y + box_h),
                    outline=INK_BLACK, width=2)
        f_b = font(bold=True)
        bbox = d.textbbox((0, 0), start_at, font=f_b)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text((x + PADDING + (box_w - tw) // 2,
                next_y + (box_h - th) // 2 - 4),
               start_at, fill=INK_BLACK, font=f_b)
        next_y += box_h + 12

    attendees = data.get("attendees", "")
    if attendees:
        next_y = body_text(d, x + PADDING, next_y, w - 2 * PADDING,
                           f"with {attendees}")

    location = data.get("location", "")
    if location:
        d.text((x + PADDING, next_y), location,
               fill=DIVIDER_GRAY, font=font())


def paint_pr_queue(d, rect, data, stale=False):
    """GitHub PR review queue + your own open PRs."""
    x, y, w, h = rect
    rc = data.get("review_count", 0)
    yc = data.get("your_open_count", 0)
    meta = f"{rc} / {yc}" if (rc or yc) else ""
    next_y = header_bar(d, rect, "PRs", meta)
    next_y += 12

    f = font()
    f_b = font(bold=True)
    items = (data.get("items") or [])[:4]
    if not items:
        body_text(d, x + PADDING, next_y, w - 2 * PADDING, "queue empty — nice")
        return

    row_h = BODY_SIZE * 2 + 16
    for it in items:
        status = it.get("status", "")
        # ASCII / wide-Unicode-safe markers. PingFang Bold variant lacks
        # ▸ ✓ ✕ — renders as .notdef tofu. ● / ○ are reliably present
        # across both Regular and Bold variants.
        marker = "●"
        if status == "yours":      marker = "○"
        elif status == "approved": marker = "+"
        elif status == "blocked":  marker = "!"
        num = it.get("number", "")
        title = it.get("title", "")
        author = it.get("author", "")
        head = f"{marker}  {num}  {title}" if num else f"{marker}  {title}"
        head_trunc = head
        if d.textlength(head_trunc, font=f_b) > w - 2 * PADDING:
            while head_trunc and d.textlength(head_trunc + "...", font=f_b) > w - 2 * PADDING:
                head_trunc = head_trunc[:-1]
            head_trunc += "..."
        d.text((x + PADDING, next_y), head_trunc, fill=INK_BLACK, font=f_b)
        sub_parts = []
        if author: sub_parts.append(f"by {author}")
        if status: sub_parts.append(status)
        if sub_parts:
            d.text((x + PADDING + 38, next_y + BODY_SIZE + 4),
                   "  ·  ".join(sub_parts), fill=DIVIDER_GRAY, font=f)
        next_y += row_h
        if next_y > y + h - PADDING: break


def paint_break_reminder(d, rect, data, stale=False):
    """Health-nudge: time since last break + sitting + eye-rest countdown."""
    x, y, w, h = rect
    next_y = header_bar(d, rect, "BREAK")
    next_y += 16

    f = font()
    f_b = font(bold=True)

    def fmt_mins(m):
        if m is None: return "—"
        if m < 60: return f"{m}m"
        return f"{m // 60}h {m % 60:02d}m"

    rows = []
    if data.get("last_break_min_ago") is not None:
        rows.append(("last break", fmt_mins(data["last_break_min_ago"]) + " ago",
                     data["last_break_min_ago"] > 45))
    if data.get("sitting_min") is not None:
        rows.append(("sitting", fmt_mins(data["sitting_min"]),
                     data["sitting_min"] > 60))
    eye = data.get("next_eye_rest_min")
    if eye is not None:
        if eye < 0:
            rows.append(("eye rest", f"overdue {fmt_mins(-eye)}", True))
        else:
            rows.append(("eye rest", f"in {fmt_mins(eye)}", False))

    row_h = BODY_SIZE + 14
    for label, val, urgent in rows:
        d.text((x + PADDING, next_y), label, fill=INK_BLACK, font=f)
        val_font = f_b if urgent else f
        vw = d.textlength(val, font=val_font)
        d.text((x + w - PADDING - vw, next_y), val,
               fill=INK_BLACK if urgent else DIVIDER_GRAY, font=val_font)
        next_y += row_h

    advice = data.get("advice", "")
    if advice:
        divider(d, x + PADDING, next_y + 4, x + w - PADDING)
        body_text(d, x + PADDING, next_y + 16, w - 2 * PADDING, advice, bold=True)


def paint_deadlines(d, rect, data, stale=False):
    """Upcoming deadlines countdown — list of title + days-remaining."""
    x, y, w, h = rect
    next_y = header_bar(d, rect, "DEADLINES")
    next_y += 12

    f = font()
    f_b = font(bold=True)
    items = (data.get("items") or [])[:5]
    if not items:
        body_text(d, x + PADDING, next_y, w - 2 * PADDING, "no deadlines")
        return

    row_h = BODY_SIZE + 12
    for it in items:
        title = it.get("title", "")
        due = it.get("due_label", "")
        urgent = it.get("is_urgent", False)
        title_font = f_b if urgent else f
        due_w = d.textlength(due, font=f_b) if due else 0
        title_max_w = w - 2 * PADDING - due_w - 16
        title_trunc = title
        if d.textlength(title_trunc, font=title_font) > title_max_w:
            while title_trunc and d.textlength(title_trunc + "...", font=title_font) > title_max_w:
                title_trunc = title_trunc[:-1]
            title_trunc += "..."
        marker = "● " if urgent else "  "
        d.text((x + PADDING, next_y), marker + title_trunc,
               fill=INK_BLACK, font=title_font)
        if due:
            d.text((x + w - PADDING - due_w, next_y), due,
                   fill=INK_BLACK if urgent else DIVIDER_GRAY,
                   font=f_b if urgent else f)
        next_y += row_h
        if next_y > y + h - PADDING: break


PAINTERS = {
    "weather":        paint_weather,
    "todo":           paint_todo,
    "todo-dashboard": paint_todo_dashboard,
    "agent-live-map": paint_agent_live_map,
    "page-placeholder": paint_page_placeholder,
    "calendar":       paint_calendar,
    "messages":       paint_messages,
    "ai-status":      paint_ai_status,
    "ai-tasks":       paint_ai_tasks,
    "scratch":        paint_scratch,
    "focus":          paint_focus,
    "now-playing":    paint_now_playing,
    "git-status":     paint_git_status,
    "system":         paint_system,
    "ai-quota":       paint_ai_quota,
    # v0.6.2 — monitor-side glance widgets.
    "inbox":          paint_inbox,
    "next-meeting":   paint_next_meeting,
    "pr-queue":       paint_pr_queue,
    "break-reminder": paint_break_reminder,
    "deadlines":      paint_deadlines,
}


def paint_empty(d, rect):
    """Empty slot — dashed outline + faint label."""
    x, y, w, h = rect
    # Dashed border.
    for i in range(x + 8, x + w - 8, 14):
        d.line((i, y + 8, i + 7, y + 8), fill=DIVIDER_GRAY)
        d.line((i, y + h - 8, i + 7, y + h - 8), fill=DIVIDER_GRAY)
    for j in range(y + 8, y + h - 8, 14):
        d.line((x + 8, j, x + 8, j + 7), fill=DIVIDER_GRAY)
        d.line((x + w - 8, j, x + w - 8, j + 7), fill=DIVIDER_GRAY)


# ---- top-level render ---------------------------------------------------

def paint_bottom_bar_at(
    d: "ImageDraw.ImageDraw",
    status: dict,
    canvas_w: int,
    bar_y: int,
    bar_h: int,
):
    """Inverted black strip at the very bottom of the canvas. v0.6.3:
    LEFT = battery + transport + age (3 quick-glance status items).
    RIGHT = sleep + settings chips. Other actions (refresh / restart /
    re-pair) moved into the settings page since they're rare.

    `status` dict shape:
        {
          "battery_pct": int / None,   # firmware status_report, v0.6.4
          "transport":   "USB" / "BLE" / None,
          "frame_age":   int seconds since last push / None,
        }
    """
    d.rectangle((0, bar_y, canvas_w, bar_y + bar_h), fill=INK_BLACK)
    pad = 20
    f = font_bar()
    f_b = font_bar_bold()
    text_y = bar_y + (bar_h - 22) // 2 - 2

    # ---- LEFT zone: status pieces ----
    pieces = []
    bp = status.get("battery_pct")
    if bp is not None:
        pieces.append((f"{bp}%", bp <= 20))   # bold + caller-visible if low
    # v0.9: if device hasn't reported in >90s, the transport label is
    # misleading — show OFFLINE in bold instead so user can tell at a
    # glance whether the device is actually alive.
    alive = status.get("device_alive", True)
    if not alive:
        pieces.append(("OFFLINE", True))
    else:
        t = status.get("transport")
        if t:
            pieces.append((t, False))
    # v0.7: removed live frame_age display from the bar — it shifted on
    # every push and broke the dirty-region diff (bottom bar always different
    # → bbox stretched to full canvas → 50% threshold → full re-push). The
    # "when was this last updated" info is now indirectly visible through
    # widget content changes; settings page still surfaces uptime explicitly.

    cx = pad
    for i, (text, bold) in enumerate(pieces):
        if i > 0:
            d.line((cx, bar_y + 14, cx, bar_y + bar_h - 14), fill=140, width=1)
            cx += 14
        fnt = f_b if bold else f
        d.text((cx, text_y), text, fill=255, font=fnt)
        cx += d.textlength(text, font=fnt) + 14

    # ---- RIGHT zone: sleep + settings chips ----
    # Touch hot zones rebuilt from scratch every render so width changes
    # (e.g., bold-vs-regular font swap) don't strand stale rects.
    global LAST_BOTTOM_BAR_HOT_ZONES
    LAST_BOTTOM_BAR_HOT_ZONES = []

    actions = [("Sleep", "sleep"), ("Settings", "settings")]
    chip_pad = 20
    sep_w = 14
    total_w = sum(d.textlength(lbl, font=f_b) for lbl, _ in actions) \
            + chip_pad * 2 * len(actions) \
            + sep_w * (len(actions) - 1)
    chip_x = canvas_w - pad - total_w
    if chip_x < cx + 16:
        return   # left + right would collide; safer to skip right zone

    for i, (label, action) in enumerate(actions):
        if i > 0:
            d.line((chip_x, bar_y + 14, chip_x, bar_y + bar_h - 14),
                   fill=140, width=1)
            chip_x += sep_w
        d.text((chip_x + chip_pad, text_y), label, fill=255, font=f_b)
        chip_w = int(d.textlength(label, font=f_b)) + chip_pad * 2
        # Whole-bar-height tap target so users don't need to land inside the
        # text — chip rect spans full BOTTOM_BAR_H, not just the text band.
        LAST_BOTTOM_BAR_HOT_ZONES.append({
            "rect":   (chip_x, bar_y, chip_x + chip_w, bar_y + bar_h),
            "action": action,
        })
        chip_x += chip_w


def paint_bottom_bar(d: "ImageDraw.ImageDraw", status: dict):
    paint_bottom_bar_at(d, status, CANVAS_W, BOTTOM_BAR_Y, BOTTOM_BAR_H)


def render_image(widget_snapshot: Iterable[dict],
                 status: "dict | None" = None) -> "Image.Image":
    if Image is None:
        raise RuntimeError("install Pillow")

    img = Image.new("L", (CANVAS_W, CANVAS_H), 255)
    d = ImageDraw.Draw(img)

    seen = set()
    for w in widget_snapshot:
        slot = w.get("slot")
        wtype = w.get("type")
        rect = SLOT_RECTS.get(slot)
        fn = PAINTERS.get(wtype)
        if rect and fn:
            seen.add(slot)
            try:
                fn(d, rect, w.get("data") or {}, w.get("stale", False))
            except Exception as e:
                d.text((rect[0] + 16, rect[1] + 16),
                       f"render err: {e!r}", fill=INK_BLACK, font=font())

    for slot, rect in SLOT_RECTS.items():
        if slot == "full" or slot in seen:
            continue
        paint_empty(d, rect)

    # Structural dividers — drawn AFTER widget content so they sit on top
    # of any widget chrome and bind the grid together visually. Made
    # generously chunky (~4-8 px) so 4bpp packing + e-ink low-contrast
    # don't smear them into invisibility.
    mid_y = SLOT_RECTS["middle"][1]

    # Single vertical 3 px black line between top-left / top-right.
    d.rectangle((269, 16, 272, mid_y - 16), fill=INK_BLACK)

    # Bottom status/settings bar (always rendered).
    paint_bottom_bar(d, status or {})

    return img


def render_kindle_image(widget_snapshot: Iterable[dict],
                        status: "dict | None" = None) -> "Image.Image":
    """Render a Kindle PW1 native 758x1024 frame.

    The M5Paper renderer keeps the upstream 540x960 canvas. Kindle PW1 has
    enough horizontal room for wider top widgets, so this target uses native
    slot geometry instead of scaling and letterboxing the M5Paper frame.
    """
    if Image is None:
        raise RuntimeError("install Pillow")

    img = Image.new("L", (KINDLE_CANVAS_W, KINDLE_CANVAS_H), 255)
    d = ImageDraw.Draw(img)

    seen = set()
    for w in widget_snapshot:
        slot = w.get("slot")
        wtype = w.get("type")
        rect = KINDLE_SLOT_RECTS.get(slot)
        fn = PAINTERS.get(wtype)
        if rect and fn:
            seen.add(slot)
            try:
                fn(d, rect, w.get("data") or {}, w.get("stale", False))
            except Exception as e:
                d.text((rect[0] + 16, rect[1] + 16),
                       f"render err: {e!r}", fill=INK_BLACK, font=font())

    if "full" in seen:
        return img

    for slot, rect in KINDLE_SLOT_RECTS.items():
        if slot == "full" or slot in seen:
            continue
        if "main" in seen and slot in ("middle", "bottom"):
            continue
        if slot == "main":
            continue
        paint_empty(d, rect)

    d.rectangle((378, 16, 381, KINDLE_SLOT_RECTS["middle"][1] - 16),
                fill=INK_BLACK)
    paint_bottom_bar_at(
        d,
        status or {},
        KINDLE_CANVAS_W,
        KINDLE_BOTTOM_BAR_Y,
        KINDLE_BOTTOM_BAR_H,
    )

    return img


def to_4bpp_packed(img: "Image.Image") -> bytes:
    """Convert PIL L-mode image to M5EPD 4bpp packed buffer.

    Uses the image's own size — so this works for full 540×960 frames AND
    for the cropped sub-rectangles used by v0.7 dirty-region diff. Caller
    is responsible for using a width that's multiple of 2 (one byte = two
    horizontally-adjacent pixels).

    M5EPD convention: 0=white, 15=black. PIL L: 0=black, 255=white.
    Invert + quantize. 2 pixels per byte, high nibble first.
    """
    if img.mode != "L":
        img = img.convert("L")
    w, h = img.size
    if w % 2 != 0:
        # 4bpp packing needs even width — pad right with white.
        new = Image.new("L", (w + 1, h), 255)
        new.paste(img, (0, 0))
        img = new
        w += 1
    pixels = img.tobytes()
    out = bytearray(w * h // 2)
    for i in range(0, len(pixels), 2):
        a = pixels[i]
        b = pixels[i + 1] if i + 1 < len(pixels) else 255
        na = (255 - a) >> 4
        nb = (255 - b) >> 4
        out[i // 2] = (na << 4) | nb
    return bytes(out)


# ---- legacy PNG preview API (kept for /widgets/preview HTTP endpoint) ----

def render_preview_png(widget_snapshot: Iterable[dict], theme: str = "minimal",
                       status: "dict | None" = None) -> bytes:
    img = render_image(widget_snapshot, status=status)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---- CLI ---------------------------------------------------------------

if __name__ == "__main__":
    import argparse, json, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    if a.sample:
        widgets = [
            {"slot": "top-left", "type": "weather", "data": {
                "location": "Shanghai",
                "current": {"temp_c": 22, "condition": "Cloudy"},
                "forecast": [{"day": "Tomorrow", "high": 26, "low": 19, "condition": "Sunny"}]
            }},
            {"slot": "top-right", "type": "ai-status", "data": {
                "session_name": "kindle-side-card",
                "model": "Opus 4.7",
                "task": "Test v0.6 server-side rendering with single-size type",
                "context": {"used": 45000, "limit": 200000}
            }},
            {"slot": "middle", "type": "calendar", "data": {
                "now_iso": "2026-05-20T18:30",
                "events": [
                    {"start": "10:00", "title": "Morning standup"},
                    {"start": "16:00", "title": "Design review"},
                    {"start": "19:00", "title": "Dinner"}
                ]
            }},
            {"slot": "bottom", "type": "todo", "data": {
                "title": "Next 3 Days",
                "items": [
                    {"text": "Run v0.6 end to end", "tag": "today"},
                    {"text": "Server rendering + one font size", "tag": "today"},
                    {"text": "Reply to email", "tag": "overdue"}
                ]
            }}
        ]
    else:
        widgets = json.load(sys.stdin)
    # CLI sample: fake a status payload so the bottom bar isn't blank.
    from datetime import datetime as _dt
    fake_status = {
        "transport":  "USB",
        "ble_paired": True,
        "time":       _dt.now().strftime("%H:%M"),
        "frame_age":  5,
    }
    png = render_preview_png(widgets, status=fake_status)
    if a.out == "-":
        sys.stdout.buffer.write(png)
    else:
        with open(a.out, "wb") as f: f.write(png)
        print(f"wrote {a.out}", file=sys.stderr)
