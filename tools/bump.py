#!/usr/bin/env python3
"""GURT bump bot 🤖 — finds recipes whose GitHub project has a newer release and bumps them.

  python3 tools/bump.py            # dry run: just print what's outdated
  python3 tools/bump.py --write    # edit the recipes in place (pkgver, pkgrel=1, checksums, .gurtinfo)
  python3 tools/bump.py --pr       # one branch + pull request per bumped package (CI uses this)
  python3 tools/bump.py --only btop

Only touches recipes that (1) use $pkgver in a source and (2) point at github.com.
Opt a recipe out with a line:  nobump=true
"""
import json, os, re, subprocess, sys, urllib.request, urllib.error, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
GH_RE = re.compile(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?(?=[/#?\"')\s]|$)")


def api(path):
    req = urllib.request.Request(os.environ.get("GURT_BUMP_API", "https://api.github.com") + path, headers={"Accept": "application/vnd.github+json", "User-Agent": "gurt-bump-bot"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def vkey(v):
    """version → sortable tuple (1.10 > 1.9, 2.0 > 2.0rc1)."""
    out = []
    for part in re.findall(r"\d+|[A-Za-z]+", v):
        out.append((1, int(part), "") if part.isdigit() else (0, 0, part.lower()))
    return tuple(out)


def clean_tag(tag, name):
    t = tag.strip()
    for p in (f"{name}-", f"{name}_", f"{name} ", "release-", "version-", "v", "V"):
        if t.lower().startswith(p.lower()):
            t = t[len(p):]
    return t if re.fullmatch(r"\d[0-9A-Za-z.+~]*", t) else None


def latest(owner, repo, name):
    rel = api(f"/repos/{owner}/{repo}/releases/latest")
    if rel and not rel.get("prerelease") and not rel.get("draft"):
        v = clean_tag(rel.get("tag_name", ""), name)
        if v:
            return v
    tags = api(f"/repos/{owner}/{repo}/tags?per_page=100") or []
    vs = [v for v in (clean_tag(t["name"], name) for t in tags) if v and not re.search(r"(rc|alpha|beta|pre|dev)", v, re.I)]
    return max(vs, key=vkey) if vs else None


def field(text, key):
    m = re.search(rf"^{key}=[\"']?([^\"'\s]*)", text, re.M)
    return m.group(1) if m else None


def recipes(only):
    for tree in ("packages", "dirt"):
        for f in sorted((ROOT / tree).glob("*/GURTBUILD")):
            if not only or f.parent.name in only:
                yield f


def check(f):
    text = f.read_text()
    name, ver = field(text, "pkgname"), field(text, "pkgver")
    if re.search(r"^(nobump|via_repo)=", text, re.M) or not ver or not re.fullmatch(r"\d[0-9A-Za-z.+~]*", ver):
        return None
    srcs = re.search(r"^source=\((.*?)\)", text, re.M | re.S)
    srcs = srcs.group(1) if srcs else ""
    if not re.search(r"\$\{?pkgver\}?", srcs):
        return None                      # version isn't used by the download → nothing to bump
    m = GH_RE.search(srcs) or GH_RE.search(field(text, "url") or "")
    if not m:
        return None
    new = latest(m.group(1), m.group(2), name)
    if new and vkey(new) > vkey(ver):
        return {"name": name, "dir": f.parent, "old": ver, "new": new, "repo": f"{m.group(1)}/{m.group(2)}"}
    return None


def write(b):
    f = b["dir"] / "GURTBUILD"
    text = f.read_text()
    text = re.sub(r"^pkgver=.*$", f"pkgver={b['new']}", text, count=1, flags=re.M)
    text = re.sub(r"^pkgrel=.*$", "pkgrel=1", text, count=1, flags=re.M)
    f.write_text(text)
    # new checksums (git sources stay SKIP)
    out = subprocess.run([str(ROOT / "gurt"), "checksum", str(b["dir"])], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"checksum failed for {b['name']}: {out.stderr.strip()}")
    sums = [l.split()[0] for l in out.stdout.splitlines() if l.strip()]
    if sums:
        arr = "sha256sums=(" + " ".join(s if s == "SKIP" else f"'{s}'" for s in sums) + ")"
        text = re.sub(r"^sha256sums=\(.*?\)", arr, f.read_text(), count=1, flags=re.M | re.S)
        f.write_text(text)
    info = subprocess.run([str(ROOT / "gurt"), "srcinfo", str(b["dir"])], capture_output=True, text=True, check=True)
    (b["dir"] / ".gurtinfo").write_text(info.stdout)


def git(*a, check=True):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=check)


def open_pr(b):
    branch = f"bump/{b['name']}-{b['new']}"
    if git("ls-remote", "--exit-code", "--heads", "origin", branch, check=False).returncode == 0:
        print(f"  {b['name']}: PR branch {branch} already exists, skipping")
        return
    base = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    git("checkout", "-q", "-b", branch)
    try:
        write(b)
        rel = b["dir"].relative_to(ROOT)
        git("add", str(rel))
        git("commit", "-q", "-m", f"{b['name']}: {b['old']} -> {b['new']}\n\nbumped by the GURT bump bot 🤖")
        git("push", "-q", "origin", branch)
        body = (f"🤖 **{b['name']}** has a new release upstream: **{b['old']} → {b['new']}**\n\n"
                f"https://github.com/{b['repo']}/releases\n\n"
                f"pkgver bumped, pkgrel reset to 1, checksums + .gurtinfo regenerated. "
                f"Give it a look (and check the build) before merging 👀")
        subprocess.run(["gh", "pr", "create", "--base", base, "--head", branch,
                        "--title", f"{b['name']}: {b['old']} → {b['new']}", "--body", body], cwd=ROOT, check=True)
    finally:
        git("checkout", "-q", base)


def main():
    args = sys.argv[1:]
    only = [args[i + 1] for i, a in enumerate(args) if a == "--only" and i + 1 < len(args)]
    mode = "pr" if "--pr" in args else "write" if "--write" in args else "dry"
    bumps, failed = [], 0
    for f in recipes(only):
        try:
            b = check(f)
        except Exception as e:  # one broken upstream shouldn't stop the rest
            print(f"⚠️  {f.parent.name}: {e}")
            failed += 1
            continue
        if b:
            print(f"⬆️  {b['name']}: {b['old']} -> {b['new']}  ({b['repo']})")
            bumps.append(b)
    if not bumps:
        print("everything's up to date 😎")
    for b in bumps:
        try:
            if mode == "write":
                write(b)
            elif mode == "pr":
                open_pr(b)
        except Exception as e:
            print(f"⚠️  {b['name']}: {e}")
            failed += 1
    return 1 if failed and not bumps else 0


if __name__ == "__main__":
    sys.exit(main())
