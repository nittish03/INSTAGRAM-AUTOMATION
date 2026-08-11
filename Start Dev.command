#!/usr/bin/env bash
# Double-click this file in Finder to start Leadway (Instagram API + frontend).
# Use ./run-dev.sh --daemon for the Instagram automation worker as well.

cd "$(dirname "$0")"
./run-dev.sh
echo
echo "Leadway Instagram outreach"
echo "  Backend  -> http://127.0.0.1:8000"
echo "  Frontend -> http://localhost:3000"
echo
echo "You can close this window. Servers are running in the other Terminal windows."
echo "Press Enter to close..."
read -r
