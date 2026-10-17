#!/usr/bin/env python3
"""GURT bump bot 🤖 — finds recipes whose GitHub project has a newer release and bumps them.

  python3 tools/bump.py            # dry run: just print what's outdated
  python3 tools/bump.py --write    # edit the recipes in place (pkgver, pkgrel=1, checksums, .gurtinfo)
  python3 tools/bump.py --pr       # one branch + pull request per bumped package (CI uses this)
  python3 tools/bump.py --only btop

Only touches recipes that (1) use $pkgver in a source (directly, through a helper like _tag=v$pkgver, or in
per-arch source_x86_64=(...) arrays) and (2) point at github.com.
Opt a recipe out with a line:  nobump=true
"""
import hashlib, json, os, re, subprocess, sys, urllib.request, urllib.error, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
MAX_PRS = int(os.environ.get("GURT_BUMP_MAX", "15"))   # per run, so a big first sweep doesn't drop 200 PRs at once
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


SENTINEL = "0.0.0gurtbump"
SH = r'''
set -e; cd "$1"; prefix=/usr/local; CARCH=x86_64
eval "$(cat)"
for v in source $(compgen -v | grep -E '^source_[A-Za-z0-9_]+$' || true); do
  declare -n a=$v; for s in "${a[@]}"; do printf 'SRC\t%s\t%s\n' "$v" "$s"; done; unset -n a
done
'''


def sources(d, text):
    """evaluate the recipe in bash → {"source": [...], "source_x86_64": [...], ...} (catches _tag=v$pkgver and friends)"""
    out = subprocess.run(["bash", "-c", SH, "bump", str(d)], input=text, capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(f"couldn't read the recipe: {out.stderr.strip()[:200]}")
    srcs = {}
    for line in out.stdout.splitlines():
        k, *rest = line.split("\t")
        if k == "SRC" and len(rest) == 2:
            srcs.setdefault(rest[0], []).append(rest[1])
    return srcs


def check(f):
    text = f.read_text()
    name, ver = field(text, "pkgname"), field(text, "pkgver")
    if re.search(r"^(nobump|via_repo|via_type)=", text, re.M) or not ver or not re.fullmatch(r"\d[0-9A-Za-z.+~]*", ver):
        return None
    probe = re.sub(r"^pkgver=.*$", f"pkgver={SENTINEL}", text, count=1, flags=re.M)
    srcs = sources(f.parent, probe)
    flat = " ".join(s for v in srcs.values() for s in v)
    if SENTINEL not in flat:
        return None                      # version isn't used by the download → nothing to bump
    m = GH_RE.search(flat) or GH_RE.search(field(text, "url") or "")
    if not m:
        return None
    new = latest(m.group(1), m.group(2), name)
    if new and vkey(new) > vkey(ver):
        return {"name": name, "dir": f.parent, "old": ver, "new": new, "repo": f"{m.group(1)}/{m.group(2)}"}
    return None


def sha256_of(d, src):
    loc = src.split("::", 1)[1] if "::" in src else src
    if loc.startswith("git+"):
        return "SKIP"
    h = hashlib.sha256()
    if re.match(r"(https?|ftp)://", loc):
        req = urllib.request.Request(loc, headers={"User-Agent": "gurt-bump-bot"})
        with urllib.request.urlopen(req, timeout=120) as r:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                h.update(chunk)
    else:
        h.update((d / loc).read_bytes())
    return h.hexdigest()


def write(b):
    f = b["dir"] / "GURTBUILD"
    text = f.read_text()
    text = re.sub(r"^pkgver=.*$", f"pkgver={b['new']}", text, count=1, flags=re.M)
    text = re.sub(r"^pkgrel=.*$", "pkgrel=1", text, count=1, flags=re.M)
    # new checksums for every source array (source → sha256sums, source_aarch64 → sha256sums_aarch64); git stays SKIP
    for var, srcs in sources(b["dir"], text).items():
        sums = [sha256_of(b["dir"], s) for s in srcs]
        key = "sha256sums" + var[len("source"):]
        arr = f"{key}=(" + " ".join(x if x == "SKIP" else f"'{x}'" for x in sums) + ")"
        text, n = re.subn(rf"^{key}=\(.*?\)", lambda _: arr, text, count=1, flags=re.M | re.S)
        if not n:
            raise RuntimeError(f"no {key}=() line to update")
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
    if mode == "pr" and len(bumps) > MAX_PRS:
        print(f"opening {MAX_PRS} PRs now, the other {len(bumps) - MAX_PRS} come on the next runs")
        bumps = bumps[:MAX_PRS]
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
