#!/usr/bin/env python3
"""Build a Debian package and portable archive from public source only."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def checksum(path, algorithm='sha512'):
    digest = hashlib.new(algorithm)
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download_browser(cache, manifest):
    archive = cache / f'firefox-{manifest["version"]}.tar.xz'
    if not archive.exists() or checksum(archive) != manifest['sha512']:
        temporary = archive.with_suffix('.partial')
        print(f'Downloading official Firefox {manifest["version"]}...', flush=True)
        try:
            with urllib.request.urlopen(manifest['url'], timeout=60) as response, temporary.open('wb') as output:
                shutil.copyfileobj(response, output)
            if checksum(temporary) != manifest['sha512']:
                raise RuntimeError('Firefox checksum does not match browser.json; refusing to package it.')
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    print('Firefox SHA-512 verified.', flush=True)
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    if platform.machine() not in ('x86_64', 'amd64'):
        parser.error('The published browser and native helpers target Linux x86_64.')
    for command in ('gcc', 'dpkg-deb'):
        if not shutil.which(command):
            parser.error(f'{command} is required (sudo apt install build-essential dpkg-dev).')
    version = (ROOT / 'VERSION').read_text().strip()
    manifest = json.loads((ROOT / 'browser.json').read_text())
    build = ROOT / 'build'
    cache = build / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    browser_archive = download_browser(cache, manifest)
    stage = build / f'figma-for-linux-{version}'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    # Explicit allowlist: never copy ~/.local/share, a working browser install,
    # caches, profiles, cookies, session storage, or machine-specific settings.
    for directory in ('app', 'assets', 'bin', 'profile-template'):
        shutil.copytree(ROOT / directory, stage / directory,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.so', '*.log'))
    for name in ('VERSION', 'browser.json', 'install.sh', 'README.md', 'LICENSE', 'THIRD_PARTY.md'):
        shutil.copy2(ROOT / name, stage / name)
    with tarfile.open(browser_archive, 'r:xz') as archive:
        archive.extractall(stage, filter='data')
    for source in ('cursor-anchor', 'pinch-gtk'):
        subprocess.run([
            'gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
            '-fPIC', '-fstack-protector-strong', '-D_FORTIFY_SOURCE=2',
            '-shared', '-Wl,-z,relro,-z,now',
            '-o', str(stage / f'app/{source}.so'), str(stage / f'app/{source}.c'),
            '-ldl', '-lm',
        ], check=True)
    for name in ('install.sh', 'bin/figma-for-linux'):
        (stage / name).chmod(0o755)
    # The template is deliberately a few shipped text/SVG files only.
    forbidden = {'cookies.sqlite', 'places.sqlite', 'key4.db', 'logins.json', 'prefs.js'}
    for path in stage.rglob('*'):
        if path.name in forbidden or path.name.startswith('sessionstore'):
            raise RuntimeError(f'Unexpected profile data in package: {path.relative_to(stage)}')
    portable = output / f'figma-for-linux-{version}-linux-x86_64.tar.gz'
    print(f'Building {portable.name}...', flush=True)
    with tarfile.open(portable, 'w:gz', compresslevel=6) as archive:
        archive.add(stage, arcname=stage.name)
    deb_root = build / 'deb-root'
    if deb_root.exists():
        shutil.rmtree(deb_root)
    app_root = deb_root / 'opt/figma-for-linux'
    shutil.copytree(stage, app_root)
    applications = deb_root / 'usr/share/applications'
    applications.mkdir(parents=True)
    (applications / 'figma-for-linux.desktop').write_text(
        '[Desktop Entry]\nVersion=1.0\nType=Application\nName=Figma for Linux\n'
        'Comment=Dedicated Figma workspace with desktop tabs\n'
        'Exec=/opt/figma-for-linux/bin/figma-for-linux %U\n'
        'Icon=figma-for-linux\nTerminal=false\nCategories=Graphics;\n'
        'StartupWMClass=Figma\nStartupNotify=true\n'
    )
    icons = deb_root / 'usr/share/icons/hicolor/scalable/apps'
    icons.mkdir(parents=True)
    shutil.copy2(stage / 'assets/figma-for-linux.svg', icons)
    binaries = deb_root / 'usr/bin'
    binaries.mkdir(parents=True)
    (binaries / 'figma-for-linux').symlink_to('/opt/figma-for-linux/bin/figma-for-linux')
    metadata = deb_root / 'DEBIAN'
    metadata.mkdir()
    installed_size = sum(path.stat().st_size for path in app_root.rglob('*') if path.is_file()) // 1024
    (metadata / 'control').write_text(
        f'Package: figma-for-linux\nVersion: {version}\nArchitecture: amd64\n'
        'Section: graphics\nPriority: optional\n'
        'Maintainer: Wezzeso <189402633+Wezzeso@users.noreply.github.com>\n'
        'Homepage: https://github.com/Wezzeso/figma-for-linux\n'
        f'Installed-Size: {installed_size}\n'
        'Depends: python3 (>= 3.9), python3-xlib, python3-gi, gir1.2-gdkpixbuf-2.0, '
        'wmctrl, x11-xkb-utils, libc6 (>= 2.35), libgtk-3-0t64 | libgtk-3-0, '
        'libasound2t64 | libasound2, libdbus-1-3, libx11-xcb1, libxt6t64 | libxt6, '
        'libxcomposite1, libxdamage1, libxfixes3, libxrandr2, libgbm1, '
        'libfontconfig1, libfreetype6, ca-certificates\n'
        'Recommends: fonts-noto-core\n'
        'Description: Dedicated Figma workspace for Linux\n'
        ' Unofficial Firefox-based Figma app with independent profile, desktop tabs,\n'
        ' window integration, resize cursor fixes and optional Cinnamon pinch relay.\n'
    )
    for hook in ('postinst', 'postrm'):
        script = metadata / hook
        script.write_text('#!/bin/sh\nset -e\nif command -v update-desktop-database >/dev/null 2>&1; then\n  update-desktop-database -q /usr/share/applications || true\nfi\nif command -v gtk-update-icon-cache >/dev/null 2>&1; then\n  gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true\nfi\nexit 0\n')
        script.chmod(0o755)
    deb = output / f'figma-for-linux_{version}_amd64.deb'
    print(f'Building {deb.name}...', flush=True)
    subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '-z6', '--build', str(deb_root), str(deb)], check=True)
    checksums = output / 'SHA256SUMS'
    checksums.write_text(''.join(f'{checksum(path, "sha256")}  {path.name}\n' for path in (deb, portable)))
    print(f'Done: {deb}\n      {portable}\n      {checksums}', flush=True)


if __name__ == '__main__':
    main()
