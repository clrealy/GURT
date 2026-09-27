#!/usr/bin/env python3
"""Builds site/packages.json from every packages/*/.gurtinfo (never executes recipes)."""
import json, pathlib, subprocess, time
root = pathlib.Path(__file__).resolve().parent.parent
LIST = {"arch", "depends", "makedepends", "source"}
pkgs = []
for info in sorted(root.glob("packages/*/.gurtinfo")):
    p = {k: [] for k in LIST}
    for line in info.read_text().splitlines():
        if " = " not in line:
            continue
        k, v = line.split(" = ", 1)
        (p[k].append(v) if k in LIST else p.__setitem__(k, v))
    try:
        ts = subprocess.run(["git", "log", "-1", "--format=%ct", "--", str(info.parent)],
                            cwd=root, capture_output=True, text=True).stdout.strip()
        p["updated"] = int(ts) if ts else int(time.time())
    except Exception:
        p["updated"] = int(time.time())
    pkgs.append(p)
out = root / "site" / "packages.json"
out.write_text(json.dumps({"generated": int(time.time()), "packages": pkgs}, indent=1))
print(f"wrote {len(pkgs)} packages -> {out.relative_to(root)}")
