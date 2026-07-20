#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
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
)
from PyQt6.QtCore import Qt, QTimer

import wemod_manager as wm


CONFIG_PATH = os.path.expanduser('~/.config/trainer_manager/config.json')


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

MONITOR_INTERVAL_MS = 5000


class ProtonRunner(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Action Shark')
        self.setMinimumSize(800, 680)

        self.config = load_config()
        self._handled_pids = set()
        self._target_proc_name = ''
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self._monitor_tick)

        self._build_ui()
        self.log_widget.setVisible(False)
        self._refresh()
        self._refresh_trainer_list()
        QTimer.singleShot(150, self._wemod_refresh)

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh)
        self._auto_refresh_timer.start(5000)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        # ── tab 0: consolidated tree ──
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Jogo / Prefixo', 'Fonte', 'WINEPREFIX', 'AppID'])
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._on_select)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        self.tabs.addTab(self.tree, 'W/Process')

        # ── tab 1: auto monitor ──
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

        tg.addWidget(QLabel(
            'Marque os trainers que serão executados quando o processo for detectado:'
        ))

        self.trainer_list = QListWidget()
        self.trainer_list.setMinimumHeight(150)
        tg.addWidget(self.trainer_list)

        self.trainer_list.itemChanged.connect(self._update_monitor_btn)

        mon_layout.addWidget(trainers_group)

        monitor_group = QGroupBox('Monitoramento Automático')
        mg = QVBoxLayout(monitor_group)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel('Nome do processo:'))
        self.monitor_proc_name = QLineEdit()
        self.monitor_proc_name.setPlaceholderText('Ex.: game.exe, eldenring.exe, eldenring')
        self.monitor_proc_name.textChanged.connect(self._update_monitor_btn)
        name_row.addWidget(self.monitor_proc_name)
        mg.addLayout(name_row)

        ctrl_row = QHBoxLayout()
        self.monitor_btn = QPushButton('Iniciar Monitor')
        self.monitor_btn.setCheckable(True)
        self.monitor_btn.setEnabled(False)
        self.monitor_btn.toggled.connect(self._on_monitor_toggle)
        ctrl_row.addWidget(self.monitor_btn)
        self.monitor_status = QLabel('⏸  Parado')
        ctrl_row.addWidget(self.monitor_status)
        ctrl_row.addStretch()
        mg.addLayout(ctrl_row)

        mg.addWidget(QLabel('Log do monitor:'))
        self.auto_log = QTextEdit()
        self.auto_log.setReadOnly(True)
        self.auto_log.setMaximumHeight(120)
        mg.addWidget(self.auto_log)

        mon_layout.addWidget(monitor_group)
        mon_layout.addStretch()

        self.tabs.addTab(monitor_tab, 'Auto')

        self._build_wemod_tab()

        # ── exe path ──
        self.exe_row_widget = QWidget()
        exe_row = QHBoxLayout(self.exe_row_widget)
        exe_row.setContentsMargins(0, 0, 0, 0)
        exe_row.addWidget(QLabel('EXE:'))
        self.exe_path = QLineEdit()
        self.exe_path.setPlaceholderText('Caminho do .exe')
        self.exe_path.textChanged.connect(self._on_select)
        exe_row.addWidget(self.exe_path)
        browse_btn = QPushButton('Procurar…')
        browse_btn.clicked.connect(self._browse)
        exe_row.addWidget(browse_btn)
        layout.addWidget(self.exe_row_widget)

        # ── actions ──
        self.actions_widget = QWidget()
        btn_row = QHBoxLayout(self.actions_widget)
        btn_row.setContentsMargins(0, 0, 0, 0)
        add_pfx_btn = QPushButton('Adicionar Prefixo')
        add_pfx_btn.clicked.connect(self._add_custom_prefix)
        btn_row.addWidget(add_pfx_btn)

        self.run_btn = QPushButton('Executar no Prefixo')
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._run)
        btn_row.addWidget(self.run_btn)
        layout.addWidget(self.actions_widget)

        # ── log ──
        self.log_widget = QWidget()
        log_ly = QVBoxLayout(self.log_widget)
        log_ly.setContentsMargins(0, 0, 0, 0)
        log_ly.addWidget(QLabel('Log:'))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        log_ly.addWidget(self.log)
        layout.addWidget(self.log_widget)

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
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.wemod_tree.itemSelectionChanged.connect(self._wemod_selection_changed)
        self.wemod_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.wemod_tree.customContextMenuRequested.connect(self._wemod_tree_context_menu)
        layout.addWidget(self.wemod_tree)

        # action buttons
        btn_row = QHBoxLayout()
        self.wemod_install_btn = QPushButton('Instalar')
        self.wemod_install_btn.clicked.connect(self._wemod_install)
        self.wemod_install_btn.setEnabled(False)
        btn_row.addWidget(self.wemod_install_btn)

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

        # log
        layout.addWidget(QLabel('Log:'))
        self.wemod_log = QTextEdit()
        self.wemod_log.setReadOnly(True)
        layout.addWidget(self.wemod_log)

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

    def _wemod_install(self):
        pfx = self._wemod_selected_prefix()
        if not pfx:
            return
        if not wm.is_wemod_downloaded():
            try:
                wm.download_wemod()
            except Exception as e:
                QMessageBox.critical(self, 'Erro', f'Falha ao baixar WeMod.exe:\n{e}')
                return

        self.wemod_install_btn.setEnabled(False)
        self._wemod_log(f'Instalando WeMod em {pfx}...')
        self._wemod_log('')

        # dialog modal sem botão de fechar (trava closeEvent)
        class _InstallDialog(QDialog):
            def closeEvent(self, event):
                event.ignore()
        self._wemod_progress = _InstallDialog(self)
        self._wemod_progress.setWindowTitle('Instalando WeMod')
        self._wemod_progress.setModal(True)
        self._wemod_progress.setMinimumWidth(400)
        layout = QVBoxLayout(self._wemod_progress)
        self._wemod_progress_label = QLabel('Preparando…')
        self._wemod_progress_label.setWordWrap(True)
        layout.addWidget(self._wemod_progress_label)
        self._wemod_progress.show()
        QApplication.processEvents()

        # desabilita input da janela principal
        self.setEnabled(False)

        def gui_log(msg):
            QTimer.singleShot(0, lambda: self._wemod_log(msg))

        def gui_progress(stage, pct):
            def _update():
                self._wemod_progress_label.setText(stage)
                QApplication.processEvents()
            QTimer.singleShot(0, _update)

        def task():
            try:
                ok = wm.install_wemod_prefix(
                    pfx, log_callback=gui_log, progress_callback=gui_progress
                )
                if not ok:
                    gui_log('ERRO: instalacao falhou')
            except Exception as e:
                gui_log(f'ERRO: {e}')
            finally:
                QTimer.singleShot(0, self._finish_install)

        threading.Thread(target=task, daemon=True).start()

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
            self.wemod_install_btn.setEnabled(False)
            self.wemod_uninstall_btn.setEnabled(False)
            self.wemod_start_btn.setEnabled(False)
            self.wemod_stop_btn.setEnabled(False)
            return
        installed = wm.is_wemod_installed(pfx)
        running = wm.is_wemod_running(pfx)
        self.wemod_install_btn.setEnabled(not installed and not running)
        self.wemod_install_btn.setText('Instalar')
        self.wemod_uninstall_btn.setEnabled(installed and not running)
        self.wemod_start_btn.setEnabled(installed and not running)
        self.wemod_stop_btn.setEnabled(installed and running)

    def _on_tab_changed(self, idx):
        if not hasattr(self, 'exe_row_widget'):
            return
        hide = idx in (1, 2)
        self.exe_row_widget.setVisible(not hide)
        self.actions_widget.setVisible(not hide)
        self.log_widget.setVisible(False)

    # ── trainers folder ────────────────────────────────────────────

    def _refresh_trainer_list(self):
        path = self.trainers_path.text().strip()
        self.config['trainers_folder'] = path
        save_config(self.config)

        self.trainer_list.clear()
        exes = scan_trainer_exes(path)
        if not exes:
            self._auto_log('Nenhum .exe encontrado na pasta selecionada.')
            return

        for exe in exes:
            rel = os.path.relpath(exe, path) if path else exe
            item = QListWidgetItem(rel)
            item.setData(Qt.ItemDataRole.UserRole, exe)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.trainer_list.addItem(item)

        self._auto_log(f'{len(exes)} .exe(s) encontrado(s).')

    def _get_checked_trainers(self):
        checked = []
        for i in range(self.trainer_list.count()):
            item = self.trainer_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                checked.append(item.data(Qt.ItemDataRole.UserRole))
        return checked

    def _browse_trainers(self):
        path = QFileDialog.getExistingDirectory(
            self, 'Selecionar pasta de trainers',
            self.trainers_path.text() or os.path.expanduser('~'),
        )
        if path:
            self.trainers_path.setText(path)
            self._refresh_trainer_list()

    # ── monitor ────────────────────────────────────────────────────

    def _update_monitor_btn(self):
        has_name = bool(self.monitor_proc_name.text().strip())
        has_checked = bool(self._get_checked_trainers())
        self.monitor_btn.setEnabled(has_name and has_checked)
        if self.monitor_btn.isChecked() and not (has_name and has_checked):
            self.monitor_btn.setChecked(False)

    def _on_monitor_toggle(self, active):
        if active:
            proc_name = self.monitor_proc_name.text().strip()
            if not proc_name:
                self.monitor_btn.setChecked(False)
                return
            self._handled_pids.clear()
            self._target_proc_name = proc_name.lower()
            self.monitor_timer.start(MONITOR_INTERVAL_MS)
            self.monitor_btn.setText('Parar Monitor')
            self.monitor_status.setText('▶  Monitorando (a cada 5s)')
            self._auto_log(f'Monitor iniciado — alvo: "{proc_name}"')
            self._monitor_tick()
        else:
            self.monitor_timer.stop()
            self.monitor_btn.setText('Iniciar Monitor')
            self.monitor_status.setText('⏸  Parado')
            self._auto_log('Monitor parado')

    def _monitor_tick(self):
        try:
            all_procs = get_running_wine_entries()
        except Exception:
            return

        target = self._target_proc_name
        checked = self._get_checked_trainers()
        if not checked:
            return

        # skip if any checked trainer is already running (avoid duplicates)
        trainer_basenames = {os.path.basename(t).lower() for t in checked}
        already_running = False
        for p in all_procs:
            if os.path.splitext(p['name'])[0].lower() in trainer_basenames or \
               p['name'].lower() in trainer_basenames:
                already_running = True
                break

        for proc in all_procs:
            if proc['pid'] in self._handled_pids:
                continue
            if proc['is_launcher']:
                continue

            proc_lower = proc['name'].lower()
            if target not in proc_lower and proc_lower not in target:
                continue

            self._handled_pids.add(proc['pid'])

            if already_running:
                self._auto_log(
                    f'[{proc["name"]}] PID {proc["pid"]} — '
                    f'trainer já está rodando, ignorando'
                )
                continue

            pfx = proc['wineprefix']
            if not pfx and proc.get('appid'):
                pfx = _find_steam_prefix(proc['appid'])
            if not pfx:
                self._auto_log(
                    f'[{proc["name"]}] PID {proc["pid"]} — WINEPREFIX não encontrado'
                )
                continue

            wine_bin = (
                _find_wine_bin_for_pid(proc['pid'])
                or find_wine_binary(pfx)
            )
            for trainer in checked:
                logfile = run_exe_in_prefix(
                    wine_bin, trainer, pfx, pin=proc['pid']
                )
                self._auto_log(
                    f'[{proc["name"]}] PID {proc["pid"]} → '
                    f'{os.path.basename(trainer)} (log: {logfile})'
                )

    def _auto_log(self, msg):
        self.auto_log.append(msg)

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

    def _load_tree(self):
        self.tree.clear()
        for e in get_all_entries():
            item = QTreeWidgetItem([
                e['name'],
                e.get('source', ''),
                e.get('wineprefix', ''),
                str(e.get('appid', '')),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, e)
            self.tree.addTopLevelItem(item)
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
        reply = QMessageBox.question(
            self, 'Confirmar',
            f'Tem certeza que deseja apagar permanentemente o prefixo?\n{pfx}',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._kill_prefix_processes(pfx)
        import subprocess
        result = subprocess.run(['rm', '-rf', pfx], capture_output=True, text=True)
        if result.returncode != 0:
            QMessageBox.critical(self, 'Erro', f'Não foi possível apagar o prefixo:\n{result.stderr}')
            return
        if is_custom:
            cfg = load_config()
            cfg['custom_prefixes'] = [c for c in cfg.get('custom_prefixes', []) if c['wineprefix'] != pfx]
            save_config(cfg)
        self._refresh()
        self._wemod_refresh()
        self._log(f'Prefixo apagado do disco: {pfx}')

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
