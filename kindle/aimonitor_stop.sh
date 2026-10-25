#!/bin/sh
# Name: AI Monitor - Stop
# Author: kindle_aimonitor
# DontUseFBInk
# Stop drawing the dashboard and allow the screensaver again.
PIDFILE=/tmp/aimonitor.pid
[ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
rm -f "$PIDFILE"
lipc-set-prop com.lab126.powerd preventScreenSaver 0
