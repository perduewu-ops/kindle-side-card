# Install

## Requirements

- macOS or Linux computer on the same Wi-Fi network as the Kindle.
- Python 3.10 or newer.
- Pillow, installed from `requirements.txt`.
- Jailbroken Kindle with KUAL installed.
- A Kindle model that supports `eips -g` for drawing PNG frames.

This project does not include jailbreak instructions or exploit tooling. Install
and maintain your Kindle jailbreak separately.

## Run the Daemon

```bash
git clone https://github.com/perduewu-ops/kindle-side-card.git
cd kindle-side-card
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python daemon/kindle_daemon.py --host 0.0.0.0 --port 9878
```

Open the preview URL from the same computer:

```bash
curl -o /tmp/kindle-side-card.png http://127.0.0.1:9878/kindle/frame.png
```

Push demo widgets:

```bash
python examples/push-demo-widgets.py
```

## Find Your Computer IP

On macOS:

```bash
ipconfig getifaddr en0
```

On Linux:

```bash
hostname -I
```

The Kindle must be able to reach:

```text
http://YOUR_COMPUTER_IP:9878/kindle/frame.png
```

## Install the KUAL Extension

1. Connect the Kindle over USB.
2. Copy `kindle/kindle-side-card/` into the Kindle extensions directory.
3. Copy `kindle-side-card.conf.example` to `kindle-side-card.conf`.
4. Edit `AIDESCARD_URL` to point at your computer IP.
5. Eject the Kindle.
6. Open KUAL and choose `Kindle Side Card -> Start`.

## Optional macOS System Widget

```bash
python examples/macos-system-widget.py --daemon http://127.0.0.1:9878 --once
```

Run without `--once` to keep updating the `system` widget every 60 seconds.
