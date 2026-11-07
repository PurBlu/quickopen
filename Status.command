#!/bin/bash
# Double-click to print a quick status report of the local service.
cd "$(dirname "$0")" || exit 1
./status.sh
echo
echo "Web console: http://127.0.0.1:${QO_PORT:-8787}"
echo "(Closing this window does not stop the background service.)"
