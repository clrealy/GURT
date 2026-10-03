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

### Got a `.deb` or `.rpm` file? Just install it 📥

(For AppImages, tarballs, `.exe`s, `.dmg`s and more, see [`gurt outsource`](#outsource-any-file-you-downloaded-).)

```sh
gurt install ./google-chrome-stable_current_amd64.deb   # on Fedora, Arch, openSUSE, whatever
gurt install ~/Downloads/some-app.rpm                   # on Debian/Ubuntu/Mint
gurt install ./thing-1.0-1-x86_64.pkg.tar.zst           # Arch packages too
gurt install https://example.com/app.deb                # urls work
```

gurt reads the name, version and deps out of the file, repacks it and installs it **straight onto your system — no box**. It shows up as `file/<name>` (`gurt remove file/<name>`, `gurt info file/<name>`). Deps get resolved the same way as below: your system first, then your distro, then the distro the file was made for. If the file is already your distro's own kind (a `.deb` on Ubuntu, an `.rpm` on Fedora), gurt just hands it to your package manager. The same safety rails apply: it won't install something built for a different CPU, it refuses kernels/bootloaders/core system packages, and it never overwrites files your distro owns. To update one, install the newer file.

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

### On Windows 🪟

gurt runs on Windows through **WSL** (the Linux that's built into Windows). Paste this in PowerShell:

```powershell
irm https://raw.githubusercontent.com/clrealy/GURT/main/install.ps1 | iex
```

- **No WSL yet?** It installs WSL + Ubuntu for you (Windows asks for admin and might want a reboot). Open Ubuntu once to make your Linux user, then run the line again.
- It installs gurt inside WSL and adds a `gurt` command to Windows, so `gurt install firefox` works straight from PowerShell or cmd.
- **GURT** shows up in your Start menu, and Linux apps you install show up there too (WSLg, on Windows 11 or Windows 10 21H2+).
- Want a different distro than your default? `$env:GURT_WSL_DISTRO = "Debian"` before running it.
- Linux desktops (`gurt de`) don't make sense on Windows, so they're turned off there. Snaps need systemd switched on in WSL; gurt tells you how.

## Update your whole system 🐧

gurt isn't just an installer: `gurt upgrade` updates **everything**. First your system, using your distro's own package manager the right way, then everything gurt installed, then flatpaks + snaps.

| your distro | what `gurt upgrade` runs |
|---|---|
| Arch, CachyOS, EndeavourOS, Manjaro… | `pacman -Syu` |
| openSUSE Tumbleweed / Slowroll / MicroOS | `zypper refresh` + `zypper dup` (the rolling way) |
| openSUSE Leap | `zypper refresh` + `zypper update` |
| Debian, Ubuntu, Mint, Pop… | `apt-get update` + `apt-get full-upgrade` |
| Fedora, RHEL-likes | `dnf upgrade --refresh` |
| Fedora Atomic (Silverblue, Kinoite, Bazzite…) | `rpm-ostree upgrade` |
| Alpine | `apk upgrade -U` |
| Void | `xbps-install -Su` (xbps itself first) |
| Solus | `eopkg upgrade` |
| Gentoo | `emerge --sync` + `emerge -uDN @world` |

```sh
gurt update               # what's waiting (system + gurt + gurt itself), installs nothing
gurt upgrade             # system + everything gurt installed
gurt upgrade --no-system # only gurt's stuff
gurt sysup               # only the system
```

In the app, the Updates tab shows a 🐧 "your system" card with how many distro updates are waiting.

## Utilities apps need: `gurt utils` 🔧

Most apps need a few tools to install: flatpak for Flathub apps, `ar`/bsdtar/zstd/7zip/rpm2cpio to unpack `.deb`, `.rpm`, `.pkg.tar.zst`, `.dmg` and `.exe` files, git + a compiler + make + pkg-config for source builds, plus curl, unzip, gnupg, patchelf and xdg-utils. One command grabs all of them from your distro and sets up Flathub:

```sh
gurt utils        # install whatever's missing
gurt utils list   # see what you've got (gurt doctor shows it too)
```

**Donk OS 🫏** (basically worse Ubuntu) runs on gurt, so there gurt does this by itself: the installer sets up the utilities right away, and `gurt self-update` makes sure they're still there. On every other distro nothing extra gets installed until you run `gurt utils` (gurt still grabs single tools when an install needs one).

## Build your setup + the app lottery 🧰🎰

The [website](https://clrealy.github.io/GURT/) has a **Build your setup** picker (like tuxmate, but gurt): tick the apps you want, grouped by category, and copy one `gurt install …` command that works on every distro. Tick "I don't have gurt yet" and the command installs gurt first.

Can't decide? Spin for one:

```sh
gurt lottery          # 🎰 a random app from Main GURT, asks before installing
gurt lottery gaming   # only from one category (browsers chat media creative office dev cli gaming internet system security fun)
```

The site and the app have a 🎰 button too.

## Aliases + hidden packages

In a GURTBUILD:
```bash
aliases=(code visual-studio-code)   # gurt install code  → installs vscode
hidden=true                         # not listed on the site or in gurt search, still installable by exact name
```
The linter makes sure aliases never collide with other packages or aliases.

## Desktop environments 🖥️

```sh
gurt de list            # what your distro can install: kde, gnome, xfce, cinnamon, mate, lxqt, budgie, cosmic, hyprland, niri, sway, i3
gurt de install gnome   # installs it from YOUR distro's repos, then tells you how to pick it at login
gurt de remove gnome    # deletes a desktop (never the one you're logged into, keeps your login screen)
```

Desktops are system software, so gurt **only** installs them from your own distro's repos, never from another distro (that's how systems break). It uses the real group or pattern for each distro: `plasma-meta` on Arch, `@kde-desktop-environment` on Fedora, `pattern:kde` on openSUSE, `kde-plasma-desktop` on Debian/Ubuntu. On Arch it comes with a full `-Syu` (no partial upgrades). It's also in the app under the **🖥️ Desktops** tab.

## GURT app 🖥️

```sh
gurt gui
```

Opens GURT as an app: browse Main GURT, search every source, install or remove with one click, and see updates, holds and rollbacks, with gurt's output live at the bottom. When something needs sudo, it asks for your password in the app. After the first run, **GURT** is in your app menu (with its icon 🦆). The ☀️/🌙 button up top flips between light and dark. It starts on your system theme and remembers what you pick (`~/.config/gurt/gui.json`).

Run `gurt gui --setup` once and it opens in its own real app window (GTK + WebKit, or Qt WebEngine if you have it on KDE). Without that it still works, it just uses a browser window.

It only needs python3 and a browser. It runs a tiny server that only your own machine can reach (127.0.0.1, with a random secret token), opens it in a Chromium-style app window if you have one (otherwise your default browser), and quits by itself after you close the window.

**Sound effects 🔊**: clicks, lottery ticks + a jackpot jingle, a chime when something finishes (a buzz if it fails). The 🔊 button mutes them, and the app and the website both remember it. In the app, every skin has its own sound set: Windows 11 is soft and round, XP gets bells and a big swelly startup-style chord, and 95 is chunky square waves with a brassy ta-da. Switching skins plays its "startup" sound. They're all homemade synth lookalikes, not Microsoft's actual sound files. The website has its own 🌙/☀️ dark mode button too.

**Background music 🎵**: a chill, original shop-style bossa loop (chords, walking bass, a vibraphone-ish tune and shakers), synthesized live, no audio files. The 🎵 button pauses it and GURT remembers. It's on by default in the app and off by default on the website.

**No sound?** The app window plays audio through GStreamer. If its audio plugins are missing, GURT shows a 🔇 banner with a **fix sound** button that installs them (or run `gurt gui-setup`), then reopen GURT.

**Drop in files 📥**: drag a `.deb`, `.rpm`, `.pkg.tar.zst`, AppImage, `.tar.gz`, `.zip`, `.flatpak`, `.exe` or `.dmg` anywhere onto the app (or open the **📥 Install a file** tab and click the big box) and gurt installs it, same as `gurt outsource <file>`. It asks first. On a narrow window the tab hides itself and a 📥 button shows up next to the Discover search instead.

**Skins 🪟**: next to the light/dark button there's a skin picker: 🦆 GURT, Windows 11, Windows XP (Luna blue + the green start button) and Windows 95 (grey bevels on teal). It remembers what you pick.

## Build any git repo: `gurt outsource` 🛠️

Instead of `git clone … && cd … && make && sudo make install`:

```sh
gurt outsource https://github.com/Cyanidenjoyers/Crosshair-W
gurt outsource Cyanidenjoyers/Crosshair-W     # GitHub user/repo works too
```

gurt clones it and builds it with the repo's own **GURTBUILD**, then its **PKGBUILD**, and otherwise guesses from **make / cmake / meson / autotools / cargo / go**. It pulls in build deps (using `-dev`/`-devel` packages on non-Arch distros), shows you the recipe and asks before running anything, then installs it as `git/<name>`, so `gurt remove git/<name>` removes it cleanly and `gurt upgrade` rebuilds it when the repo gets new commits.

⚠️ This runs code from whatever repo you point it at. Only outsource repos you trust.

### Outsource any file you downloaded 📥

`gurt outsource` also takes **files** (or links to them). Whatever you downloaded, on whatever distro you run, **no box**:

```sh
gurt outsource ./google-chrome-stable_current_amd64.deb   # on Fedora? sure
gurt outsource ~/Downloads/Some-App-2.1.0-linux-x64.tar.gz
gurt outsource https://example.com/cool-thing.AppImage
gurt outsource ./Photoshop.dmg                            # yes, we went that far 🍎
```

| you give it | what gurt does |
|---|---|
| `.deb` `.rpm` `.pkg.tar.zst` `.apk` (Alpine) `.xbps` (Void) `.eopkg` (Solus) | reads the name/version/deps out of it, repacks it and installs it straight onto your system. If it's your own distro's format, your package manager does it |
| `.tar.gz` `.tar.xz` `.tar.zst` `.zip` `.7z` … with **source code** inside | builds it like a git repo (make / cmake / meson / cargo / go / GURTBUILD / PKGBUILD), keeping the tarball's version |
| `.tar.*` `.zip` `.7z` `.zst` … with a **prebuilt app** inside, or a lone program | puts it in `/usr/local/lib/gurt-apps/<name>`, links its programs into `/usr/local/bin` and adds a menu entry |
| `.AppImage` | installs it with its own menu entry + icon (runs even without FUSE 2) |
| `.snap` `.flatpak` `.flatpakref` | hands it to snap / flatpak |
| `.exe` `.msi` 🪟 | Wine. Installers (`setup.exe`, `.msi`) run in Wine; portable `.exe`s get installed with a launcher + menu entry |
| `.dmg` 🍎 | pulls the `.app` out with 7-Zip and gives it a launcher that runs it through [Darling](https://darlinghq.org). Real talk: Darling mostly runs command-line Mac apps; GUI ones usually don't work yet |

Everything tracked shows up as `file/<name>` (`gurt remove file/<name>`). Same safety rails as always: files for another CPU get refused, so do Alpine/musl builds on a glibc system, kernels/bootloaders/core packages, and anything that would overwrite files your distro owns. `gurt install ./thing.deb` works too for package files.

## Convert packages: `gurt convert` 🔁

Got an `.rpm` but you're on Debian? Turn it into a `.deb`. Any Linux package format goes into any other:

```sh
gurt convert app.rpm deb                 # → app_1.0-1_amd64.deb
gurt convert app.deb pacman              # → .pkg.tar.zst for Arch/CachyOS
gurt convert thing.xbps app.pkg.tar.zst  # or just name the file you want
gurt convert Cool.AppImage rpm           # an AppImage wrapped up as a real package
gurt convert app.deb appimage            # the other way too
gurt convert game.exe deb                # a package that runs it with Wine 🍷
gurt convert app.rpm deb -o ~/Downloads  # pick where it goes
```

| reads | makes |
| --- | --- |
| `.deb` `.rpm` `.pkg.tar.*` `.apk` (Alpine) `.xbps` `.eopkg` `.gurt` AppImage `.tar.gz`/`.zip` (laid out like `usr/…`), `.exe`/`.msi` (runs through Wine) | `deb` `rpm` `pacman` `apk` `xbps` `eopkg` `appimage` `gurt` `tar.gz` `zip` |

The files go across as-is. Dependencies get translated through `deps.map`, and any gurt doesn't know the new names for get listed instead of guessed. gurt writes `.deb`, `.rpm`, `.apk`, `.xbps` and `.eopkg` itself (no rpmbuild or dpkg needed). Making AppImages uses appimagetool, which gurt downloads for you. In the app it's **The Congurter™** (📥 Install a file tab): drop a package in the hopper, pick a format, smash the 🔘, and it drops into the **Download Zone™** as `<file>-converted.<ext>`. Hit ⬇️ retrieve to put it in your Downloads.

**Double-click a `.gurt` file** and it opens in GURT, ready to install. GURT registers the file type the first time you open the app.

What it won't do: make a `.dmg`, `.exe` or `.msi`. Those are for macOS and Windows, and a Linux program doesn't run there no matter what box it's in 💀

## Oops buttons: rollback, hold, export/import ⏪

In the app, the **Installed** tab has 📤 export my list (saves `gurt-list-<date>.txt` to your Downloads) and 📥 import a list.

```sh
gurt rollback btop        # update broke it? go back to the version before (and hold it there)
gurt hold btop            # upgrade skips it
gurt unhold btop          # back to getting updates
gurt export gurt-list.txt # everything you installed on purpose
gurt import gurt-list.txt # …reinstalled on a new PC in one go
```

gurt keeps the last 3 versions of each package it installs in `~/.cache/gurt/rollback/` (change with `GURT_ROLLBACK_KEEP`).

## Tab completion ⌨️

bash and fish set themselves up the first time you run gurt; open a new terminal and `gurt install bt<TAB>` just works. zsh: add `eval "$(gurt completions zsh)"` to your `~/.zshrc`.

## Bump bot 🤖

Every day `.github/workflows/bump.yml` runs `tools/bump.py`, which checks every recipe with a GitHub source that uses `$pkgver`. When upstream has a newer release, it opens a PR with the new pkgver, pkgrel reset to 1, and fresh checksums + `.gurtinfo`. Add `nobump=true` to a recipe to opt out. Run it yourself with `python3 tools/bump.py` (dry run) or `--write`.

## Desktop shortcuts 🖥️

Put `desktop_icon=true` in a GURTBUILD and gurt copies the package's `.desktop` file onto your desktop when it installs (and cleans it up on `gurt remove`). Don't want that? `--no-desktop` or `GURT_DESKTOP_ICONS=0`.

`gurt remove` plays the Wilhelm scream when it deletes something 😱 (uses whatever you have: `pw-play`, `paplay`, `mpg123`, `ffplay` or `mpv`). Too much? `--quiet-yeet` or `GURT_SOUNDS=0`.

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
