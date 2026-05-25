# Architecture

Kindle Side Card is intentionally split into two small halves.

## Computer Side

- `daemon/kindle_daemon.py` owns HTTP, widget state, page state, and PNG rendering.
- `daemon/card_render.py` owns widget layout and Pillow drawing.
- `examples/*.py` are optional producers that push widget JSON to the daemon.

The daemon stores local state under `~/.kindle-side-card` by default. Override
with `KINDLE_SIDE_CARD_STATE_DIR` when running multiple copies.

## Kindle Side

- `kindle/kindle-side-card/` is a KUAL extension.
- The shell script downloads `/kindle/frame.png` with `wget`.
- The script paints the frame using `eips -g`.
- The script periodically repaints the cached frame to reduce home-screen redraw interference.

The Kindle does not parse widgets, run Python, or know about AI tools.

## Widget Flow

```text
Producer
  -> POST /widget
  -> widget cache
  -> card_render.render_kindle_image()
  -> /tmp/kindle_side_card.png
  -> GET /kindle/frame.png
  -> KUAL script
  -> eips
```

## Page Model

The daemon defaults to two pages:

- Page 1: top-left, top-right, main, middle, and bottom slots.
- Page 2: placeholder unless a full-screen widget is active.

Set `KINDLE_SIDE_CARD_PAGE_COUNT=1` to disable the second page, or
`KINDLE_SIDE_CARD_AUTO_PAGE_SECONDS=0` to disable automatic page rotation.

## Security Model

The daemon is designed for a trusted LAN. It does not implement authentication.
Do not expose the daemon to the public internet.
