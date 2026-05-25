#!/usr/bin/env python3
"""Push demo widgets into a local Kindle Side Card daemon."""
from __future__ import annotations

import argparse
import json
import urllib.request


def post_widget(base_url: str, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/widget",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", default="http://127.0.0.1:9878")
    args = parser.parse_args()

    widgets = [
        {
            "slot": "top-left",
            "type": "system",
            "data": {
                "cpu_pct": 18,
                "memory_pct": 54,
                "disk_pct": 61,
                "battery_pct": 255,
            },
        },
        {
            "slot": "top-right",
            "type": "ai-quota",
            "data": {
                "providers": [
                    {
                        "name": "Claude",
                        "windows": [
                            {"label": "5H", "used_pct": 38, "reset_seconds": 7200},
                            {"label": "7D", "used_pct": 64, "reset_seconds": 259200},
                        ],
                    },
                    {
                        "name": "Codex",
                        "windows": [
                            {"label": "5H", "used_pct": 22, "reset_seconds": 5400},
                            {"label": "7D", "used_pct": 47, "reset_seconds": 432000},
                        ],
                    },
                ]
            },
        },
        {
            "slot": "main",
            "type": "todo",
            "data": {
                "title": "Launch",
                "items": [
                    {"text": "Start daemon", "tag": "today"},
                    {"text": "Install KUAL extension", "tag": "today"},
                    {"text": "Point Kindle at frame URL", "tag": "next"},
                ],
            },
        },
    ]

    for widget in widgets:
        post_widget(args.daemon, widget)
        print(f"pushed {widget['slot']} <- {widget['type']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
