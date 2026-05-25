# Troubleshooting

## The Kindle Shows a Blank Screen

Verify the daemon first:

```bash
curl http://127.0.0.1:9878/heartbeat
curl -o /tmp/frame.png http://127.0.0.1:9878/kindle/frame.png
```

Then verify the LAN URL from another device:

```bash
curl http://YOUR_COMPUTER_IP:9878/heartbeat
```

If LAN access fails, check the computer IP, firewall, and Wi-Fi network.

## KUAL Says the Fetch Failed

Edit `kindle-side-card.conf` on the Kindle and confirm:

```sh
AIDESCARD_URL="http://YOUR_COMPUTER_IP:9878/kindle/frame.png"
```

The URL must use the computer LAN IP, not `127.0.0.1`.

## The Kindle Home Screen Covers the Dashboard

Start the KUAL extension again. The script repaints the cached frame every
`AIDESCARD_REPAINT_INTERVAL` seconds. The default is 15 seconds.

## Touch Controls Open Books

Keep `AIDESCARD_TOUCH=0`. Some Kindle launchers receive touch events underneath
the extension. Use KUAL menu actions or automatic page rotation instead.

## The Frame Renders Locally but Not on Kindle

Confirm that `eips -g` supports PNG drawing on your Kindle model. Some models or
firmware builds may need a different draw command.

## The AI Limits Widget Is Empty

That is expected until you push a widget payload with `providers`. This repo
does not read private AI account state. See `examples/push-demo-widgets.py` for
the expected JSON shape.
