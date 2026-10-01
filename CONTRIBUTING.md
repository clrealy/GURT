# Submitting a package to gurt 🦆

## 1. Scaffold it

```sh
cd packages
../gurt new my-app
```

## 2. Write the GURTBUILD

```bash
pkgname=my-app            # lowercase, must match the folder name
pkgver=1.2.3              # upstream version (no dashes)
pkgrel=1                  # bump this when you change the recipe but not the version
pkgdesc="one line about it"
url="https://github.com/someone/my-app"
license="MIT"
maintainer="your-handle"
arch=(x86_64 aarch64)     # or (any) for scripts/themes/fonts
depends=(ncurses)         # runtime deps, GENERIC names
makedepends=(cc cmake)    # build-only deps, GENERIC names
source=("my-app-$pkgver.tar.gz::https://example.com/my-app-$pkgver.tar.gz")
sha256sums=("abc123...")  # gurt checksum my-app

category="cli"            # browsers chat media creative office dev cli gaming internet system security fun — groups it on the site + the app
aliases=(my-app-cli ma)   # optional: other names that install this (gurt install ma)
hidden=true               # optional: keep it out of the store/search — still installable by exact name

prepare() { ...; }        # optional: patches
build()   { ...; }        # optional: compile
check()   { ...; }        # optional: tests (skipped with --nocheck)
package() { ...; }        # REQUIRED: install into "$pkgdir"
```

### Variables you get

| var | what it is |
|---|---|
| `$srcdir` | where sources get unpacked. Every function starts here |
| `$pkgdir` | the fake root. Install into `"$pkgdir$prefix/..."` or use `DESTDIR="$pkgdir"` |
| `$prefix` | install prefix, usually `/usr/local`. **Always use it and never hardcode `/usr`** |
| `$startdir` | the recipe folder, for local patches and files |

### Source formats

- `https://...` downloads, checks the sha256, and auto-extracts tarballs and zips
- `name.tar.gz::https://...` does the same but renames the download
- `git+https://...repo.git#tag=v1.0` (also `#branch=` or `#commit=`), with `SKIP` for the checksum. Prefer `#commit=` so builds are reproducible
- `file.patch` is a local file next to the GURTBUILD

### Deps

Use the **generic names** from [`deps.map`](deps.map). If a dep isn't there, add a line mapping it for as many distros as you can. That's the most useful PR you can make. A dep that's another gurt package gets built from gurt automatically.

You can also depend on another source directly with `depends=(aur/some-pkg apt/some-lib)`. Only do that when your distro-agnostic options run out.

## 3. Test it

```sh
../gurt build my-app                          # builds my-app-*.gurt
../gurt add my-app-*.gurt                     # installs it
../gurt srcinfo my-app > my-app/.gurtinfo     # REQUIRED, commit this
../tools/lint.sh
```

Testing without touching your system:

```sh
../gurt -y --root /tmp/testroot add my-app-*.gurt
```

## 4. Open a PR

CI lints the recipe and builds it on **Debian, Fedora, Arch, Alpine and openSUSE**. If it's green, it gets merged.

## Rules (no cap)

- 🚫 Never use `sudo` or `doas` in a recipe, and never `curl | sh`
- 🚫 Don't install outside `$prefix` unless you really have to (the linter will warn)
- 🚫 Don't repackage something that's already in basically every distro's official repos
- ✅ Always use checksums for tarballs
- ✅ Pin git sources to a tag or commit
- ✅ The build has to work as a normal user
