#!/bin/sh
# geektyper — opens geektyper.com in its own app window (like a real app, not a browser tab)
URL="https://geektyper.com/"
for b in chromium chromium-browser google-chrome-stable google-chrome brave brave-browser microsoft-edge-stable vivaldi-stable; do
  command -v "$b" >/dev/null 2>&1 && exec "$b" --app="$URL" "$@"
done
command -v firefox >/dev/null 2>&1 && exec firefox --new-window "$URL"
exec xdg-open "$URL"
