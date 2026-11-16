#!/usr/bin/env python3
"""
Action Shark - Linux Wine/Proton Trainer Manager
Overhaul: Desktop Pro UI (Faithful to Mockup 2)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import traceback
import zipfile
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
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon

import error_logger
import wemod_manager as wm
import styles
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
    get_filter_icon,
    get_back_icon,
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
    try:
        r = subprocess.run(
            ['protontricks', '-l'],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []

    games = []
    for line in r.stdout.strip().splitlines():
        line = line.strip()
        if '(' in line and line.endswith(')'):
            name = line[:line.rfind('(')].strip()
            appid = line[line.rfind('(') + 1:-1].strip()
            if appid.isdigit():
                games.append({
                    'name': name,
                    'appid': appid,
                    'wineprefix': _find_steam_prefix(appid),
                    'source': 'Steam',
                    'pid': None,
                })
    return games


# ── running Wine/Proton processes ──────────────────────────────────

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
            m_hydra = re.search(r'hydralauncher/wine-prefixes/(\d+)', wineprefix)
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

def _detect_lutris():
    out = []
    cfg_dir = os.path.expanduser('~/.config/lutris/games/')
    if not os.path.isdir(cfg_dir):
        return out
    for fname in os.listdir(cfg_dir):
        if not fname.endswith('.json'):
            continue
        try:
            data = json.loads(Path(os.path.join(cfg_dir, fname)).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        pfx = data.get('wine_prefix') or ''
        if pfx and os.path.isdir(pfx):
            out.append({
                'name': f"Lutris: {data.get('name', fname)}",
                'wineprefix': pfx,
                'source': 'Lutris',
                'exe': data.get('exe', ''),
            })
    return out


def _detect_bottles():
    out = []
    for base in [
        os.path.expanduser('~/.var/app/com.usebottles.bottles/data/bottles/'),
        os.path.expanduser('~/.local/share/bottles/'),
    ]:
        if not os.path.isdir(base):
            continue
        for bottle in os.listdir(base):
            pfx = os.path.join(base, bottle)
            if os.path.isdir(os.path.join(pfx, 'drive_dos')):
                out.append({
                    'name': f"Bottles: {bottle}",
                    'wineprefix': pfx,
                    'source': 'Bottles',
                    'exe': '',
                })
    return out


def _detect_heroic():
    out = []
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
                if pfx and os.path.isdir(pfx):
                    out.append({
                        'name': f"Heroic: {game_data.get('title', game_id)}",
                        'wineprefix': pfx,
                        'source': 'Heroic',
                        'exe': game_data.get('executable', ''),
                    })

        gc_dir = os.path.join(cfg_dir, 'GamesConfig')
        if os.path.isdir(gc_dir):
            for fname in os.listdir(gc_dir):
                if not fname.endswith('.json'):
                    continue
                try:
                    gc = json.loads(Path(os.path.join(gc_dir, fname)).read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                pfx = gc.get('winePrefix') or gc.get('wine_prefix', '')
                if pfx and os.path.isdir(pfx):
                    out.append({
                        'name': f"Heroic: {gc.get('title', fname[:-5])}",
                        'wineprefix': pfx,
                        'source': 'Heroic',
                        'exe': gc.get('executable', ''),
                    })
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


def _get_hydra_games_metadata():
    """Extract game metadata (title, executablePath) from Hydra database and logs."""
    import glob
    games = {}
    hydra_dirs = [
        os.path.expanduser('~/.config/hydralauncher'),
        os.path.expanduser('~/.var/app/io.github.hydralauncher.hydra/config/hydralauncher'),
    ]

    for h_dir in hydra_dirs:
        db_dir = os.path.join(h_dir, 'hydra-db')
        if os.path.isdir(db_dir):
            for fpath in glob.glob(os.path.join(db_dir, '*')):
                if not fpath.endswith(('.log', '.ldb')):
                    continue
                try:
                    data = Path(fpath).read_bytes()
                except OSError:
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
                        depth = 0
                        in_string = False
                        escape = False
                        for i in range(brace_start, min(len(data), brace_start + 10000)):
                            b = data[i:i+1]
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
                                        raw = data[brace_start:i+1].decode('utf-8', errors='ignore')
                                        try:
                                            obj = json.loads(raw)
                                            oid = str(obj.get('objectId') or obj.get('id') or '')
                                            title = obj.get('title')
                                            exe = obj.get('executablePath') or ''
                                            if oid and title:
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

                # 2. Regex fallback for string pairs across binary LevelDB blocks
                p1 = re.compile(rb'"objectId":"(\d+)"[^}{]{1,800}"title":"((?:[^"\\]|\\.)*)"')
                p2 = re.compile(rb'"title":"((?:[^"\\]|\\.)*)"[^}{]{1,800}"objectId":"(\d+)"')
                for m in p1.finditer(data):
                    oid = m.group(1).decode('utf-8', errors='ignore')
                    t = m.group(2).decode('utf-8', errors='ignore')
                    try:
                        t = json.loads(f'"{t}"')
                    except Exception:
                        pass
                    if oid not in games or not games[oid].get('title'):
                        games[oid] = {'title': t, 'exe': ''}
                for m in p2.finditer(data):
                    t = m.group(1).decode('utf-8', errors='ignore')
                    oid = m.group(2).decode('utf-8', errors='ignore')
                    try:
                        t = json.loads(f'"{t}"')
                    except Exception:
                        pass
                    if oid not in games or not games[oid].get('title'):
                        games[oid] = {'title': t, 'exe': ''}

        # 3. Check logs directory for achievements notifications and umu executable commands
        logs_dir = os.path.join(h_dir, 'logs')
        if os.path.isdir(logs_dir):
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
                                        if aid not in games:
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

    return games


def _detect_hydra():
    out = []
    meta = _get_hydra_games_metadata()
    bases = [
        os.path.expanduser('~/.config/hydralauncher/wine-prefixes'),
        os.path.expanduser('~/.var/app/io.github.hydralauncher.hydra/config/hydralauncher/wine-prefixes'),
    ]
    seen_prefixes = set()
    for base in bases:
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            pfx = os.path.join(base, entry)
            if not os.path.isdir(os.path.join(pfx, 'drive_c')):
                continue
            if pfx in seen_prefixes:
                continue
            seen_prefixes.add(pfx)

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


def _detect_custom():
    out = []
    default = os.path.expanduser('~/.wine')
    if os.path.isdir(os.path.join(default, 'drive_c')):
        out.append({
            'name': 'Default Wine (~/.wine)',
            'wineprefix': default,
            'source': 'Custom',
            'exe': '',
        })
    for base in [os.path.expanduser('~/Games'), os.path.expanduser('~/wineprefixes')]:
        if not os.path.isdir(base):
            continue
        for item in os.listdir(base):
            pfx = os.path.join(base, item)
            if os.path.isdir(os.path.join(pfx, 'drive_c')):
                out.append({
                    'name': item,
                    'wineprefix': pfx,
                    'source': 'Custom',
                    'exe': '',
                })
    return out


_LAUNCHER_DETECTORS = [
    _detect_lutris,
    _detect_bottles,
    _detect_heroic,
    _detect_portproton,
    _detect_playonlinux,
    _detect_hydra,
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
        key = f"{entry.get('source','')}:{entry.get('appid','')}:{entry.get('wineprefix','')}"
        if key not in seen:
            seen.add(key)
            if entry.get('source') != 'Não-Steam' and entry.get('wineprefix', '') in hidden:
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

        self.process_error_detected.connect(self._handle_process_error)

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
        for button in (self.ce_btn, self.wemod_btn, self.open_folder_btn, self.open_logs_btn):
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
        self._apply_filters()
        self._on_item_selected()

    def _on_pref_item_double_clicked(self, item, column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        pfx = data.get('wineprefix', '')
        if column == 3 and pfx:
            dlg = WeModDialog(pfx, data.get('name', 'Jogo'), self)
            dlg.exec()
            self._load_tree()

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

        # Center: Search Bar (Pill) + Filter Icon
        search_container = QHBoxLayout()
        search_container.setSpacing(12)

        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("searchBar")
        self.search_bar.setPlaceholderText("Filtrar por nome, PID ou executável...")
        self.search_bar.setFixedWidth(516)
        self.search_bar.setFixedHeight(35)
        self.search_bar.addAction(get_search_icon(16), QLineEdit.ActionPosition.LeadingPosition)
        self.search_bar.setClearButtonEnabled(True)
        self.search_bar.textChanged.connect(self._apply_filters)
        search_container.addWidget(self.search_bar)

        filter_menu_btn = QPushButton()
        filter_menu_btn.setIcon(get_filter_icon(18))
        filter_menu_btn.setObjectName("headerIconBtn")
        filter_menu_btn.setFixedSize(28, 32)
        filter_menu_btn.setToolTip("Filtrar / Opções Rápidas")
        filter_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        filter_menu_btn.clicked.connect(self._quick_menu)
        search_container.addWidget(filter_menu_btn)

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

        self.tab_proc_btn = QPushButton("⚡ Processos Ativos (0)")
        self.tab_proc_btn.setObjectName("navTabBtn")
        self.tab_proc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tab_proc_btn.setProperty("selected", "true")
        self.tab_proc_btn.clicked.connect(lambda: self._switch_tab(0))

        self.tab_pref_btn = QPushButton("📁 Prefixos Instalados (0)")
        self.tab_pref_btn.setObjectName("navTabBtn")
        self.tab_pref_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tab_pref_btn.setProperty("selected", "false")
        self.tab_pref_btn.clicked.connect(lambda: self._switch_tab(1))

        tab_bar_layout.addWidget(self.tab_proc_btn)
        tab_bar_layout.addWidget(self.tab_pref_btn)

        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(0, 0, 0, 8)
        nav_row.addWidget(tab_container)
        nav_row.addStretch()
        left_layout.addLayout(nav_row)

        # ── Stacked View ─────────────────────────────────────────────
        self.view_stack = QStackedWidget()

        # Page 0: Processos Ativos
        proc_page = QWidget()
        proc_layout = QVBoxLayout(proc_page)
        proc_layout.setContentsMargins(0, 0, 0, 0)
        proc_layout.setSpacing(0)

        self.proc_tree = QTreeWidget()
        self.proc_tree.setHeaderLabels(['PID', 'Jogo / Executável', 'Ambiente / Runner', 'Status'])
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
        self.pref_tree.setHeaderLabels(['Jogo / Prefixo', 'Origem', 'Arquitetura', 'WeMod'])
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

        back_btn = QPushButton()
        back_btn.setIcon(get_back_icon(18))
        back_btn.setObjectName("windowIconBtn")
        back_btn.setFixedSize(28, 32)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self._refresh)
        insp_top.addWidget(back_btn)

        insp_top.addStretch()

        insp_gear = QPushButton()
        insp_gear.setIcon(get_gear_icon(14))
        insp_gear.setToolTip('Configurações')
        insp_gear.setObjectName("windowIconBtn")
        insp_gear.setFixedSize(28, 32)
        insp_gear.clicked.connect(self._open_settings)
        insp_top.addWidget(insp_gear)

        minimize_btn = QPushButton()
        minimize_btn.setIcon(get_minimize_icon(16))
        minimize_btn.setToolTip('Minimizar')
        minimize_btn.setObjectName("windowIconBtn")
        minimize_btn.setFixedSize(28, 32)
        minimize_btn.clicked.connect(self.showMinimized)
        insp_top.addWidget(minimize_btn)

        maximize_btn = QPushButton()
        maximize_btn.setIcon(get_maximize_icon(16))
        maximize_btn.setToolTip('Maximizar / Restaurar')
        maximize_btn.setObjectName("windowIconBtn")
        maximize_btn.setFixedSize(28, 32)
        maximize_btn.clicked.connect(self._toggle_maximized)
        insp_top.addWidget(maximize_btn)

        close_btn = QPushButton()
        close_btn.setIcon(get_close_icon(16))
        close_btn.setToolTip('Fechar')
        close_btn.setObjectName("windowIconBtn")
        close_btn.setFixedSize(28, 32)
        close_btn.clicked.connect(self.close)
        insp_top.addWidget(close_btn)
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

        self.copy_pfx_btn = QPushButton("Copiar")
        self.copy_pfx_btn.setFixedHeight(22)
        self.copy_pfx_btn.setStyleSheet("font-size: 11px; padding: 2px 8px; background: #272834; border: 1px solid #3f4258; border-radius: 4px; color: #d1d5db;")
        self.copy_pfx_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_pfx_btn.clicked.connect(self._copy_prefix_path)
        pfx_header_row.addWidget(self.copy_pfx_btn)

        self.open_pfx_quick_btn = QPushButton("Abrir Pasta")
        self.open_pfx_quick_btn.setFixedHeight(22)
        self.open_pfx_quick_btn.setStyleSheet("font-size: 11px; padding: 2px 8px; background: transparent; border: 1px solid #3f4258; border-radius: 4px; color: #818cf8;")
        self.open_pfx_quick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_pfx_quick_btn.clicked.connect(self._open_prefix_folder)
        pfx_header_row.addWidget(self.open_pfx_quick_btn)
        pfx_layout.addLayout(pfx_header_row)

        self.pfx_path_label = QLabel("Nenhum prefixo selecionado")
        self.pfx_path_label.setStyleSheet("font-size: 11px; font-family: monospace; color: #d4d4d8; background: transparent; border: none;")
        self.pfx_path_label.setWordWrap(True)
        pfx_layout.addWidget(self.pfx_path_label)

        self.add_to_lib_btn = QPushButton("➕ Adicionar à Lista de Prefixos")
        self.add_to_lib_btn.setFixedHeight(26)
        self.add_to_lib_btn.setStyleSheet("font-size: 11px; font-weight: 600; background: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.35); border-radius: 6px; color: #a5b4fc;")
        self.add_to_lib_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_to_lib_btn.clicked.connect(self._save_selected_to_custom_prefixes)
        self.add_to_lib_btn.setVisible(False)
        pfx_layout.addWidget(self.add_to_lib_btn)

        inspector_layout.addWidget(pfx_info_frame)
        inspector_layout.addSpacing(10)

        # Wine Version Section
        wine_lbl = QLabel("Wine Version  ⓘ")
        wine_lbl.setStyleSheet("font-size: 15px; font-weight: 400; color: #dddddf;")
        wine_lbl.setFixedHeight(24)
        wine_lbl.setToolTip("Versão do Wine/Proton em uso para este prefixo.")
        inspector_layout.addWidget(wine_lbl)
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

        self.wine_version_label = QLabel("Nenhum selecionado")
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
        self.trainer_exe_input.setPlaceholderText("/path/to/trainer.exe")
        tr_row.addWidget(self.trainer_exe_input)

        browse_btn = RoundedButton("Browse")
        browse_btn.setObjectName("browseBtn")
        browse_btn.setFixedSize(81, 37)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._browse_trainer_exe)
        tr_row.addWidget(browse_btn)
        inspector_layout.addWidget(trainer_field)
        inspector_layout.addSpacing(15)

        # Primary Action: Launch Trainer Button (Always vibrant blue, clickable)
        self.launch_btn = RoundedButton("Launch Trainer")
        self.launch_btn.setObjectName("launchTrainerBtn")
        self.launch_btn.setFixedHeight(40)
        self.launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.launch_btn.clicked.connect(self._launch_trainer)
        inspector_layout.addWidget(self.launch_btn)

        inspector_layout.addSpacing(14)
        divider = QFrame()
        divider.setObjectName('divider')
        divider.setFixedHeight(1)
        inspector_layout.addWidget(divider)
        inspector_layout.addSpacing(13)

        # Quick Actions Header
        qa_lbl = QLabel("Quick Actions")
        qa_lbl.setStyleSheet("font-size: 15px; font-weight: 400; color: #eeeeef;")
        qa_lbl.setFixedHeight(24)
        inspector_layout.addWidget(qa_lbl)
        inspector_layout.addSpacing(14)

        # Quick Actions 2x2 Grid (Exact Mockup Layout)
        qa_grid = QGridLayout()
        qa_grid.setSpacing(14)
        qa_grid.setColumnStretch(0, 1)
        qa_grid.setColumnStretch(1, 1)

        self.ce_btn = RoundedButton(" Cheat Engine")
        self.ce_btn.setIcon(get_cheatengine_icon(16))
        self.ce_btn.setObjectName("quickActionBtn")
        self.ce_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ce_btn.clicked.connect(self._run_ce_inspector)
        qa_grid.addWidget(self.ce_btn, 0, 0)

        self.wemod_btn = RoundedButton(" WeMod Manager")
        self.wemod_btn.setIcon(get_wemod_icon(16))
        self.wemod_btn.setObjectName("quickActionBtn")
        self.wemod_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wemod_btn.clicked.connect(self._open_wemod_modal)
        qa_grid.addWidget(self.wemod_btn, 0, 1)

        self.open_folder_btn = RoundedButton(" Open Folder")
        self.open_folder_btn.setIcon(get_folder_icon(16))
        self.open_folder_btn.setObjectName("quickActionBtn")
        self.open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_btn.clicked.connect(self._open_prefix_folder)
        qa_grid.addWidget(self.open_folder_btn, 1, 0)

        self.open_logs_btn = RoundedButton(" Logs")
        self.open_logs_btn.setIcon(get_log_icon(16))
        self.open_logs_btn.setObjectName("quickActionBtn")
        self.open_logs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_logs_btn.setToolTip("Abrir pasta de logs de erros/crashes na raiz do app")
        self.open_logs_btn.clicked.connect(self._open_logs_folder)
        qa_grid.addWidget(self.open_logs_btn, 1, 1)

        for button in (self.ce_btn, self.wemod_btn, self.open_folder_btn, self.open_logs_btn):
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

    def _create_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(styles.MENU_STYLESHEET)
        return menu

    def _quick_menu(self):
        menu = self._create_menu()
        menu.addAction('Adicionar Prefixo', self._add_custom_prefix)
        menu.addAction('Atualizar Lista', self._refresh)
        menu.addAction('Abrir Pasta de Logs', self._open_logs_folder)
        menu.addAction('Configurações', self._open_settings)
        menu.exec(self.search_bar.mapToGlobal(self.search_bar.rect().bottomRight()))

    # ── Toast status ─────────────────────────────────────────────────

    def _show_toast(self, msg: str, is_error: bool = False):
        color = "#f87171" if is_error else "#34d399"
        self.status_toast.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 500;")
        self.status_toast.setText(msg)
        self._log(msg)
        QTimer.singleShot(5000, lambda: self.status_toast.setText("") if self.status_toast.text() == msg else None)

    # ── Data Loading & Table Population ──────────────────────────────

    def _refresh(self):
        self._show_toast("Atualizando...")
        self._load_tree()
        self._show_toast("✓ Lista atualizada.")

    def _auto_refresh(self):
        # Rebuild the model so processes started or stopped after launch are
        # actually added/removed from the table.
        self._load_tree()

    def _load_tree(self):
        sel_data = self._selected_data()
        sel_pfx = sel_data.get('wineprefix') if sel_data else None

        # ── 1. Populate Active Processes ─────────────────────────────
        self.proc_tree.clear()
        running_entries = get_running_wine_entries()

        proc_first_item = None
        proc_matched_item = None
        for p in running_entries:
            pid = str(p.get('pid', ''))
            name = p.get('name', '')
            comm = p.get('comm', '')
            display_name = f"{name} ({comm})" if comm and comm != name else name
            runner = "Proton" if p.get('is_proton') else "Wine"
            status = "Rodando"
            pfx = p.get('wineprefix', '')

            item = QTreeWidgetItem([pid, display_name, runner, status])
            item.setData(0, Qt.ItemDataRole.UserRole, p)
            self.proc_tree.addTopLevelItem(item)

            if not proc_first_item and pfx:
                proc_first_item = item
            if sel_pfx and pfx == sel_pfx:
                proc_matched_item = item

        self.tab_proc_btn.setText(f"⚡ Processos Ativos ({len(running_entries)})")

        # ── 2. Populate Installed Prefixes (Steam, Launchers, Custom) ──
        self.pref_tree.clear()
        pref_entries = []
        seen_pfx = set()
        hidden = set(load_config().get('hidden_prefixes', []))

        def _add_pref(entry):
            pfx = entry.get('wineprefix', '')
            key = f"{entry.get('source','')}:{pfx}"
            if key not in seen_pfx:
                seen_pfx.add(key)
                if pfx in hidden and entry.get('source') != 'Não-Steam':
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
                    'source': 'Personalizado',
                    'exe': '',
                    'is_proton': False,
                })

        pref_first_item = None
        pref_matched_item = None

        for e in pref_entries:
            pfx = e.get('wineprefix', '')
            name = e.get('name', '')
            source = e.get('source', '')
            arch = "win64"

            has_wemod = bool(pfx and wm.is_wemod_installed(pfx))
            wemod_label = "✓ Instalado" if has_wemod else "Não instalado"

            item = QTreeWidgetItem([name, source, arch, wemod_label])
            item.setData(0, Qt.ItemDataRole.UserRole, e)
            self.pref_tree.addTopLevelItem(item)

            if not pref_first_item and pfx:
                pref_first_item = item
            if sel_pfx and pfx == sel_pfx:
                pref_matched_item = item

        self.tab_pref_btn.setText(f"📁 Prefixos Instalados ({self.pref_tree.topLevelItemCount()})")

        self._apply_filters()

        curr_tree = self.proc_tree if self.view_stack.currentIndex() == 0 else self.pref_tree
        target = (proc_matched_item or proc_first_item) if self.view_stack.currentIndex() == 0 else (pref_matched_item or pref_first_item)
        if target:
            curr_tree.setCurrentItem(target)

    # ── Filtering ────────────────────────────────────────────────────

    def _apply_filters(self):
        search_query = self.search_bar.text().strip().lower()
        active_chip = self.chip_bar.get_active_filter()

        # Filters for Active Processes Tree
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
                chip_match = ('steam' in source)
            elif active_chip == 'HEROIC':
                chip_match = ('heroic' in source)
            elif active_chip == 'LUTRIS':
                chip_match = ('lutris' in source)
            elif active_chip == 'BOTTLES':
                chip_match = ('bottles' in source)
            elif active_chip == 'CUSTOM':
                chip_match = ('custom' in source or 'personalizado' in source or 'não-steam' in source)

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
        if not data:
            self.banner_widget.set_game("Select a Game", "", "")
            self._current_wine_bin = None
            if hasattr(self, 'wine_version_label'):
                self.wine_version_label.setText("Nenhum selecionado")
                self.wine_version_label.setStyleSheet("font-size: 14px; font-weight: 400; color: #71717a; background: transparent; border: none;")
            if hasattr(self, 'wine_version_frame'):
                self.wine_version_frame.setToolTip("")
            if hasattr(self, 'pfx_path_label'):
                self.pfx_path_label.setText("Nenhum prefixo selecionado")
            if hasattr(self, 'add_to_lib_btn'):
                self.add_to_lib_btn.setVisible(False)
            return

        name = data.get('name', 'Unknown')
        source = data.get('source', '')
        appid = data.get('appid', '')
        pfx = data.get('wineprefix', '')

        self.banner_widget.set_game(name, source, appid)

        if hasattr(self, 'pfx_path_label'):
            self.pfx_path_label.setText(pfx if pfx else "Nenhum prefixo associado")

        if hasattr(self, 'add_to_lib_btn'):
            is_proc = bool(data.get('pid'))
            cfg = load_config()
            saved_pfxs = {c.get('wineprefix') for c in cfg.get('custom_prefixes', [])}
            can_save = is_proc and pfx and (pfx not in saved_pfxs)
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
                display_text = f"{label} (Em execução)" if is_live else label
                self.wine_version_label.setText(display_text)
                self.wine_version_label.setStyleSheet("font-size: 14px; font-weight: 400; color: #eeeeef; background: transparent; border: none;")
                if hasattr(self, 'wine_version_frame'):
                    self.wine_version_frame.setToolTip(f"Binário: {wine_bin}")
            else:
                self.wine_version_label.setText("Não detectado")
                self.wine_version_label.setStyleSheet("font-size: 14px; font-weight: 400; color: #71717a; background: transparent; border: none;")
                if hasattr(self, 'wine_version_frame'):
                    self.wine_version_frame.setToolTip("")

    # ── Actions ──────────────────────────────────────────────────────

    def _browse_trainer_exe(self):
        start_dir = self.config.get('trainers_folder', '') or os.path.expanduser('~')
        path, _ = QFileDialog.getOpenFileName(
            self, 'Selecionar Executável do Trainer',
            start_dir,
            'Executáveis (*.exe);;Todos os arquivos (*)',
        )
        if path:
            self.trainer_exe_input.setText(path)

    def _launch_trainer(self):
        data = self._selected_data()
        if not data:
            self._show_toast("Selecione um jogo/prefixo na tabela primeiro", is_error=True)
            return
        pfx = data.get('wineprefix', '')
        if not pfx or not os.path.isdir(pfx):
            self._show_toast("WINEPREFIX não encontrado ou inválido", is_error=True)
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
            self._show_toast("✓ Trainer iniciado!")
        except Exception as e:
            self._show_toast(f"✗ Falha ao iniciar trainer: {e}", is_error=True)

    def _run_ce_inspector(self):
        data = self._selected_data()
        if not data:
            self._show_toast("Selecione um prefixo primeiro", is_error=True)
            return
        pfx = data.get('wineprefix', '')
        if not pfx or not os.path.isdir(pfx):
            self._show_toast("Selecione um prefixo válido primeiro", is_error=True)
            return

        ce_exe = self.config.get('ce_path', '').strip()
        if not ce_exe or not os.path.isfile(ce_exe):
            reply = QMessageBox.question(
                self, 'Cheat Engine Não Configurado',
                'O executável do Cheat Engine ainda não foi configurado.\nDeseja selecionar o arquivo agora?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                f, _ = QFileDialog.getOpenFileName(
                    self, 'Selecionar Cheat Engine',
                    os.path.expanduser('~'),
                    'Executáveis (*.exe);;Todos os arquivos (*)',
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
            self._show_toast("✓ Cheat Engine iniciado!")
        except Exception as e:
            self._show_toast(f"✗ Falha ao iniciar Cheat Engine: {e}", is_error=True)

    def _open_logs_folder(self):
        logs_dir = error_logger.get_logs_dir()
        if error_logger.open_logs_folder():
            self._show_toast("✓ Pasta de logs aberta")
        else:
            self._show_toast(f"✗ Falha ao abrir pasta de logs ({logs_dir})", is_error=True)

    def _on_process_error(self, log_path, msg):
        self.process_error_detected.emit(log_path, msg)

    def _handle_process_error(self, log_path, msg):
        log_name = os.path.basename(log_path)
        self._show_toast(f"✗ Erro/Crash detectado! Log salvo: {log_name}", is_error=True)
        self._log(f"Problema detectado: log gerado em {log_path}")

    def _open_wemod_modal(self):
        data = self._selected_data()
        if not data:
            self._show_toast("Selecione um jogo/prefixo primeiro", is_error=True)
            return
        pfx = data.get('wineprefix', '')
        name = data.get('name', 'Jogo')
        dlg = WeModDialog(pfx, name, self)
        dlg.exec()

    def _copy_prefix_path(self):
        data = self._selected_data()
        if not data:
            return
        pfx = data.get('wineprefix', '')
        if pfx:
            QApplication.clipboard().setText(pfx)
            self._show_toast("✓ Caminho do WINEPREFIX copiado!")

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
            self._show_toast(f"✓ Pasta aberta: {os.path.basename(pfx)}")

    def _open_settings(self):
        dlg = SettingsDialog(self.config, save_config, self)
        if dlg.exec():
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
            self, 'Adicionar à Lista de Prefixos',
            'Nome para o prefixo:', text=clean_name
        )
        if not ok or not name.strip():
            return
        cfg = load_config()
        custom = cfg.setdefault('custom_prefixes', [])
        for c in custom:
            if c.get('wineprefix') == pfx:
                QMessageBox.information(self, 'Info', 'Este prefixo já está na lista de prefixos.')
                return
        custom.append({'name': name.strip(), 'wineprefix': pfx})
        save_config(cfg)
        self._refresh()
        self._show_toast(f"✓ Prefixo adicionado à lista: {name.strip()}")

    def _tree_context_menu(self, pos):
        curr_tree = self.tree
        if not curr_tree:
            return
        item = curr_tree.itemAt(pos)
        if not item:
            menu = self._create_menu()
            act_add = menu.addAction('Adicionar Prefixo...')
            menu.addSeparator()
            act_refresh = menu.addAction('Atualizar Lista')
            act_show = menu.addAction('Mostrar Prefixos Ocultos')
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
            act_add_to_list = menu.addAction('➕ Adicionar este Prefixo à Lista de Prefixos')

        if pfx:
            act_open = menu.addAction('Abrir pasta do WINEPREFIX')
            act_copy = menu.addAction('Copiar caminho WINEPREFIX')
        else:
            act_open = None
            act_copy = None

        menu.addSeparator()
        act_trainer = menu.addAction('Executar Trainer (.exe)...')
        act_wemod = menu.addAction('Gerenciador WeMod...')
        act_ce = menu.addAction('Iniciar Cheat Engine')

        if has_pid:
            menu.addSeparator()
            act_kill = menu.addAction('Finalizar Processo (Kill)')
        else:
            act_kill = None

        if not is_proc_tab:
            menu.addSeparator()
            save_menu = menu.addMenu('Salvar como')
            act_backup = save_menu.addAction('Backup')
            act_standard = save_menu.addAction('Prefixo Padrão')
            act_restore = menu.addAction('Restaurar Backup')
            menu.addSeparator()
            act_hide = menu.addAction('Ocultar Prefixo')
            act_remove = menu.addAction('Remover Prefixo do Disco')
        else:
            act_backup = act_standard = act_restore = act_hide = act_remove = None

        action = menu.exec(curr_tree.viewport().mapToGlobal(pos))
        if act_add_to_list and action == act_add_to_list:
            self._save_existing_to_custom_prefixes(pfx, data.get('name', ''))
        elif act_copy and action == act_copy:
            QApplication.clipboard().setText(pfx)
            self._show_toast("✓ WINEPREFIX copiado para a área de transferência")
        elif act_open and action == act_open:
            if os.path.isdir(pfx):
                subprocess.Popen(['xdg-open', pfx])
                self._show_toast(f"✓ Pasta aberta: {os.path.basename(pfx)}")
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
                self._show_toast(f"✓ {len(killed)} processo(s) finalizado(s) no prefixo")
            else:
                self._show_toast("Nenhum processo rodando neste prefixo")
        return len(killed)

    def _add_custom_prefix(self):
        name, ok = QInputDialog.getText(
            self, 'Adicionar Prefixo Não-Steam',
            'Nome do jogo / prefixo:'
        )
        if not ok or not name.strip():
            return
        pfx = QFileDialog.getExistingDirectory(
            self, 'Selecionar WINEPREFIX (pasta que contém drive_c/)'
        )
        if not pfx:
            return
        if not os.path.isdir(os.path.join(pfx, 'drive_c')):
            QMessageBox.warning(
                self, 'Aviso',
                'A pasta selecionada não contém "drive_c".\nNão é um WINEPREFIX válido.'
            )
            return
        cfg = load_config()
        custom = cfg.setdefault('custom_prefixes', [])
        for c in custom:
            if c['wineprefix'] == pfx:
                QMessageBox.information(self, 'Info', 'Este prefixo já foi adicionado.')
                return
        custom.append({'name': name.strip(), 'wineprefix': pfx})
        save_config(cfg)
        self._refresh()
        self._show_toast(f"✓ Prefixo adicionado: {name.strip()}")

    def _show_hidden_prefixes(self):
        self._open_settings()

    def _hide_prefix(self, pfx):
        cfg = load_config()
        hidden = cfg.setdefault('hidden_prefixes', [])
        if pfx not in hidden:
            hidden.append(pfx)
        save_config(cfg)
        self._refresh()
        self._show_toast("Prefixo ocultado")

    def _remove_prefix(self, pfx, is_custom=False):
        if not os.path.isdir(pfx):
            QMessageBox.warning(self, 'Aviso', 'Prefixo não existe no disco.')
            return

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
            os.path.abspath(os.path.join(home, '.var/app/io.github.hydralauncher.hydra/config/hydralauncher/wine-prefixes')),
            os.path.abspath(os.path.join(home, '.PlayOnLinux/wineprefix')),
            os.path.abspath(os.path.join(home, 'PortProton/prefixes')),
            os.path.abspath(os.path.join(home, '.local/share/bottles/bottles')),
            os.path.abspath(os.path.join(home, '.var/app/com.usebottles.bottles/data/bottles')),
        }
        if os.path.abspath(delete_target) in critical_roots:
            QMessageBox.critical(
                self, 'Erro de Segurança',
                f'Operação cancelada: a pasta alvo ({delete_target}) é um diretório raiz ou de biblioteca do sistema.'
            )
            return

        reply = QMessageBox.question(
            self, 'Confirmar',
            f'Tem certeza que deseja apagar permanentemente a pasta do prefixo?\n{delete_target}',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._kill_prefix_processes(pfx)
        result = subprocess.run(['rm', '-rf', delete_target], capture_output=True, text=True)
        if result.returncode != 0:
            QMessageBox.critical(self, 'Erro', f'Não foi possível apagar o prefixo:\n{result.stderr}')
            return
        cfg = load_config()
        if 'custom_prefixes' in cfg:
            cfg['custom_prefixes'] = [c for c in cfg['custom_prefixes'] if c.get('wineprefix') != pfx]
            save_config(cfg)
        self._refresh()
        self._show_toast("✓ Prefixo apagado do disco")

    def _wemod_built_log_window(self, title: str):
        win = QDialog(self)
        win.setWindowTitle(title)
        win.setModal(True)
        win.setMinimumSize(700, 480)
        win.setStyleSheet(styles.GLOBAL_STYLESHEET)
        layout = QVBoxLayout(win)

        self._wemod_built_label = QLabel('Preparando…')
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

        self._wemod_built_close_btn = QPushButton('Fechar')
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
            QMessageBox.warning(self, 'Aviso', 'Pasta do prefixo não encontrada.')
            return
        default_name = os.path.basename(source)
        name, ok = QInputDialog.getText(
            self, 'Salvar Backup',
            'Nome do backup:', text=default_name,
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        dst = os.path.join(source, f'{name}.zip')
        if os.path.exists(dst):
            reply = QMessageBox.question(
                self, 'Sobrescrever',
                f'O arquivo já existe:\n{dst}\nSobrescrever?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._wemod_built_progress = self._wemod_built_log_window(f'Backup — {name}')
        self.setEnabled(False)
        self._built_msg_queue.clear()
        self._built_progress_queue.clear()
        self._built_task_done = False
        self._built_poll.start()

        def task():
            try:
                self._built_msg_queue.append(f'Salvando backup em: {dst}')
                self._built_progress_queue.append(('Compactando arquivos...', 0))
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
                            self._built_progress_queue.append((f'Compactando... ({current}/{file_count})', pct))
                if skipped:
                    self._built_msg_queue.append(f'{skipped} arquivo(s) especial(is) ignorado(s)')
                self._built_progress_queue.append(('Concluído!', 100))
                self._built_msg_queue.append(f'Backup salvo com sucesso: {dst}')
                self._built_task_ok = True
            except Exception as e:
                self._built_msg_queue.append(f'ERRO: {e}')
                self._built_task_ok = False
            self._built_task_done = True

        import threading
        threading.Thread(target=task, daemon=True).start()

    def _save_as_standard_prefix(self, pfx, is_custom=False):
        source = _resolve_prefix_root(pfx)
        if not os.path.isdir(source):
            QMessageBox.warning(self, 'Aviso', 'Pasta do prefixo não encontrada.')
            return
        default_name = os.path.basename(source)
        name, ok = QInputDialog.getText(
            self, 'Salvar como Prefixo Padrão',
            'Nome do prefixo padrão:', text=default_name,
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        dst = os.path.join(BUILT_PREFIX_DIR, f'{name}.zip')
        if os.path.exists(dst):
            reply = QMessageBox.question(
                self, 'Sobrescrever',
                f'O arquivo já existe:\n{dst}\nSobrescrever?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._wemod_built_progress = self._wemod_built_log_window(f'Prefixo Padrão — {name}')
        self.setEnabled(False)
        self._built_msg_queue.clear()
        self._built_progress_queue.clear()
        self._built_task_done = False
        self._built_poll.start()

        def task():
            try:
                self._built_msg_queue.append(f'Salvando prefixo padrão em: {dst}')
                self._built_progress_queue.append(('Compactando arquivos...', 0))
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
                            self._built_progress_queue.append((f'Compactando... ({current}/{file_count})', pct))
                if skipped:
                    self._built_msg_queue.append(f'{skipped} arquivo(s) especial(is) ignorado(s)')
                self._built_progress_queue.append(('Concluído!', 100))
                self._built_msg_queue.append(f'Prefixo padrão salvo: {dst}')
                self._built_task_ok = True
            except Exception as e:
                self._built_msg_queue.append(f'ERRO: {e}')
                self._built_task_ok = False
            self._built_task_done = True

        import threading
        threading.Thread(target=task, daemon=True).start()

    def _restore_backup(self, pfx, is_custom=False):
        source = _resolve_prefix_root(pfx)
        if not os.path.isdir(source):
            QMessageBox.warning(self, 'Aviso', 'Pasta do prefixo não encontrada.')
            return
        backups = sorted(
            f for f in os.listdir(source)
            if f.endswith('.zip') and os.path.isfile(os.path.join(source, f))
        )
        if not backups:
            QMessageBox.information(self, 'Backup', 'Nenhum backup encontrado neste prefixo.')
            return
        if len(backups) == 1:
            selected = backups[0]
        else:
            selected, ok = QInputDialog.getItem(
                self, 'Restaurar Backup',
                'Selecione o backup:', backups, 0, False,
            )
            if not ok:
                return
        backup_path = os.path.join(source, selected)
        reply = QMessageBox.question(
            self, 'Confirmar',
            f'Restaurar backup?\n{selected}\n\nOs arquivos atuais do prefixo serão substituídos.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._wemod_built_progress = self._wemod_built_log_window(f'Restaurar — {selected}')
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
                        f'{killed} processo(s) finalizado(s) antes da restauração')
                self._built_msg_queue.append(f'Restaurando backup: {selected}')
                self._built_progress_queue.append(('Removendo prefixo atual...', 10))
                if os.path.isdir(pfx):
                    shutil.rmtree(pfx)
                self._built_progress_queue.append(('Extraindo backup...', 30))
                with zipfile.ZipFile(backup_path, 'r') as zf:
                    zf.extractall(source)
                self._built_progress_queue.append(('Concluído!', 100))
                self._built_msg_queue.append('Backup restaurado com sucesso!')
                self._built_task_ok = True
            except Exception as e:
                self._built_msg_queue.append(f'ERRO: {e}')
                self._built_task_ok = False
            self._built_task_done = True

        import threading
        threading.Thread(target=task, daemon=True).start()

    def _log(self, msg):
        self.log.append(msg)


# ── entry point ────────────────────────────────────────────────────

def main():
    error_logger.setup_global_exception_handler()
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
