#!/usr/bin/env python3
"""Builds site/packages.json (Main GURT) and site/dirt.json (DIRT, shown behind the 18+ gate) from .gurtinfo files (never executes recipes)."""
import json, pathlib, subprocess, time
root = pathlib.Path(__file__).resolve().parent.parent
LIST = {"arch", "depends", "makedepends", "source", "alias"}
def collect(tree):
    pkgs = []
    for info in sorted(root.glob(f"{tree}/*/.gurtinfo")):
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
        if p.get("hidden") == "true":
            continue   # hidden = installable by name, but not listed in the store
        pkgs.append(p)
    return pkgs

for tree, fname in (("packages", "packages.json"), ("dirt", "dirt.json")):
    pkgs = collect(tree)
    out = root / "site" / fname
    out.write_text(json.dumps({"generated": int(time.time()), "packages": pkgs}, indent=1))
    print(f"wrote {len(pkgs)} {tree} -> {out.relative_to(root)}")
