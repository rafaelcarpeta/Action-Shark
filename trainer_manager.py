#!/usr/bin/env python3
"""
Action Shark - Linux Wine/Proton Trainer Manager
Overhaul: Desktop Pro UI (Faithful to Mockup 2)
"""

import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import tempfile
import traceback
import zipfile
import zlib
from pathlib import Path
from pathlib import Path
from collections import deque

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QLineEdit,
    QLabel,
    QFileDialog,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QMessageBox,
    QInputDialog,
    QMenu,
    QProgressBar,
    QSplitter,
    QComboBox,
    QFrame,
    QStackedWidget,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSignalBlocker
from PyQt6.QtGui import QIcon

import error_logger
import wemod_manager as wm
import styles
import i18n
from i18n import t
from ui_components import (
    StatusBadgeDelegate,
    FilterChipBar,
    GameBannerWidget,
    WeModDialog,
    SettingsDialog,
    get_shark_icon,
    get_cheatengine_icon,
    get_wemod_icon,
    get_folder_icon,
    get_log_icon,
    get_gear_icon,
    get_refresh_icon,
    get_minimize_icon,
    get_maximize_icon,
    get_close_icon,
    get_search_icon,
    RoundedButton,
    SurfaceFrame,
)


CONFIG_PATH = os.path.expanduser('~/.config/trainer_manager/config.json')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILT_PREFIX_DIR = os.path.expanduser('~/.config/trainer_manager/built_prefixes')


# ── helpers ────────────────────────────────────────────────────────

def _read_file_safe(path, mode='r'):
    try:
        return Path(path).read_text() if mode == 'r' else Path(path).read_bytes()
    except (OSError, PermissionError):
        return '' if mode == 'r' else b''


def load_config():
    try:
        return json.loads(Path(CONFIG_PATH).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(cfg):
    Path(CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(CONFIG_PATH).write_text(json.dumps(cfg, indent=2))


def _steam_libraries():
    steam_roots = [
        os.path.expanduser('~/.local/share/Steam'),
        os.path.expanduser('~/.steam/steam'),
        os.path.expanduser('~/.steam/root'),
    ]
    libs = []
    for r in steam_roots:
        if os.path.isdir(r) and r not in libs:
            libs.append(r)
    vdf_path = None
    for lib in libs:
        p = os.path.join(lib, 'steamapps', 'libraryfolders.vdf')
        if os.path.isfile(p):
            vdf_path = p
            break
    if not vdf_path:
        return libs
    vdf = vdf_path
    raw = _read_file_safe(vdf)
    if raw:
        for m in re.finditer(r'"path"\s+"([^"]+)"', raw):
            p = m.group(1)
            if p and os.path.isdir(p) and p not in libs:
                libs.append(p)
    return libs


def _find_steam_prefix(appid):
    libraries = _steam_libraries()
    manifest_name = f'appmanifest_{appid}.acf'
    # Quando o mesmo AppID possui mais de um compatdata (por exemplo, um
    # prefixo auxiliar no Steam principal e o jogo numa biblioteca
    # secundária), o manifesto identifica a biblioteca correta.
    manifest_libraries = [
        lib for lib in libraries
        if os.path.isfile(os.path.join(lib, 'steamapps', manifest_name))
    ]
    ordered = manifest_libraries + [
        lib for lib in libraries if lib not in manifest_libraries
    ]
    for lib in ordered:
        pfx = os.path.join(lib, 'steamapps', 'compatdata', str(appid), 'pfx')
        if os.path.isdir(pfx):
            return pfx
    return None


def _resolve_prefix_root(pfx: str) -> str:
    """Resolve o diretório raiz do prefixo individual.

    Para jogos Steam onde o caminho termina em 'compatdata/<appid>/pfx',
    a pasta do jogo é o diretório do AppID ('compatdata/<appid>').
    Para todos os demais launchers (Hydra, Lutris, Heroic, Bottles,
    PortProton, PlayOnLinux, Custom), a pasta do prefixo em si já é pfx.
    Nunca apaga ou opera sobre o diretório pai que contém múltiplos prefixos.
    """
    if not pfx:
        return ''
    clean = os.path.abspath(pfx.rstrip('/'))
    if os.path.basename(clean) == 'pfx':
        parent = os.path.dirname(clean)
        grandparent = os.path.dirname(parent)
        if os.path.basename(grandparent) == 'compatdata':
            return parent
    return clean


# ── Steam games (via protontricks) ─────────────────────────────────

def get_steam_games():
    games = []
    seen_appids = set()
    try:
        r = subprocess.run(
            ['protontricks', '-l'],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().splitlines():
                line = line.strip()
                if '(' in line and line.endswith(')'):
                    name = line[:line.rfind('(')].strip()
                    appid = line[line.rfind('(') + 1:-1].strip()
                    if appid.isdigit() and appid not in seen_appids:
                        seen_appids.add(appid)
                        games.append({
                            'name': name,
                            'appid': appid,
                            'wineprefix': _find_steam_prefix(appid),
                            'source': 'Steam',
                            'pid': None,
                        })
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback / complemento via appmanifest_*.acf para jogos Steam com prefixo válido
    for lib in _steam_libraries():
        steamapps = os.path.join(lib, 'steamapps')
        if not os.path.isdir(steamapps):
            continue
        for fname in os.listdir(steamapps):
            if not (fname.startswith('appmanifest_') and fname.endswith('.acf')):
                continue
            appid = fname[len('appmanifest_'):-len('.acf')]
            if not appid.isdigit() or appid in seen_appids:
                continue
            pfx = os.path.join(steamapps, 'compatdata', appid, 'pfx')
            if not os.path.isdir(os.path.join(pfx, 'drive_c')):
                continue
            acf_raw = _read_file_safe(os.path.join(steamapps, fname))
            m = re.search(r'"name"\s+"([^"\n]+)"', acf_raw)
            name = m.group(1).strip() if m else f"Steam App {appid}"
            if any(skip in name.lower() for skip in ('proton', 'steamworks common', 'steam linux runtime')):
                continue
            seen_appids.add(appid)
            games.append({
                'name': name,
                'appid': appid,
                'wineprefix': pfx,
                'source': 'Steam',
                'pid': None,
            })
    return games


# ── running Wine/Proton processes ──────────────────────────────────

def _canonical_prefix_path(wineprefix: str) -> str:
    """Normaliza WINEPREFIX resolvendo barra final e symlinks (ex.: pfx -> .)."""
    if not wineprefix:
        return ''
    clean = wineprefix.rstrip('/') or wineprefix
    try:
        return os.path.realpath(clean)
    except OSError:
        return os.path.abspath(clean)


def _normalize_wineprefix(wineprefix):
    """Remove trailing slashes so the same prefix compares equal everywhere.

    /proc/*/environ reports WINEPREFIX with a trailing slash
    (e.g. .../pfx/) while Steam/compatdata detection builds it without one.
    os.path.dirname() on the un-normalized form returns .../pfx instead of
    .../compatdata/<appid>, which breaks the Proton version lookup and makes
    the app pick an arbitrary (wrong) wine build for a running game.
    """
    if not wineprefix:
        return wineprefix
    normalized = wineprefix.rstrip('/')
    return normalized or wineprefix


def _wine_bin_from_wineserver_exe(wineserver_exe):
    """Derive files/bin/wine from a live wineserver /proc/<pid>/exe path."""
    try:
        real = os.path.realpath(wineserver_exe)
    except OSError:
        return None
    bindir = os.path.dirname(real)
    for name in ('wine', 'wine64'):
        candidate = os.path.join(bindir, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def get_running_wine_entries():
    entries = []
    seen_prefixes = set()

    # Map normalized prefix -> wine binary of its LIVE wineserver. This is the
    # exact build hosting the running game; reusing it guarantees the trainer
    # / CE attaches to the same server instead of fighting it with a
    # different Proton build (which fails exactly when the game is running).
    live_wine_bins = {}
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            comm = _read_file_safe(f'/proc/{entry}/comm').strip()
        except OSError:
            continue
        if 'wineserver' not in comm.lower():
            continue
        environ_raw = _read_file_safe(f'/proc/{entry}/environ', 'rb')
        if not environ_raw:
            continue
        environ = environ_raw.decode('utf-8', errors='replace').split('\0')
        prefix = None
        for var in environ:
            if var.startswith('WINEPREFIX='):
                prefix = _normalize_wineprefix(var.split('=', 1)[1])
                break
        if not prefix:
            continue
        try:
            exe = os.readlink(f'/proc/{entry}/exe')
        except OSError:
            continue
        wine_bin = _wine_bin_from_wineserver_exe(exe)
        if wine_bin and prefix not in live_wine_bins:
            live_wine_bins[prefix] = wine_bin

    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        pid = entry

        environ_raw = _read_file_safe(f'/proc/{pid}/environ', 'rb')
        if not environ_raw:
            continue
        environ = environ_raw.decode('utf-8', errors='replace').split('\0')
        env = {}
        for var in environ:
            if '=' in var:
                k, v = var.split('=', 1)
                env[k] = v

        wineprefix = _normalize_wineprefix(env.get('WINEPREFIX'))
        if not wineprefix:
            continue

        cmdline_raw = _read_file_safe(f'/proc/{pid}/cmdline', 'rb')
        cmdline = cmdline_raw.decode('utf-8', errors='replace').replace('\0', ' ').strip() if cmdline_raw else ''
        comm = _read_file_safe(f'/proc/{pid}/comm').strip()

        if 'wineserver' in comm.lower():
            continue

        is_wine_proc = (
            'wine' in comm.lower() or 'wine' in cmdline.lower() or
            comm.lower() in ('wine', 'wine64', 'wine-preloader') or
            '.exe' in cmdline.lower()
        )
        if not is_wine_proc:
            continue

        is_proton = 'proton' in cmdline.lower()
        exe_path = None
        appid = None

        for part in cmdline.split():
            if part.lower().endswith('.exe') and os.path.isfile(part):
                exe_path = part
                break
            m2 = re.search(r"'([^']+\.exe)'", part)
            if m2 and os.path.isfile(m2.group(1)):
                exe_path = m2.group(1)
                break

        proc_name = comm
        if exe_path:
            proc_name = os.path.basename(exe_path)
        elif '.exe' in cmdline.lower():
            m = re.search(r'([^/\s]+\.exe)', cmdline, re.I)
            if m:
                proc_name = m.group(1)

        m = re.search(r'compatdata/(\d+)/', cmdline)
        if m:
            appid = m.group(1)
        elif wineprefix:
            m_hydra = re.search(r'hydralauncher(?:-native)?/wine-prefixes/(\d+)', wineprefix)
            if m_hydra:
                appid = m_hydra.group(1)

        launcher_keywords = [
            'lutris', 'bottles', 'heroic', 'epicgames', 'epic',
            'gog', 'battlenet', 'battle.net', 'ubisoft', 'uplay',
            'origin', 'ea', 'galaxy', 'launcher', 'upc', 'socialclub',
        ]
        is_launcher = any(k in proc_name.lower() for k in launcher_keywords)

        entry = {
            'name': proc_name,
            'pid': int(pid),
            'comm': comm,
            'cmdline': cmdline,
            'wineprefix': wineprefix,
            'appid': appid,
            'exe_path': exe_path,
            'is_proton': is_proton,
            'is_launcher': is_launcher,
            'wine_bin': live_wine_bins.get(wineprefix),
        }
        entries.append(entry)
        if wineprefix not in seen_prefixes:
            seen_prefixes.add(wineprefix)

    return entries


# ── launcher-config prefix detection ───────────────────────────────

def _parse_shortcuts_vdf(vdf_path: str) -> list[dict]:
    """Parseia Steam userdata/*/config/shortcuts.vdf (formato VDF binário)."""
    raw = _read_file_safe(vdf_path, 'rb')
    if not raw:
        return []
    pos = 0
    n = len(raw)

    def _read_cstr() -> str:
        nonlocal pos
        end = raw.find(b'\x00', pos)
        if end == -1:
            pos = n
            return ''
        val = raw[pos:end].decode('utf-8', errors='replace')
        pos = end + 1
        return val

    def _read_dict() -> dict:
        nonlocal pos
        obj = {}
        while pos < n:
            tcode = raw[pos]
            pos += 1
            if tcode == 0x08:  # end of map
                break
            key = _read_cstr()
            if tcode == 0x00:
                obj[key] = _read_dict()
            elif tcode == 0x01:
                obj[key] = _read_cstr()
            elif tcode == 0x02:
                if pos + 4 <= n:
                    obj[key] = struct.unpack_from('<i', raw, pos)[0]
                    pos += 4
                else:
                    pos = n
            elif tcode == 0x03:
                pos = min(n, pos + 4)
            elif tcode == 0x07:
                pos = min(n, pos + 8)
            else:
                break
        return obj

    root = _read_dict()
    shortcuts = root.get('shortcuts') if isinstance(root.get('shortcuts'), dict) else root
    entries = []
    if not isinstance(shortcuts, dict):
        return entries
    for val in shortcuts.values():
        if not isinstance(val, dict):
            continue
        norm = {str(k).lower(): v for k, v in val.items()}
        appname = str(norm.get('appname') or '').strip()
        exe = str(norm.get('exe') or '').strip().strip('"')
        raw_id = norm.get('appid')
        if isinstance(raw_id, int):
            appid = str(raw_id & 0xFFFFFFFF)
        elif appname and exe:
            crc = zlib.crc32((exe + appname).encode('utf-8')) | 0x80000000
            appid = str(crc & 0xFFFFFFFF)
        else:
            continue
        if appname:
            entries.append({'name': appname, 'appid': appid, 'exe': exe})
    return entries


def _detect_steam_non_steam():
    """Detecta jogos Não-Steam adicionados ao Steam (shortcuts.vdf + compatdata)."""
    out = []
    seen_pfx = set()
    steam_roots = [
        os.path.expanduser('~/.local/share/Steam'),
        os.path.expanduser('~/.steam/steam'),
        os.path.expanduser('~/.steam/root'),
    ]
    for root in steam_roots:
        userdata = os.path.join(root, 'userdata')
        if not os.path.isdir(userdata):
            continue
        for uid in os.listdir(userdata):
            vdf_path = os.path.join(userdata, uid, 'config', 'shortcuts.vdf')
            if not os.path.isfile(vdf_path):
                continue
            for sc in _parse_shortcuts_vdf(vdf_path):
                pfx = _find_steam_prefix(sc['appid'])
                if not pfx or not os.path.isdir(os.path.join(pfx, 'drive_c')):
                    continue
                canon = _canonical_prefix_path(pfx)
                if canon in seen_pfx:
                    continue
                seen_pfx.add(canon)
                out.append({
                    'name': sc['name'],
                    'appid': sc['appid'],
                    'wineprefix': pfx,
                    'source': 'Non-Steam',
                    'exe': sc['exe'],
                })
    return out


def _detect_lutris():
    out = []
    seen = set()
    cfg_dir = os.path.expanduser('~/.config/lutris/games/')
    if os.path.isdir(cfg_dir):
        for fname in os.listdir(cfg_dir):
            fpath = os.path.join(cfg_dir, fname)
            if fname.endswith('.json'):
                try:
                    data = json.loads(Path(fpath).read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                pfx = data.get('wine_prefix') or ''
                if pfx and os.path.isdir(os.path.join(pfx, 'drive_c')):
                    canon = _canonical_prefix_path(pfx)
                    if canon not in seen:
                        seen.add(canon)
                        out.append({
                            'name': f"Lutris: {data.get('name', fname[:-5])}",
                            'wineprefix': pfx,
                            'source': 'Lutris',
                            'exe': data.get('exe', ''),
                        })
            elif fname.endswith(('.yml', '.yaml')):
                raw = _read_file_safe(fpath)
                if not raw:
                    continue
                pfx = ''
                exe = ''
                gname = fname.rsplit('.', 1)[0]
                section = ''
                for line in raw.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#'):
                        continue
                    indent = len(line) - len(line.lstrip())
                    if indent == 0 and ':' in stripped:
                        k, v = stripped.split(':', 1)
                        section = k.strip()
                        v = v.strip().strip("'\"")
                        if section == 'name' and v:
                            gname = v
                    elif indent > 0 and ':' in stripped:
                        k, v = stripped.split(':', 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if section == 'wine' and k == 'prefix' and v:
                            pfx = os.path.expanduser(v)
                        elif section == 'game' and k == 'exe' and v:
                            exe = os.path.expanduser(v)
                if pfx and os.path.isdir(os.path.join(pfx, 'drive_c')):
                    canon = _canonical_prefix_path(pfx)
                    if canon not in seen:
                        seen.add(canon)
                        out.append({
                            'name': f"Lutris: {gname}",
                            'wineprefix': pfx,
                            'source': 'Lutris',
                            'exe': exe,
                        })

    pga_db = os.path.expanduser('~/.local/share/lutris/pga.db')
    if os.path.isfile(pga_db):
        try:
            conn = sqlite3.connect(f'file:{pga_db}?mode=ro', uri=True)
            cur = conn.cursor()
            cur.execute("SELECT name, directory FROM games WHERE directory IS NOT NULL AND directory != ''")
            for gname, directory in cur.fetchall():
                pfx = os.path.expanduser(str(directory))
                if pfx and os.path.isdir(os.path.join(pfx, 'drive_c')):
                    canon = _canonical_prefix_path(pfx)
                    if canon not in seen:
                        seen.add(canon)
                        out.append({
                            'name': f"Lutris: {gname or os.path.basename(pfx)}",
                            'wineprefix': pfx,
                            'source': 'Lutris',
                            'exe': '',
                        })
            conn.close()
        except Exception:
            pass
    return out


def _detect_bottles():
    out = []
    seen = set()
    bases = [
        os.path.expanduser('~/.var/app/com.usebottles.bottles/data/bottles/bottles/'),
        os.path.expanduser('~/.var/app/com.usebottles.bottles/data/bottles/'),
        os.path.expanduser('~/.local/share/bottles/bottles/'),
        os.path.expanduser('~/.local/share/bottles/'),
    ]
    for base in bases:
        if not os.path.isdir(base):
            continue
        for bottle in os.listdir(base):
            pfx = os.path.join(base, bottle)
            if os.path.isdir(os.path.join(pfx, 'drive_c')):
                canon = _canonical_prefix_path(pfx)
                if canon in seen:
                    continue
                seen.add(canon)
                out.append({
                    'name': f"Bottles: {bottle}",
                    'wineprefix': pfx,
                    'source': 'Bottles',
                    'exe': '',
                })
    return out


def _detect_heroic():
    out = []
    seen = set()

    def _add_heroic(title, pfx, exe=''):
        if pfx and os.path.isdir(os.path.join(pfx, 'drive_c')):
            canon = _canonical_prefix_path(pfx)
            if canon not in seen:
                seen.add(canon)
                out.append({
                    'name': f"Heroic: {title}",
                    'wineprefix': pfx,
                    'source': 'Heroic',
                    'exe': exe,
                })

    for cfg_dir in [
        os.path.expanduser('~/.config/heroic/'),
        os.path.expanduser('~/.var/app/com.heroicgameslauncher.hgl/config/heroic/'),
    ]:
        if not os.path.isdir(cfg_dir):
            continue

        cfg_file = os.path.join(cfg_dir, 'config.json')
        if os.path.isfile(cfg_file):
            try:
                data = json.loads(Path(cfg_file).read_text())
            except (OSError, json.JSONDecodeError):
                data = {}
            for game_id, game_data in data.items():
                if not isinstance(game_data, dict):
                    continue
                pfx = game_data.get('winePrefix') or game_data.get('wine_prefix', '')
                _add_heroic(game_data.get('title', game_id), pfx, game_data.get('executable', ''))

        gc_dir = os.path.join(cfg_dir, 'GamesConfig')
        if os.path.isdir(gc_dir):
            for fname in os.listdir(gc_dir):
                if not fname.endswith('.json'):
                    continue
                try:
                    gc = json.loads(Path(os.path.join(gc_dir, fname)).read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(gc, dict):
                    continue
                pfx = gc.get('winePrefix') or gc.get('wine_prefix', '')
                if pfx:
                    _add_heroic(gc.get('title', fname[:-5]), pfx, gc.get('executable', ''))
                for sub_key, sub_val in gc.items():
                    if isinstance(sub_val, dict):
                        spfx = sub_val.get('winePrefix') or sub_val.get('wine_prefix', '')
                        _add_heroic(sub_val.get('title', sub_key or fname[:-5]), spfx, sub_val.get('executable', ''))

    for pfx_root in [
        os.path.expanduser('~/Games/Heroic/Prefixes/default'),
        os.path.expanduser('~/Games/Heroic/Prefixes'),
    ]:
        if not os.path.isdir(pfx_root):
            continue
        for item in os.listdir(pfx_root):
            pfx = os.path.join(pfx_root, item)
            _add_heroic(item, pfx)
    return out


def _detect_portproton():
    out = []
    seen_real = set()
    bases = [
        os.path.expanduser('~/.var/app/ru.linux_gaming.PortProton/data/prefixes/'),
        os.path.expanduser('~/PortProton/prefixes/'),
        os.path.expanduser('~/PortProton/data/prefixes/'),
    ]
    for base in bases:
        if not os.path.isdir(base):
            continue
        for entry in os.listdir(base):
            pfx = os.path.join(base, entry)
            if not os.path.isdir(os.path.join(pfx, 'drive_c')):
                continue
            real = os.path.realpath(pfx)
            if real in seen_real:
                continue
            seen_real.add(real)
            out.append({
                'name': entry,
                'wineprefix': real,
                'source': 'PortProton',
                'exe': '',
            })
    return out


def _detect_playonlinux():
    out = []
    pol = os.path.expanduser('~/.PlayOnLinux/wineprefix/')
    if not os.path.isdir(pol):
        return out
    for name in os.listdir(pol):
        pfx = os.path.join(pol, name)
        if os.path.isdir(os.path.join(pfx, 'drive_c')):
            out.append({
                'name': f"PlayOnLinux: {name}",
                'wineprefix': pfx,
                'source': 'PlayOnLinux',
                'exe': '',
            })
    return out


def _resolve_steam_title(appid: str) -> str:
    """Resolve steam appid to game title, caching results locally."""
    if not appid or not str(appid).isdigit():
        return ''
    appid = str(appid)
    cache_path = os.path.expanduser('~/.config/trainer_manager/steam_titles_cache.json')
    cache = {}
    if os.path.isfile(cache_path):
        try:
            cache = json.loads(Path(cache_path).read_text())
        except (OSError, json.JSONDecodeError):
            cache = {}
    if appid in cache and cache[appid]:
        return cache[appid]

    try:
        import urllib.request
        url = f'https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            name = data.get(appid, {}).get('data', {}).get('name')
            if name:
                cache[appid] = name
                try:
                    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(cache_path).write_text(json.dumps(cache, indent=2))
                except OSError:
                    pass
                return name
    except Exception:
        pass
    return ''


_HYDRA_META_CACHE: dict[tuple, dict] = {}


def _get_hydra_games_metadata(target_ids=None):
    """Extract game metadata (title, executablePath) from Hydra database and logs."""
    import glob
    hydra_dirs = [
        os.path.expanduser('~/.config/hydralauncher'),
        os.path.expanduser('~/.config/hydralauncher-native'),
        os.path.expanduser('~/.var/app/io.github.hydralauncher.hydra/config/hydralauncher'),
        os.path.expanduser('~/.var/app/io.github.hydralauncher.hydra/config/hydralauncher-native'),
    ]

    if target_ids is not None and len(target_ids) == 0:
        return {}

    target_set = {str(t_id) for t_id in target_ids} if target_ids is not None else None
    target_bytes = [t_id.encode('utf-8') for t_id in target_set] if target_set else []

    sig_parts = []
    db_files = []
    log_dirs = []
    for h_dir in hydra_dirs:
        db_dir = os.path.join(h_dir, 'hydra-db')
        if os.path.isdir(db_dir):
            for fpath in sorted(glob.glob(os.path.join(db_dir, '*'))):
                if not fpath.endswith(('.log', '.ldb')):
                    continue
                try:
                    st = os.stat(fpath)
                    sig_parts.append((fpath, st.st_mtime_ns, st.st_size))
                    db_files.append(fpath)
                except OSError:
                    continue
        logs_dir = os.path.join(h_dir, 'logs')
        if os.path.isdir(logs_dir):
            log_dirs.append(logs_dir)
            ach_path = os.path.join(logs_dir, 'achievements.txt')
            if os.path.isfile(ach_path):
                try:
                    st = os.stat(ach_path)
                    sig_parts.append((ach_path, st.st_mtime_ns, st.st_size))
                except OSError:
                    pass

    cache_key = (tuple(sig_parts), frozenset(target_set) if target_set is not None else None)
    if cache_key in _HYDRA_META_CACHE:
        return _HYDRA_META_CACHE[cache_key]

    games = {}

    for fpath in db_files:
        try:
            data = Path(fpath).read_bytes()
        except OSError:
            continue

        # Fast skip when searching specific installed Hydra IDs
        if target_bytes and not any(tb in data for tb in target_bytes):
            continue

        # 1. Parse structured JSON payloads following !games! and !gameShopAssets!
        idx = 0
        while True:
            p_games = data.find(b'!games!', idx)
            p_shop = data.find(b'!gameShopAssets!', idx)
            candidates = [p for p in (p_games, p_shop) if p != -1]
            if not candidates:
                break
            p_next = min(candidates)
            idx = p_next + 7

            brace_start = data.find(b'{', p_next)
            if brace_start != -1 and brace_start - p_next < 120:
                window = data[brace_start:brace_start + 10000]
                if target_bytes and not any(tb in window for tb in target_bytes):
                    continue
                depth = 0
                in_string = False
                escape = False
                for i in range(len(window)):
                    b = window[i:i+1]
                    if escape:
                        escape = False
                        continue
                    if b == b'\\':
                        escape = True
                        continue
                    if b == b'"':
                        in_string = not in_string
                        continue
                    if not in_string:
                        if b == b'{':
                            depth += 1
                        elif b == b'}':
                            depth -= 1
                            if depth == 0:
                                raw = window[:i+1].decode('utf-8', errors='ignore')
                                try:
                                    obj = json.loads(raw)
                                    oid = str(obj.get('objectId') or obj.get('id') or '')
                                    title = obj.get('title')
                                    exe = obj.get('executablePath') or ''
                                    if oid and title and (target_set is None or oid in target_set):
                                        if oid not in games:
                                            games[oid] = {'title': title, 'exe': exe}
                                        else:
                                            if title:
                                                games[oid]['title'] = title
                                            if exe and (not games[oid]['exe'] or os.path.isfile(exe)):
                                                games[oid]['exe'] = exe
                                except Exception:
                                    pass
                                break

        # 2. Targeted regex fallback for string pairs across binary LevelDB blocks
        if target_set is not None:
            for tid in target_set:
                if tid in games and games[tid].get('title'):
                    continue
                tid_b = re.escape(tid.encode('utf-8'))
                m1 = re.search(rb'"objectId":"' + tid_b + rb'"[^}{]{1,800}"title":"((?:[^"\\]|\\.)*)"', data)
                m2 = None if m1 else re.search(rb'"title":"((?:[^"\\]|\\.)*)"[^}{]{1,800}"objectId":"' + tid_b + rb'"', data)
                m = m1 or m2
                if m:
                    t_raw = m.group(1).decode('utf-8', errors='ignore')
                    try:
                        t_raw = json.loads(f'"{t_raw}"')
                    except Exception:
                        pass
                    games[tid] = {'title': t_raw, 'exe': games.get(tid, {}).get('exe', '')}
        else:
            p1 = re.compile(rb'"objectId":"(\d+)"[^}{]{1,800}"title":"((?:[^"\\]|\\.)*)"')
            p2 = re.compile(rb'"title":"((?:[^"\\]|\\.)*)"[^}{]{1,800}"objectId":"(\d+)"')
            for m in p1.finditer(data):
                oid = m.group(1).decode('utf-8', errors='ignore')
                t_raw = m.group(2).decode('utf-8', errors='ignore')
                try:
                    t_raw = json.loads(f'"{t_raw}"')
                except Exception:
                    pass
                if oid not in games or not games[oid].get('title'):
                    games[oid] = {'title': t_raw, 'exe': ''}
            for m in p2.finditer(data):
                t_raw = m.group(1).decode('utf-8', errors='ignore')
                oid = m.group(2).decode('utf-8', errors='ignore')
                try:
                    t_raw = json.loads(f'"{t_raw}"')
                except Exception:
                    pass
                if oid not in games or not games[oid].get('title'):
                    games[oid] = {'title': t_raw, 'exe': ''}

    # 3. Check logs directory for achievements notifications and umu executable commands
    for logs_dir in log_dirs:
        ach_path = os.path.join(logs_dir, 'achievements.txt')
        if os.path.isfile(ach_path):
            try:
                with open(ach_path, 'r', encoding='utf-8', errors='ignore') as fp:
                    for line in fp:
                        if 'Publishing achievement notification' in line:
                            parts = line.strip().split('Publishing achievement notification', 1)
                            if len(parts) == 2:
                                sub = parts[1].strip().split(' ', 1)
                                if len(sub) == 2 and sub[0].isdigit():
                                    aid, tname = sub[0], sub[1].strip()
                                    if (target_set is None or aid in target_set) and aid not in games:
                                        games[aid] = {'title': tname, 'exe': ''}
            except OSError:
                pass

        for oid, info in games.items():
            if not info.get('exe') or not os.path.isfile(info['exe']):
                umu_log = os.path.join(logs_dir, f'umu-{oid}.log')
                if os.path.isfile(umu_log):
                    try:
                        with open(umu_log, 'r', encoding='utf-8', errors='ignore') as fp:
                            for line in fp:
                                if 'Command:' in line and '.exe' in line:
                                    m = re.findall(r"['\"]([^'\"]+\.exe)['\"]", line)
                                    if m and os.path.isfile(m[-1]):
                                        info['exe'] = m[-1]
                    except OSError:
                        pass

    if len(_HYDRA_META_CACHE) > 8:
        _HYDRA_META_CACHE.clear()
    _HYDRA_META_CACHE[cache_key] = games
    return games


def _detect_hydra():
    out = []
    bases = [
        os.path.expanduser('~/.config/hydralauncher/wine-prefixes'),
        os.path.expanduser('~/.config/hydralauncher-native/wine-prefixes'),
        os.path.expanduser('~/.var/app/io.github.hydralauncher.hydra/config/hydralauncher/wine-prefixes'),
        os.path.expanduser('~/.var/app/io.github.hydralauncher.hydra/config/hydralauncher-native/wine-prefixes'),
    ]
    found_entries = []
    seen_prefixes = set()
    for base in bases:
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            pfx = _canonical_prefix_path(os.path.join(base, entry))
            if not os.path.isdir(os.path.join(pfx, 'drive_c')):
                continue
            if pfx in seen_prefixes:
                continue
            seen_prefixes.add(pfx)
            found_entries.append((entry, pfx))

    if not found_entries:
        return out

    meta = _get_hydra_games_metadata(target_ids={entry for entry, _ in found_entries})
    for entry, pfx in found_entries:
        game_info = meta.get(entry, {})
        title = game_info.get('title')
        if not title and entry.isdigit():
            title = _resolve_steam_title(entry)
        display_title = title if title else entry
        exe = game_info.get('exe', '')

        out.append({
            'name': f"Hydra: {display_title}",
            'wineprefix': pfx,
            'source': 'Hydra',
            'exe': exe,
            'appid': entry if entry.isdigit() else None,
        })
    return out


def _detect_default_wine():
    out = []
    default = os.path.expanduser('~/.wine')
    if os.path.isdir(os.path.join(default, 'drive_c')):
        out.append({
            'name': 'Default Wine (~/.wine)',
            'wineprefix': _canonical_prefix_path(default),
            'source': 'Default Wine',
            'exe': '',
        })
    return out


def _detect_custom():
    out = []
    seen = set()
    no_steam_base = os.path.expanduser('~/Games/NoSteamGames')
    if os.path.isdir(no_steam_base):
        for item in os.listdir(no_steam_base):
            pfx = os.path.join(no_steam_base, item)
            if os.path.isdir(os.path.join(pfx, 'drive_c')):
                canon = _canonical_prefix_path(pfx)
                if canon not in seen:
                    seen.add(canon)
                    out.append({
                        'name': item,
                        'wineprefix': canon,
                        'source': 'Non-Steam',
                        'exe': '',
                    })

    for base in [os.path.expanduser('~/Games'), os.path.expanduser('~/wineprefixes')]:
        if not os.path.isdir(base):
            continue
        for item in os.listdir(base):
            if item in ('SteamLibrary', 'Heroic', 'NoSteamGames') or item.startswith('.'):
                continue
            pfx = os.path.join(base, item)
            if os.path.isdir(os.path.join(pfx, 'drive_c')):
                canon = _canonical_prefix_path(pfx)
                if canon not in seen:
                    seen.add(canon)
                    out.append({
                        'name': item,
                        'wineprefix': canon,
                        'source': 'Custom',
                        'exe': '',
                    })
    return out


_LAUNCHER_DETECTORS = [
    _detect_steam_non_steam,
    _detect_lutris,
    _detect_bottles,
    _detect_heroic,
    _detect_portproton,
    _detect_playonlinux,
    _detect_hydra,
    _detect_default_wine,
    _detect_custom,
]


def get_launcher_prefixes():
    out = []
    for fn in _LAUNCHER_DETECTORS:
        out.extend(fn())
    return out


def get_custom_prefixes():
    cfg = load_config()
    return cfg.get('custom_prefixes', [])


def scan_trainer_exes(folder_path):
    if not folder_path or not os.path.isdir(folder_path):
        return []
    exes = []
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if f.lower().endswith('.exe'):
                exes.append(os.path.join(root, f))
    return exes


def get_all_entries():
    seen = set()
    items = []
    hidden = set(load_config().get('hidden_prefixes', []))

    def _add(entry):
        pfx = entry.get('wineprefix', '')
        canon = _canonical_prefix_path(pfx)
        key = canon if canon else f"{entry.get('source','')}:{entry.get('appid','')}"
        if key not in seen:
            seen.add(key)
            if entry.get('source') not in ('Não-Steam', 'Non-Steam') and (pfx in hidden or canon in hidden):
                return
            items.append(entry)

    for g in get_steam_games():
        _add(g)

    for p in get_running_wine_entries():
        pfx = p['wineprefix']
        appid = p['appid']
        if appid:
            steam_pfx = _find_steam_prefix(appid)
            if steam_pfx:
                pfx = steam_pfx
        if not pfx and appid:
            pfx = _find_steam_prefix(appid)

        label = p['name']
        if p['is_proton']:
            label += ' [Proton]'
        if p['is_launcher']:
            label = f"Launcher: {label}"

        _add({
            'name': label,
            'appid': appid,
            'wineprefix': pfx or '',
            'source': f"PID {p['pid']} — {p['comm']}",
            'exe': p.get('exe_path', ''),
            'pid': p['pid'],
            'is_proton': p['is_proton'],
        })

    for l in get_launcher_prefixes():
        _add({
            'name': l['name'],
            'appid': l.get('appid', None),
            'wineprefix': l['wineprefix'],
            'source': l['source'],
            'exe': l.get('exe', ''),
            'is_proton': False,
        })

    for c in get_custom_prefixes():
        pfx = c.get('wineprefix', '')
        if pfx:
            _add({
                'name': c.get('name', pfx),
                'appid': None,
                'wineprefix': pfx,
                'source': 'Não-Steam',
                'exe': '',
                'is_proton': False,
            })

    return items


# ── wine binary ────────────────────────────────────────────────────

def find_wine_binary(wineprefix=None):
    if wineprefix:
        from wemod_manager import _get_wine_binary
        wb = _get_wine_binary(wineprefix)
        if wb:
            return wb
    steam_roots = [
        os.path.expanduser('~/.local/share/Steam'),
        os.path.expanduser('~/.steam/steam'),
        os.path.expanduser('~/.steam/root'),
    ]
    candidates = []
    for r in steam_roots:
        common = os.path.join(r, 'steamapps', 'common')
        if os.path.isdir(common):
            candidates.append(common)
        compat = os.path.join(r, 'compatibilitytools.d')
        if os.path.isdir(compat):
            candidates.append(compat)

    proton_dirs = []
    for base in candidates:
        if not os.path.isdir(base):
            continue
        for d in os.listdir(base):
            if 'proton' in d.lower():
                proton_dirs.append(os.path.join(base, d))

    for d in proton_dirs:
        for name in ('wine', 'wine64'):
            wine = os.path.join(d, 'files', 'bin', name)
            if os.path.isfile(wine):
                return wine

    for candidate in ('/usr/bin/wine', '/usr/local/bin/wine'):
        if os.path.isfile(candidate):
            return candidate
    for candidate in ('/usr/bin/wine64', '/usr/local/bin/wine64'):
        if os.path.isfile(candidate):
            return candidate
    return shutil.which('wine') or shutil.which('wine64') or 'wine'


def get_available_wine_runners(wineprefix=None):
    """Return one executable per real installation, with the preferred one first."""
    runners = []
    seen = set()

    def identity(path):
        # wine and wine64 belong to one runner even when they are distinct
        # executables. Resolve directory aliases before comparing installations.
        binary_dir = Path(os.path.realpath(os.path.dirname(path)))
        if binary_dir.name == 'bin' and binary_dir.parent.name in ('files', 'dist'):
            return str(binary_dir.parent.parent)
        return os.path.realpath(path)

    def add(label, path):
        if os.path.isfile(path) and identity(path) not in seen:
            seen.add(identity(path))
            runners.append((label, os.path.realpath(path)))

    def display_name(directory):
        manifest = _read_file_safe(os.path.join(directory, 'compatibilitytool.vdf'))
        match = re.search(r'"display_name"\s+"([^"\n]+)"', manifest)
        return match.group(1) if match else os.path.basename(directory)

    for cand in ('/usr/bin/wine', '/usr/bin/wine64', '/usr/local/bin/wine'):
        if os.path.isfile(cand):
            add('System Wine', cand)
            break

    scanned = set()
    for r in _steam_libraries():
        candidates = [
            os.path.join(r, 'compatibilitytools.d'),
            os.path.join(r, 'steamapps', 'common'),
        ]
        for base in candidates:
            base = os.path.realpath(base)
            if base in scanned or not os.path.isdir(base):
                continue
            scanned.add(base)
            for d in sorted(os.listdir(base), key=str.casefold):
                directory = os.path.join(base, d)
                # CachyOS and other valid tools need not have "proton" in
                # their folder name. Keep a fallback for older installations.
                if not (os.path.isfile(os.path.join(directory, 'compatibilitytool.vdf'))
                        or os.path.isfile(os.path.join(directory, 'proton'))
                        or 'proton' in d.lower()):
                    continue
                for relative in ('files/bin/wine', 'files/bin/wine64',
                                 'dist/bin/wine', 'dist/bin/wine64'):
                    binary = os.path.join(directory, relative)
                    if os.path.isfile(binary):
                        add(display_name(directory), binary)
                        break

    if wineprefix:
        preferred = find_wine_binary(wineprefix)
        if preferred and os.path.isfile(preferred):
            key = identity(preferred)
            for index, (label, path) in enumerate(runners):
                if identity(path) == key:
                    runners.pop(index)
                    runners.insert(0, (label, os.path.realpath(preferred)))
                    break
            else:
                directory = key if os.path.isdir(key) else os.path.dirname(key)
                label = display_name(directory) if os.path.isdir(key) else f'Wine ({os.path.basename(preferred)})'
                runners.insert(0, (label, os.path.realpath(preferred)))

    return runners


_WINE_VERSION_CACHE = {}


def get_wine_runner_label(wine_bin, wineprefix=None):
    """Return a concise, human-readable display name for the Wine / Proton version."""
    if not wine_bin and wineprefix:
        wine_bin = find_wine_binary(wineprefix)
    if not wine_bin:
        return "Não detectado"

    real_bin = os.path.realpath(wine_bin)

    # 1. Match against scanned runners (covers Steam Protons, GE-Proton, etc.)
    runners = get_available_wine_runners(wineprefix)
    for label, path in runners:
        if os.path.realpath(path) == real_bin and label.lower() not in ('wine', 'wine64'):
            return label

    # 2. Check compatibilitytool.vdf or proton script in parent directories
    p = Path(real_bin)
    cur = p.parent
    for _ in range(4):
        vdf = cur / 'compatibilitytool.vdf'
        if vdf.is_file():
            content = _read_file_safe(str(vdf))
            m = re.search(r'"display_name"\s+"([^"\n]+)"', content)
            if m:
                return m.group(1).strip()
            return cur.name
        if (cur / 'proton').is_file():
            return cur.name
        cur = cur.parent

    # 3. Check version file in compatdata parent
    if wineprefix:
        pfx_clean = wineprefix.rstrip('/')
        ver_file = os.path.join(os.path.dirname(pfx_clean), 'version')
        if os.path.isfile(ver_file):
            v_content = _read_file_safe(ver_file).strip()
            if v_content:
                return f"Proton ({v_content})"

        # PortProton .wine_ver
        pp_ver = os.path.join(pfx_clean, '.wine_ver')
        if os.path.isfile(pp_ver):
            pp_content = _read_file_safe(pp_ver).strip()
            if pp_content:
                return f"PortProton ({pp_content})"

    # 4. Check system wine
    if '/usr/bin' in real_bin or '/usr/local/bin' in real_bin:
        return "System Wine"

    # 5. Try wine --version for custom/bundled builds
    if real_bin in _WINE_VERSION_CACHE:
        return _WINE_VERSION_CACHE[real_bin]

    try:
        r = subprocess.run([real_bin, '--version'], capture_output=True, text=True, timeout=1.5)
        if r.returncode == 0 and r.stdout.strip():
            ver = r.stdout.strip()
            _WINE_VERSION_CACHE[real_bin] = ver
            return ver
    except Exception:
        pass

    # 6. Fallback to enclosing directory or binary name
    parent_name = os.path.basename(os.path.dirname(os.path.dirname(real_bin)))
    fallback = parent_name if parent_name and parent_name not in ('', '.', 'bin', 'files', 'dist') else os.path.basename(real_bin)
    _WINE_VERSION_CACHE[real_bin] = fallback
    return fallback


def _setup_proton_env_for_exe(env, wine_bin):
    wine_real = os.path.realpath(wine_bin)
    wine_dir = os.path.dirname(wine_real)
    for base in (os.path.dirname(wine_dir), os.path.dirname(os.path.dirname(wine_dir))):
        lib = os.path.join(base, 'lib')
        lib64 = os.path.join(base, 'lib64')
        dll_paths = []
        lib_paths = []
        for d in (lib64, lib):
            wine_dll = os.path.join(d, 'wine')
            if os.path.isdir(wine_dll):
                dll_paths.append(wine_dll)
            if os.path.isdir(d):
                lib_paths.append(d)
        if dll_paths:
            env['WINEDLLPATH'] = ':'.join(dll_paths)
        if lib_paths:
            existing = env.get('LD_LIBRARY_PATH', '')
            env['LD_LIBRARY_PATH'] = ':'.join(lib_paths) + (':' + existing if existing else '')
            break


def _trainer_temp_dir(wineprefix):
    """Resolve the Windows TEMP directory recorded by a Wine prefix."""
    user_reg = _read_file_safe(os.path.join(wineprefix, 'user.reg'))
    section = re.search(
        r'^\[Environment\][^\n]*\n(.*?)(?=^\[|\Z)',
        user_reg,
        re.MULTILINE | re.DOTALL,
    )
    if section:
        match = re.search(r'^"TEMP"="(.*)"$', section.group(1), re.MULTILINE)
        if match:
            windows_path = match.group(1).replace('\\\\', '\\')
            drive_match = re.match(r'^([A-Za-z]):[\\/](.*)$', windows_path)
            if drive_match and drive_match.group(1).lower() == 'c':
                parts = [
                    part for part in re.split(r'[\\/]+', drive_match.group(2))
                    if part not in ('', '.')
                ]
                if '..' not in parts:
                    return os.path.join(wineprefix, 'drive_c', *parts)

    # Proton normally uses steamuser.  Older/custom prefixes can use any
    # profile name, so fall back to the first real user profile.
    users_dir = os.path.join(wineprefix, 'drive_c', 'users')
    preferred = os.path.join(users_dir, 'steamuser')
    if os.path.isdir(preferred):
        return os.path.join(preferred, 'Temp')
    if os.path.isdir(users_dir):
        ignored = {'public', 'default', 'default user', 'all users'}
        for name in sorted(os.listdir(users_dir), key=str.casefold):
            profile = os.path.join(users_dir, name)
            if os.path.isdir(profile) and name.casefold() not in ignored:
                return os.path.join(profile, 'AppData', 'Local', 'Temp')
    return os.path.join(wineprefix, 'drive_c', 'windows', 'temp')


def _clean_stale_fling_locks(wineprefix):
    """Remove stale FLiNG locks (info.ini) that falsely signal that another
    instance is already running for the active game PID."""
    users_dir = os.path.join(wineprefix, 'drive_c', 'users')
    if not os.path.isdir(users_dir):
        return
    for user in os.listdir(users_dir):
        fling_logs = os.path.join(users_dir, user, 'AppData', 'Local', 'FLiNGTrainer', 'trainer-logs')
        if os.path.isdir(fling_logs):
            for root, _, files in os.walk(fling_logs):
                for f in files:
                    if f.lower() == 'info.ini':
                        try:
                            os.remove(os.path.join(root, f))
                        except OSError:
                            pass


def _prepare_trainer_prefix(wine_bin, wineprefix, env):
    """Prepare a prefix for current FLiNG/WPF self-extracting trainers."""
    temp_dir = _trainer_temp_dir(wineprefix)
    os.makedirs(temp_dir, exist_ok=True)
    _clean_stale_fling_locks(wineprefix)

    # Recent FLiNG trainers unpack a managed WPF payload into %TEMP%.  Native
    # .NET WPF can crash in wpfgfx_v0400 while probing the Proton/DXVK graphics
    # stack.  This documented Avalon switch keeps only WPF on software
    # rendering; it does not disable DXVK for the game itself.
    try:
        result = subprocess.run(
            [
                wine_bin, 'reg', 'add',
                r'HKCU\Software\Microsoft\Avalon.Graphics',
                '/v', 'DisableHWAcceleration',
                '/t', 'REG_DWORD', '/d', '1', '/f',
            ],
            env=env,
            capture_output=True,
            text=True,
            errors='replace',
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('timeout ao configurar renderizacao WPF no prefixo') from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            'nao foi possivel configurar renderizacao WPF no prefixo'
            + (f': {detail}' if detail else '')
        )
    return temp_dir


def run_exe_in_prefix(wine_bin, exe_path, wineprefix, pin=None, extra_env=None,
                      prepare_prefix=True, game_name=None, app_name=None,
                      on_error_callback=None):
    wineprefix = _normalize_wineprefix(wineprefix)
    if not app_name:
        app_name = os.path.basename(exe_path)

    temp_fd, temp_logfile = tempfile.mkstemp(
        prefix=f'as_run_{error_logger.sanitize_name(app_name)}_{pin or os.getpid()}_',
        suffix='.tmp'
    )
    os.close(temp_fd)

    env = os.environ.copy()
    env['WINEPREFIX'] = wineprefix
    if extra_env:
        env.update(extra_env)

    # The runner may be a custom Proton build whose path does not contain the
    # word "proton". The helper is harmless for system Wine and correctly
    # detects whether the expected lib/lib64 layout exists.
    _setup_proton_env_for_exe(env, wine_bin)
    env['PATH'] = os.path.dirname(wine_bin) + ':' + env.get('PATH', '')
    temp_dir = None
    if prepare_prefix:
        try:
            temp_dir = _prepare_trainer_prefix(wine_bin, wineprefix, env)
        except Exception as prep_exc:
            err_log = error_logger.save_error_log(
                game_name=game_name,
                app_name=app_name,
                problem_type="Erro_de_Inicializacao",
                details=f"Falha na preparação do prefixo: {prep_exc}\n{traceback.format_exc()}",
                context={
                    'WINEPREFIX': wineprefix,
                    'Wine Binary': wine_bin,
                    'Executable': exe_path,
                }
            )
            try:
                os.remove(temp_logfile)
            except OSError:
                pass
            raise RuntimeError(f"Falha na preparação do prefixo (log: {os.path.basename(err_log)}): {prep_exc}") from prep_exc

    try:
        log_stream = open(temp_logfile, 'w')
        log_stream.write(f'[Action Shark] WINEPREFIX={wineprefix}\n')
        if temp_dir:
            log_stream.write(f'[Action Shark] TEMP={temp_dir}\n')
            log_stream.write('[Action Shark] WPF software rendering enabled\n')
        log_stream.flush()
        proc = subprocess.Popen(
            [wine_bin, exe_path],
            cwd=os.path.dirname(os.path.abspath(exe_path)),
            env=env,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception as popen_exc:
        err_log = error_logger.save_error_log(
            game_name=game_name,
            app_name=app_name,
            problem_type="Erro_de_Inicializacao",
            details=f"Falha ao iniciar processo: {popen_exc}\n{traceback.format_exc()}",
            context={
                'WINEPREFIX': wineprefix,
                'Wine Binary': wine_bin,
                'Executable': exe_path,
            }
        )
        try:
            os.remove(temp_logfile)
        except OSError:
            pass
        raise RuntimeError(f"Falha ao iniciar processo (log: {os.path.basename(err_log)}): {popen_exc}") from popen_exc

    context_info = {
        'WINEPREFIX': wineprefix,
        'Wine Binary': wine_bin,
        'Executable': exe_path,
        'PID': proc.pid,
    }
    error_logger.watch_process_execution(
        proc=proc,
        temp_logfile=temp_logfile,
        game_name=game_name,
        app_name=app_name,
        context=context_info,
        on_error_callback=on_error_callback,
    )
    return proc


def _find_wine_bin_for_pid(pid):
    seen = set()
    while pid and pid not in seen:
        seen.add(pid)
        raw = _read_file_safe(f'/proc/{pid}/cmdline', 'rb')
        if raw:
            for part in raw.decode('utf-8', errors='replace').split('\0'):
                part = part.strip("'\"")
                if re.search(r'/wine(64)?$', part) and os.path.isfile(part):
                    return part
        env_raw = _read_file_safe(f'/proc/{pid}/environ', 'rb')
        if env_raw:
            for var in env_raw.decode('utf-8', errors='replace').split('\0'):
                if var.startswith('WINEDLLPATH='):
                    base_part = var.split('=', 1)[1].split(':', 1)[0]
                    base_dir = base_part.rsplit('/files/', 1)[0]
                    for name in ('wine', 'wine64'):
                        candidate = os.path.join(base_dir, 'files', 'bin', name)
                        if os.path.isfile(candidate):
                            return candidate
        status = _read_file_safe(f'/proc/{pid}/status')
        if not status:
            break
        m = re.search(r'PPid:\s+(\d+)', status)
        if not m:
            break
        pid = int(m.group(1))
    return None


# ── UI: ProtonRunner (Exact Mockup 2 Desktop Pro) ────────────────────

class ProtonRunner(QWidget):
    process_error_detected = pyqtSignal(str, str)
    wemod_action_finished = pyqtSignal(str, bool, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Action Shark')
        self.setWindowIcon(get_shark_icon(32))
        # The mockup uses a custom, frameless window chrome.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(980, 620)
        self.resize(1270, 676)
        self._drag_origin = None

        if QApplication.instance():
            QApplication.instance().setStyleSheet(styles.GLOBAL_STYLESHEET)
        self.setStyleSheet(styles.GLOBAL_STYLESHEET)
        self.config = load_config()
        i18n.init_language(self.config.get('language', 'en'))

        self.process_error_detected.connect(self._handle_process_error)
        self.wemod_action_finished.connect(self._on_wemod_inline_finished)

        self._last_proc_signature = None
        self._last_pref_signature = None
        self._proc_initialized = False
        self._pref_initialized = False
        self._last_inspector_key = None
        self._cached_pref_entries = []
        self._known_prefixes_canon = set()

        # Thread queues for built prefix / backups
        self._built_msg_queue = deque()
        self._built_progress_queue = deque()
        self._built_task_done = False
        self._built_task_ok = False
        self._built_poll = QTimer(self)
        self._built_poll.timeout.connect(self._built_poll_tick)
        self._built_poll.setInterval(100)

        self._build_ui()
        self.ensurePolished()
        self.search_bar.setFixedSize(516, 35)
        for button in (self.ce_btn, self.wemod_btn):
            button.setFixedHeight(53)
        self._load_tree()

        # Clear initial focus so search bar doesn't start focused with outline
        self.tree.setFocus()

        # 5-second auto refresh
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh)
        self._auto_refresh_timer.start(5000)

    @property
    def tree(self):
        if hasattr(self, 'view_stack') and self.view_stack.currentIndex() == 1:
            return getattr(self, 'pref_tree', None)
        return getattr(self, 'proc_tree', None)

    def _switch_tab(self, index):
        self.view_stack.setCurrentIndex(index)
        self.tab_proc_btn.setProperty("selected", "true" if index == 0 else "false")
        self.tab_pref_btn.setProperty("selected", "true" if index == 1 else "false")
        self.tab_proc_btn.style().unpolish(self.tab_proc_btn)
        self.tab_proc_btn.style().polish(self.tab_proc_btn)
        self.tab_pref_btn.style().unpolish(self.tab_pref_btn)
        self.tab_pref_btn.style().polish(self.tab_pref_btn)
        if hasattr(self, 'add_prefix_btn'):
            self.add_prefix_btn.setVisible(index == 1)
        self._apply_filters()
        self._on_item_selected()

    def _on_pref_item_double_clicked(self, item, column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        pfx = data.get('wineprefix', '')
        if column == 3 and pfx and not wm.is_wemod_installed(pfx):
            dlg = WeModDialog(pfx, data.get('name', 'Jogo'), self)
            dlg.exec()
            self._load_tree(force=True)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # The mockup is one rounded surface with both headers integrated.
        surface = SurfaceFrame()
        surface.setObjectName("surface")
        surface_layout = QHBoxLayout(surface)
        surface_layout.setContentsMargins(1, 1, 1, 1)
        surface_layout.setSpacing(0)

        left_container = QFrame()
        left_container.setObjectName("tableContainer")
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(18, 0, 18, 16)
        left_layout.setSpacing(0)

        left_header = QFrame()
        left_header.setObjectName("leftHeader")
        left_header.setFixedHeight(62)
        top_bar_layout = QHBoxLayout(left_header)
        top_bar_layout.setContentsMargins(0, 0, 0, 0)
        top_bar_layout.setSpacing(0)

        # Left: Vector Shark Icon + Title
        logo_layout = QHBoxLayout()
        logo_layout.setSpacing(8)
        shark_label = QLabel()
        shark_label.setPixmap(get_shark_icon(30).pixmap(30, 30))
        logo_layout.addWidget(shark_label)

        title_label = QLabel("Action Shark")
        title_label.setStyleSheet("font-size: 23px; font-weight: 500; color: #e5e5e8;")
        logo_layout.addWidget(title_label)
        top_bar_layout.addLayout(logo_layout)

        top_bar_layout.addStretch()

        # Center: Search Bar (Pill)
        search_container = QHBoxLayout()
        search_container.setSpacing(12)

        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("searchBar")
        self.search_bar.setPlaceholderText(t("search_placeholder"))
        self.search_bar.setToolTip(t("tooltip_search_bar"))
        self.search_bar.setFixedWidth(516)
        self.search_bar.setFixedHeight(35)
        self.search_bar.addAction(get_search_icon(16), QLineEdit.ActionPosition.LeadingPosition)
        self.search_bar.setClearButtonEnabled(True)
        self.search_bar.textChanged.connect(self._apply_filters)
        search_container.addWidget(self.search_bar)

        top_bar_layout.addLayout(search_container)

        left_layout.addWidget(left_header)

        # ── Split-View Content ──────────────────────────────────────
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)

        # ── Segmented Navigation (Processos Ativos vs Prefixos Instalados) ──
        tab_container = QFrame()
        tab_container.setObjectName("navTabContainer")
        tab_container.setStyleSheet(
            "QFrame#navTabContainer { background-color: #1a1b24; border: 1px solid #2d2f3d; border-radius: 8px; padding: 2px; }"
        )
        tab_bar_layout = QHBoxLayout(tab_container)
        tab_bar_layout.setContentsMargins(2, 2, 2, 2)
        tab_bar_layout.setSpacing(4)

        self.tab_proc_btn = QPushButton(t("nav_active_processes", count=0))
        self.tab_proc_btn.setObjectName("navTabBtn")
        self.tab_proc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tab_proc_btn.setToolTip(t("tooltip_tab_proc"))
        self.tab_proc_btn.setProperty("selected", "true")
        self.tab_proc_btn.clicked.connect(lambda: self._switch_tab(0))

        self.tab_pref_btn = QPushButton(t("nav_installed_prefixes", count=0))
        self.tab_pref_btn.setObjectName("navTabBtn")
        self.tab_pref_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tab_pref_btn.setToolTip(t("tooltip_tab_pref"))
        self.tab_pref_btn.setProperty("selected", "false")
        self.tab_pref_btn.clicked.connect(lambda: self._switch_tab(1))

        tab_bar_layout.addWidget(self.tab_proc_btn)
        tab_bar_layout.addWidget(self.tab_pref_btn)

        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(0, 0, 0, 8)
        nav_row.setSpacing(8)
        nav_row.addWidget(tab_container)
        nav_row.addStretch()

        self.add_prefix_btn = QPushButton(t("btn_add_prefix_toolbar"))
        self.add_prefix_btn.setObjectName("toolbarBtn")
        self.add_prefix_btn.setFixedHeight(30)
        self.add_prefix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_prefix_btn.setToolTip(t("tooltip_add_prefix"))
        self.add_prefix_btn.clicked.connect(self._add_custom_prefix)
        self.add_prefix_btn.setVisible(False)
        nav_row.addWidget(self.add_prefix_btn)

        self.refresh_btn = QPushButton()
        self.refresh_btn.setObjectName("toolbarBtn")
        self.refresh_btn.setIcon(get_refresh_icon(15))
        self.refresh_btn.setFixedSize(30, 30)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setToolTip(t("tooltip_refresh"))
        self.refresh_btn.clicked.connect(self._refresh)
        nav_row.addWidget(self.refresh_btn)

        left_layout.addLayout(nav_row)

        # ── Stacked View ─────────────────────────────────────────────
        self.view_stack = QStackedWidget()

        # Page 0: Processos Ativos
        proc_page = QWidget()
        proc_layout = QVBoxLayout(proc_page)
        proc_layout.setContentsMargins(0, 0, 0, 0)
        proc_layout.setSpacing(0)

        self.proc_tree = QTreeWidget()
        self.proc_tree.setHeaderLabels([t('col_pid'), t('col_game_exe'), t('col_env_runner'), t('col_status')])
        self.proc_tree.setRootIsDecorated(False)
        self.proc_tree.setAlternatingRowColors(False)
        self.proc_tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.proc_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.proc_tree.customContextMenuRequested.connect(self._tree_context_menu)
        self.proc_tree.itemSelectionChanged.connect(self._on_item_selected)

        self.proc_status_delegate = StatusBadgeDelegate(self.proc_tree)
        self.proc_tree.setItemDelegate(self.proc_status_delegate)

        ph = self.proc_tree.header()
        ph.setFixedHeight(35)
        ph.setStretchLastSection(False)
        ph.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        ph.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ph.setMinimumSectionSize(60)
        ph.setSectionsMovable(False)
        self.proc_tree.setHorizontalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.proc_tree.setColumnWidth(0, 75)
        self.proc_tree.setColumnWidth(2, 220)
        self.proc_tree.setColumnWidth(3, 110)

        proc_layout.addWidget(self.proc_tree)

        self.proc_empty_frame = QFrame()
        self.proc_empty_frame.setStyleSheet("background: #141418; border-radius: 8px; border: 1px solid rgba(255,255,255,0.04);")
        empty_layout = QVBoxLayout(self.proc_empty_frame)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(6)
        empty_layout.addStretch()
        self.proc_empty_title = QLabel(t("empty_proc_title"))
        self.proc_empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.proc_empty_title.setStyleSheet("font-size: 15px; font-weight: 500; color: #d4d4d8; background: transparent; border: none;")
        empty_layout.addWidget(self.proc_empty_title)
        self.proc_empty_sub = QLabel(t("empty_proc_subtitle"))
        self.proc_empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.proc_empty_sub.setWordWrap(True)
        self.proc_empty_sub.setStyleSheet("font-size: 12px; color: #8e90a0; background: transparent; border: none;")
        empty_layout.addWidget(self.proc_empty_sub)
        empty_layout.addStretch()
        self.proc_empty_frame.setVisible(False)
        proc_layout.addWidget(self.proc_empty_frame, stretch=1)

        self.view_stack.addWidget(proc_page)

        # Page 1: Prefixos Instalados
        pref_page = QWidget()
        pref_layout = QVBoxLayout(pref_page)
        pref_layout.setContentsMargins(0, 0, 0, 0)
        pref_layout.setSpacing(8)

        # Filter Chips Bar (Launcher sub-filters)
        self.chip_bar = FilterChipBar()
        self.chip_bar.filter_changed.connect(lambda code: self._apply_filters())
        pref_layout.addWidget(self.chip_bar)

        self.pref_tree = QTreeWidget()
        self.pref_tree.setHeaderLabels([t('col_game_prefix'), t('col_source'), t('col_arch'), t('col_wemod')])
        self.pref_tree.setRootIsDecorated(False)
        self.pref_tree.setAlternatingRowColors(False)
        self.pref_tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.pref_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pref_tree.customContextMenuRequested.connect(self._tree_context_menu)
        self.pref_tree.itemSelectionChanged.connect(self._on_item_selected)
        self.pref_tree.itemDoubleClicked.connect(self._on_pref_item_double_clicked)

        self.pref_status_delegate = StatusBadgeDelegate(self.pref_tree)
        self.pref_tree.setItemDelegate(self.pref_status_delegate)

        pfh = self.pref_tree.header()
        pfh.setFixedHeight(35)
        pfh.setStretchLastSection(False)
        pfh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        pfh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        pfh.setMinimumSectionSize(60)
        pfh.setSectionsMovable(False)
        self.pref_tree.setHorizontalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.pref_tree.setColumnWidth(1, 140)
        self.pref_tree.setColumnWidth(2, 110)
        self.pref_tree.setColumnWidth(3, 140)

        pref_layout.addWidget(self.pref_tree)
        self.view_stack.addWidget(pref_page)

        left_layout.addWidget(self.view_stack)
        self.splitter.addWidget(left_container)

        # ── Right Column: Inspector + integrated window controls ─────
        inspector_panel = QFrame()
        inspector_panel.setObjectName("inspectorPanel")
        inspector_layout = QVBoxLayout(inspector_panel)
        inspector_layout.setContentsMargins(20, 0, 20, 16)
        inspector_layout.setSpacing(0)

        # The window chrome lives inside the right header in the mockup.
        insp_top = QHBoxLayout()
        insp_top.setContentsMargins(0, 0, 0, 0)
        insp_top.setSpacing(8)
        insp_top_widget = QWidget()
        insp_top_widget.setFixedHeight(62)
        insp_top_widget.setLayout(insp_top)

        insp_top.addStretch()

        self.insp_gear = QPushButton()
        self.insp_gear.setIcon(get_gear_icon(14))
        self.insp_gear.setToolTip(t('tooltip_settings'))
        self.insp_gear.setObjectName("windowIconBtn")
        self.insp_gear.setFixedSize(28, 32)
        self.insp_gear.clicked.connect(self._open_settings)
        insp_top.addWidget(self.insp_gear)

        self.minimize_btn = QPushButton()
        self.minimize_btn.setIcon(get_minimize_icon(16))
        self.minimize_btn.setToolTip(t('tooltip_minimize'))
        self.minimize_btn.setObjectName("windowIconBtn")
        self.minimize_btn.setFixedSize(28, 32)
        self.minimize_btn.clicked.connect(self.showMinimized)
        insp_top.addWidget(self.minimize_btn)

        self.maximize_btn = QPushButton()
        self.maximize_btn.setIcon(get_maximize_icon(16))
        self.maximize_btn.setToolTip(t('tooltip_maximize'))
        self.maximize_btn.setObjectName("windowIconBtn")
        self.maximize_btn.setFixedSize(28, 32)
        self.maximize_btn.clicked.connect(self._toggle_maximized)
        insp_top.addWidget(self.maximize_btn)

        self.close_btn = QPushButton()
        self.close_btn.setIcon(get_close_icon(16))
        self.close_btn.setToolTip(t('tooltip_close'))
        self.close_btn.setObjectName("windowIconBtn")
        self.close_btn.setFixedSize(28, 32)
        self.close_btn.clicked.connect(self.close)
        insp_top.addWidget(self.close_btn)
        inspector_layout.addWidget(insp_top_widget)

        # Game Banner Widget
        self.banner_widget = GameBannerWidget()
        inspector_layout.addWidget(self.banner_widget)
        inspector_layout.addSpacing(10)

        # WINEPREFIX Quick Info & Actions in Inspector
        pfx_info_frame = QFrame()
        pfx_info_frame.setObjectName("pfxInfoFrame")
        pfx_info_frame.setStyleSheet(
            "QFrame#pfxInfoFrame { background-color: #202128; border: 1px solid #2d2e3b; border-radius: 8px; }"
        )
        pfx_layout = QVBoxLayout(pfx_info_frame)
        pfx_layout.setContentsMargins(10, 8, 10, 8)
        pfx_layout.setSpacing(6)

        pfx_header_row = QHBoxLayout()
        pfx_title_lbl = QLabel("WINEPREFIX")
        pfx_title_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #9ca3af; text-transform: uppercase; background: transparent; border: none;")
        pfx_header_row.addWidget(pfx_title_lbl)
        pfx_header_row.addStretch()

        self.copy_pfx_btn = QPushButton(t("btn_copy"))
        self.copy_pfx_btn.setFixedHeight(22)
        self.copy_pfx_btn.setStyleSheet("font-size: 11px; padding: 2px 8px; background: #272834; border: 1px solid #3f4258; border-radius: 4px; color: #d1d5db;")
        self.copy_pfx_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_pfx_btn.setToolTip(t("tooltip_copy_pfx"))
        self.copy_pfx_btn.clicked.connect(self._copy_prefix_path)
        pfx_header_row.addWidget(self.copy_pfx_btn)

        self.open_pfx_quick_btn = QPushButton(t("btn_open_folder"))
        self.open_pfx_quick_btn.setFixedHeight(22)
        self.open_pfx_quick_btn.setStyleSheet("font-size: 11px; padding: 2px 8px; background: transparent; border: 1px solid #3f4258; border-radius: 4px; color: #818cf8;")
        self.open_pfx_quick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_pfx_quick_btn.setToolTip(t("tooltip_open_pfx"))
        self.open_pfx_quick_btn.clicked.connect(self._open_prefix_folder)
        pfx_header_row.addWidget(self.open_pfx_quick_btn)
        pfx_layout.addLayout(pfx_header_row)

        self.pfx_path_label = QLabel(t("pfx_none_selected"))
        self.pfx_path_label.setStyleSheet("font-size: 11px; font-family: monospace; color: #d4d4d8; background: transparent; border: none;")
        self.pfx_path_label.setWordWrap(True)
        pfx_layout.addWidget(self.pfx_path_label)

        self.add_to_lib_btn = QPushButton(t("btn_add_to_list"))
        self.add_to_lib_btn.setFixedHeight(26)
        self.add_to_lib_btn.setStyleSheet("font-size: 11px; font-weight: 600; background: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.35); border-radius: 6px; color: #a5b4fc;")
        self.add_to_lib_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_to_lib_btn.setToolTip(t("tooltip_add_to_list"))
        self.add_to_lib_btn.clicked.connect(self._save_selected_to_custom_prefixes)
        self.add_to_lib_btn.setVisible(False)
        pfx_layout.addWidget(self.add_to_lib_btn)

        inspector_layout.addWidget(pfx_info_frame)
        inspector_layout.addSpacing(10)

        # Wine Version Section
        self.wine_lbl = QLabel(t("label_wine_version"))
        self.wine_lbl.setStyleSheet("font-size: 15px; font-weight: 400; color: #dddddf;")
        self.wine_lbl.setFixedHeight(24)
        self.wine_lbl.setToolTip(t("tooltip_wine_version"))
        inspector_layout.addWidget(self.wine_lbl)
        inspector_layout.addSpacing(6)

        self.wine_version_frame = QFrame()
        self.wine_version_frame.setObjectName("wineVersionFrame")
        self.wine_version_frame.setFixedHeight(35)
        self.wine_version_frame.setStyleSheet(
            "QFrame#wineVersionFrame { background-color: #202127; border: 1px solid #3a3b46; border-radius: 8px; }"
        )
        wv_layout = QHBoxLayout(self.wine_version_frame)
        wv_layout.setContentsMargins(11, 0, 11, 0)
        wv_layout.setSpacing(6)

        self.wine_version_label = QLabel(t("wv_none_selected"))
        self.wine_version_label.setStyleSheet("font-size: 14px; font-weight: 400; color: #71717a; background: transparent; border: none;")
        self.wine_version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        wv_layout.addWidget(self.wine_version_label)
        wv_layout.addStretch()

        inspector_layout.addWidget(self.wine_version_frame)
        inspector_layout.addSpacing(8)

        # Trainer Path Section
        trainer_field = QFrame()
        trainer_field.setObjectName('trainerField')
        trainer_field.setFixedHeight(49)
        tr_row = QHBoxLayout(trainer_field)
        tr_row.setContentsMargins(4, 5, 6, 5)
        tr_row.setSpacing(4)
        self.trainer_exe_input = QLineEdit()
        self.trainer_exe_input.setObjectName('trainerInput')
        self.trainer_exe_input.setPlaceholderText(t("placeholder_trainer_path"))
        self.trainer_exe_input.setToolTip(t("tooltip_trainer_input"))
        tr_row.addWidget(self.trainer_exe_input)

        self.browse_btn = RoundedButton(t("btn_browse"))
        self.browse_btn.setObjectName("browseBtn")
        self.browse_btn.setFixedSize(81, 37)
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.setToolTip(t("tooltip_browse_trainer"))
        self.browse_btn.clicked.connect(self._browse_trainer_exe)
        tr_row.addWidget(self.browse_btn)
        inspector_layout.addWidget(trainer_field)
        inspector_layout.addSpacing(15)

        # Primary Action: Launch Trainer Button (Always vibrant blue, clickable)
        self.launch_btn = RoundedButton(t("btn_launch_trainer"))
        self.launch_btn.setObjectName("launchTrainerBtn")
        self.launch_btn.setFixedHeight(40)
        self.launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.launch_btn.setToolTip(t("tooltip_launch_trainer"))
        self.launch_btn.clicked.connect(self._launch_trainer)
        inspector_layout.addWidget(self.launch_btn)

        inspector_layout.addSpacing(14)
        divider = QFrame()
        divider.setObjectName('divider')
        divider.setFixedHeight(1)
        inspector_layout.addWidget(divider)
        inspector_layout.addSpacing(13)

        # Quick Actions Header
        self.qa_lbl = QLabel(t("label_quick_actions"))
        self.qa_lbl.setStyleSheet("font-size: 15px; font-weight: 400; color: #eeeeef;")
        self.qa_lbl.setFixedHeight(24)
        inspector_layout.addWidget(self.qa_lbl)
        inspector_layout.addSpacing(14)

        # Quick Actions (Centralized contextual actions for selected prefix/process)
        qa_grid = QGridLayout()
        qa_grid.setSpacing(12)
        qa_grid.setColumnStretch(0, 1)
        qa_grid.setColumnStretch(1, 1)

        self.ce_btn = RoundedButton(t("btn_cheat_engine"))
        self.ce_btn.setIcon(get_cheatengine_icon(18))
        self.ce_btn.setObjectName("quickActionBtn")
        self.ce_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ce_btn.setToolTip(t("tooltip_cheat_engine"))
        self.ce_btn.clicked.connect(self._run_ce_inspector)
        qa_grid.addWidget(self.ce_btn, 0, 0)

        self.wemod_btn = RoundedButton(t("btn_wemod_manager"))
        self.wemod_btn.setIcon(get_wemod_icon(16))
        self.wemod_btn.setObjectName("quickActionBtn")
        self.wemod_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wemod_btn.setToolTip(t("tooltip_wemod_manager"))
        self.wemod_btn.clicked.connect(self._open_wemod_modal)
        qa_grid.addWidget(self.wemod_btn, 0, 1)

        for button in (self.ce_btn, self.wemod_btn):
            button.setFixedHeight(53)

        inspector_layout.addLayout(qa_grid)
        inspector_layout.addStretch()

        # Toast / Status output
        self.status_toast = QLabel("")
        self.status_toast.setStyleSheet("color: #34d399; font-size: 11px; font-weight: 500;")
        self.status_toast.setWordWrap(True)
        inspector_layout.addWidget(self.status_toast)

        self.splitter.addWidget(inspector_panel)
        self.splitter.setStretchFactor(0, 7)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([884, 386])

        surface_layout.addWidget(self.splitter)
        main_layout.addWidget(surface)

        self.log = QTextEdit()
        self.log.setVisible(False)

    def _toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Dragging the integrated header moves the frameless window.
            pos = event.position().toPoint()
            edges = Qt.Edge(0)
            if pos.x() < 6:
                edges |= Qt.Edge.LeftEdge
            elif pos.x() >= self.width() - 6:
                edges |= Qt.Edge.RightEdge
            if pos.y() < 6:
                edges |= Qt.Edge.TopEdge
            elif pos.y() >= self.height() - 6:
                edges |= Qt.Edge.BottomEdge
            if edges and not self.isMaximized() and self.windowHandle():
                if self.windowHandle().startSystemResize(edges):
                    return
            if pos.y() < 62:
                if self.windowHandle() and self.windowHandle().startSystemMove():
                    return
                self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.position().y() < 62:
            self._toggle_maximized()

    def retranslate_ui(self):
        self.setWindowTitle(t('app_title'))
        if hasattr(self, 'search_bar'):
            self.search_bar.setPlaceholderText(t('search_placeholder'))
            self.search_bar.setToolTip(t('tooltip_search_bar'))
        if hasattr(self, 'tab_proc_btn'):
            self.tab_proc_btn.setToolTip(t('tooltip_tab_proc'))
        if hasattr(self, 'tab_pref_btn'):
            self.tab_pref_btn.setToolTip(t('tooltip_tab_pref'))
        if hasattr(self, 'proc_empty_title'):
            self.proc_empty_title.setText(t('empty_proc_title'))
        if hasattr(self, 'proc_empty_sub'):
            self.proc_empty_sub.setText(t('empty_proc_subtitle'))
        if hasattr(self, 'proc_tree'):
            self.proc_tree.setHeaderLabels([t('col_pid'), t('col_game_exe'), t('col_env_runner'), t('col_status')])
        if hasattr(self, 'pref_tree'):
            self.pref_tree.setHeaderLabels([t('col_game_prefix'), t('col_source'), t('col_arch'), t('col_wemod')])
        if hasattr(self, 'chip_bar'):
            self.chip_bar.retranslate()
        if hasattr(self, 'add_prefix_btn'):
            self.add_prefix_btn.setText(t('btn_add_prefix_toolbar'))
            self.add_prefix_btn.setToolTip(t('tooltip_add_prefix'))
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setToolTip(t('tooltip_refresh'))
        if hasattr(self, 'insp_gear'):
            self.insp_gear.setToolTip(t('tooltip_settings'))
        if hasattr(self, 'minimize_btn'):
            self.minimize_btn.setToolTip(t('tooltip_minimize'))
        if hasattr(self, 'maximize_btn'):
            self.maximize_btn.setToolTip(t('tooltip_maximize'))
        if hasattr(self, 'close_btn'):
            self.close_btn.setToolTip(t('tooltip_close'))
        if hasattr(self, 'wine_lbl'):
            self.wine_lbl.setText(t('label_wine_version'))
            self.wine_lbl.setToolTip(t('tooltip_wine_version'))
        if hasattr(self, 'trainer_exe_input'):
            self.trainer_exe_input.setPlaceholderText(t('placeholder_trainer_path'))
            self.trainer_exe_input.setToolTip(t('tooltip_trainer_input'))
        if hasattr(self, 'browse_btn'):
            self.browse_btn.setText(t('btn_browse'))
            self.browse_btn.setToolTip(t('tooltip_browse_trainer'))
        if hasattr(self, 'launch_btn'):
            self.launch_btn.setText(t('btn_launch_trainer'))
            self.launch_btn.setToolTip(t('tooltip_launch_trainer'))
        if hasattr(self, 'qa_lbl'):
            self.qa_lbl.setText(t('label_quick_actions'))
        if hasattr(self, 'ce_btn'):
            self.ce_btn.setText(t('btn_cheat_engine'))
            self.ce_btn.setToolTip(t('tooltip_cheat_engine'))
        if hasattr(self, 'wemod_btn'):
            self.wemod_btn.setText(t('btn_wemod_manager'))
            self.wemod_btn.setToolTip(t('tooltip_wemod_manager'))
        if hasattr(self, 'copy_pfx_btn'):
            self.copy_pfx_btn.setText(t('btn_copy'))
            self.copy_pfx_btn.setToolTip(t('tooltip_copy_pfx'))
        if hasattr(self, 'open_pfx_quick_btn'):
            self.open_pfx_quick_btn.setText(t('btn_open_folder'))
            self.open_pfx_quick_btn.setToolTip(t('tooltip_open_pfx'))
        if hasattr(self, 'add_to_lib_btn'):
            self.add_to_lib_btn.setText(t('btn_add_to_list'))
            self.add_to_lib_btn.setToolTip(t('tooltip_add_to_list'))
        self._on_item_selected()
        self._load_tree(force=True)

    def _create_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(styles.MENU_STYLESHEET)
        return menu

    # ── Toast status ─────────────────────────────────────────────────

    def _show_toast(self, msg: str, is_error: bool = False):
        color = "#f87171" if is_error else "#34d399"
        self.status_toast.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 500;")
        self.status_toast.setText(msg)
        self._log(msg)
        QTimer.singleShot(5000, lambda: self.status_toast.setText("") if self.status_toast.text() == msg else None)

    # ── Data Loading & Table Population ──────────────────────────────

    def _refresh(self):
        self._show_toast(t("toast_updating"))
        self._load_tree(force=True, refresh_prefixes=True)
        self._show_toast(t("toast_list_updated"))

    def _auto_refresh(self):
        # Poll running processes & live WeMod states without blocking the UI
        # thread on protontricks/launcher DB scans every 5 seconds.
        self._load_tree(force=False, refresh_prefixes=False)

    def _build_wemod_cell_widget(self, pfx: str, game_name: str, wemod_status: str) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(0)

        is_running = (wemod_status == 'Rodando')
        btn = QPushButton(t("wemod_btn_stop_inline") if is_running else t("wemod_btn_start_inline"))
        btn.setObjectName("wemodInlineStopBtn" if is_running else "wemodInlineStartBtn")
        btn.setFixedHeight(28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(t("tooltip_wemod_inline_stop") if is_running else t("tooltip_wemod_inline_start"))
        action = 'stop' if is_running else 'start'
        btn.clicked.connect(lambda checked=False, p=pfx, n=game_name, a=action, b=btn: self._toggle_wemod_inline(p, n, a, b))
        layout.addWidget(btn)
        return holder

    def _toggle_wemod_inline(self, pfx: str, game_name: str, action: str, btn: QPushButton):
        if not pfx or not os.path.isdir(pfx):
            self._show_toast(t("toast_pfx_invalid"), is_error=True)
            return
        btn.setEnabled(False)
        btn.setText(t("wemod_inline_stopping") if action == 'stop' else t("wemod_inline_starting"))

        def task():
            try:
                if action == 'stop':
                    wm.stop_wemod(pfx)
                    self.wemod_action_finished.emit(pfx, True, t("toast_wemod_stopped", name=game_name))
                else:
                    pid = wm.launch_wemod(pfx, game_name=game_name)
                    if pid:
                        self.wemod_action_finished.emit(pfx, True, t("toast_wemod_started", name=game_name))
                    else:
                        self.wemod_action_finished.emit(pfx, False, t("wemod_log_not_started"))
            except Exception as exc:
                key = "toast_wemod_stop_failed" if action == 'stop' else "toast_wemod_start_failed"
                self.wemod_action_finished.emit(pfx, False, t(key, error=exc))

        threading.Thread(target=task, daemon=True).start()

    def _on_wemod_inline_finished(self, pfx: str, ok: bool, msg: str):
        self._show_toast(msg, is_error=not ok)
        self._load_tree(force=True)

    def _load_tree(self, force: bool = False, refresh_prefixes: bool = True):
        # Snapshot selection per tree independently so active process selection never jumps.
        proc_sel_items = self.proc_tree.selectedItems()
        prev_proc_data = proc_sel_items[0].data(0, Qt.ItemDataRole.UserRole) if proc_sel_items else None
        prev_proc_pid = str(prev_proc_data.get('pid', '')) if prev_proc_data else None
        prev_proc_pfx = _canonical_prefix_path(prev_proc_data.get('wineprefix', '')) if prev_proc_data else ''
        prev_proc_name = prev_proc_data.get('name', '') if prev_proc_data else ''

        pref_sel_items = self.pref_tree.selectedItems()
        prev_pref_data = pref_sel_items[0].data(0, Qt.ItemDataRole.UserRole) if pref_sel_items else None
        prev_pref_source = prev_pref_data.get('source', '') if prev_pref_data else ''
        prev_pref_pfx = _canonical_prefix_path(prev_pref_data.get('wineprefix', '')) if prev_pref_data else ''

        # ── 1. Populate Active Processes ─────────────────────────────
        running_entries = get_running_wine_entries()
        proc_sig = tuple(
            (
                str(p.get('pid', '')),
                p.get('name', ''),
                p.get('comm', ''),
                bool(p.get('is_proton')),
                _canonical_prefix_path(p.get('wineprefix', '')),
                p.get('wine_bin') or '',
            )
            for p in running_entries
        )

        if force or not self._proc_initialized or proc_sig != self._last_proc_signature:
            proc_vscroll = self.proc_tree.verticalScrollBar().value()
            with QSignalBlocker(self.proc_tree):
                self.proc_tree.clear()
                proc_first_item = None
                pid_matched_item = None
                pfx_name_matched_item = None
                pfx_matched_item = None

                for p in running_entries:
                    pid = str(p.get('pid', ''))
                    name = p.get('name', '')
                    comm = p.get('comm', '')
                    display_name = f"{name} ({comm})" if comm and comm != name else name
                    runner = "Proton" if p.get('is_proton') else "Wine"
                    status = t("status_running")
                    pfx = p.get('wineprefix', '')
                    canon_pfx = _canonical_prefix_path(pfx)

                    item = QTreeWidgetItem([pid, display_name, runner, status])
                    item.setData(0, Qt.ItemDataRole.UserRole, p)
                    self.proc_tree.addTopLevelItem(item)

                    if not proc_first_item and pfx:
                        proc_first_item = item
                    if prev_proc_pid and pid == prev_proc_pid:
                        pid_matched_item = item
                    elif prev_proc_pfx and canon_pfx == prev_proc_pfx:
                        if prev_proc_name and name == prev_proc_name and not pfx_name_matched_item:
                            pfx_name_matched_item = item
                        elif not pfx_matched_item:
                            pfx_matched_item = item

                target_proc = (
                    pid_matched_item
                    or pfx_name_matched_item
                    or pfx_matched_item
                    or (proc_first_item if (not self._proc_initialized or prev_proc_pid is not None) else None)
                )
                if target_proc:
                    self.proc_tree.setCurrentItem(target_proc)
                self.proc_tree.verticalScrollBar().setValue(proc_vscroll)

            self._last_proc_signature = proc_sig
            self._proc_initialized = True

        self.tab_proc_btn.setText(t("nav_active_processes", count=len(running_entries)))

        # ── 2. Populate Installed Prefixes (Steam, Launchers, Custom) ──
        if refresh_prefixes or not self._pref_initialized:
            pref_entries = []
            seen_pfx = set()
            hidden = set(load_config().get('hidden_prefixes', []))
            hidden_canon = {_canonical_prefix_path(h) for h in hidden if h}

            def _add_pref(entry):
                pfx = entry.get('wineprefix', '')
                canon = _canonical_prefix_path(pfx)
                key = canon if canon else f"{entry.get('source','')}:{entry.get('name','')}"
                if key not in seen_pfx:
                    seen_pfx.add(key)
                    if entry.get('source') not in ('Não-Steam', 'Non-Steam') and (pfx in hidden or canon in hidden_canon):
                        return
                    pref_entries.append(entry)

            for g in get_steam_games():
                _add_pref(g)

            for l in get_launcher_prefixes():
                _add_pref(l)

            for c in get_custom_prefixes():
                pfx = c.get('wineprefix', '')
                if pfx:
                    _add_pref({
                        'name': c.get('name', pfx),
                        'appid': None,
                        'wineprefix': pfx,
                        'source': c.get('source', 'Custom'),
                        'exe': '',
                        'is_proton': False,
                    })
            self._cached_pref_entries = pref_entries
            self._known_prefixes_canon = {
                _canonical_prefix_path(e.get('wineprefix', ''))
                for e in pref_entries if e.get('wineprefix')
            }
        else:
            pref_entries = self._cached_pref_entries

        running_wemod = wm.get_running_wemod_prefixes()
        pref_rows = []
        for e in pref_entries:
            pfx = e.get('wineprefix', '')
            if not pfx or not wm.is_wemod_installed(pfx):
                wemod_status = 'Nao instalado'
            else:
                norm_p = pfx.rstrip('/')
                canon_p = _canonical_prefix_path(pfx)
                wemod_status = 'Rodando' if (norm_p in running_wemod or canon_p in running_wemod) else 'Instalado'
            pref_rows.append((e, wemod_status))

        pref_sig = tuple(
            (
                e.get('name', ''),
                e.get('source', ''),
                _canonical_prefix_path(e.get('wineprefix', '')),
                ws,
            )
            for e, ws in pref_rows
        )

        if force or not self._pref_initialized or pref_sig != self._last_pref_signature:
            pref_vscroll = self.pref_tree.verticalScrollBar().value()
            with QSignalBlocker(self.pref_tree):
                self.pref_tree.clear()
                pref_first_item = None
                pref_exact_match = None
                pref_pfx_match = None

                for e, wemod_status in pref_rows:
                    pfx = e.get('wineprefix', '')
                    canon_pfx = _canonical_prefix_path(pfx)
                    name = e.get('name', '')
                    source = e.get('source', '')
                    arch = "win64"

                    display_source = source
                    if source in ('Personalizado', 'Custom'):
                        display_source = t('source_custom')
                    elif source in ('Não-Steam', 'Non-Steam'):
                        display_source = t('source_non_steam')
                    elif source == 'Default Wine':
                        display_source = t('source_default_wine')

                    wemod_label = t("status_not_installed") if wemod_status == 'Nao instalado' else ""
                    item = QTreeWidgetItem([name, display_source, arch, wemod_label])
                    item.setData(0, Qt.ItemDataRole.UserRole, e)
                    self.pref_tree.addTopLevelItem(item)

                    if wemod_status in ('Instalado', 'Rodando') and pfx:
                        self.pref_tree.setItemWidget(
                            item, 3, self._build_wemod_cell_widget(pfx, name, wemod_status)
                        )
                    else:
                        item.setToolTip(3, t("tooltip_wemod_not_installed"))

                    if not pref_first_item and pfx:
                        pref_first_item = item
                    if prev_pref_pfx and canon_pfx == prev_pref_pfx:
                        if source == prev_pref_source:
                            pref_exact_match = item
                        elif not pref_pfx_match:
                            pref_pfx_match = item

                target_pref = (
                    pref_exact_match
                    or pref_pfx_match
                    or (pref_first_item if not self._pref_initialized else None)
                )
                if target_pref:
                    self.pref_tree.setCurrentItem(target_pref)
                self.pref_tree.verticalScrollBar().setValue(pref_vscroll)

            self._last_pref_signature = pref_sig
            self._pref_initialized = True

        self.tab_pref_btn.setText(t("nav_installed_prefixes", count=self.pref_tree.topLevelItemCount()))

        self._apply_filters()

        curr_data = self._selected_data()
        curr_key = (
            str(curr_data.get('pid', '')) if curr_data else None,
            _canonical_prefix_path(curr_data.get('wineprefix', '')) if curr_data else '',
            curr_data.get('wine_bin') if curr_data else None,
            self.view_stack.currentIndex(),
        )
        if force or curr_key != self._last_inspector_key:
            self._on_item_selected()

    # ── Filtering ────────────────────────────────────────────────────

    def _apply_filters(self):
        search_query = self.search_bar.text().strip().lower()
        active_chip = self.chip_bar.get_active_filter()

        # Filters for Active Processes Tree
        visible_procs = 0
        for i in range(self.proc_tree.topLevelItemCount()):
            item = self.proc_tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            pid = str(data.get('pid') or '')
            name = (data.get('name') or '').lower()
            exe = (data.get('exe') or '').lower()
            pfx = (data.get('wineprefix') or '').lower()

            match = True
            if search_query:
                match = (search_query in pid or search_query in name or search_query in exe or search_query in pfx)
            item.setHidden(not match)
            if match:
                visible_procs += 1

        if hasattr(self, 'proc_empty_frame'):
            has_visible = (visible_procs > 0)
            self.proc_tree.setVisible(has_visible)
            self.proc_empty_frame.setVisible(not has_visible)

        # Filters for Installed Prefixes Tree
        for i in range(self.pref_tree.topLevelItemCount()):
            item = self.pref_tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            name = (data.get('name') or '').lower()
            source = (data.get('source') or '').lower()
            appid = str(data.get('appid') or '')
            pfx = (data.get('wineprefix') or '').lower()

            chip_match = True
            if active_chip == 'STEAM':
                chip_match = (source == 'steam')
            elif active_chip == 'HYDRA':
                chip_match = ('hydra' in source)
            elif active_chip == 'HEROIC':
                chip_match = ('heroic' in source)
            elif active_chip == 'LUTRIS':
                chip_match = ('lutris' in source)
            elif active_chip == 'BOTTLES':
                chip_match = ('bottles' in source)
            elif active_chip == 'NON_STEAM':
                chip_match = (source in ('non-steam', 'não-steam'))
            elif active_chip == 'DEFAULT_WINE':
                chip_match = (source == 'default wine')
            elif active_chip == 'CUSTOM':
                chip_match = (source in ('custom', 'personalizado'))

            search_match = True
            if search_query:
                search_match = (
                    search_query in name or
                    search_query in source or
                    search_query in appid or
                    search_query in pfx
                )

            item.setHidden(not (chip_match and search_match))

    # ── Selection & Inspector Sync ───────────────────────────────────

    def _selected_data(self):
        curr_tree = self.proc_tree if (hasattr(self, 'view_stack') and self.view_stack.currentIndex() == 0) else getattr(self, 'pref_tree', None)
        if not curr_tree:
            return None
        sel = curr_tree.selectedItems()
        return sel[0].data(0, Qt.ItemDataRole.UserRole) if sel else None

    def _on_item_selected(self):
        data = self._selected_data()
        self._last_inspector_key = (
            str(data.get('pid', '')) if data else None,
            _canonical_prefix_path(data.get('wineprefix', '')) if data else '',
            data.get('wine_bin') if data else None,
            self.view_stack.currentIndex() if hasattr(self, 'view_stack') else 0,
        )
        if not data:
            self.banner_widget.set_game(t("banner_select_game"), "", "")
            self._current_wine_bin = None
            if hasattr(self, 'wine_version_label'):
                self.wine_version_label.setText(t("wv_none_selected"))
                self.wine_version_label.setStyleSheet("font-size: 14px; font-weight: 400; color: #71717a; background: transparent; border: none;")
            if hasattr(self, 'wine_version_frame'):
                self.wine_version_frame.setToolTip("")
            if hasattr(self, 'pfx_path_label'):
                self.pfx_path_label.setText(t("pfx_none_selected"))
            if hasattr(self, 'add_to_lib_btn'):
                self.add_to_lib_btn.setVisible(False)
            return

        name = data.get('name', 'Unknown')
        source = data.get('source', '')
        appid = data.get('appid', '')
        pfx = data.get('wineprefix', '')
        canon_pfx = _canonical_prefix_path(pfx)
        banner_source = source
        if data.get('pid') and (not source or source.startswith('PID ')):
            banner_source = "Proton" if data.get('is_proton') else "Wine"

        self.banner_widget.set_game(name, banner_source, appid, pid=data.get('pid'))

        if hasattr(self, 'pfx_path_label'):
            self.pfx_path_label.setText(pfx if pfx else t("pfx_none_associated"))

        if hasattr(self, 'add_to_lib_btn'):
            is_proc = bool(data.get('pid'))
            if is_proc and canon_pfx:
                cfg = load_config()
                saved_pfxs = {_canonical_prefix_path(c.get('wineprefix', '')) for c in cfg.get('custom_prefixes', [])}
                can_save = (canon_pfx not in saved_pfxs) and (canon_pfx not in self._known_prefixes_canon)
            else:
                can_save = False
            self.add_to_lib_btn.setVisible(bool(can_save))

        live_bin = (data.get('wine_bin') or '').strip() if isinstance(data.get('wine_bin'), str) else data.get('wine_bin')
        pid = data.get('pid')
        wine_bin = None
        is_live = False

        if live_bin and os.path.isfile(live_bin):
            wine_bin = os.path.realpath(live_bin)
            is_live = True
        elif pid:
            found = _find_wine_bin_for_pid(pid)
            if found and os.path.isfile(found):
                wine_bin = os.path.realpath(found)
                is_live = True

        if not wine_bin and pfx:
            found = find_wine_binary(pfx)
            if found and os.path.isfile(found):
                wine_bin = os.path.realpath(found)

        self._current_wine_bin = wine_bin

        if hasattr(self, 'wine_version_label'):
            if wine_bin:
                label = get_wine_runner_label(wine_bin, pfx)
                display_text = f"{label} {t('wv_running_suffix')}" if is_live else label
                self.wine_version_label.setText(display_text)
                self.wine_version_label.setStyleSheet("font-size: 14px; font-weight: 400; color: #eeeeef; background: transparent; border: none;")
                if hasattr(self, 'wine_version_frame'):
                    self.wine_version_frame.setToolTip(t("wv_binary_tooltip", bin=wine_bin))
            else:
                self.wine_version_label.setText(t("wv_not_detected"))
                self.wine_version_label.setStyleSheet("font-size: 14px; font-weight: 400; color: #71717a; background: transparent; border: none;")
                if hasattr(self, 'wine_version_frame'):
                    self.wine_version_frame.setToolTip("")

    # ── Actions ──────────────────────────────────────────────────────

    def _browse_trainer_exe(self):
        start_dir = self.config.get('trainers_folder', '') or os.path.expanduser('~')
        path, _ = QFileDialog.getOpenFileName(
            self, t('dialog_select_trainer_exe'),
            start_dir,
            t('dialog_filter_exe'),
        )
        if path:
            self.trainer_exe_input.setText(path)

    def _launch_trainer(self):
        data = self._selected_data()
        if not data:
            self._show_toast(t("toast_select_first"), is_error=True)
            return
        pfx = data.get('wineprefix', '')
        if not pfx or not os.path.isdir(pfx):
            self._show_toast(t("toast_pfx_invalid"), is_error=True)
            return

        exe = self.trainer_exe_input.text().strip()
        if not exe or not os.path.isfile(exe):
            # Prompt user directly to choose trainer exe
            self._browse_trainer_exe()
            exe = self.trainer_exe_input.text().strip()
            if not exe or not os.path.isfile(exe):
                return

        wine_bin = getattr(self, '_current_wine_bin', None)
        if not wine_bin or not os.path.isfile(wine_bin):
            live_bin = data.get('wine_bin')
            pid = data.get('pid')
            if live_bin and os.path.isfile(live_bin):
                wine_bin = live_bin
            else:
                wine_bin = (_find_wine_bin_for_pid(pid) or find_wine_binary(pfx)) if pid else find_wine_binary(pfx)

        game_name = data.get('name', '')
        trainer_name = f"Trainer_{os.path.basename(exe)}"
        try:
            run_exe_in_prefix(
                wine_bin, exe, pfx,
                game_name=game_name,
                app_name=trainer_name,
                on_error_callback=self._on_process_error
            )
            self._show_toast(t("toast_trainer_launched"))
        except Exception as e:
            self._show_toast(t("toast_trainer_failed", error=e), is_error=True)

    def _run_ce_inspector(self):
        data = self._selected_data()
        if not data:
            self._show_toast(t("toast_select_prefix_first"), is_error=True)
            return
        pfx = data.get('wineprefix', '')
        if not pfx or not os.path.isdir(pfx):
            self._show_toast(t("toast_select_valid_prefix"), is_error=True)
            return

        ce_exe = self.config.get('ce_path', '').strip()
        if not ce_exe or not os.path.isfile(ce_exe):
            reply = QMessageBox.question(
                self, t('msg_ce_not_configured_title'),
                t('msg_ce_not_configured_body'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                f, _ = QFileDialog.getOpenFileName(
                    self, t('dialog_select_ce_exe'),
                    os.path.expanduser('~'),
                    t('dialog_filter_exe'),
                )
                if f:
                    ce_exe = f
                    self.config['ce_path'] = f
                    save_config(self.config)
                else:
                    return
            else:
                return

        wine_bin = getattr(self, '_current_wine_bin', None)
        if not wine_bin or not os.path.isfile(wine_bin):
            live_bin = data.get('wine_bin')
            pid = data.get('pid')
            if live_bin and os.path.isfile(live_bin):
                wine_bin = live_bin
            else:
                wine_bin = (_find_wine_bin_for_pid(pid) or find_wine_binary(pfx)) if pid else find_wine_binary(pfx)

        game_name = data.get('name', '')
        try:
            # O Cheat Engine e um executavel nativo (Lazarus/FPC, sem WPF ou
            # .NET): o prepare do prefixo (reg add Avalon.Graphics) e
            # desnecessario e, com o jogo rodando, pode bloquear no
            # wineserver e abortar o lancamento. Pula essa etapa para o CE.
            run_exe_in_prefix(
                wine_bin, ce_exe, pfx,
                prepare_prefix=False,
                game_name=game_name,
                app_name="CheatEngine",
                on_error_callback=self._on_process_error
            )
            self._show_toast(t("toast_ce_launched"))
        except Exception as e:
            self._show_toast(t("toast_ce_failed", error=e), is_error=True)

    def _open_logs_folder(self):
        logs_dir = error_logger.get_logs_dir()
        if error_logger.open_logs_folder():
            self._show_toast(t("toast_logs_opened"))
        else:
            self._show_toast(t("toast_logs_open_failed", dir=logs_dir), is_error=True)

    def _on_process_error(self, log_path, msg):
        self.process_error_detected.emit(log_path, msg)

    def _handle_process_error(self, log_path, msg):
        log_name = os.path.basename(log_path)
        self._show_toast(t("toast_crash_detected", name=log_name), is_error=True)
        self._log(t("log_issue_detected", path=log_path))

    def _open_wemod_modal(self):
        data = self._selected_data()
        if not data:
            self._show_toast(t("toast_select_first"), is_error=True)
            return
        pfx = data.get('wineprefix', '')
        name = data.get('name', 'Jogo')
        dlg = WeModDialog(pfx, name, self)
        dlg.exec()
        self._load_tree(force=True)

    def _copy_prefix_path(self):
        data = self._selected_data()
        if not data:
            return
        pfx = data.get('wineprefix', '')
        if pfx:
            QApplication.clipboard().setText(pfx)
            self._show_toast(t("toast_pfx_copied"))

    def _save_selected_to_custom_prefixes(self):
        data = self._selected_data()
        if not data:
            return
        pfx = data.get('wineprefix', '')
        name = data.get('name', '')
        if pfx:
            self._save_existing_to_custom_prefixes(pfx, name)

    def _open_prefix_folder(self):
        data = self._selected_data()
        if not data:
            return
        pfx = data.get('wineprefix', '')
        if pfx and os.path.isdir(pfx):
            subprocess.Popen(['xdg-open', pfx])
            self._show_toast(t("toast_folder_opened", name=os.path.basename(pfx)))

    def _open_settings(self):
        old_lang = i18n.get_language()
        self.config = load_config()
        dlg = SettingsDialog(
            self.config, save_config, self,
            delete_prefix_callback=self._remove_prefix,
        )
        if dlg.exec():
            new_lang = self.config.get('language', 'en')
            if new_lang != old_lang:
                i18n.set_language(new_lang)
                self.retranslate_ui()
        self._refresh()

    # ── Context Menu (Right Click) ───────────────────────────────────

    def _save_existing_to_custom_prefixes(self, pfx, default_name=''):
        clean_name = default_name
        for tag in ('Launcher: ', 'Hydra: ', 'Lutris: ', 'Heroic: ', 'Bottles: ', 'PlayOnLinux: ', 'PortProton: '):
            if clean_name.startswith(tag):
                clean_name = clean_name[len(tag):].strip()
        if clean_name.endswith(' [Proton]'):
            clean_name = clean_name[:-9].strip()

        name, ok = QInputDialog.getText(
            self, t('msg_add_to_list_title'),
            t('msg_add_to_list_prompt'), text=clean_name
        )
        if not ok or not name.strip():
            return
        cfg = load_config()
        custom = cfg.setdefault('custom_prefixes', [])
        canon_pfx = _canonical_prefix_path(pfx)
        for c in custom:
            if _canonical_prefix_path(c.get('wineprefix', '')) == canon_pfx:
                QMessageBox.information(self, 'Info', t('msg_already_in_list'))
                return
        custom.append({'name': name.strip(), 'wineprefix': canon_pfx or pfx, 'source': 'Custom'})
        save_config(cfg)
        self._refresh()
        self._show_toast(t('toast_prefix_added', name=name.strip()))

    def _tree_context_menu(self, pos):
        curr_tree = self.tree
        if not curr_tree:
            return
        item = curr_tree.itemAt(pos)
        if not item:
            menu = self._create_menu()
            act_add = menu.addAction(t('menu_add_prefix'))
            menu.addSeparator()
            act_refresh = menu.addAction(t('menu_refresh_list'))
            act_show = menu.addAction(t('menu_show_hidden_prefixes'))
            action = menu.exec(curr_tree.viewport().mapToGlobal(pos))
            if action == act_add:
                self._add_custom_prefix()
            elif action == act_refresh:
                self._refresh()
            elif action == act_show:
                self._show_hidden_prefixes()
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        pfx = data.get('wineprefix', '')
        has_pid = bool(data.get('pid')) or any(
            p.get('wineprefix') == pfx for p in get_running_wine_entries()
        )
        is_proc_tab = (hasattr(self, 'view_stack') and self.view_stack.currentIndex() == 0)

        menu = self._create_menu()

        # Opção destacada para salvar prefixo de processo ativo
        act_add_to_list = None
        cfg = load_config()
        saved_pfxs = {c.get('wineprefix') for c in cfg.get('custom_prefixes', [])}
        if pfx and pfx not in saved_pfxs:
            act_add_to_list = menu.addAction(t('menu_add_to_list'))

        if pfx:
            act_open = menu.addAction(t('menu_open_pfx_folder'))
            act_copy = menu.addAction(t('menu_copy_pfx_path'))
        else:
            act_open = None
            act_copy = None

        menu.addSeparator()
        act_trainer = menu.addAction(t('menu_launch_trainer'))
        act_wemod = menu.addAction(t('menu_wemod_manager'))
        act_ce = menu.addAction(t('menu_launch_ce'))

        if has_pid:
            menu.addSeparator()
            act_kill = menu.addAction(t('menu_kill_process'))
        else:
            act_kill = None

        if not is_proc_tab:
            menu.addSeparator()
            save_menu = menu.addMenu(t('menu_save_as'))
            act_backup = save_menu.addAction(t('menu_backup'))
            act_standard = save_menu.addAction(t('menu_standard_prefix'))
            act_restore = menu.addAction(t('menu_restore_backup'))
            menu.addSeparator()
            act_hide = menu.addAction(t('menu_hide_prefix'))
            act_remove = menu.addAction(t('menu_remove_prefix'))
        else:
            act_backup = act_standard = act_restore = act_hide = act_remove = None

        action = menu.exec(curr_tree.viewport().mapToGlobal(pos))
        if act_add_to_list and action == act_add_to_list:
            self._save_existing_to_custom_prefixes(pfx, data.get('name', ''))
        elif act_copy and action == act_copy:
            QApplication.clipboard().setText(pfx)
            self._show_toast(t('toast_pfx_copied'))
        elif act_open and action == act_open:
            if os.path.isdir(pfx):
                subprocess.Popen(['xdg-open', pfx])
                self._show_toast(t('toast_folder_opened', name=os.path.basename(pfx)))
        elif action == act_trainer:
            self._launch_trainer()
        elif action == act_wemod:
            dlg = WeModDialog(pfx, data.get('name', 'Jogo'), self)
            dlg.exec()
            self._load_tree()
        elif action == act_ce:
            self._run_ce_inspector()
        elif has_pid and act_kill and action == act_kill:
            self._kill_prefix_processes(pfx)
            self._refresh()
        elif act_backup and action == act_backup:
            self._backup_prefix(pfx, data.get('source') in ('Personalizado', 'Não-Steam'))
        elif act_standard and action == act_standard:
            self._save_as_standard_prefix(pfx, data.get('source') in ('Personalizado', 'Não-Steam'))
        elif act_restore and action == act_restore:
            self._restore_backup(pfx, data.get('source') in ('Personalizado', 'Não-Steam'))
        elif act_hide and action == act_hide:
            self._hide_prefix(pfx)
        elif act_remove and action == act_remove:
            self._remove_prefix(pfx, data.get('source') in ('Personalizado', 'Não-Steam'))

    # ── Prefix Management & Backups ──────────────────────────────────

    def _kill_prefix_processes(self, wineprefix, notify=True):
        wineprefix_bytes = f'WINEPREFIX={wineprefix}\0'.encode('utf-8')
        killed = []
        for entry in os.listdir('/proc'):
            if not entry.isdigit():
                continue
            env_raw = _read_file_safe(f'/proc/{entry}/environ', 'rb')
            if not env_raw or wineprefix_bytes not in env_raw:
                continue
            comm = _read_file_safe(f'/proc/{entry}/comm').strip().lower()
            if 'wineserver' in comm:
                continue
            try:
                os.kill(int(entry), 9)
                killed.append(int(entry))
            except (OSError, PermissionError):
                pass
        if notify:
            if killed:
                self._show_toast(t('toast_processes_killed', count=len(killed)))
            else:
                self._show_toast(t('toast_no_processes'))
        return len(killed)

    def _add_custom_prefix(self):
        name, ok = QInputDialog.getText(
            self, t('msg_add_custom_pfx_title'),
            t('msg_add_custom_pfx_prompt')
        )
        if not ok or not name.strip():
            return
        pfx = QFileDialog.getExistingDirectory(
            self, t('dialog_select_pfx_dir')
        )
        if not pfx:
            return
        if not os.path.isdir(os.path.join(pfx, 'drive_c')):
            QMessageBox.warning(
                self, t('msg_confirm_title'),
                t('msg_not_valid_pfx')
            )
            return
        cfg = load_config()
        custom = cfg.setdefault('custom_prefixes', [])
        for c in custom:
            if c['wineprefix'] == pfx:
                QMessageBox.information(self, 'Info', t('msg_pfx_already_added'))
                return
        custom.append({'name': name.strip(), 'wineprefix': pfx})
        save_config(cfg)
        self._refresh()
        self._show_toast(t('toast_prefix_added', name=name.strip()))

    def _show_hidden_prefixes(self):
        self._open_settings()

    def _hide_prefix(self, pfx):
        cfg = load_config()
        hidden = cfg.setdefault('hidden_prefixes', [])
        if pfx not in hidden:
            hidden.append(pfx)
        save_config(cfg)
        self._refresh()
        self._show_toast(t('toast_pfx_hidden'))

    def _remove_prefix(self, pfx, is_custom=False):
        canon_pfx = _canonical_prefix_path(pfx)
        if not pfx or not os.path.isdir(pfx):
            reply = QMessageBox.question(
                self, t('msg_confirm_title'),
                t('msg_confirm_remove_stale_pfx', pfx=pfx),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
            cfg = load_config()
            if 'custom_prefixes' in cfg:
                cfg['custom_prefixes'] = [
                    c for c in cfg['custom_prefixes']
                    if c.get('wineprefix') != pfx and _canonical_prefix_path(c.get('wineprefix', '')) != canon_pfx
                ]
            if 'hidden_prefixes' in cfg:
                cfg['hidden_prefixes'] = [
                    h for h in cfg['hidden_prefixes']
                    if h != pfx and _canonical_prefix_path(h) != canon_pfx
                ]
            save_config(cfg)
            self.config = cfg
            self._refresh()
            self._show_toast(t('toast_pfx_deleted'))
            return True

        delete_target = _resolve_prefix_root(pfx)

        # Proteção contra exclusão acidental de diretórios do sistema ou bibliotecas
        home = os.path.expanduser('~')
        critical_roots = {
            os.path.abspath(home),
            os.path.abspath('/'),
            os.path.abspath(os.path.join(home, '.config')),
            os.path.abspath(os.path.join(home, 'Games')),
            os.path.abspath(os.path.join(home, 'wineprefixes')),
            os.path.abspath(os.path.join(home, '.config/hydralauncher/wine-prefixes')),
            os.path.abspath(os.path.join(home, '.config/hydralauncher-native/wine-prefixes')),
            os.path.abspath(os.path.join(home, '.var/app/io.github.hydralauncher.hydra/config/hydralauncher/wine-prefixes')),
            os.path.abspath(os.path.join(home, '.var/app/io.github.hydralauncher.hydra/config/hydralauncher-native/wine-prefixes')),
            os.path.abspath(os.path.join(home, '.PlayOnLinux/wineprefix')),
            os.path.abspath(os.path.join(home, 'PortProton/prefixes')),
            os.path.abspath(os.path.join(home, '.local/share/bottles/bottles')),
            os.path.abspath(os.path.join(home, '.var/app/com.usebottles.bottles/data/bottles')),
        }
        if os.path.abspath(delete_target) in critical_roots:
            QMessageBox.critical(
                self, t('msg_security_error_title'),
                t('msg_security_error_body', target=delete_target)
            )
            return False

        reply = QMessageBox.question(
            self, t('msg_confirm_title'),
            t('msg_confirm_delete_pfx', target=delete_target),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        self._kill_prefix_processes(pfx)
        result = subprocess.run(['rm', '-rf', delete_target], capture_output=True, text=True)
        if result.returncode != 0:
            QMessageBox.critical(self, t('msg_confirm_title'), t('msg_error_delete_pfx', error=result.stderr))
            return False
        cfg = load_config()
        if 'custom_prefixes' in cfg:
            cfg['custom_prefixes'] = [
                c for c in cfg['custom_prefixes']
                if c.get('wineprefix') != pfx and _canonical_prefix_path(c.get('wineprefix', '')) != canon_pfx
            ]
        if 'hidden_prefixes' in cfg:
            cfg['hidden_prefixes'] = [
                h for h in cfg['hidden_prefixes']
                if h != pfx and _canonical_prefix_path(h) != canon_pfx
            ]
        save_config(cfg)
        self.config = cfg
        self._refresh()
        self._show_toast(t('toast_pfx_deleted'))
        return True

    def _wemod_built_log_window(self, title: str):
        win = QDialog(self)
        win.setWindowTitle(title)
        win.setModal(True)
        win.setMinimumSize(700, 480)
        win.setStyleSheet(styles.GLOBAL_STYLESHEET)
        layout = QVBoxLayout(win)

        self._wemod_built_label = QLabel(t('task_preparing'))
        self._wemod_built_label.setWordWrap(True)
        layout.addWidget(self._wemod_built_label)

        self._wemod_built_bar = QProgressBar()
        self._wemod_built_bar.setRange(0, 100)
        self._wemod_built_bar.setValue(0)
        layout.addWidget(self._wemod_built_bar)

        self._wemod_built_log = QTextEdit()
        self._wemod_built_log.setReadOnly(True)
        self._wemod_built_log.setStyleSheet(
            'background: #181920; color: #d4d4d8; font-family: monospace; font-size: 11px;'
        )
        layout.addWidget(self._wemod_built_log, stretch=1)

        self._wemod_built_close_btn = QPushButton(t('btn_close'))
        self._wemod_built_close_btn.setVisible(False)
        self._wemod_built_close_btn.clicked.connect(win.accept)
        layout.addWidget(self._wemod_built_close_btn, alignment=Qt.AlignmentFlag.AlignRight)
        win.show()
        QApplication.processEvents()
        return win

    def _built_poll_tick(self):
        while self._built_msg_queue:
            msg = self._built_msg_queue.popleft()
            if hasattr(self, '_wemod_built_log'):
                self._wemod_built_log.append(msg)
        while self._built_progress_queue:
            step, pct = self._built_progress_queue.popleft()
            if hasattr(self, '_wemod_built_label'):
                self._wemod_built_label.setText(step)
            if hasattr(self, '_wemod_built_bar'):
                self._wemod_built_bar.setValue(pct)
        if self._built_task_done:
            self._built_poll.stop()
            self.setEnabled(True)
            if hasattr(self, '_wemod_built_close_btn'):
                self._wemod_built_close_btn.setVisible(True)

    def _backup_prefix(self, pfx, is_custom=False):
        source = _resolve_prefix_root(pfx)
        if not os.path.isdir(source):
            QMessageBox.warning(self, t('msg_confirm_title'), t('msg_pfx_dir_not_found'))
            return
        default_name = os.path.basename(source)
        name, ok = QInputDialog.getText(
            self, t('msg_save_backup_title'),
            t('msg_save_backup_prompt'), text=default_name,
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        dst = os.path.join(source, f'{name}.zip')
        if os.path.exists(dst):
            reply = QMessageBox.question(
                self, t('msg_overwrite_title'),
                t('msg_overwrite_prompt', dst=dst),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._wemod_built_progress = self._wemod_built_log_window(f"{t('menu_backup')} — {name}")
        self.setEnabled(False)
        self._built_msg_queue.clear()
        self._built_progress_queue.clear()
        self._built_task_done = False
        self._built_poll.start()

        def task():
            try:
                self._built_msg_queue.append(t('task_saving_backup_to', dst=dst))
                self._built_progress_queue.append((t('task_compressing_files'), 0))
                skipped = 0
                file_count = sum(len(f) for _, _, f in os.walk(source, followlinks=False))
                with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zf:
                    current = 0
                    for root, dirs, files in os.walk(source, followlinks=False):
                        for f in files:
                            fpath = os.path.join(root, f)
                            if os.path.islink(fpath):
                                skipped += 1
                                continue
                            arcname = os.path.relpath(fpath, source)
                            try:
                                zf.write(fpath, arcname)
                                current += 1
                            except (PermissionError, OSError):
                                skipped += 1
                                continue
                            pct = int(80 * current / file_count) if file_count else 80
                            self._built_progress_queue.append((t('task_compressing_progress', curr=current, total=file_count), pct))
                if skipped:
                    self._built_msg_queue.append(t('task_special_files_skipped', count=skipped))
                self._built_progress_queue.append((t('task_completed'), 100))
                self._built_msg_queue.append(t('task_backup_saved', dst=dst))
                self._built_task_ok = True
            except Exception as e:
                self._built_msg_queue.append(t('task_error', error=e))
                self._built_task_ok = False
            self._built_task_done = True

        import threading
        threading.Thread(target=task, daemon=True).start()

    def _save_as_standard_prefix(self, pfx, is_custom=False):
        source = _resolve_prefix_root(pfx)
        if not os.path.isdir(source):
            QMessageBox.warning(self, t('msg_confirm_title'), t('msg_pfx_dir_not_found'))
            return
        default_name = os.path.basename(source)
        name, ok = QInputDialog.getText(
            self, t('msg_save_std_pfx_title'),
            t('msg_save_std_pfx_prompt'), text=default_name,
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        dst = os.path.join(BUILT_PREFIX_DIR, f'{name}.zip')
        if os.path.exists(dst):
            reply = QMessageBox.question(
                self, t('msg_overwrite_title'),
                t('msg_overwrite_prompt', dst=dst),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._wemod_built_progress = self._wemod_built_log_window(f"{t('menu_standard_prefix')} — {name}")
        self.setEnabled(False)
        self._built_msg_queue.clear()
        self._built_progress_queue.clear()
        self._built_task_done = False
        self._built_poll.start()

        def task():
            try:
                self._built_msg_queue.append(t('task_saving_std_to', dst=dst))
                self._built_progress_queue.append((t('task_compressing_files'), 0))
                os.makedirs(BUILT_PREFIX_DIR, exist_ok=True)
                skipped = 0
                file_count = sum(len(f) for _, _, f in os.walk(source, followlinks=False))
                with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zf:
                    current = 0
                    for root, dirs, files in os.walk(source, followlinks=False):
                        for f in files:
                            fpath = os.path.join(root, f)
                            if os.path.islink(fpath):
                                skipped += 1
                                continue
                            arcname = os.path.relpath(fpath, source)
                            try:
                                zf.write(fpath, arcname)
                                current += 1
                            except (PermissionError, OSError):
                                skipped += 1
                                continue
                            pct = int(80 * current / file_count) if file_count else 80
                            self._built_progress_queue.append((t('task_compressing_progress', curr=current, total=file_count), pct))
                if skipped:
                    self._built_msg_queue.append(t('task_special_files_skipped', count=skipped))
                self._built_progress_queue.append((t('task_completed'), 100))
                self._built_msg_queue.append(t('task_std_pfx_saved', dst=dst))
                self._built_task_ok = True
            except Exception as e:
                self._built_msg_queue.append(t('task_error', error=e))
                self._built_task_ok = False
            self._built_task_done = True

        import threading
        threading.Thread(target=task, daemon=True).start()

    def _restore_backup(self, pfx, is_custom=False):
        source = _resolve_prefix_root(pfx)
        if not os.path.isdir(source):
            QMessageBox.warning(self, t('msg_confirm_title'), t('msg_pfx_dir_not_found'))
            return
        backups = sorted(
            f for f in os.listdir(source)
            if f.endswith('.zip') and os.path.isfile(os.path.join(source, f))
        )
        if not backups:
            QMessageBox.information(self, t('menu_backup'), t('msg_no_backups_found'))
            return
        if len(backups) == 1:
            selected = backups[0]
        else:
            selected, ok = QInputDialog.getItem(
                self, t('msg_restore_backup_title'),
                t('msg_restore_backup_prompt'), backups, 0, False,
            )
            if not ok:
                return
        backup_path = os.path.join(source, selected)
        reply = QMessageBox.question(
            self, t('msg_confirm_title'),
            t('msg_confirm_restore_backup', name=selected),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._wemod_built_progress = self._wemod_built_log_window(f"{t('msg_restore_backup_title')} — {selected}")
        self.setEnabled(False)
        self._built_msg_queue.clear()
        self._built_progress_queue.clear()
        self._built_task_done = False
        self._built_poll.start()

        def task():
            try:
                killed = self._kill_prefix_processes(pfx, notify=False)
                if killed:
                    self._built_msg_queue.append(
                        t('task_killed_before_restore', count=killed))
                self._built_msg_queue.append(t('task_restoring_backup', name=selected))
                self._built_progress_queue.append((t('task_removing_current_pfx'), 10))
                if os.path.isdir(pfx):
                    shutil.rmtree(pfx)
                self._built_progress_queue.append((t('task_extracting_backup'), 30))
                with zipfile.ZipFile(backup_path, 'r') as zf:
                    zf.extractall(source)
                self._built_progress_queue.append((t('task_completed'), 100))
                self._built_msg_queue.append(t('task_backup_restored'))
                self._built_task_ok = True
            except Exception as e:
                self._built_msg_queue.append(t('task_error', error=e))
                self._built_task_ok = False
            self._built_task_done = True

        import threading
        threading.Thread(target=task, daemon=True).start()

    def _log(self, msg):
        self.log.append(msg)


# ── entry point ────────────────────────────────────────────────────

def main():
    error_logger.setup_global_exception_handler()
    cfg = load_config()
    i18n.init_language(cfg.get('language', 'en'))
    app = QApplication(sys.argv)
    app.setStyleSheet(styles.GLOBAL_STYLESHEET)
    app.setApplicationName('Action Shark')
    app.setDesktopFileName('trainer_manager')
    app.setWindowIcon(get_shark_icon())
    win = ProtonRunner()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
