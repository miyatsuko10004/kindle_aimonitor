#!/bin/sh
# Name: AI Monitor - Start
# Author: kindle_aimonitor
# DontUseFBInk
# Draw the dashboard image full screen every minute and keep the screen awake.
# Press the power button to stop. The URL below is filled in by `kindlemon install`.
URL="__IMAGE_URL__"
PIDFILE=/tmp/aimonitor.pid
IMG=/tmp/aimonitor.png

[ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
lipc-set-prop com.lab126.powerd preventScreenSaver 1

# Detached so it outlives the scriptlet; the Kindle returns to the library
# when a scriptlet ends, so wait for that redraw before drawing.
(
  trap 'lipc-set-prop com.lab126.powerd preventScreenSaver 0; rm -f "$PIDFILE"' EXIT
  trap 'exit 0' TERM
  sleep 3
  n=0
  while :; do
    if curl -sf -m 20 -o "$IMG.tmp" "$URL" || wget -q -T 20 -O "$IMG.tmp" "$URL"; then
      mv "$IMG.tmp" "$IMG"
      # Full refresh every 10 draws clears e-ink ghosting; partial otherwise.
      if [ $((n % 10)) -eq 0 ]; then eips -f -g "$IMG"; else eips -g "$IMG"; fi
      n=$((n + 1))
    fi
    # Check every 5 s whether the power button sent the Kindle to sleep.
    i=0
    while [ $i -lt 12 ]; do
      sleep 5
      case "$(lipc-get-prop com.lab126.powerd state 2>/dev/null)" in
        screenSaver|readyToSuspend|suspended) exit 0 ;;
      esac
      i=$((i + 1))
    done
  done
) </dev/null >/dev/null 2>&1 &
echo $! > "$PIDFILE"
