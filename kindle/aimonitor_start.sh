#!/bin/sh
# Name: AI Monitor - Start
# Author: kindle_aimonitor
# DontUseFBInk
# Keep the screen awake and open the dashboard in the browser.
# The URL below is filled in by `kindlemon install`.
URL="__URL__"
lipc-set-prop com.lab126.powerd preventScreenSaver 1
lipc-set-prop com.lab126.appmgrd start "app://com.lab126.browser?view=$URL"
