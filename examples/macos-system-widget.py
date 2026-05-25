"""Push macOS system metrics into the Kindle Side Card daemon."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request


TEMP_UNAVAILABLE = -32768
NO_BATTERY = 255


def run_text(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)


def cpu_percent() -> int:
    out = run_text(["top", "-l", "2", "-n", "0", "-s", "1"])
    matches = re.findall(
        r"CPU usage:\s*([\d.]+)% user,\s*([\d.]+)% sys,\s*([\d.]+)% idle",
        out,
    )
    if not matches:
        return 0
    idle = float(matches[-1][2])
    return max(0, min(100, round(100 - idle)))


def memory_percent() -> int:
    page_size = 16384
    active = wired = compressed = 0
    for line in run_text(["vm_stat"]).splitlines():
        if "page size of" in line:
            m = re.search(r"page size of (\d+) bytes", line)
            if m:
                page_size = int(m.group(1))
        elif line.startswith("Pages active:"):
            active = int(re.sub(r"\D", "", line))
        elif line.startswith("Pages wired down:"):
            wired = int(re.sub(r"\D", "", line))
        elif line.startswith("Pages occupied by compressor:"):
            compressed = int(re.sub(r"\D", "", line))

    total = int(run_text(["sysctl", "-n", "hw.memsize"]).strip())
    used = (active + wired + compressed) * page_size
    return max(0, min(100, round(used / total * 100)))


def disk_percent() -> int:
    usage = shutil.disk_usage("/")
    return max(0, min(100, round(usage.used / usage.total * 100)))


def sample() -> dict:
    return {
        "cpu_pct": cpu_percent(),
        "memory_pct": memory_percent(),
        "disk_pct": disk_percent(),
        "battery_pct": NO_BATTERY,
        "net_down_kbps": 0,
        "net_up_kbps": 0,
        "temp_c": TEMP_UNAVAILABLE,
    }


def post_widget(daemon_url: str, slot: str, data: dict) -> None:
    body = json.dumps({
        "slot": slot,
        "type": "system",
        "data": data,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{daemon_url.rstrip('/')}/widget",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", default="http://127.0.0.1:9878")
    parser.add_argument("--slot", default="top-left")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    while True:
        try:
            data = sample()
            post_widget(args.daemon, args.slot, data)
            log(f"updated {args.slot}: {data}")
        except (OSError, subprocess.SubprocessError, urllib.error.URLError) as exc:
            log(f"update failed: {exc}")

        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
