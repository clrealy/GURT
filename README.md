<p align="center"><img src="assets/gurt-logo.png" alt="gurt" width="360"></p>

# gurt 🦆

**G**URT **U**niversal **R**epository **T**hingy. With it, you can install **any distro's packages on any distro**, and use **Main GURT**, a community repo of its own.

```sh
gurt install btop           # Main GURT: community recipes, built for your distro
gurt install aur/yay        # the AUR... on Mint
gurt install apt/cowsay     # Debian's apt repos... on openSUSE
gurt install zypper/htop    # openSUSE's repos... on Red Star OS, if you're brave
gurt install dnf/fastfetch  # Fedora's repos... on Arch
gurt install pacman/btop    # Arch's official repos... on Ubuntu
```

Prefer flags? `--repo` works too, and `aur/yay` and `yay --repo aur` do the exact same thing:

```sh
gurt install yay --repo aur
gurt install htop --repo apt
gurt search fetch --repo fedora
gurt remove htop --repo apt
```

It works on Debian, Ubuntu, Mint, Fedora, RHEL, Arch, Manjaro, openSUSE, Alpine, Void, Gentoo, Solus, Devuan and anything else built on those.

## Sources

| prefix | what it is | how it installs |
|---|---|---|
| *(none)* or `gurt/` | **Main GURT**: community recipes ([`packages/`](packages)) | builds from source into `/usr/local` |
| `aur/` | the **Arch User Repository** | runs the real PKGBUILD (makepkg-compatible) |
| `apt/` `debian/` `ubuntu/` | **Debian** (or Ubuntu) repos | downloads the `.deb`, checks it, unpacks it |
| `dnf/` `fedora/` | **Fedora** repos | downloads the `.rpm`, checks it, unpacks it |
| `zypper/` `suse/` | **openSUSE Tumbleweed** repos | downloads the `.rpm`, checks it, unpacks it |
| `pacman/` `arch/` | **Arch** official repos | downloads the `.pkg.tar.zst`, checks it, unpacks it |

Mirrors and releases are set in [`gurt.conf`](gurt.conf), so apt can point at Ubuntu instead of Debian, for example.

### How cross-distro deps work

When a foreign package needs something, gurt looks in this order:

1. **Does your system already have it?** It checks package names, commands and **shared libraries by soname**. For example, Debian's `libncurses6` counts as installed if `libncurses.so.6` is on your system, whatever your distro calls the package.
2. **Can your distro install it?** It translates the name through [`deps.map`](deps.map) and installs it with your own package manager.
3. **Otherwise it pulls the dep from the same foreign source.** For the AUR, it tries Arch's official repos first and then the AUR.

It **never** pulls another distro's glibc, systemd, bash, coreutils, package manager or other core stuff, because that would wreck your install 💀

### The honest part

Main GURT and `aur/` build from source, so they work pretty much everywhere. Binary sources (`apt/` `dnf/` `zypper/` `pacman/`) are **vibes-based**. A binary built for a distro with a newer glibc than yours won't run.

gurt checks every binary after installing it and tells you if something is missing. If it says your glibc is too old, try the `aur/` version, which builds on your system.

Maintainer scripts (postinst, .install hooks) are **not** run.

## Add your own repos

PPAs, vendor apt repos, Fedora COPRs, custom pacman repos: add them once and install from them on **any** distro.

```sh
# an Ubuntu PPA (gurt finds the signing key itself)
gurt repo add ppa:fastfetch/stable

# any apt repo, with its signing key
gurt repo add claude apt https://downloads.claude.ai/claude-code/apt/stable stable main \
  --key https://downloads.claude.ai/keys/claude-code.asc
gurt install claude-code --repo claude

# rpm repos (Fedora, openSUSE, COPR…) and pacman repos work too
gurt repo add mycopr rpm 'https://download.copr.fedorainfracloud.org/results/owner/project/fedora-44-$arch' --key <key-url>
gurt repo add chaotic pacman 'https://cdn-mirror.chaotic.cx/$repo/$arch' chaotic-aur

gurt repo list            # everything gurt knows about
gurt repo remove claude
```

- 🔏 **With `--key`:** gurt checks the repo's GPG signature (apt `InRelease`, rpm `repomd.xml.asc`) and makes sure the package index matches it. A bad signature or a tampered index gets refused, and the repo isn't added. Pacman repo signatures aren't checked yet
- ⚠️ **Without a key:** packages are still checked against the repo's own checksums, but gurt warns you that the index itself isn't signature-verified
- 🧩 **Deps:** anything a custom repo's package needs but doesn't ship gets pulled from its parent distro. A PPA's missing libs come from Ubuntu/Debian, for example
- Repo files live in `~/.config/gurt/repos.d/` (or `/etc/gurt/repos.d/` for everyone on the machine)

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/clrealy/GURT/main/install.sh | sh
```

You need `bash`, `git`, GNU `tar`, and `curl` or `wget`. The foreign sources also need:

- `python3` for AUR search and rpm repos
- `zstd` for Fedora, openSUSE and Arch
- `ar` or `bsdtar` for `.deb` files

`gurt doctor` shows which sources are ready on your system.

## Usage

```sh
gurt sync                 # pull the latest Main GURT recipes
gurt sync all             # + download the apt/dnf/zypper/pacman indexes
gurt search fetch         # search Main GURT
gurt search aur/fetch     # search one source
gurt search -a fetch      # search EVERYTHING
gurt info apt/htop        # details
gurt install aur/yay      # shows you the PKGBUILD, asks, builds, installs
gurt update               # refresh package lists + show what's outdated (installs nothing)
gurt upgrade              # actually install the new versions, from every source
gurt self-update          # update gurt itself
gurt remove yay           # clean uninstall (say aur/yay if it's in 2 sources)
gurt autoremove           # yeet deps nothing needs anymore
gurt list                 # what you've installed
gurt files apt/htop       # what files a package owns
gurt owns /usr/bin/htop
```

Flags: `-r`/`--repo SRC` (pick the source), `-y` (don't ask), `-f` (force), `-a` (all sources), `--nodeps`, `--nocheck`, `--keep` (keep build dir), `--root DIR` (install into a chroot/test dir).

⚠️ **AUR PKGBUILDs and GURTBUILDs are user-submitted. Read them before you hit `y`.** gurt shows them to you on purpose.

## Safety rails

- **Nothing gets overwritten.** gurt refuses to overwrite any file it didn't install, including files owned by your distro or by a package from another source.
- **It builds as your user, never as root.**
- **Checksums are checked for everything it downloads.**
- **Core system packages from other distros are blocked.**
- **Every file is tracked**, so `remove` takes out exactly what went in.

## Repo layout

```
gurt                  the CLI (one bash script)
deps.map              generic dep name → every distro's package names
packages/<name>/      Main GURT, one folder per package
  GURTBUILD           the recipe
  .gurtinfo           generated metadata (so search/info never run recipe code)
site/                 the package-browser website (GitHub Pages)
tools/lint.sh         recipe checks (CI runs these on every PR)
tools/gen-index.py    builds site/packages.json
```

## Hosting your own

Fork it, then set `GURT_REPO_URL` in `/etc/gurt.conf` to your fork. Turn on GitHub Pages with the source set to "GitHub Actions" and the site deploys every time you push to `main`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Make a recipe, open a PR, and CI builds it on Debian, Fedora, Arch, Alpine and openSUSE. Adding lines to `deps.map` makes the cross-distro dep matching smarter for everyone 🙏

## Disclaimer

GURT is an independent project and is **not affiliated with, endorsed by, or sponsored by** Arch Linux, the AUR, Debian, Ubuntu/Canonical, Fedora/Red Hat, openSUSE/SUSE, or any other distro. Their names are only used to say which repos gurt can talk to, and all trademarks belong to their owners. Packages from other sources are downloaded straight from those projects' official mirrors and keep their original licenses.

MIT © clearly124
