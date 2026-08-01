#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import threading

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLineEdit,
    QLabel,
    QFileDialog,
    QTextEdit,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QGroupBox,
    QMessageBox,
    QInputDialog,
    QMenu,
    QWidget,
    QProgressBar,
    QSplitter,
    QComboBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon

import wemod_manager as wm


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
            if p and os.path.isdir(p):
                libs.append(p)
    return libs


def _find_steam_prefix(appid):
    for lib in _steam_libraries():
        pfx = os.path.join(lib, 'steamapps', 'compatdata', str(appid), 'pfx')
        if os.path.isdir(pfx):
            return pfx
    return None


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

def get_running_wine_entries():
    entries = []
    seen_prefixes = set()

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

        wineprefix = env.get('WINEPREFIX')
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

        # Heroic v1: config.json com entradas de jogos
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

        # Heroic v2+: GamesConfig/*.json
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


def _detect_hydra():
    out = []
    base = os.path.expanduser('~/.config/hydralauncher/wine-prefixes')
    if not os.path.isdir(base):
        return out
    for entry in sorted(os.listdir(base)):
        pfx = os.path.join(base, entry)
        if not os.path.isdir(os.path.join(pfx, 'drive_c')):
            continue
        out.append({
            'name': f"Hydra: {entry}",
            'wineprefix': pfx,
            'source': 'Hydra',
            'exe': '',
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


# ── custom (non-Steam) prefixes from config ─────────────────────────

def get_custom_prefixes():
    """Return list of manually added non-Steam prefixes from config."""
    cfg = load_config()
    return cfg.get('custom_prefixes', [])


# ── trainers folder scanner ────────────────────────────────────────

def scan_trainer_exes(folder_path):
    """Recursively find all .exe files under folder_path. Returns list of absolute paths."""
    if not folder_path or not os.path.isdir(folder_path):
        return []
    exes = []
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if f.lower().endswith('.exe'):
                exes.append(os.path.join(root, f))
    return exes


# ── unified source ─────────────────────────────────────────────────

def get_all_entries():
    seen = set()
    items = []
    hidden = set(load_config().get('hidden_prefixes', []))

    def _add(entry):
        key = f"{entry.get('source','')}:{entry.get('appid','')}:{entry.get('wineprefix','')}"
        if key not in seen:
            seen.add(key)
            # skip hidden auto-detected prefixes
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
            'appid': None,
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


def _setup_proton_env_for_exe(env, wine_bin):
    """Configura LD_LIBRARY_PATH e WINEDLLPATH para wine do Proton."""
    wine_real = os.path.realpath(wine_bin)
    wine_dir = os.path.dirname(wine_real)
    # Estrutura tipica: .../Proton-X/files/bin/wine
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


def run_exe_in_prefix(wine_bin, exe_path, wineprefix, pin=None, extra_env=None):
    logfile = f'/tmp/trainer_{pin or os.getpid()}.log'
    env = os.environ.copy()
    env['WINEPREFIX'] = wineprefix
    if extra_env:
        env.update(extra_env)

    # Se o wine for de um Proton, configura LD_LIBRARY_PATH e WINEDLLPATH
    if 'proton' in wine_bin.lower():
        _setup_proton_env_for_exe(env, wine_bin)

    subprocess.Popen(
        [wine_bin, exe_path],
        env=env,
        stdout=open(logfile, 'w'),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return logfile


def _find_wine_bin_for_pid(pid):
    """Walk up the process tree from PID to find the wine/wine64 binary being used."""
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
        m = re.search(r'^PPid:\s*(\d+)', status, re.M)
        if not m:
            break
        pid = int(m.group(1))
    return None


# ── UI ─────────────────────────────────────────────────────────────

class ProtonRunner(QWidget):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Action Shark v1.1')
        self.setWindowIcon(QIcon.fromTheme('applications-games'))
        self.setMinimumSize(800, 680)

        self.config = load_config()

        # fila thread-safe para comunicacao com a thread de instalacao
        self._built_msg_queue = []
        self._built_progress_queue = []
        self._built_task_done = False
        self._built_task_ok = False
        self._built_poll = QTimer(self)
        self._built_poll.timeout.connect(self._built_poll_tick)
        self._built_poll.setInterval(100)

        self._build_ui()
        self._refresh()
        self._refresh_trainer_list()
        QTimer.singleShot(150, self._wemod_refresh)

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh)
        self._auto_refresh_timer.start(5000)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.setMovable(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        # ── tab 0: consolidated tree ──
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Jogo / Prefixo', 'Fonte', 'WINEPREFIX', 'AppID'])
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 220)
        self.tree.setColumnWidth(3, 100)
        self.tree.itemSelectionChanged.connect(self._on_select)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)

        tab0_widget = QWidget()
        tab0_layout = QVBoxLayout(tab0_widget)
        tab0_layout.setContentsMargins(0, 0, 0, 0)
        tab0_layout.addWidget(self.tree)

        wine_btn_row = QHBoxLayout()
        wine_btn_row.addWidget(QLabel('EXE:'))
        self.exe_path = QLineEdit()
        self.exe_path.setPlaceholderText('Caminho do .exe')
        self.exe_path.textChanged.connect(self._on_select)
        wine_btn_row.addWidget(self.exe_path)
        browse_btn = QPushButton('Procurar…')
        browse_btn.clicked.connect(self._browse)
        wine_btn_row.addWidget(browse_btn)
        tab0_layout.addLayout(wine_btn_row)

        wine_actions_row = QHBoxLayout()
        add_pfx_btn = QPushButton('Adicionar Prefixo')
        add_pfx_btn.clicked.connect(self._add_custom_prefix)
        wine_actions_row.addWidget(add_pfx_btn)
        self.run_btn = QPushButton('Executar no Prefixo')
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._run)
        wine_actions_row.addWidget(self.run_btn)
        wine_actions_row.addStretch()
        tab0_layout.addLayout(wine_actions_row)

        self.tabs.addTab(tab0_widget, 'Wine')

        # ── tab 1: trainers + CE ──
        monitor_tab = QWidget()
        mon_layout = QVBoxLayout(monitor_tab)

        trainers_group = QGroupBox('Pasta de Trainers')
        tg = QVBoxLayout(trainers_group)

        tr_row = QHBoxLayout()
        self.trainers_path = QLineEdit()
        self.trainers_path.setText(self.config.get('trainers_folder', ''))
        self.trainers_path.setPlaceholderText('Selecione a pasta raiz com os trainers…')
        tr_row.addWidget(self.trainers_path)
        btn_tr = QPushButton('Procurar…')
        btn_tr.clicked.connect(self._browse_trainers)
        tr_row.addWidget(btn_tr)
        btn_scan = QPushButton('Buscar .exes')
        btn_scan.clicked.connect(self._refresh_trainer_list)
        tr_row.addWidget(btn_scan)
        tg.addLayout(tr_row)

        tg.addWidget(QLabel('Selecione um prefixo:'))

        self.trainer_prefix_combo = QComboBox()
        tg.addWidget(self.trainer_prefix_combo)

        tg.addWidget(QLabel('Selecione um trainer para executar:'))

        self.trainer_list = QListWidget()
        self.trainer_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        tg.addWidget(self.trainer_list)

        btn_run_trainer = QPushButton('Iniciar Trainer')
        btn_run_trainer.clicked.connect(self._run_trainer)
        tg.addWidget(btn_run_trainer)

        mon_layout.addWidget(trainers_group)

        ce_group = QGroupBox('Cheat Engine')
        cg = QVBoxLayout(ce_group)

        ce_row = QHBoxLayout()
        self.ce_path = QLineEdit()
        self.ce_path.setText(self.config.get('ce_path', ''))
        self.ce_path.setPlaceholderText('cheatengine-x86_64-SSE4-AVX2.exe')
        self.ce_path.textChanged.connect(self._on_ce_path_changed)
        ce_row.addWidget(self.ce_path, 1)
        btn_ce_browse = QPushButton('Procurar…')
        btn_ce_browse.clicked.connect(self._browse_ce)
        ce_row.addWidget(btn_ce_browse)
        cg.addLayout(ce_row)

        btn_run_ce = QPushButton('Iniciar Cheat Engine no prefixo selecionado')
        btn_run_ce.clicked.connect(self._run_ce)
        cg.addWidget(btn_run_ce)

        mon_layout.addWidget(ce_group)

        self.tabs.addTab(monitor_tab, 'Trainer/CE')

        self._build_wemod_tab()

        # hidden log (used by _log)
        self.log = QTextEdit()
        self.log.setVisible(False)

    def _build_wemod_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # download + clear cache row
        dl_row = QHBoxLayout()
        self.wemod_dl_btn = QPushButton('Baixar WeMod.exe')
        self.wemod_dl_btn.clicked.connect(self._wemod_download)
        self.wemod_dl_btn.setEnabled(not wm.is_wemod_downloaded())
        dl_row.addWidget(self.wemod_dl_btn)
        self.wemod_dl_status = QLabel(
            'OK' if wm.is_wemod_downloaded() else ''
        )
        dl_row.addWidget(self.wemod_dl_status)

        self.wemod_clear_cache_btn = QPushButton('Limpar cache')
        self.wemod_clear_cache_btn.clicked.connect(self._wemod_clear_cache)
        self.wemod_clear_cache_btn.setEnabled(os.path.isdir(wm.WEMOD_BIN_DIR))
        dl_row.addWidget(self.wemod_clear_cache_btn)

        dl_row.addStretch()
        layout.addLayout(dl_row)

        # tree with prefix entries + status + actions
        self.wemod_tree = QTreeWidget()
        self.wemod_tree.setHeaderLabels(
            ['Jogo / Prefixo', 'Fonte', 'WINEPREFIX', 'Status']
        )
        h = self.wemod_tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.wemod_tree.setColumnWidth(1, 100)
        self.wemod_tree.setColumnWidth(2, 220)
        self.wemod_tree.setColumnWidth(3, 100)
        self.wemod_tree.itemSelectionChanged.connect(self._wemod_selection_changed)
        self.wemod_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.wemod_tree.customContextMenuRequested.connect(self._wemod_tree_context_menu)

        wemod_splitter = QSplitter(Qt.Orientation.Vertical)
        wemod_splitter.addWidget(self.wemod_tree)

        # log
        log_container = QWidget()
        log_ly = QVBoxLayout(log_container)
        log_ly.setContentsMargins(0, 0, 0, 0)
        log_ly.addWidget(QLabel('Log:'))
        self.wemod_log = QTextEdit()
        self.wemod_log.setReadOnly(True)
        log_ly.addWidget(self.wemod_log)
        wemod_splitter.addWidget(log_container)

        layout.addWidget(wemod_splitter)

        # action buttons
        btn_row = QHBoxLayout()

        self.wemod_built_btn = QPushButton('Instalar Prefixo')
        self.wemod_built_btn.clicked.connect(self._wemod_install_built)
        self.wemod_built_btn.setEnabled(False)
        btn_row.addWidget(self.wemod_built_btn)

        self.wemod_uninstall_btn = QPushButton('Desinstalar')
        self.wemod_uninstall_btn.clicked.connect(self._wemod_uninstall)
        self.wemod_uninstall_btn.setEnabled(False)
        btn_row.addWidget(self.wemod_uninstall_btn)

        self.wemod_start_btn = QPushButton('Iniciar')
        self.wemod_start_btn.clicked.connect(self._wemod_start)
        self.wemod_start_btn.setEnabled(False)
        btn_row.addWidget(self.wemod_start_btn)

        self.wemod_stop_btn = QPushButton('Parar')
        self.wemod_stop_btn.clicked.connect(self._wemod_stop)
        self.wemod_stop_btn.setEnabled(False)
        btn_row.addWidget(self.wemod_stop_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.tabs.addTab(tab, 'WeMod')

    def _wemod_log(self, msg):
        self.wemod_log.append(msg)

    def _wemod_download(self):
        self.wemod_dl_btn.setEnabled(False)
        self.wemod_dl_status.setText('Baixando...')
        try:
            wm.download_wemod()
            self.wemod_dl_status.setText('OK')
            self.wemod_dl_btn.setEnabled(False)
            self._wemod_log('WeMod.exe baixado com sucesso')
        except Exception as e:
            self.wemod_dl_status.setText(f'ERRO: {e}')
            self.wemod_dl_btn.setEnabled(True)
            self._wemod_log(f'Falha no download: {e}')

    def _wemod_refresh(self):
        sel = self.wemod_tree.selectedItems()
        sel_pfx = sel[0].data(0, Qt.ItemDataRole.UserRole).get('wineprefix') if sel else None

        self.wemod_tree.clear()

        downloaded = wm.is_wemod_downloaded()
        has_cache = os.path.isdir(wm.WEMOD_BIN_DIR)
        self.wemod_dl_btn.setEnabled(not downloaded)
        self.wemod_clear_cache_btn.setEnabled(has_cache)
        if downloaded:
            self.wemod_dl_status.setText('OK')
        else:
            self.wemod_dl_status.setText('Não baixado')

        for e in get_all_entries():
            pfx = e.get('wineprefix', '')
            if not pfx:
                continue
            # WeMod tab: mostra apenas prefixes, não processos wine rodando
            if e.get('pid'):
                continue
            if not pfx or not os.path.isdir(pfx):
                st = '—'
            else:
                s = wm.get_status(pfx)
                if s == 'Rodando':
                    st = '▶ ' + s
                elif s == 'Instalado':
                    st = '● ' + s
                else:
                    st = '○ ' + s
            item = QTreeWidgetItem([
                e['name'],
                e.get('source', ''),
                pfx,
                st,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, e)
            self.wemod_tree.addTopLevelItem(item)

        if sel_pfx:
            for i in range(self.wemod_tree.topLevelItemCount()):
                item = self.wemod_tree.topLevelItem(i)
                d = item.data(0, Qt.ItemDataRole.UserRole)
                if d and d.get('wineprefix') == sel_pfx:
                    self.wemod_tree.setCurrentItem(item)
                    break

    def _wemod_selected_prefix(self):
        sel = self.wemod_tree.selectedItems()
        if not sel:
            return None
        return sel[0].data(0, Qt.ItemDataRole.UserRole).get('wineprefix', '')

    def _wemod_built_log_window(self, pfx: str):
        win = QDialog(self)
        win.setWindowTitle(f'Instalando Prefixo — {os.path.basename(pfx)}')
        win.setModal(True)
        win.setMinimumSize(750, 500)
        layout = QVBoxLayout(win)

        self._wemod_built_label = QLabel('Preparando…')
        self._wemod_built_label.setWordWrap(True)
        layout.addWidget(self._wemod_built_label)

        self._wemod_built_bar = QProgressBar()
        self._wemod_built_bar.setRange(0, 100)
        self._wemod_built_bar.setValue(0)
        self._wemod_built_bar.setTextVisible(True)
        layout.addWidget(self._wemod_built_bar)

        self._wemod_built_log = QTextEdit()
        self._wemod_built_log.setReadOnly(True)
        self._wemod_built_log.setStyleSheet(
            'QTextEdit { background: #1e1e1e; color: #d4d4d4; '
            'font-family: "JetBrains Mono", "Fira Code", "Consolas", monospace; '
            'font-size: 12px; }')
        layout.addWidget(self._wemod_built_log, stretch=1)

        self._wemod_built_close_btn = QPushButton('Fechar')
        self._wemod_built_close_btn.setVisible(False)
        self._wemod_built_close_btn.clicked.connect(self._wemod_built_close)
        layout.addWidget(self._wemod_built_close_btn,
                         alignment=Qt.AlignmentFlag.AlignRight)
        win.show()
        QApplication.processEvents()
        return win

    def _wemod_install_built(self):
        pfx = self._wemod_selected_prefix()
        if not pfx:
            return

        self.wemod_built_btn.setEnabled(False)
        self._wemod_built_progress = self._wemod_built_log_window(pfx)
        self.setEnabled(False)

        # limpa filas
        self._built_msg_queue.clear()
        self._built_progress_queue.clear()
        self._built_task_done = False
        self._built_poll.start()

        def task():
            try:
                ok = wm.install_built_prefix(
                    pfx,
                    log_callback=lambda m: self._built_msg_queue.append(m),
                    progress_callback=lambda s, p: self._built_progress_queue.append((s, p)),
                )
                if ok:
                    self._built_msg_queue.append('Configurando symlinks do WeMod...')
                    wm.install_wemod_prefix(
                        pfx,
                        log_callback=lambda m: self._built_msg_queue.append(m),
                        progress_callback=lambda s, p: self._built_progress_queue.append((s, p)),
                    )
            except Exception as e:
                self._built_msg_queue.append(f'ERRO: {e}')
                ok = False
            self._built_task_ok = ok
            self._built_task_done = True

        threading.Thread(target=task, daemon=True).start()

    def _built_poll_tick(self):
        while self._built_msg_queue and hasattr(self, '_wemod_built_log'):
            msg = self._built_msg_queue.pop(0)
            self._wemod_built_log.append(msg)
            sb = self._wemod_built_log.verticalScrollBar()
            sb.setValue(sb.maximum())

        while self._built_progress_queue and hasattr(self, '_wemod_built_label'):
            stage, pct = self._built_progress_queue.pop(0)
            self._wemod_built_label.setText(stage)
            self._wemod_built_bar.setValue(pct)

        if self._built_task_done and hasattr(self, '_wemod_built_label'):
            self._built_poll.stop()
            self._built_task_done = False
            ok = self._built_task_ok
            self.setEnabled(True)
            if ok:
                self._wemod_built_label.setText('Concluido!')
                self._wemod_built_bar.setValue(100)
            else:
                self._wemod_built_label.setText('Falhou — veja o log acima')
            self._wemod_built_close_btn.setVisible(True)
            self._wemod_refresh()
            self._refresh()

    def _wemod_built_close(self):
        self._built_poll.stop()
        if hasattr(self, '_wemod_built_progress') and self._wemod_built_progress:
            self._wemod_built_progress.done(0)
            self._wemod_built_progress.deleteLater()
        self._wemod_refresh()
        self._refresh()

    def _finish_install(self):
        self.setEnabled(True)
        if hasattr(self, '_wemod_progress') and self._wemod_progress:
            self._wemod_progress.close()
            self._wemod_progress.deleteLater()
        self._wemod_refresh()

    def _wemod_clear_cache(self):
        reply = QMessageBox.question(
            self, 'Limpar cache do WeMod',
            'Isso vai apagar o WeMod.exe baixado e forçar um novo download.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if os.path.isdir(wm.WEMOD_BIN_DIR):
            shutil.rmtree(wm.WEMOD_BIN_DIR)
        self._wemod_log('Cache do WeMod limpo')
        self._wemod_refresh()

    def _wemod_uninstall(self):
        pfx = self._wemod_selected_prefix()
        if not pfx:
            return
        reply = QMessageBox.question(
            self, 'Desinstalar WeMod',
            f'Remover WeMod do prefixo {pfx}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        wm.remove_wemod_prefix(pfx)
        self._wemod_log('WeMod desinstalado do prefixo')
        self._wemod_refresh()

    def _wemod_start(self):
        pfx = self._wemod_selected_prefix()
        if not pfx:
            return
        self._wemod_log(f'Iniciando WeMod em {pfx}...')
        pid = wm.launch_wemod(pfx)
        if pid:
            self._wemod_log(f'WeMod iniciado (PID {pid})')
        else:
            self._wemod_log('Falha ao iniciar WeMod')
        self._wemod_refresh()

    def _wemod_stop(self):
        pfx = self._wemod_selected_prefix()
        if not pfx:
            return
        self._wemod_log(f'Parando WeMod em {pfx}...')
        wm.stop_wemod(pfx)
        self._wemod_log('WeMod parado')
        self._wemod_refresh()

    def _wemod_selection_changed(self):
        pfx = self._wemod_selected_prefix()
        if not pfx:
            self.wemod_uninstall_btn.setEnabled(False)
            self.wemod_start_btn.setEnabled(False)
            self.wemod_stop_btn.setEnabled(False)
            self.wemod_built_btn.setEnabled(False)
            return
        installed = wm.is_wemod_installed(pfx)
        running = wm.is_wemod_running(pfx)
        self.wemod_built_btn.setEnabled(not installed and not running)
        self.wemod_uninstall_btn.setEnabled(installed and not running)
        self.wemod_start_btn.setEnabled(installed and not running)
        self.wemod_stop_btn.setEnabled(installed and running)

    def _on_tab_changed(self, idx):
        if not hasattr(self, 'exe_row_widget'):
            return
        hide = idx in (1, 2)
        self.exe_row_widget.setVisible(not hide)
        self.actions_widget.setVisible(not hide)

    # ── trainers folder ────────────────────────────────────────────

    def _refresh_trainer_list(self):
        path = self.trainers_path.text().strip()
        self.config['trainers_folder'] = path
        save_config(self.config)

        self.trainer_list.clear()
        exes = scan_trainer_exes(path)
        if not exes:
            self._log('Nenhum .exe encontrado na pasta selecionada.')
            return

        for exe in exes:
            rel = os.path.relpath(exe, path) if path else exe
            item = QListWidgetItem(rel)
            item.setData(Qt.ItemDataRole.UserRole, exe)
            self.trainer_list.addItem(item)

        self._log(f'{len(exes)} .exe(s) encontrado(s).')

    def _browse_trainers(self):
        path = QFileDialog.getExistingDirectory(
            self, 'Selecionar pasta de trainers',
            self.trainers_path.text() or os.path.expanduser('~'),
        )
        if path:
            self.trainers_path.setText(path)
            self._refresh_trainer_list()

    def _run_trainer(self):
        items = self.trainer_list.selectedItems()
        if not items:
            QMessageBox.information(self, 'Aviso', 'Selecione um trainer na lista.')
            return
        exe = items[0].data(Qt.ItemDataRole.UserRole)

        idx = self.trainer_prefix_combo.currentIndex()
        if idx < 0:
            QMessageBox.information(self, 'Aviso', 'Selecione um prefixo na lista.')
            return
        data = self.trainer_prefix_combo.itemData(idx)
        pfx = data.get('wineprefix', '')
        if not pfx:
            QMessageBox.warning(self, 'Aviso', 'WINEPREFIX não encontrado.')
            return

        pid = data.get('pid')
        wine_bin = (
            _find_wine_bin_for_pid(pid)
            or find_wine_binary(pfx)
        ) if pid else find_wine_binary(pfx)

        self._log(f'Trainer:  {os.path.basename(exe)}')
        self._log(f'Prefix:   {pfx}')
        self._log(f'Wine:     {wine_bin}')

        logfile = run_exe_in_prefix(wine_bin, exe, pfx)
        self._log(f'OK — trainer enviado para execução (log: {logfile})')

    # ── cheat engine ──────────────────────────────────────────────

    def _on_ce_path_changed(self, text):
        self.config['ce_path'] = text
        save_config(self.config)

    def _browse_ce(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Selecionar executável do Cheat Engine',
            os.path.dirname(self.ce_path.text()) or os.path.expanduser('~'),
            'Executáveis (*.exe);;Todos os arquivos (*)',
        )
        if path:
            self.ce_path.setText(path)

    def _run_ce(self):
        idx = self.trainer_prefix_combo.currentIndex()
        if idx < 0:
            QMessageBox.information(self, 'Aviso', 'Selecione um prefixo na lista.')
            return
        data = self.trainer_prefix_combo.itemData(idx)
        pfx = data.get('wineprefix', '')
        if not pfx:
            QMessageBox.warning(self, 'Aviso', 'WINEPREFIX não encontrado.')
            return

        ce_exe = self.ce_path.text().strip()
        if not ce_exe:
            QMessageBox.information(
                self, 'Aviso', 'Configure o caminho do executável do Cheat Engine.')
            return
        if not os.path.isfile(ce_exe):
            QMessageBox.warning(
                self, 'Aviso', 'Executável do Cheat Engine não encontrado.')
            return

        pid = data.get('pid')
        wine_bin = (
            _find_wine_bin_for_pid(pid)
            or find_wine_binary(pfx)
        ) if pid else find_wine_binary(pfx)

        self._log(f'CE:       {os.path.basename(ce_exe)}')
        self._log(f'Prefix:   {pfx}')
        self._log(f'Wine:     {wine_bin}')

        logfile = run_exe_in_prefix(wine_bin, ce_exe, pfx)
        self._log(f'OK — Cheat Engine enviado para execução (log: {logfile})')

    # ── data loading ───────────────────────────────────────────────

    def _refresh(self):
        self.log.clear()
        self._log('Detectando jogos, processos e prefixos…')
        self._load_tree()
        self._log('OK')

    def _auto_refresh(self):
        sel = self.tree.selectedItems()
        sel_pfx = sel[0].data(0, Qt.ItemDataRole.UserRole).get('wineprefix') if sel else None
        self._load_tree()
        if sel_pfx:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                d = item.data(0, Qt.ItemDataRole.UserRole)
                if d and d.get('wineprefix') == sel_pfx:
                    self.tree.setCurrentItem(item)
                    break
        self._wemod_refresh()

    def _load_tree(self):
        self.tree.clear()
        self.trainer_prefix_combo.clear()
        for e in get_all_entries():
            item = QTreeWidgetItem([
                e['name'],
                e.get('source', ''),
                e.get('wineprefix', ''),
                str(e.get('appid', '')),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, e)
            self.tree.addTopLevelItem(item)
            if e.get('wineprefix'):
                self.trainer_prefix_combo.addItem(
                    f"{e['name']} ({os.path.basename(e['wineprefix'])})",
                    e,
                )
        self._log(f'{self.tree.topLevelItemCount()} entradas')

    # ── selection ──────────────────────────────────────────────────

    def _selected_data(self):
        if self.tabs.currentIndex() == 0:
            sel = self.tree.selectedItems()
            return sel[0].data(0, Qt.ItemDataRole.UserRole) if sel else None
        return None

    def _on_select(self):
        data = self._selected_data()
        has_exe = bool(self.exe_path.text().strip())
        has_prefix = bool(data) and bool(data.get('wineprefix'))
        self.run_btn.setEnabled(bool(data) and has_exe and has_prefix)

        if data and not data.get('wineprefix'):
            self._log('⚠  Entrada selecionada não tem WINEPREFIX — selecione outra.')

    # ── kill prefix processes ──────────────────────────────────────

    def _kill_prefix_processes(self, wineprefix):
        wineprefix_bytes = f'WINEPREFIX={wineprefix}\0'.encode('utf-8')
        killed = []
        for entry in os.listdir('/proc'):
            if not entry.isdigit():
                continue
            env_raw = _read_file_safe(f'/proc/{entry}/environ', 'rb')
            if not env_raw:
                continue
            if wineprefix_bytes not in env_raw:
                continue
            try:
                os.kill(int(entry), 9)
                killed.append(int(entry))
            except (OSError, PermissionError):
                pass
        if killed:
            self._log(f'{len(killed)} processo(s) finalizado(s) no prefixo')
        else:
            self._log('Nenhum processo rodando neste prefixo')
        # NOTA: nao mata wineserver para evitar derrubar outros processos
        # (ex.: jogo) que estejam rodando no mesmo prefixo

    # ── context menus ─────────────────────────────────────────────

    def _tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            menu = QMenu(self)
            act_show = menu.addAction('Mostrar Ocultos')
            action = menu.exec(self.tree.viewport().mapToGlobal(pos))
            if action == act_show:
                self._show_hidden_prefixes()
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        pfx = data.get('wineprefix', '')
        if not pfx:
            return
        has_pid = bool(data.get('pid'))
        menu = QMenu(self)
        act_copy = menu.addAction('Copiar WINEPREFIX')
        act_open = menu.addAction('Abrir pasta do WINEPREFIX')
        if has_pid:
            act_kill = menu.addAction('Matar Processo')
        menu.addSeparator()
        save_menu = menu.addMenu('Salvar como')
        act_backup = save_menu.addAction('Backup')
        act_standard = save_menu.addAction('Prefixo Padrão')
        act_restore = menu.addAction('Restaurar Backup')
        menu.addSeparator()
        act_hide = menu.addAction('Ocultar Prefixo')
        act_remove = menu.addAction('Remover Prefixo')
        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action == act_copy:
            QApplication.clipboard().setText(pfx)
            self._log(f'WINEPREFIX copiado: {pfx}')
        elif action == act_open:
            if os.path.isdir(pfx):
                subprocess.Popen(['xdg-open', pfx])
        elif has_pid and action == act_kill:
            self._kill_prefix_processes(pfx)
            self._refresh()
        elif action == act_backup:
            self._backup_prefix(pfx, data.get('source') == 'Não-Steam')
        elif action == act_standard:
            self._save_as_standard_prefix(pfx, data.get('source') == 'Não-Steam')
        elif action == act_restore:
            self._restore_backup(pfx, data.get('source') == 'Não-Steam')
        elif action == act_hide:
            self._hide_prefix(pfx)
        elif action == act_remove:
            self._remove_prefix(pfx, data.get('source') == 'Não-Steam')

    def _wemod_tree_context_menu(self, pos):
        item = self.wemod_tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        pfx = data.get('wineprefix', '')
        if not pfx:
            return
        menu = QMenu(self)
        act_copy = menu.addAction('Copiar WINEPREFIX')
        act_open = menu.addAction('Abrir pasta do WINEPREFIX')
        action = menu.exec(self.wemod_tree.viewport().mapToGlobal(pos))
        if action == act_copy:
            QApplication.clipboard().setText(pfx)
            self._wemod_log(f'WINEPREFIX copiado: {pfx}')
        elif action == act_open:
            if os.path.isdir(pfx):
                subprocess.Popen(['xdg-open', pfx])

    # ── actions ────────────────────────────────────────────────────

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Selecionar EXE',
            os.path.expanduser('~'),
            'Executáveis (*.exe);;Todos os arquivos (*)',
        )
        if path:
            self.exe_path.setText(path)

    def _run(self):
        data = self._selected_data()
        if not data:
            return
        exe = self.exe_path.text().strip()
        if not exe:
            return
        pfx = data.get('wineprefix', '')
        if not pfx:
            self._log('ERRO: WINEPREFIX não encontrado')
            return

        self.run_btn.setEnabled(False)
        self.log.clear()

        self._log(f'Jogo:    {data.get("name", "?")}')
        self._log(f'Fonte:   {data.get("source", "?")}')
        self._log(f'Prefix:  {pfx}')

        pid = data.get('pid')
        wine_bin = (
            _find_wine_bin_for_pid(pid)
            or find_wine_binary(pfx)
        ) if pid else find_wine_binary(pfx)
        self._log(f'Wine:    {wine_bin}')
        self._log(f'EXE:     {exe}')

        logfile = run_exe_in_prefix(wine_bin, exe, pfx)
        self._log(f'OK — trainer enviado para execução (log: {logfile})')

        self.run_btn.setEnabled(True)

    # ── custom prefix management ─────────────────────────────────

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
                'A pasta selecionada não contém "drive_c".\n'
                'Não é um WINEPREFIX válido.'
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
        self._wemod_refresh()
        self._log(f'Prefixo Não-Steam adicionado: {name.strip()} → {pfx}')

    def _show_hidden_prefixes(self):
        cfg = load_config()
        hidden = cfg.get('hidden_prefixes', [])
        if not hidden:
            QMessageBox.information(self, 'Ocultos', 'Nenhum prefixo oculto.')
            return

        dialog = QDialog(self)
        dialog.setWindowTitle('Prefixos Ocultos')
        dialog.setMinimumSize(500, 350)
        layout = QVBoxLayout(dialog)

        label = QLabel(
            f'{len(hidden)} prefixo(s) oculto(s). '
            'Marque os que deseja restaurar e clique em "Restaurar":'
        )
        layout.addWidget(label)

        list_widget = QListWidget()
        for pfx in hidden:
            item = QListWidgetItem(pfx)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, pfx)
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        btn_row = QHBoxLayout()
        btn_restore = QPushButton('Restaurar Selecionados')
        btn_close = QPushButton('Fechar')
        btn_row.addWidget(btn_restore)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        def restore():
            to_restore = []
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    to_restore.append(item.data(Qt.ItemDataRole.UserRole))
            if not to_restore:
                QMessageBox.information(dialog, 'Info', 'Nenhum item selecionado.')
                return
            cfg = load_config()
            cfg['hidden_prefixes'] = [
                h for h in cfg.get('hidden_prefixes', [])
                if h not in to_restore
            ]
            save_config(cfg)
            self._refresh()
            self._wemod_refresh()
            self._log(f'{len(to_restore)} prefixo(s) restaurado(s) da lista de ocultos')
            dialog.accept()

        btn_restore.clicked.connect(restore)
        btn_close.clicked.connect(dialog.reject)
        dialog.exec()

    def _hide_prefix(self, pfx):
        cfg = load_config()
        hidden = cfg.setdefault('hidden_prefixes', [])
        if pfx not in hidden:
            hidden.append(pfx)
        save_config(cfg)
        self._refresh()
        self._wemod_refresh()
        self._log(f'Prefixo ocultado: {pfx}')

    def _remove_prefix(self, pfx, is_custom=False):
        if not os.path.isdir(pfx):
            QMessageBox.warning(self, 'Aviso', 'Prefixo não existe no disco.')
            return
        delete_target = os.path.dirname(pfx) if not is_custom else pfx
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
        if is_custom:
            cfg = load_config()
            cfg['custom_prefixes'] = [c for c in cfg.get('custom_prefixes', []) if c['wineprefix'] != pfx]
            save_config(cfg)
        self._refresh()
        self._wemod_refresh()
        self._log(f'Prefixo apagado do disco: {delete_target}')

    def _backup_prefix(self, pfx, is_custom=False):
        source = os.path.dirname(pfx) if not is_custom else pfx
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

        self._wemod_built_progress = self._wemod_built_log_window(
            f'Backup — {name}')
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
                file_count = sum(
                    len(f) for _, _, f in os.walk(source, followlinks=False))
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
                            self._built_progress_queue.append(
                                (f'Compactando... ({current}/{file_count})', pct))
                if skipped:
                    self._built_msg_queue.append(
                        f'{skipped} arquivo(s) especial(is) ignorado(s)')
                self._built_progress_queue.append(('Concluido!', 100))
                self._built_msg_queue.append(f'Backup salvo: {dst}')
                self._built_task_ok = True
            except Exception as e:
                self._built_msg_queue.append(f'ERRO: {e}')
                self._built_task_ok = False
            self._built_task_done = True

        threading.Thread(target=task, daemon=True).start()

    def _save_as_standard_prefix(self, pfx, is_custom=False):
        source = os.path.dirname(pfx) if not is_custom else pfx
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

        self._wemod_built_progress = self._wemod_built_log_window(
            f'Prefixo Padrao — {name}')
        self.setEnabled(False)
        self._built_msg_queue.clear()
        self._built_progress_queue.clear()
        self._built_task_done = False
        self._built_poll.start()

        def task():
            try:
                self._built_msg_queue.append(
                    f'Salvando prefixo padrao em: {dst}')
                self._built_progress_queue.append(('Compactando arquivos...', 0))
                os.makedirs(BUILT_PREFIX_DIR, exist_ok=True)
                skipped = 0
                file_count = sum(
                    len(f) for _, _, f in os.walk(source, followlinks=False))
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
                            self._built_progress_queue.append(
                                (f'Compactando... ({current}/{file_count})', pct))
                if skipped:
                    self._built_msg_queue.append(
                        f'{skipped} arquivo(s) especial(is) ignorado(s)')
                self._built_progress_queue.append(('Concluido!', 100))
                self._built_msg_queue.append(f'Prefixo padrao salvo: {dst}')
                self._built_task_ok = True
            except Exception as e:
                self._built_msg_queue.append(f'ERRO: {e}')
                self._built_task_ok = False
            self._built_task_done = True

        threading.Thread(target=task, daemon=True).start()

    def _restore_backup(self, pfx, is_custom=False):
        source = os.path.dirname(pfx) if not is_custom else pfx
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
            f'Restaurar backup?\n{selected}\n\n'
            'Os arquivos atuais do prefixo serao substituidos.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._wemod_built_progress = self._wemod_built_log_window(
            f'Restaurar — {selected}')
        self.setEnabled(False)
        self._built_msg_queue.clear()
        self._built_progress_queue.clear()
        self._built_task_done = False
        self._built_poll.start()

        def task():
            try:
                self._kill_prefix_processes(pfx)
                self._built_msg_queue.append(f'Restaurando backup: {selected}')
                self._built_progress_queue.append(('Removendo prefixo atual...', 10))
                if os.path.isdir(pfx):
                    shutil.rmtree(pfx)
                self._built_progress_queue.append(('Extraindo backup...', 30))
                with zipfile.ZipFile(backup_path, 'r') as zf:
                    zf.extractall(source)
                self._built_progress_queue.append(('Concluido!', 100))
                self._built_msg_queue.append('Backup restaurado com sucesso!')
                self._built_task_ok = True
            except Exception as e:
                self._built_msg_queue.append(f'ERRO: {e}')
                self._built_task_ok = False
            self._built_task_done = True

        threading.Thread(target=task, daemon=True).start()

    def _log(self, msg):
        self.log.append(msg)


# ── entry point ────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    win = ProtonRunner()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
