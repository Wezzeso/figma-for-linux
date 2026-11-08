![](docs/images/readme-cover.png)

# Figma for Linux

A packaged version of my working Figma desktop setup on Linux: a dedicated Firefox window with a Figma-style tab strip, its own application icon, an isolated profile, and the cursor and input fixes I use daily.

**[Download the latest Linux packages](https://github.com/Wezzeso/figma-for-linux/releases/latest)**

This is an unofficial community wrapper for Figma's website. It does not bundle Figma's proprietary editor. Sign in with your own Figma account after installation. An internet connection is required.

## Установка — Linux Mint / Ubuntu / Debian

Скачайте `.deb` из [последнего релиза](https://github.com/Wezzeso/figma-for-linux/releases/latest), откройте терминал в папке загрузки и выполните:

```bash
sudo apt install ./figma-for-linux_1.0.0_amd64.deb
```

После установки откройте **Figma for Linux** в меню приложений. Firefox уже включён в пакет; устанавливать отдельный браузер или копировать чужой профиль не нужно.

Пакет рассчитан на **64-битный Linux x86_64**, X11 или XWayland и glibc 2.35+. Запуск проверен на Linux Mint 22.3 (на базе Ubuntu 24.04). Для других дистрибутивов есть архив и исходники ниже. Исправление pinch-жеста предназначено для Cinnamon с включёнными жестами и работающим TouchEgg; остальные функции от него не зависят.

## Debian package

Download `figma-for-linux_1.0.0_amd64.deb` from [Releases](https://github.com/Wezzeso/figma-for-linux/releases/latest), then:

```bash
sudo apt install ./figma-for-linux_1.0.0_amd64.deb
figma-for-linux
```

`apt` installs the Python, GTK, and X11 runtime dependencies. The package contains a clean, checksum-verified official Firefox distribution. It creates **Figma for Linux** in the application menu and a `figma-for-linux` command.

## Portable archive / per-user installation

Extract the archive and either run it directly or register it in your application menu:

```bash
tar -xzf figma-for-linux-1.0.0-linux-x86_64.tar.gz
cd figma-for-linux-1.0.0
./bin/figma-for-linux      # run directly
./install.sh              # optional: install into ~/.local
```

Portable does not mean statically linked: Python 3.9+, python-xlib, PyGObject with GdkPixbuf, GTK 3, X11, and the usual Firefox runtime libraries are still required. On Ubuntu / Mint / Debian:

```bash
sudo apt install python3 python3-xlib python3-gi gir1.2-gdkpixbuf-2.0 wmctrl x11-xkb-utils libgtk-3-0
```

On Ubuntu 24.04, `libgtk-3-0t64` is the renamed GTK package. On Fedora / Arch, install the equivalent distribution packages. Runtime verification so far is on Linux Mint 22.3, based on Ubuntu 24.04.

To verify the downloads, place `SHA256SUMS` next to both packages and run:

```bash
sha256sum -c SHA256SUMS
```

## What is included

- Figma-style file tabs and window controls, with the browser address bar hidden.
- A separate Firefox profile, so your normal browser settings and accounts stay independent.
- Figma window title, icon, application-menu entry, and taskbar identity.
- A stable resize-arrow hotspot with a direction badge.
- An X11 input guard that temporarily removes conflicting Alt+Shift layout shortcuts while Figma is focused and restores them on focus loss or exit.
- Optional smooth two-finger pinch relay from TouchEgg to GTK on Cinnamon, plus finer Ctrl+wheel zoom.
- A pinned, unmodified official Firefox 159.0.1 build, matching the original installed setup.

The package ships source and profile **templates only**: no cookies, passwords, account tokens, browsing history, design files, or sessions. Each user starts with a new local profile.

## Open a file / troubleshoot

```bash
figma-for-linux 'https://www.figma.com/design/FILE_KEY/Name'
figma-for-linux --diagnostics
```

Application data is in `${XDG_DATA_HOME:-~/.local/share}/figma-for-linux/`. The most recent launch log is `last-launch.log` in that directory. To isolate an input issue:

```bash
FIGMA_DISABLE_PINCH=1 figma-for-linux
FIGMA_DISABLE_CURSOR_FIX=1 figma-for-linux
FIGMA_DISABLE_INPUT_GUARD=1 figma-for-linux
```

Close the existing Figma for Linux window before changing these settings. On Wayland the package uses XWayland; a native Wayland integration is not included. The pinch relay does not install or alter system gesture settings. Local font bridging and the official Figma desktop app's private authentication protocol are not included; this uses the normal Figma website login. Custom browser chrome can require adjustments after Firefox upgrades.

## Build from source

Use Linux x86_64, Python 3.12+, GCC, and `dpkg-deb`:

```bash
git clone https://github.com/Wezzeso/figma-for-linux.git
cd figma-for-linux
sudo apt install build-essential dpkg-dev python3
python3 -m unittest discover -s tests -v
python3 scripts/build.py
```

The build downloads Firefox directly from Mozilla and verifies the **pinned SHA-512** in `browser.json`. It compiles the native helpers from source and creates the `.deb`, `.tar.gz`, and `SHA256SUMS` in `dist/`. It never reads your installed app or browser profile. GitHub Actions runs the same build and publishes downloadable workflow artifacts.

To update the bundled browser, update its version, URL, source URL, and official SHA-512 in `browser.json`, increment `VERSION`, build, and test. The system-owned Debian copy is updated by installing a new package release; it is not an apt repository with automatic updates.

## Uninstall

Debian installation:

```bash
sudo apt remove figma-for-linux
```

Per-user installation:

```bash
~/.local/opt/figma-for-linux/install.sh --uninstall
```

Both preserve your local Figma profile. Remove the `figma-for-linux` application-data directory yourself if you also want to erase its login and cache.

## License and upstream

Launcher and customizations: GPL-3.0. See [LICENSE](LICENSE) and [THIRD_PARTY.md](THIRD_PARTY.md) for Firefox, icon, and trademark notices.

Upstream: [Figma system requirements](https://help.figma.com/hc/en-us/articles/360039827194-What-are-the-system-requirements-for-Figma), [official Firefox Linux installation](https://support.mozilla.org/en-US/kb/install-firefox-linux), [Firefox download checksums](https://archive.mozilla.org/pub/firefox/releases/159.0.1/SHA512SUMS).
