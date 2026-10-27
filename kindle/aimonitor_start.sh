#!/bin/sh
# Name: AI Monitor - Start
# Author: kindle_aimonitor
# DontUseFBInk
# 5分ごとに画像を表示。通信失敗時は再試行間隔を最大30分まで延ばす。
# Press the power button to stop. The URL below is filled in by `kindlemon install`.
URL="__IMAGE_URL__"
PIDFILE=/tmp/aimonitor.pid
IMG=/tmp/aimonitor.png
INTERVAL=300
MAX_RETRY=1800

# curl がある環境では、通信失敗のたびに wget で再試行しない。
if command -v curl >/dev/null 2>&1; then
  fetch_image() { curl -sf -m 20 -o "$IMG.tmp" "$URL"; }
else
  fetch_image() { wget -q -T 20 -O "$IMG.tmp" "$URL"; }
fi

[ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
lipc-set-prop com.lab126.powerd preventScreenSaver 1

# Detached so it outlives the scriptlet; the Kindle returns to the library
# when a scriptlet ends, so wait for that redraw before drawing.
(
  trap 'lipc-set-prop com.lab126.powerd preventScreenSaver 0; rm -f "$PIDFILE"' EXIT
  trap 'exit 0' TERM
  sleep 3
  n=0
  delay=$INTERVAL
  while :; do
    if fetch_image; then
      delay=$INTERVAL
      mv "$IMG.tmp" "$IMG"
      # Full refresh every 10 draws clears e-ink ghosting; partial otherwise.
      if [ $((n % 10)) -eq 0 ]; then eips -f -g "$IMG"; else eips -g "$IMG"; fi
      n=$((n + 1))
    else
      rm -f "$IMG.tmp"
      delay=$((delay * 2))
      [ "$delay" -gt "$MAX_RETRY" ] && delay=$MAX_RETRY
    fi
    # Check every 5 s whether the power button sent the Kindle to sleep.
    i=0
    while [ $i -lt "$delay" ]; do
      sleep 5
      case "$(lipc-get-prop com.lab126.powerd state 2>/dev/null)" in
        screenSaver|readyToSuspend|suspended) exit 0 ;;
      esac
      i=$((i + 5))
    done
  done
) </dev/null >/dev/null 2>&1 &
echo $! > "$PIDFILE"
