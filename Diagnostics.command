#!/bin/bash
# Double-click to run a harmless protocol health check.
# Uses a fake phone number, a fake SMS code and a fake session;
# it never sends an SMS, logs in, or opens a door.
cd "$(dirname "$0")" || exit 1
/usr/bin/python3 diagnose.py
echo
echo "(Closing this window does not stop the background service.)"
