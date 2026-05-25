# Contributing

Contributions are welcome, especially:

- Kindle model reports.
- `eips` compatibility fixes.
- Safer KUAL refresh behavior.
- New widget producers that post generic JSON to `/widget`.
- Documentation improvements.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python daemon/kindle_daemon.py --host 127.0.0.1 --port 9878
python examples/push-demo-widgets.py
```

Preview the frame at:

```text
http://127.0.0.1:9878/kindle/frame.png
```

## Rules

- Keep all docs, code comments, examples, and UI strings in English.
- Do not commit personal paths, device serial numbers, LAN IPs, logs, account
  quota caches, or jailbreak exploit payloads.
- Keep the project local-first. Do not add cloud dependencies for the core frame
  path.
- Preserve GPL-3.0 licensing and visible attribution to `op7418 / ai-desk-card`.

## Pull Requests

Include:

- What Kindle model or host OS you tested.
- A screenshot or generated frame when changing layout.
- The command used to verify the daemon.
