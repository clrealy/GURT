# GURT changelog 🦆

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
