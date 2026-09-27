# 🦆 gurt

**G**URT **U**niversal **R**epository **T**hingy. It's a community build repo like the AUR, but it works on **every** distro.

Arch has the AUR. Everyone else gets PPAs, COPRs, OBS, random `.sh` installers, or compiling from source by hand. gurt is one repo and one command that works the same everywhere:

```sh
gurt install fastfetch
```

It works on Debian, Ubuntu, Mint, Fedora, RHEL, Arch, Manjaro, openSUSE, Alpine, Void, Gentoo, Solus, Devuan and anything else built on those.

## How it works

1. Every package is a **recipe** (`packages/<name>/GURTBUILD`). If you've seen a PKGBUILD, this is basically the same thing.
2. Recipes list deps with **generic names** like `cc`, `cmake` or `openssl`. [`deps.map`](deps.map) turns those into each distro's real package names, so `openssl` becomes `libssl-dev` on Debian, `openssl-devel` on Fedora, and `openssl` on Arch.
3. gurt detects your package manager (apt, dnf, yum, pacman, zypper, apk, xbps, emerge or eopkg) and installs the build deps through it.
4. It builds as **your user, never as root**. It packs the result into a `.gurt` file and installs it into **`/usr/local`**, so it never fights your distro's own packages.
5. It tracks every file it installs, so `gurt remove` deletes exactly those files and only the directories it created.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/clrealy/gurt/main/install.sh | sh
```

You need `bash`, `git`, GNU `tar`, and `curl` or `wget`. Run `gurt doctor` to check your setup.

## Usage

```sh
gurt sync                 # pull the latest recipes
gurt search fetch         # find stuff
gurt info btop            # details
gurt install btop         # shows you the GURTBUILD, asks, then builds + installs
gurt upgrade              # rebuild anything that got a new version
gurt remove btop          # clean uninstall
gurt list                 # what you've installed
gurt files btop           # what files a package owns
gurt owns /usr/local/bin/btop
```

Flags: `-y` (don't ask), `-f` (force), `--nodeps`, `--nocheck`, `--keep` (keep build dir), `--root DIR` (install into a chroot/test dir).

⚠️ **Recipes are user-submitted. Read the GURTBUILD before you hit `y`.** gurt shows it to you on purpose.

## Repo layout

```
gurt                  the CLI (one bash script)
deps.map              generic dep name → distro package names
packages/<name>/      one folder per package
  GURTBUILD           the recipe
  .gurtinfo           generated metadata (so search/info never run recipe code)
site/                 the package-browser website (GitHub Pages)
tools/lint.sh         recipe checks (CI runs these on every PR)
tools/gen-index.py    builds site/packages.json
```

## Hosting your own

Fork it, then set `GURT_REPO_URL` in `/etc/gurt.conf` to your fork. Turn on GitHub Pages with the source set to "GitHub Actions" and the site deploys every time you push to `main`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Make a recipe, open a PR, and CI builds it on Debian, Fedora, Arch, Alpine and openSUSE.

MIT © clearly124
