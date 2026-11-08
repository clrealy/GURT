#!/usr/bin/env bash
# the GURT infomercial: renders promo/gurt-ad.mp4 (16:9) and promo/gurt-ad-vertical.mp4 (9:16, Shorts/TikTok/Reels)
# needs: node + Playwright (Chromium), ffmpeg, espeak-ng, python3, and the internet for the Google Fonts
set -euo pipefail
cd "$(dirname "$0")"
work=$(mktemp -d); trap 'kill "$srv" 2>/dev/null || true; rm -rf "$work"' EXIT
python3 -m http.server 8750 --bind 127.0.0.1 >/dev/null 2>&1 & srv=$!
sleep 1
python3 make-audio.py "$work/ad.wav"
node render.js http://127.0.0.1:8750/ad.html "$work/wide" 1920 1080 30 & a=$!
node render.js http://127.0.0.1:8750/ad.html "$work/tall" 1080 1920 30 & b=$!
wait "$a" "$b"
for v in wide:gurt-ad tall:gurt-ad-vertical; do
  ffmpeg -v error -y -framerate 30 -i "$work/${v%%:*}/f%05d.jpg" -i "$work/ad.wav" \
    -af "loudnorm=I=-14:TP=-1.5:LRA=11" -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -c:a aac -b:a 160k -ar 44100 \
    -movflags +faststart -shortest "../${v#*:}.mp4"
  echo "made promo/${v#*:}.mp4"
done
