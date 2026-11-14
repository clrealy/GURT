# GURT changelog 🦆

## Not released yet

### New
- **Gentoo 🐧** gurt works on Gentoo like on any other distro now. Portage does deps, `gurt utils`, `gurt sysup` (`emaint sync` + `emerge -uDN @world`), `gurt remove` (`--deselect` + `--depclean`) and native first (`gurt install gimp` emerges `media-gfx/gimp`). `gurt hogs --all`, `gurt dupes`, `gurt why` and the junk cleaner know your Portage packages, Hotwyr wraps `emerge`, and the Updates tab counts what `emerge -uDN @world` would update. Install it with `curl -fsSL https://gurtproject.org/install.sh | sh`.

### Fixed
- **The setup wizard's app install looked stuck.** It installed every app you picked as one long step (a Gaming pack is a few GB of Flathub runtimes). Now it's one app at a time ("install steam (7 of 8)"), the bar moves with each one, and the line under it shows what's happening right now, download % included. One app failing doesn't stop the rest anymore.
- `gurt install a b c` stopped at the first app that failed. Each one installs on its own now, and at the end gurt tells you which didn't work.

## 1.4.1: Packed 📦

Whole bunches of apps in one go, your distro's own GIMP and Steam instead of Flathub's, and GURT keys 🔑

### New
- **Package packs 📦** `gurt pack gaming` installs a whole bunch of apps for one thing. 12 packs: gaming, retro gaming, streaming, coding, art and design, music production, video editing, school and office, privacy, watch and listen, terminal setup, 3D printing and making. `gurt pack` lists them, `gurt pack show <name>` shows what's in one, `--skip app,app` leaves some out. The app's Setup tab, the setup wizard's starter apps and the site's Build your setup get pack buttons that tick the whole pack. New achievement: packed up.
- **Native first 🐧** Main GURT apps that come from Flathub or Snap (GIMP, Steam…) install from your distro instead when it has the same app: apt's GIMP on Ubuntu, pacman's Steam on Arch. Flathub / Snap is the fallback, and if your package manager can't install it, gurt uses that build. `gurt native off` always uses the Flathub / Snap build.
- **GURT keys 🔑** Got a key like `GURT-XXXX-XXXX-XXXX`? Redeem it with `gurt redeem <key>` or in the app (look → redeem a key). What it unlocks? That's for you to find out 👀 Some keys get handed out, some are hidden. `gurt redeem list` shows what yours unlocked.
- Dev builds have everything a key unlocks, plus a **make a key** button (look → make a key) that makes a key, says what it redeems, gives you its `keys.map` line, and checks what any key redeems.
- **New in Main GURT:** brrr (printing without CUPS or drivers), Wallpaper Engine on Linux (linux-wallpaperengine + wallpaperx, you need to own it on Steam), nah (nano with normal keys) and yoink (curl that talks like a person).
- `tools/onion.sh` puts gurtproject.org on Tor, as a gurtpm….onion address 🧅

### Removed
- 16 apps Flathub stopped carrying (Notejot, Khronos, Colorway, Countdown, Dot Matrix, Black Box, EasySSH, Luna, Linux Assistant, Processing IDE, PDF Slicer, the Photopea wrapper, TradeSim, vServer, Android Virtual Pen, Al-Quran Tafsir). `gurt install pdf-slicer` gets PDF Arranger now. Already installed one? It keeps working, it just won't get updates.
- Mecalin is called Teclas now: `gurt install teclas` (mecalin still works).

### Fixed
- **Install buttons in the app went grey for minutes** right after opening it: the quiet update check it runs in the background counted as "busy". It still stops for your click like it should, so the buttons stay on now.
- **jacb wouldn't build** (`cd: jacb-0.1.0: No such file or directory`): its recipe cloned into `JACB/` and looked in `jacb-0.1.0/`.
- Recipes with a git tag as their source printed git's whole "detached HEAD" lecture while building. gurt keeps git quiet about it now.

## 1.4.0: Oxidized 🦀

GURT's app is rewritten in Rust: a native window, no python, no webview. Plus 39 apps that only ship on GitHub, installable by name.

### New
- **GURT's app is a native app now 🦀** Rewritten in Rust: one ~10 MB program instead of python + a webview + a local web server. Every tab, all six skins (each still with its own fonts, borders and controls), the setup wizard, the sounds and music, sudo's password asked right in the window, and GURTd too. It opens instantly, runs on X11 and Wayland (and WSLg on Windows), and the GURTSetupWizard packages don't need python anymore. Installed another way? `gurt gui` downloads it for your CPU (x86_64 or aarch64) from the release and checks its sha256.
- **Only on GitHub 🐙** `gurt gh-only` lists 39 free apps that ship their Linux builds on GitHub releases (Vesktop, Zen, PrismLauncher, lazygit, Ollama…), and they install by name: `gurt install gh/vesktop`. The app and gurtproject.org show them on the gh/ tab, and CI checks every one still has a Linux file.

## 1.3.0: Hotwyred ⚡

gurt hooks into the package manager you already type, tries apps without keeping them, finds the ones you have twice, and `gurt self-update` stops looping on Arch.

### New
- **Hotwyr ⚡: gurt backs up your package manager.** `gurt hotwyr on` (or the setup wizard): when `sudo apt install yay` can't find yay, gurt offers aur/yay. `apt upgrade`, `pacman -Syu` and friends also update what gurt installed, `apt search` / `pacman -Ss` show gurt's results too, and a command you don't have gets an "install it with gurt?". Works in bash, zsh and fish, only for what you type, never in scripts.
- **`gurt try` 🧪** Install something, try it in a new shell, type `exit` and it's gone again, deps and all (it asks if you want to keep it). `gurt try pip/cowsay -- cowsay hi` runs one command instead.
- **`gurt dupes` 👯** Finds apps you have more than once: from your distro, Flatpak (user and system), Snap and gurt, like Firefox from pacman *and* Flathub *and* `apt/firefox`.
- **The GURT infomercial 📼** A 30-second retro ad in `promo/` (16:9 and 9:16), rendered from `promo/src`.

### Fixed
- **Debian packages that need Perl or Python modules broke on other distros** (`apt/cowsay` on Void: "Can't locate Text/CharWidth.pm"). Debian keeps those modules where only its own perl/python looks, so gurt now uses your distro's package of the same module (`libtext-charwidth-perl` → Void's `perl-Text-CharWidth`, Arch's `perl-text-charwidth`).
- **Void programs wouldn't start on Debian, Ubuntu and friends.** Void builds its programs to look for their loader at `/lib/ld-linux-x86-64.so.2`, and those distros keep it in `/lib64`. gurt now points programs from other distros at the loader your system has.
- **`gh/` crashed** right after handing a release's package to your distro's package manager.
- **`gurt key trust` on Arch** failed when pacman's keyring had never been set up (fresh installs and containers). gurt sets it up now.
- Gentoo search showed "(no description)": it shows the package's category now when Gentoo leaves the description out.
- **`gurt self-update` looped on Arch, CachyOS and friends** (and on unsigned .deb installs): it said "run `sudo pacman -Syu`", pacman said "nothing to do", and `gurt update` said a new gurt was out. pacman never had a gurt repo to update from. Now `gurt self-update` grabs the newest GURTSetupWizard package from the latest release and has your package manager install it.
- **"gurt X is out" showed up late.** `gurt update` and `gurt upgrade` now ask GitHub for the newest release, so a new gurt shows up right away, even when your package lists were refreshed a little while ago.

## 1.2.0: Repomageddon 🌋

NixOS support, and gurt goes from 12 sources to 20: Void, Solus, Alpine and Gentoo repos, GitHub releases, AppImageHub, PyPI, npm, crates.io and Homebrew.

### New
- **NixOS support ❄️.** gurt spots NixOS and uses nixpkgs as its package manager: `gurt install nix/<attr>`, `gurt search nix/<term>`, `gurt remove nix/<attr>`, all into your own nix profile, no sudo (`nix/` works anywhere nix is installed). Main GURT apps come from nixpkgs when nixpkgs has them. Other distros' packages and `.deb` / `.rpm` / `.pkg.tar.zst` files install straight onto the system (no box) and run through nix-ld, AppImages run with `appimage-run`, `/usr` and `/usr/local` get added to your PATH, and `gurt sysup` runs `nixos-rebuild`. For flatpak, nix-ld and Waydroid, gurt gives you the `configuration.nix` line.
- **Void and Solus repos.** `xbps/` (alias `void/`) and `eopkg/` (alias `solus/`) work like `apt/` and `pacman/` on any distro: search them, install from them, and their deps come along. A musl system gets Void's musl repo. Downloaded `.xbps` and `.eopkg` files now pull their deps from those repos too.
- **Alpine and Gentoo repos.** `apk/` (alias `alpine/`; on glibc only scripts and data install, since Alpine is musl) and `gentoo/` (Gentoo's official binary packages).
- **GitHub releases: `gh/owner/repo`.** gurt picks the file for your system (your distro's package, an AppImage, or a Linux build for your CPU), checks its sha256 and updates it when a new release comes out.
- **AppImageHub and Homebrew.** `appimage/` installs AppImageHub's apps through `gh/`, and `brew/` runs Homebrew on Linux (gurt sets it up for you, as you).
- **pip, npm and cargo apps.** `pip/`, `npm/` and `cargo/` install each app in its own folder with its commands on your PATH, as real gurt packages: history, undo, rollback and remove all work.
- **Signed Void packages 🔏.** Every `.xbps` is checked against Void's signing key, which gurt remembers on the first sync.
- **The AUR on NixOS.** `-bin` packages run through nix-ld, and ones that compile build with nixpkgs' gcc pointed at `/usr` and your nix profile.
- **CI for every source.** Pull requests sync and install from Void, Solus, Alpine, GitHub, PyPI and npm for real, run gurt on Void itself, and test `nix/` and NixOS mode with real nix.

### Fixed
- `gurt list` hung, or printed nothing, when the Main GURT recipes weren't downloaded yet.

### Removed
- **.chrot packages.** `gurt chrot`, installing and removing `.chrot` files, and converting to or from .chrot are gone. ChromeOS support (Chromebrew, /usr/local) stays.

## 1.1.0: GURTd, undo, Android apps and ChromeOS 🐧

A new look, a background daemon, an undo button, Android apps, ChromeOS, and a mostly-free-software Main GURT with 150 more apps.

### New
- **A new look.** Denser and cleaner in every skin: real app logos instead of emoji icons, no more tiny all-caps labels, and the same rules on gurtproject.org.
- **GURTd**, gurt's background daemon (`gurt gurtd on`, `gurt gurtd config`, or Updates → GURTd in the app). It keeps package lists fresh, checks for updates (and auto-updates if you want), asks to install new .deb/.rpm/AppImage downloads, and makes the app open instantly. Saver mode waits on battery or metered data; quiet hours hold its popups.
- **`gurt undo`** takes back the last thing gurt did (installs, removes, upgrades, all as one step). Run it again to redo. In the app: **undo last** in the history dialog.
- **The disk hog finder.** `gurt hogs all` shows everything on your disk, not just gurt's apps. `gurt hogs junk` lists caches, trash, old logs and package downloads, and `gurt hogs clean` tosses them. In the app: **free up space** on the Installed tab.
- **Linux From Scratch support.** gurt detects LFS and builds what it needs from Main GURT recipes.
- **Apps you got without gurt count as installed** (flatpak, snap, your distro, /opt, AppImages), and badges say where each one came from.
- **Real app logos**: Flathub's, then your system's own icon, then a letter tile.
- **Android apps through Waydroid**: `gurt install android/<app>` installs from F-Droid (the only store, so it's all free software). A closed-source .apk you bring still installs, after a heads-up. gurt sets Waydroid up the first time (plain Android, no Google apps). `gurt android` for the rest, or Setup → Android apps in the app.
- **ChromeOS.** In Linux on ChromeOS, apps (flatpaks too) land in the launcher, Android apps go into the Chromebook's own Android, and GURTd watches ChromeOS's Downloads. On ChromeOS itself (developer mode or Brunch, with Chromebrew), gurt lives in `/usr/local` with no sudo, uses `crew` for deps (`crew/` packages too) and moves other distros' packages under `/usr/local`. gurtproject.org has a ChromeOS card.
- **.chrot packages (Tweakium).** `gurt install ./x.chrot`, `gurt remove chrot/x`, `gurt chrot list|build`, and `gurt convert` to and from .chrot. Same database as the chrot tool, chrot dependencies, sus-checked hooks. The app's Install a file tab and GURTd's Downloads watcher know .chrot too.
- **The setup wizard comes first.** Until it's finished, opening GURT opens the GURT Setup Wizard, and `gurt` in a terminal runs it before your first command. Closing the wizard halfway no longer counts as done. Scripts, `-y`, root and GURTd aren't affected (`GURT_NO_WIZARD=1` skips it).
- **GURTd restarts itself after an update**, so the app never opens onto the old version.
- **Mostly free software.** Closed-source apps are labeled, come after the free ones, and `gurt install` suggests free apps like them. `gurt foss on` (or **FOSS only** in the app and on the site) hides and blocks them. The setup wizard's starter apps are free software, except Steam.

### Site
- **Compare** up to 4 apps side by side, and share the comparison with a link.
- Flathub apps were labeled "official repo" on their cards; now they say Flathub.

### For maintainers
- The bump bot now covers recipes with per-arch sources and `_tag=v$pkgver` helpers: 274 recipes instead of 58.

## 1.0.0+hotfix1: the stuff 1.0 should've had 🩹

Same GURT 1.0, plus everything that landed right after it.

### New
- **`gurt uninstall`** takes GURT off your computer. It saves your app list first, asks before removing the apps GURT installed, then removes GURT through your package manager. `gurt uninstall <app>` still just removes that app.
- **Updates through your system.** The `.rpm` adds the GURT repo (gurtproject.org/repo), so `zypper up` / `dnf upgrade` bring new GURT versions. The `.deb` does the same for `apt upgrade` once releases are signed.
- **`gurt run <app>`** starts an app, and offers to install it first.
- **`gurt history`** shows what you installed and removed, and when. It's also under 📜 in the app.
- **`gurt cache`** shows how much space GURT's downloads use, and `gurt cache clean` frees it.
- **"Did you mean…?"** when an app name has a typo: `gurt install fierfox` → firefox.

### The app
- **A cleaner layout.** The everyday stuff stays up front, and the rest lives under **⋯ more**.
- **Updates count themselves.** The Updates tab shows how many are waiting as soon as the app opens.
- **`/` jumps to the search box.**

- **The GURT Setup Wizard is its own app.** It has its own window and its own entry in your app menu, separate from GURT. It opens at your first login, and **🦆 open GURT** on its last page starts GURT. `gurt setup` opens it, and `gurt setup --terminal` runs it in the terminal.
- **A real 404 page on gurtproject.org.** You get a different one every time, with links back to the site.

### Fixed
- **The password prompt.** Installing a file asked for your password twice; now it's once.
- **Crash on close.** Closing the app window left a crash report on some graphics drivers (WebKitGTK + Mesa).
- **The setup wizard.** On the App sources and Extras steps, the checkboxes squished the text off the screen.
- **`gurt self-update`** on a packaged install now tells you to update with your package manager instead of overwriting files.

### Site
- GURT lives at **gurtproject.org** now.

## 1.0.0: GURT 1.0 🎉

No more 0.something. GURT installs any distro's packages on any distro, and 1.0 is where it's grown up enough to say so.

### What's in it
- **2,585 apps in Main GURT.** 282 of them gurt installs itself: official prebuilt downloads with pinned checksums, AppImages, source builds and vendor repos. The rest come from Flathub. No more duplicate entries like `1password-onepassword`.
- **Every source, on every distro:** the AUR, apt, dnf, zypper, pacman, Flathub, the Snap Store, PPAs and your own repos. You can also install any file you downloaded (`.deb` `.rpm` `.pkg.tar.zst` `.apk` `.xbps` `.eopkg` AppImage `.exe` …) or build any git repo.
- **The Congurter™:** turn any Linux package into any other, signed with your own key 🔏

### Trust + safety (new in 1.0)
- `gurt verify`, plus signature checks on install: a package that was changed after it was signed won't install.
- `gurt repo publish`: a folder of packages becomes a signed apt + rpm repo that anyone can add.
- **Sus check:** gurt reads AUR and git build scripts for red flags (`curl | sh`, `rm -rf ~`, reverse shells…) before building. It never runs them to check.
- **Snapshots before system upgrades** on btrfs (snapper, timeshift or a plain btrfs snapshot).
- **Trust badges** on every app in the app, showing where it really comes from.

### Handy (new in 1.0)
- `gurt search "like photoshop"`, `gurt compare`, `gurt why`, `gurt hogs`
- `gurt profile save/load`: your whole setup under a name
- `gurt notify on`: a desktop notification when updates are waiting

### Fun (new in 1.0)
- 19 achievements 🏆, daily lottery streaks 🔥 and legendary pulls 🌈
- Vaporwave and Hacker skins, 4 music tracks, and a cursed Congurter™ 💀

### The look (new in 1.0)
- A sharper logo with a solid shadow instead of the blurry halo, plus a new app icon.
- A retro look in the app and on the website: paper background, ink outlines and hard shadows. No glow.
- Fixed: the app scrolled sideways on mid-size windows and buttons ran off the screen on phones. The look + sound settings now live in the 🎨 menu.
