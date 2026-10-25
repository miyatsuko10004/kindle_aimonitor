#!/bin/sh
# Name: AI Monitor - Start
# Author: kindle_aimonitor
# DontUseFBInk
# Keep the screen awake and open the dashboard in the browser.
# The URL below is filled in by `kindlemon install`.
URL="__URL__"
lipc-set-prop com.lab126.powerd preventScreenSaver 1
# The Kindle returns to the library when a scriptlet ends, which would hide the
# browser. Open it from a detached background job after that has happened.
(
  sleep 4
  lipc-set-prop com.lab126.appmgrd start "app://com.lab126.browser?view=$URL"
) </dev/null >/dev/null 2>&1 &
