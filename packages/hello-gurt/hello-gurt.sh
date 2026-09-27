#!/bin/sh
# the "hello world" of gurt. if this runs, your setup is bussin.
echo "gurt: yo 🦆"
echo "(installed by gurt — works on $(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-your distro}"))"
