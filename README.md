<p align="center"><img src="assets/gurt-logo.png" alt="gurt" width="360"></p>

# gurt 🦆

**G**URT **U**niversal **R**epository **T**hingy. With it, you can install **any distro's packages on any distro**, and use **Main GURT**, a community repo of its own.

```sh
gurt install btop           # Main GURT: community recipes, built for your distro
gurt install claude-desktop # Main GURT: official vendor apps from their signed repos 🔏
gurt install aur/yay        # the AUR... on Mint
gurt install apt/cowsay     # Debian's apt repos... on openSUSE
gurt install zypper/htop    # openSUSE's repos... on Red Star OS, if you're brave
gurt install dnf/fastfetch  # Fedora's repos... on Arch
gurt install pacman/btop    # Arch's official repos... on Ubuntu
gurt install flatpak/gimp   # Flathub, flatpak set up for you
gurt install snap/spotify   # the Snap Store
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
| `flatpak/` `flathub/` | **Flathub** | runs `flatpak install` for you (sets up flatpak + Flathub the first time) |
| `snap/` | **Snap Store** | runs `snap install` for you (sets up snapd the first time; asks before `--classic`) |

Mirrors and releases are set in [`gurt.conf`](gurt.conf), so apt can point at Ubuntu instead of Debian, for example.

### System tools go in a box automatically 📦

Regular `apt/` `dnf/` `zypper/` `pacman/` installs are for **apps**. **System utilities automatically go in a box**, which is a real container of their distro. gurt boxes a package when:

- it's a package manager, a frontend for one, or a distro config tool (dnfdragora, synaptic, yast, mintupdate…)
- it depends on package-manager internals (libdnf, libzypp, libapt-pkg, python3-apt…)
- it installs system services or hooks (systemd units, udev rules, PAM, polkit helpers…)
- it would overwrite files your distro owns

If your own distro packages the same system tool (like flatpak, podman or cron), gurt installs **your distro's version** instead of boxing it, since that's always better. Kernels, bootloaders and init systems are **refused**, because those have to come from your own distro. If you already have a package from your distro, gurt just tells you. `--box` forces a box, and `--no-box` turns auto-boxing off.

```sh
gurt install --box dnf/dnfdragora      # real Fedora, in a container
gurt install --box apt/synaptic        # real Debian
gurt install --box zypper/yast2        # real openSUSE
```

gurt installs podman + [distrobox](https://distrobox.it) if you need them, creates the box (`gurt-fedora`, `gurt-debian`, `gurt-opensuse`, `gurt-arch`), installs with the **real** package manager inside it, and puts the app in your menu and its commands in `~/.local/bin`. `gurt upgrade` updates the boxes, and `gurt remove` cleans up the exports too.

Things inside a box manage **the box**, not your host. dnfdragora in `gurt-fedora` manages Fedora packages inside that box, and your Arch/Mint system stays untouched 🛡️

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

## Tested in the wild ✅

| what | where | how |
|---|---|---|
| **Claude Desktop** (Debian/Ubuntu-only app) | Arch Linux + niri + DankMaterialShell | `gurt repo add claude-desktop apt https://downloads.claude.ai/claude-desktop/apt/stable stable main --key https://downloads.claude.ai/claude-desktop/key.asc` then `gurt install claude-desktop --repo claude-desktop` |

Got something working on a weird setup? PR it into this table 🙏

## Official-repo recipes 🔏

Some Main GURT packages aren't built by gurt at all. They point straight at the vendor's **official signed repo**, and the key fingerprint is pinned in the recipe:

```sh
gurt install claude-code      # Anthropic's apt repo
gurt install claude-desktop   # Anthropic's apt repo (Linux beta)
```

gurt adds the repo, refuses if the key's fingerprint doesn't match the pinned one, checks the repo signature, then installs. Updates come straight from the vendor with `gurt upgrade`.

To make one, write a GURTBUILD with `via_repo`, `via_type`, `via_url`, `via_suite`, `via_components`, `via_key` and `via_fingerprint` instead of a `package()` function. See [`packages/claude-desktop`](packages/claude-desktop/GURTBUILD).

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

## Accounts 👤

Your **GitHub account is your GURT account**. There are no new passwords, and GURT never sees your login.

- **Profiles:** every maintainer gets a page at `clrealy.github.io/GURT/?u=<github-username>` with their packages. The `maintainer=` field in a recipe is a GitHub username
- **Votes 👍 + comments 💬:** every package has them. You sign in with GitHub through [giscus](https://giscus.app), and everything is stored in this repo's GitHub Discussions
- **🚩 Flag out of date:** opens a pre-filled GitHub issue

**Maintaining packages 🛠️**
- Every package popup on the site has a **✏️ edit this package** button, which opens its GURTBUILD in GitHub's editor. Non-owners automatically get a fork + pull request
- `.github/CODEOWNERS` is generated from each recipe's `maintainer=`, so any PR touching a package **automatically asks its maintainer to review**. The repo owner can always approve too
- To make a maintainer's approval **required**: repo → Settings → Branches → add a rule for `main` → ✅ *Require a pull request* + ✅ *Require review from Code Owners*. Maintainers need to be repo collaborators for GitHub to count them

**Turning on votes + comments (one-time, repo owner):**
1. Repo → **Settings** → **General** → **Features**, then check **Discussions**
2. **Discussions** tab → add a category called **Packages** (type: *Announcement*, so only giscus creates threads)
3. Install the giscus app on this repo: <https://github.com/apps/giscus>
4. On <https://giscus.app>, enter `clrealy/GURT` and pick the **Packages** category. Copy the `data-category-id` into `GISCUS.categoryId` in `site/index.html`

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/clrealy/GURT/main/install.sh | sh
```

You need `bash`, `git`, GNU `tar`, and `curl` or `wget`. The foreign sources also need:

- `python3` for AUR search and rpm repos
- `zstd` for Fedora, openSUSE and Arch
- `ar` or `bsdtar` for `.deb` files

`gurt doctor` shows which sources are ready on your system.

## Aliases + hidden packages

In a GURTBUILD:
```bash
aliases=(code visual-studio-code)   # gurt install code  → installs vscode
hidden=true                         # not listed on the site or in gurt search, still installable by exact name
```
The linter makes sure aliases never collide with other packages or aliases.

## Desktop shortcuts 🖥️

Put `desktop_icon=true` in a GURTBUILD and gurt copies the package's `.desktop` file onto your desktop when it installs (and cleans it up on `gurt remove`). Don't want that? `--no-desktop` or `GURT_DESKTOP_ICONS=0`.

## Not sure where to get something? `--scanrepos` 🔍

```sh
gurt install gimp --scanrepos
```
```
found gimp in 3 place(s):
   1) gurt/gimp                  flathub-1          Main GURT (official flatpak)
   2) gimp (your pacman)         3.0.6-1            your distro's own package — usually the best pick
   3) flatpak/org.gimp.GIMP      3.0.6              Flathub — sandboxed
:: pick one [1-3] (enter = 1, q = cancel):
```

It checks Main GURT, your own distro, Flathub, the AUR, apt/dnf/zypper/pacman, your custom repos and the Snap Store, then lets you pick. With `-y` it takes the top one.

## DIRT 🔞 (opt-in mature section)

`dirt/` is a separate, **off-by-default** section for 18+ stuff. On the website it's the dark `dirt/` tab behind an "Are you sure?" 18+ gate. In the CLI, normal/`-a` searches skip it.

```sh
gurt dirt on              # confirm you're 18+ (per-user, ~/.config/gurt/dirt-enabled)
gurt dirt list
gurt install dirt/<name>
gurt dirt off
```

Rules are in [`dirt/README.md`](dirt/README.md) — legal, labeled, and **nothing involving minors, ever**.

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
