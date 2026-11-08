#!/usr/bin/env bash
# builds GURT's app (app/) for x86_64 + aarch64, linked against glibc 2.28 so it runs on any distro from 2018 on
#   tools/build-app.sh [out-dir]   → out-dir/gurt-app-x86_64 + out-dir/gurt-app-aarch64 (default: dist-app/)
# needs rustup + cargo-zigbuild + zig (pip install cargo-zigbuild ziglang); tools/make-setup-wizard.sh packs what it makes
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
out=${1:-$root/dist-app}
mkdir -p "$out"; out=$(cd "$out" && pwd)
command -v cargo-zigbuild >/dev/null || { echo "needs cargo-zigbuild: pip install cargo-zigbuild ziglang" >&2; exit 1; }
# zig from pip lives inside python's ziglang module; point cargo-zigbuild at it when zig isn't on the PATH
if ! command -v zig >/dev/null && [[ -z ${CARGO_ZIGBUILD_ZIG_PATH:-} ]]; then
  for py in python3 /usr/bin/python3; do
    z=$("$py" -c 'import ziglang, os; print(os.path.join(os.path.dirname(ziglang.__file__), "zig"))' 2>/dev/null) || continue
    [[ -x $z ]] && { export CARGO_ZIGBUILD_ZIG_PATH=$z; break; }
  done
fi
cd "$root/app"
for arch in x86_64 aarch64; do
  rustup target add "$arch-unknown-linux-gnu" >/dev/null 2>&1 || true
  cargo zigbuild --release --locked --target "$arch-unknown-linux-gnu.2.28"
  install -m755 "target/$arch-unknown-linux-gnu/release/gurt-app" "$out/gurt-app-$arch"
  echo "made $out/gurt-app-$arch"
done
