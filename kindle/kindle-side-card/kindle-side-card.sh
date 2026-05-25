#!/bin/sh
set -eu

BASE="$(dirname "$0")"
CONF="$BASE/kindle-side-card.conf"
PIDFILE="$BASE/kindle-side-card.pid"
TOUCHPIDFILE="$BASE/kindle-side-card-touch.pid"
LOGFILE="$BASE/kindle-side-card.log"
STOPFILE="$BASE/stop-kiosk.flag"
FRAME="/tmp/kindle-side-card.png"
TMPFRAME="/tmp/kindle-side-card.next.png"

if [ -f "$CONF" ]; then
  # shellcheck disable=SC1090
  . "$CONF"
fi

: "${AIDESCARD_URL:=http://YOUR_COMPUTER_IP:9878/kindle/frame.png}"
: "${AIDESCARD_INTERVAL:=60}"
: "${AIDESCARD_REPAINT_INTERVAL:=15}"
: "${AIDESCARD_START_DELAY:=5}"
: "${AIDESCARD_START_RETRY_SECONDS:=90}"
: "${AIDESCARD_START_RETRY_INTERVAL:=5}"
: "${AIDESCARD_TOUCH:=0}"
: "${AIDESCARD_SWIPE_THRESHOLD:=180}"
: "${AIDESCARD_TOUCH_MIN_Y:=250}"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOGFILE"
}

msg() {
  eips 2 2 "$1" || true
  log "$1"
}

fetch_frame() {
  url="${AIDESCARD_URL}?ts=$(date +%s)"
  if wget -q -T 15 -O "$TMPFRAME" "$url"; then
    mv "$TMPFRAME" "$FRAME"
    return 0
  fi
  rc="$?"
  log "Kindle Side Card wget failed ($rc): $url"
  rm -f "$TMPFRAME"
  return 1
}

paint_frame_full() {
  if [ ! -s "$FRAME" ]; then
    return 1
  fi
  eips -c || true
  eips -g "$FRAME" -f || eips -g "$FRAME" || true
}

paint_frame_light() {
  if [ ! -s "$FRAME" ]; then
    return 1
  fi
  eips -g "$FRAME" || true
}

fetch_and_paint() {
  if fetch_frame; then
    paint_frame_full || true
    return 0
  fi
  msg "Kindle Side Card fetch failed"
  return 1
}

api_base() {
  if [ "${AIDESCARD_API:-}" ]; then
    printf '%s' "$AIDESCARD_API"
    return
  fi

  base="$AIDESCARD_URL"
  case "$base" in
    */kindle/frame.png) base="${base%/kindle/frame.png}" ;;
    */frame.png) base="${base%/frame.png}" ;;
  esac
  printf '%s' "$base"
}

page_action() {
  action="$1"
  base="$(api_base)"
  if wget -q -T 5 -O /tmp/kindle-side-card-page.json "$base/kindle/page/$action"; then
    log "Kindle Side Card page action: $action"
    fetch_and_paint || true
    return 0
  fi
  log "Kindle Side Card page action failed: $action"
  return 1
}

touch_listener() {
  dev="$1"
  start_x=""
  start_y=""
  cur_x=""
  cur_y=""
  down=0

  hexdump -v -e '16/1 "%02x " "\n"' "$dev" 2>/dev/null |
  while read b0 b1 b2 b3 b4 b5 b6 b7 b8 b9 b10 b11 b12 b13 b14 b15; do
    [ "${b15:-}" ] || continue
    type=$((0x${b9}${b8}))
    code=$((0x${b11}${b10}))
    value=$((0x${b15}${b14}${b13}${b12}))

    if [ "$type" -eq 3 ]; then
      case "$code" in
        0|53) cur_x="$value" ;;
        1|54) cur_y="$value" ;;
      esac
      continue
    fi

    if [ "$type" -eq 1 ] && [ "$code" -eq 330 ]; then
      if [ "$value" -eq 1 ]; then
        down=1
        start_x="$cur_x"
        start_y="$cur_y"
      elif [ "$value" -eq 0 ] && [ "$down" -eq 1 ]; then
        down=0
        [ "$start_x" ] || continue
        [ "$start_y" ] || continue
        [ "$cur_x" ] || continue
        [ "$start_y" -ge "$AIDESCARD_TOUCH_MIN_Y" ] || continue

        dx=$((cur_x - start_x))
        if [ "$dx" -le "-$AIDESCARD_SWIPE_THRESHOLD" ]; then
          page_action next || true
        elif [ "$dx" -ge "$AIDESCARD_SWIPE_THRESHOLD" ]; then
          page_action prev || true
        elif [ "$cur_x" -lt 250 ]; then
          page_action prev || true
        elif [ "$cur_x" -gt 500 ]; then
          page_action next || true
        fi
      fi
    fi
  done
}

stop_touch_listeners() {
  if [ -f "$TOUCHPIDFILE" ]; then
    while read pid; do
      [ "$pid" ] && kill "$pid" 2>/dev/null || true
    done < "$TOUCHPIDFILE"
    rm -f "$TOUCHPIDFILE"
  fi
}

start_touch_listeners() {
  [ "$AIDESCARD_TOUCH" = "1" ] || return 0
  stop_touch_listeners
  : > "$TOUCHPIDFILE"
  for dev in /dev/input/event*; do
    [ -e "$dev" ] || continue
    touch_listener "$dev" &
    echo "$!" >> "$TOUCHPIDFILE"
    log "Kindle Side Card touch listener started for $dev"
  done
}

start_framework() {
  log "Starting Kindle framework"
  initctl start framework 2>/dev/null || /etc/init.d/framework start 2>/dev/null || true
}

stop_existing_loop() {
  stop_touch_listeners
  if [ -f "$PIDFILE" ]; then
    pid="$(cat "$PIDFILE")"
    kill "$pid" 2>/dev/null || true
    rm -f "$PIDFILE"
  fi
}

run_loop() {
  delay="$1"

  lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null || true
  log "Kindle Side Card starting conservative mode"
  sleep "$delay"

  last_fetch=0
  deadline=$(($(date +%s) + AIDESCARD_START_RETRY_SECONDS))
  wait_msg_shown=0
  while true; do
    if fetch_frame; then
      last_fetch="$(date +%s)"
      break
    fi

    now="$(date +%s)"
    if [ "$now" -ge "$deadline" ]; then
      msg "Kindle Side Card fetch failed"
      break
    fi

    if [ "$wait_msg_shown" -eq 0 ]; then
      msg "Kindle Side Card waiting for Wi-Fi"
      wait_msg_shown=1
    fi
    sleep "$AIDESCARD_START_RETRY_INTERVAL"
  done
  paint_frame_full || msg "Kindle Side Card has no frame"
  sleep 2
  paint_frame_light || true
  sleep 5
  paint_frame_light || true
  start_touch_listeners

  while true; do
    if [ -f "$STOPFILE" ]; then
      rm -f "$STOPFILE"
      break
    fi

    sleep "$AIDESCARD_REPAINT_INTERVAL"
    now="$(date +%s)"
    fetched=0
    if [ "$last_fetch" -eq 0 ] || [ $((now - last_fetch)) -ge "$AIDESCARD_INTERVAL" ]; then
      if fetch_frame; then
        last_fetch="$now"
        fetched=1
      else
        log "Kindle Side Card fetch failed; repainting cached frame"
      fi
    fi
    if [ "$fetched" -eq 1 ]; then
      paint_frame_full || log "Kindle Side Card has no cached frame to repaint"
    else
      paint_frame_light || log "Kindle Side Card has no cached frame to repaint"
    fi
  done

  rm -f "$PIDFILE"
  stop_touch_listeners
  lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null || true
  log "Kindle Side Card stopped"
}

start_loop() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    msg "Kindle Side Card already running"
    exit 0
  fi

  rm -f "$STOPFILE"
  run_loop "$AIDESCARD_START_DELAY" &
  echo "$!" > "$PIDFILE"
  log "Kindle Side Card started"
}

stop_loop() {
  touch "$STOPFILE"
  stop_existing_loop
  start_framework
  lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null || true
  msg "Kindle Side Card stopped"
}

case "${1:-refresh}" in
  start)
    start_loop
    ;;
  stop)
    stop_loop
    ;;
  refresh)
    fetch_and_paint || true
    ;;
  next)
    page_action next || true
    ;;
  prev)
    page_action prev || true
    ;;
  *)
    msg "Usage: $0 start|stop|refresh|next|prev"
    exit 2
    ;;
esac
