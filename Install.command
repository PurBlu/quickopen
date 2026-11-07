#!/bin/bash
# Double-click this file to install QuickOpen as a macOS background service.
# It opens Terminal, registers a launchd LaunchAgent and starts everything.
cd "$(dirname "$0")" || exit 1
echo "Installing QuickOpen background service..."
echo
./install.sh
echo
echo "----------------------------------------------------------"
echo "Done. You can close this window; the service keeps running."
echo "It will start automatically on every login."
echo "To check status, double-click Status.command."
echo "----------------------------------------------------------"
