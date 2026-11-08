#!/usr/bin/env bash
# Install an extracted release for the current user, without copying a profile.
set -euo pipefail
source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
prefix="$HOME/.local"
if [[ "${1:-}" == '--prefix' ]]; then
    if [[ $# -lt 2 || "$2" != /* || "$2" == / ]]; then
        printf 'Use --prefix with an absolute installation directory other than /.\n' >&2
        exit 2
    fi
    prefix="$2"
    shift 2
fi
data_base="${XDG_DATA_HOME:-$HOME/.local/share}"
if [[ "$prefix" != "$HOME/.local" ]]; then
    data_base="$prefix/share"
fi
install_root="$prefix/opt/figma-for-linux"
bin_root="$prefix/bin"
desktop_root="$data_base/applications"
icon_root="$data_base/icons/hicolor/scalable/apps"

if [[ "${1:-}" == '--uninstall' ]]; then
    rm -f -- "$bin_root/figma-for-linux" "$desktop_root/figma-for-linux.desktop" "$icon_root/figma-for-linux.svg"
    rm -rf -- "$install_root"
    printf 'Removed Figma for Linux. Your profile remains in %s/figma-for-linux.\n' "$data_base"
    exit 0
fi
if [[ $# -gt 0 ]]; then
    printf 'Usage: %s [--prefix /absolute/path] [--uninstall]\n' "$0" >&2
    exit 2
fi
if [[ ! -x "$source_root/firefox/firefox" ]]; then
    printf 'Use an extracted release archive, or build a release with python3 scripts/build.py first.\n' >&2
    exit 1
fi
if ! /usr/bin/python3 -c 'import Xlib, gi; gi.require_version("GdkPixbuf", "2.0"); from gi.repository import GdkPixbuf' 2>/dev/null; then
    printf 'Install runtime dependencies first. On Ubuntu / Mint / Debian:\n  sudo apt install python3 python3-xlib python3-gi gir1.2-gdkpixbuf-2.0 wmctrl x11-xkb-utils libgtk-3-0\n' >&2
    exit 1
fi
mkdir -p -- "$install_root" "$bin_root" "$desktop_root" "$icon_root"
if [[ "$source_root" != "$install_root" ]]; then
    cp -a -- "$source_root/." "$install_root/"
fi
ln -sfn -- "$install_root/bin/figma-for-linux" "$bin_root/figma-for-linux"
cp -- "$install_root/assets/figma-for-linux.svg" "$icon_root/figma-for-linux.svg"
# Desktop Exec quoting is different from shell quoting. Generate it explicitly.
/usr/bin/python3 - "$install_root" "$desktop_root/figma-for-linux.desktop" <<'PY'
from pathlib import Path
import sys
root, destination = map(Path, sys.argv[1:])
command = str(root / 'bin/figma-for-linux')
command = command.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
Path(destination).write_text(
    '[Desktop Entry]\nVersion=1.0\nType=Application\nName=Figma for Linux\n'
    'Comment=Dedicated Figma workspace with desktop tabs\n'
    f'Exec="{command}" %U\nIcon=figma-for-linux\nTerminal=false\n'
    'Categories=Graphics;\nStartupWMClass=Figma\nStartupNotify=true\n'
)
PY
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$desktop_root" || true
fi
printf 'Installed. Open "Figma for Linux" from your application menu.\n'
printf 'Command: %s/figma-for-linux\n' "$bin_root"
