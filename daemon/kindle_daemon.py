#!/usr/bin/env python3
"""Kindle Side Card daemon.

The daemon renders a Kindle-native PNG with Pillow and exposes it over HTTP.
A jailbroken Kindle running the bundled KUAL extension periodically downloads
`/kindle/frame.png` and paints it with `eips`.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FRAME_PATH = os.path.join(os.environ.get("TMPDIR", "/tmp"), "kindle_side_card.png")
STATE_DIR = os.environ.get(
    "KINDLE_SIDE_CARD_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".kindle-side-card"),
)
WIDGET_STATE_PATH = os.environ.get(
    "KINDLE_SIDE_CARD_WIDGET_STATE",
    os.path.join(STATE_DIR, "widgets.json"),
)
PAGE_STATE_PATH = os.environ.get(
    "KINDLE_SIDE_CARD_PAGE_STATE",
    os.path.join(STATE_DIR, "page.json"),
)
PAGE_COUNT = max(1, int(os.environ.get("KINDLE_SIDE_CARD_PAGE_COUNT", "2") or "2"))
PAGE_AUTO_SECONDS = int(os.environ.get("KINDLE_SIDE_CARD_AUTO_PAGE_SECONDS", "60") or "0")
KINDLE_ONLINE_SECONDS = int(os.environ.get("KINDLE_SIDE_CARD_ONLINE_SECONDS", "150") or "150")

WIDGET_SLOTS = ("top-left", "top-right", "main", "middle", "bottom", "full")
WIDGET_TYPES = (
    "weather", "todo", "calendar", "messages", "ai-status", "ai-tasks",
    "scratch", "focus", "now-playing", "git-status", "system", "inbox",
    "next-meeting", "pr-queue", "break-reminder", "deadlines", "ai-quota",
    "page-placeholder", "todo-dashboard", "agent-live-map",
)

WIDGET_LOCK = threading.Lock()
PAGE_LOCK = threading.Lock()
KINDLE_PULL_LOCK = threading.Lock()
WIDGET_CACHE: dict[str, dict] = {}
LAST_RENDER_TS = 0.0
LAST_KINDLE_PULL_TS = 0.0


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def _save_widget_cache_unlocked() -> None:
    os.makedirs(os.path.dirname(WIDGET_STATE_PATH), exist_ok=True)
    tmp = f"{WIDGET_STATE_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(WIDGET_CACHE, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, WIDGET_STATE_PATH)


def _load_widget_cache() -> None:
    if not os.path.exists(WIDGET_STATE_PATH):
        return
    try:
        with open(WIDGET_STATE_PATH, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception as exc:
        log(f"[state] failed to load {WIDGET_STATE_PATH}: {exc}")
        return
    if not isinstance(raw, dict):
        log(f"[state] ignoring invalid widget state: {WIDGET_STATE_PATH}")
        return

    now = time.time()
    loaded = 0
    with WIDGET_LOCK:
        WIDGET_CACHE.clear()
        for slot, entry in raw.items():
            if slot not in WIDGET_SLOTS or not isinstance(entry, dict):
                continue
            if entry.get("type") not in WIDGET_TYPES:
                continue
            if not isinstance(entry.get("data"), dict):
                continue
            entry["written_at"] = float(entry.get("written_at") or now)
            WIDGET_CACHE[slot] = entry
            loaded += 1
    log(f"[state] loaded {loaded} widgets from {WIDGET_STATE_PATH}")


def _read_page_state_unlocked() -> dict:
    try:
        with open(PAGE_STATE_PATH, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _state_page(raw: dict) -> int:
    page = raw.get("page")
    return int(page) % PAGE_COUNT if isinstance(page, int) else 0


def _state_anchor(raw: dict, now: float) -> float:
    anchor = raw.get("auto_anchor")
    if isinstance(anchor, (int, float)):
        return float(anchor)
    updated_at = raw.get("updated_at")
    if isinstance(updated_at, (int, float)):
        return float(updated_at)
    return now


def _page_from_state(raw: dict, now: float | None = None) -> int:
    now = time.time() if now is None else now
    page = _state_page(raw)
    if PAGE_AUTO_SECONDS <= 0:
        return page
    elapsed_pages = int(max(0, now - _state_anchor(raw, now)) // PAGE_AUTO_SECONDS)
    return (page + elapsed_pages) % PAGE_COUNT


def _current_page() -> int:
    with PAGE_LOCK:
        return _page_from_state(_read_page_state_unlocked())


def _set_page(page: int) -> int:
    page = int(page) % PAGE_COUNT
    now = time.time()
    os.makedirs(os.path.dirname(PAGE_STATE_PATH), exist_ok=True)
    tmp = f"{PAGE_STATE_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"page": page, "updated_at": now, "auto_anchor": now}, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, PAGE_STATE_PATH)
    return page


def _shift_page(delta: int) -> int:
    with PAGE_LOCK:
        return _set_page(_page_from_state(_read_page_state_unlocked()) + delta)


def _page_payload(page: int) -> dict:
    payload = {
        "page": page,
        "page_count": PAGE_COUNT,
        "label": f"Page {page + 1}",
        "auto_seconds": PAGE_AUTO_SECONDS,
    }
    if PAGE_AUTO_SECONDS > 0:
        raw = _read_page_state_unlocked()
        now = time.time()
        elapsed = int(max(0, now - _state_anchor(raw, now)) % PAGE_AUTO_SECONDS)
        payload["next_page_seconds"] = PAGE_AUTO_SECONDS - elapsed
    return payload


def _mark_kindle_pull() -> None:
    global LAST_KINDLE_PULL_TS
    with KINDLE_PULL_LOCK:
        LAST_KINDLE_PULL_TS = time.time()


def _kindle_online() -> bool:
    with KINDLE_PULL_LOCK:
        last = LAST_KINDLE_PULL_TS
    return bool(last and time.time() - last <= KINDLE_ONLINE_SECONDS)


def _widget_snapshot() -> list[dict]:
    now = time.time()
    out = []
    changed = False
    with WIDGET_LOCK:
        for slot, widget in list(WIDGET_CACHE.items()):
            written = float(widget.get("written_at") or now)
            ttl = int(widget.get("ttl") or 0)
            if ttl > 0 and now - written > ttl:
                WIDGET_CACHE.pop(slot, None)
                changed = True
                continue
            out.append({
                "slot": slot,
                "type": widget.get("type"),
                "data": widget.get("data") or {},
                "theme": widget.get("theme") or "",
                "stale": (
                    int(widget.get("stale_after") or 0) > 0
                    and now - written > int(widget.get("stale_after") or 0)
                ),
                "age": int(now - written),
            })
        if changed:
            _save_widget_cache_unlocked()
    return out


def _decorate_widgets(widgets: list[dict]) -> list[dict]:
    decorated = []
    online = _kindle_online()
    for widget in widgets:
        if widget.get("slot") == "top-left" and widget.get("type") == "system":
            data = dict(widget.get("data") or {})
            data["kindle_online"] = online
            decorated.append({**widget, "data": data})
        else:
            decorated.append(widget)
    return decorated


def _default_widgets() -> list[dict]:
    return [
        {
            "slot": "top-left",
            "type": "system",
            "data": {
                "cpu_pct": 0,
                "memory_pct": 0,
                "disk_pct": 0,
                "battery_pct": 255,
                "kindle_online": _kindle_online(),
            },
            "stale": False,
            "age": 0,
        },
        {
            "slot": "top-right",
            "type": "ai-quota",
            "data": {"providers": []},
            "stale": False,
            "age": 0,
        },
        {
            "slot": "main",
            "type": "page-placeholder",
            "data": {
                "title": "KINDLE SIDE CARD",
                "meta": "ready",
                "body": "Push widgets to POST /widget. The Kindle extension pulls /kindle/frame.png.",
                "label": "Page 1",
            },
            "stale": False,
            "age": 0,
        },
    ]


def _page_widgets(widgets: list[dict], page: int) -> list[dict]:
    by_slot = {widget.get("slot"): widget for widget in widgets}
    if "full" in by_slot:
        return [by_slot["full"]]

    if page == 0:
        out = []
        for slot in ("top-left", "top-right", "main", "middle", "bottom"):
            if slot in by_slot:
                out.append(by_slot[slot])
        return out

    return [
        {
            "slot": "full",
            "type": "page-placeholder",
            "data": {
                "title": "PAGE",
                "meta": f"{page + 1}/{PAGE_COUNT}",
                "body": "Use POST /widget to populate this page or disable auto pages with KINDLE_SIDE_CARD_PAGE_COUNT=1.",
                "label": f"Page {page + 1}",
            },
            "stale": False,
            "age": 0,
        }
    ]


def _status_payload() -> dict:
    return {
        "transport": "Wi-Fi",
        "time": datetime.now().strftime("%H:%M"),
        "frame_age": int(time.time() - LAST_RENDER_TS) if LAST_RENDER_TS else None,
        "device_alive": True,
    }


def render_png() -> bytes:
    global LAST_RENDER_TS
    import card_render

    widgets = _page_widgets(_decorate_widgets(_widget_snapshot() or _default_widgets()), _current_page())
    canvas = card_render.render_kindle_image(widgets, status=_status_payload()).convert("L")

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    png = buffer.getvalue()
    with open(FRAME_PATH, "wb") as handle:
        handle.write(png)
    LAST_RENDER_TS = time.time()
    return png


def widget_validate(payload: dict) -> tuple[bool, str]:
    if payload.get("type") not in WIDGET_TYPES:
        return False, f"type must be one of {WIDGET_TYPES}, got {payload.get('type')!r}"
    if payload.get("slot") not in WIDGET_SLOTS:
        return False, f"slot must be one of {WIDGET_SLOTS}, got {payload.get('slot')!r}"
    if not isinstance(payload.get("data"), dict):
        return False, "data must be an object"
    return True, ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: N802
        return

    def _reply_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reply_png(self, png: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(png)))
        self.end_headers()
        self.wfile.write(png)

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/widget":
            return self._reply_json(200, {"widgets": _widget_snapshot()})
        if path == "/kindle/page":
            return self._reply_json(200, _page_payload(_current_page()))
        if path in ("/kindle/frame.png", "/frame.png"):
            if path == "/kindle/frame.png":
                _mark_kindle_pull()
            return self._reply_png(render_png())
        if path == "/heartbeat":
            return self._reply_json(200, {
                "alive": True,
                "target": "kindle",
                "frame_path": FRAME_PATH,
                "page": _current_page(),
                "page_count": PAGE_COUNT,
                "kindle_online": _kindle_online(),
                "last_render_seconds": int(time.time() - LAST_RENDER_TS) if LAST_RENDER_TS else None,
            })
        return self._reply_json(404, {"error": f"unknown GET {path!r}"})

    def do_DELETE(self):  # noqa: N802
        path = urlparse(self.path).path
        if path != "/widget":
            return self._reply_json(404, {"error": f"unknown DELETE {path!r}"})
        slot = (parse_qs(urlparse(self.path).query).get("slot") or [None])[0]
        with WIDGET_LOCK:
            if slot:
                WIDGET_CACHE.pop(slot, None)
            else:
                WIDGET_CACHE.clear()
            _save_widget_cache_unlocked()
        render_png()
        return self._reply_json(200, {"ok": True, "cleared": slot or "all"})

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        body = self.rfile.read(int(self.headers.get("Content-Length") or "0"))
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception as exc:
            return self._reply_json(400, {"error": f"bad json: {exc}"})

        if path == "/widget":
            ok, error = widget_validate(payload)
            if not ok:
                return self._reply_json(400, {"error": error})
            entry = {
                "type": payload["type"],
                "data": payload["data"],
                "theme": payload.get("theme") or "",
                "ttl": int(payload.get("ttl") or 0),
                "stale_after": int(payload.get("stale_after") or 0),
                "written_at": time.time(),
            }
            with WIDGET_LOCK:
                WIDGET_CACHE[payload["slot"]] = entry
                _save_widget_cache_unlocked()
            render_png()
            log(f"[widget] {payload['slot']} <- {payload['type']}")
            return self._reply_json(200, {"ok": True, "slot": payload["slot"], "type": payload["type"]})

        if path == "/widgets/preview":
            return self._reply_png(render_png())

        if path in ("/kindle/page", "/kindle/page/next", "/kindle/page/prev"):
            if path == "/kindle/page/next":
                page = _shift_page(1)
            elif path == "/kindle/page/prev":
                page = _shift_page(-1)
            else:
                page_value = payload.get("page")
                if not isinstance(page_value, int):
                    return self._reply_json(400, {"error": "page must be an integer"})
                page = _set_page(page_value)
            render_png()
            log(f"[page] current page <- {page + 1}")
            return self._reply_json(200, _page_payload(page))

        return self._reply_json(404, {"error": f"unknown POST {path!r}"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9878)
    args = parser.parse_args()

    _load_widget_cache()
    render_png()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    log(f"[ready] Kindle Side Card daemon listening on {args.host}:{args.port}")
    log(f"[ready] Kindle frame URL: http://<computer-ip>:{args.port}/kindle/frame.png")
    server.serve_forever()


if __name__ == "__main__":
    main()
