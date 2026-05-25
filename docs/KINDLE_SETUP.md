# Kindle Setup

## Boundary

Kindle Side Card assumes your Kindle is already jailbroken and can run KUAL
extensions. The repo intentionally does not bundle jailbreak pages, hotfixes,
or exploit helpers.

## KUAL Layout

After copying the extension, the Kindle should contain:

```text
extensions/
  kindle-side-card/
    config.xml
    menu.json
    kindle-side-card.sh
    kindle-side-card.conf
```

`kindle-side-card.conf` is machine-local and should not be committed.

## Configuration

```sh
AIDESCARD_URL="http://YOUR_COMPUTER_IP:9878/kindle/frame.png"
AIDESCARD_INTERVAL=60
AIDESCARD_REPAINT_INTERVAL=15
AIDESCARD_TOUCH=0
```

- `AIDESCARD_INTERVAL` controls how often the Kindle downloads a fresh PNG.
- `AIDESCARD_REPAINT_INTERVAL` controls how often the Kindle repaints the cached frame.
- `AIDESCARD_TOUCH=0` is the recommended default. Some Kindle launchers pass touch events through to the home screen.

## KUAL Actions

- `Start`: starts the refresh loop.
- `Refresh Once`: downloads and paints one frame.
- `Previous Page`: asks the daemon to switch to the previous page.
- `Next Page`: asks the daemon to switch to the next page.
- `Stop`: stops the loop and restarts the Kindle framework when possible.

## Wi-Fi Notes

The Kindle and computer must be on the same LAN. If the Kindle shows a blank or
old frame, verify from another device on the same network:

```bash
curl http://YOUR_COMPUTER_IP:9878/heartbeat
curl -o /tmp/frame.png http://YOUR_COMPUTER_IP:9878/kindle/frame.png
```

If those commands fail, fix the daemon, firewall, or computer IP before
debugging the Kindle extension.
