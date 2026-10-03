#!/usr/bin/env python3
"""Add Flathub's most popular apps to Main GURT as recipes (skips ones GURT already has).

usage: tools/gen-flathub.py <how-many-new>     (needs internet: it reads flathub.org's API)
       tools/gen-flathub.py recategorize       (re-sort the categories of recipes this tool made)
Writes packages/<name>/GURTBUILD; run `gurt srcinfo` after to refresh .gurtinfo (the workflow does).
"""
import json, os, re, sys, urllib.request

API = "https://flathub.org/api/v2"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PKGS = os.path.join(ROOT, "packages")
WANT = int(sys.argv[1]) if len(sys.argv) > 1 else 100

# Flathub's search index sends these in lowercase, its appstream data capitalized: compare lowercase
CATS = {"audiovideo": "media", "audio": "media", "video": "media", "development": "dev", "education": "office", "game": "gaming",
        "graphics": "creative", "network": "internet", "office": "office", "science": "office", "system": "system", "utility": "system"}


def category(hit):
    cats = hit.get("main_categories") or hit.get("categories") or []
    if isinstance(cats, str):
        cats = [cats]
    cats = [str(c).lower() for c in cats]
    sub = " ".join(str(c).lower() for c in (hit.get("sub_categories") or []) + cats)
    cat = next((CATS[c] for c in cats if c in CATS), "system")
    if cat == "internet" and re.search(r"chat|instantmessaging|ircclient|videoconference", sub):
        cat = "chat"
    if cat == "internet" and "webbrowser" in sub:
        cat = "browsers"
    return cat


def get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "gurt-recipe-generator (github.com/clrealy/GURT)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def existing():
    names, ids = set(), set()
    for n in os.listdir(PKGS):
        f = os.path.join(PKGS, n, "GURTBUILD")
        if not os.path.isfile(f):
            continue
        names.add(n)
        s = open(f, encoding="utf-8").read()
        m = re.search(r"^via_pkg=(\S+)", s, re.M)
        if m:
            ids.add(m.group(1).strip("'\""))
        m = re.search(r"^aliases=\(([^)]*)\)", s, re.M)
        if m:
            names.update(m.group(1).split())
    return names, ids


def popular():
    """app hits, most popular first"""
    page = 1
    while True:
        try:
            d = get(f"/collection/popular?page={page}&per_page=250")
        except Exception as e:
            print(f"popular page {page}: {e}", file=sys.stderr)
            break
        hits = d.get("hits", []) if isinstance(d, dict) else d
        if not hits:
            break
        yield from hits
        total = d.get("totalPages") if isinstance(d, dict) else None
        page += 1
        if total and page > total:
            break
    # then everything else Flathub has, in its own order
    try:
        for app_id in get("/appstream"):
            yield {"app_id": app_id}
    except Exception as e:
        print(f"appstream list: {e}", file=sys.stderr)


def clean(s, n=150):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    s = s.replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ").replace("–", "-")
    s = s.replace('"', "'").replace("`", "'").replace("$", "").replace("\\", "")
    s = s.rstrip(". ")
    if len(s) > n:
        s = s[:n].rsplit(" ", 1)[0].rstrip(",;: ")
    return s[:1].upper() + s[1:]


def slug(s):
    s = re.sub(r"[^a-z0-9+]+", "-", s.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


def main():
    names, ids = existing()
    made = 0
    seen = set()
    for hit in popular():
        if made >= WANT:
            break
        app_id = hit.get("app_id") or hit.get("id")
        if not app_id or app_id in ids or app_id in seen or re.search(r"\.(BaseApp|Platform|Sdk|Extension|Locale|Debug)\b", app_id):
            continue
        seen.add(app_id)
        if "name" not in hit or "summary" not in hit:
            try:
                hit = {**get(f"/appstream/{app_id}"), "app_id": app_id}
            except Exception:
                continue
        if hit.get("type") not in (None, "desktop-application", "desktop", "console-application"):
            continue
        name, summary = clean(hit.get("name"), 60), clean(hit.get("summary"))
        if not name or not summary:
            continue
        pkg = slug(name)
        if not pkg or not re.match(r"^[a-z0-9]", pkg) or pkg in names:
            pkg = slug(name + "-" + app_id.rsplit(".", 1)[-1])
        if not pkg or pkg in names or len(pkg) > 60:
            continue
        cat = category(hit)
        lic = clean(hit.get("project_license") or "", 80)
        lic = lic if re.fullmatch(r"[A-Za-z0-9.+\- ()]+", lic or "") else "see Flathub"
        d = os.path.join(PKGS, pkg)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "GURTBUILD"), "w", encoding="utf-8") as f:
            f.write(f"""# {summary} (official Flathub app)
# gurt sets up flatpak + Flathub for you if you don't have them.
pkgname={pkg}
pkgver=flathub
pkgrel=1
pkgdesc="{summary}"
url="https://flathub.org/apps/{app_id}"
license="{lic}"
maintainer="clrealy"
category="{cat}"
arch=(x86_64 aarch64)

via_repo=flathub
via_type=flatpak
via_pkg={app_id}
""")
        names.add(pkg)
        ids.add(app_id)
        made += 1
        print(f"+ {pkg:32} {app_id}")
    print(f"added {made} Flathub apps")


def recategorize():
    """fix the category of recipes this tool made (they carry "(official Flathub app)" in their first line)"""
    todo = {}
    for n in os.listdir(PKGS):
        f = os.path.join(PKGS, n, "GURTBUILD")
        if os.path.isfile(f):
            s = open(f, encoding="utf-8").read()
            m = re.search(r"^via_pkg=(\S+)", s, re.M)
            if m and s.startswith("#") and "(official Flathub app)" in s.split("\n", 1)[0]:
                todo[m.group(1)] = f
    fixed = 0
    for hit in popular():
        app_id = hit.get("app_id") or hit.get("id")
        f = todo.pop(app_id, None)
        if not f:
            if not todo:
                break
            continue
        if not (hit.get("main_categories") or hit.get("categories")):
            try:
                hit = get(f"/appstream/{app_id}")
            except Exception:
                continue
        s = open(f, encoding="utf-8").read()
        new = re.sub(r'^category="[^"]*"', f'category="{category(hit)}"', s, count=1, flags=re.M)
        if new != s:
            open(f, "w", encoding="utf-8").write(new)
            fixed += 1
    print(f"recategorized {fixed} recipes ({len(todo)} not found on Flathub's lists)")


if __name__ == "__main__":
    recategorize() if sys.argv[1:] == ["recategorize"] else main()
