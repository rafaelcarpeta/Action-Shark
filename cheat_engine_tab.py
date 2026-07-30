import os
import threading
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QTextEdit,
    QWidget,
    QScrollArea,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QGroupBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer

from ct_parser import parse_ct, scan_ct_folder
from ce_backend import CEController, find_game_process


_STYLE_CHEAT_ITEM = """
QCheckBox { spacing: 8px; font-size: 13px; }
QCheckBox::indicator { width: 18px; height: 18px; }
"""


def _trunc(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[:n - 3] + '...'


class CheatEngineTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ce = CEController()
        self._entries = []
        self._entry_widgets = {}  # id -> (checkbox, spinbox)
        self._ct_folder = ''
        self._ct_files = []
        self._current_ct = ''
        self._process_pid = None

        self._build_ui()
        self._update_ct_list()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ── Folder selection ──
        folder_row = QHBoxLayout()
        self._folder_label = QLabel('CE Tables:')
        self._folder_path = QLabel('(nenhuma pasta selecionada)')
        self._folder_path.setStyleSheet('color: gray;')
        self._browse_btn = QPushButton('Selecionar Pasta…')
        self._browse_btn.clicked.connect(self._on_browse_folder)
        folder_row.addWidget(self._folder_label)
        folder_row.addWidget(self._folder_path, 1)
        folder_row.addWidget(self._browse_btn)

        # ── CT files list ──
        self._ct_list = QTextEdit()
        self._ct_list.setReadOnly(True)
        self._ct_list.setMaximumHeight(100)
        self._ct_list.setPlaceholderText('Arquivos .CT encontrados...')

        ct_row = QHBoxLayout()
        self._load_btn = QPushButton('Carregar .CT')
        self._load_btn.clicked.connect(self._on_load_ct)
        self._load_btn.setEnabled(False)
        self._reload_btn = QPushButton('Recarregar')
        self._reload_btn.clicked.connect(self._update_ct_list)
        ct_row.addWidget(self._load_btn)
        ct_row.addWidget(self._reload_btn)
        ct_row.addStretch()

        # ── Process connection ──
        proc_row = QHBoxLayout()
        self._proc_status = QLabel('Processo: desconectado')
        self._proc_status.setStyleSheet('color: gray;')
        self._connect_btn = QPushButton('Conectar ao Processo')
        self._connect_btn.clicked.connect(self._on_connect_process)
        self._disconnect_btn = QPushButton('Desconectar')
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        self._disconnect_btn.setEnabled(False)
        proc_row.addWidget(self._proc_status, 1)
        proc_row.addWidget(self._connect_btn)
        proc_row.addWidget(self._disconnect_btn)

        # ── Status bar ──
        self._status_label = QLabel('Pronto')
        self._status_label.setStyleSheet('color: gray; font-size: 11px;')

        # ── Cheat list (scrollable) ──
        self._cheat_container = QWidget()
        self._cheat_layout = QVBoxLayout(self._cheat_container)
        self._cheat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._cheat_container.setVisible(False)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._cheat_container)

        # ── Log ──
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setPlaceholderText('Log...')

        # ── Assemble ──
        layout.addLayout(folder_row)
        layout.addWidget(self._ct_list)
        layout.addLayout(ct_row)
        layout.addLayout(proc_row)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._status_label)
        layout.addWidget(self._log)

    # ── Actions ──

    def _log_msg(self, msg: str):
        self._log.append(f'[{time.strftime("%H:%M")}] {msg}')

    def _on_browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Selecionar pasta com .CT')
        if folder:
            self._ct_folder = folder
            self._folder_path.setText(folder)
            self._folder_path.setStyleSheet('')
            self._update_ct_list()

    def _update_ct_list(self):
        if not self._ct_folder or not os.path.isdir(self._ct_folder):
            return
        files = scan_ct_folder(self._ct_folder)
        self._ct_files = files
        if files:
            names = '\n'.join(os.path.basename(f) for f in files[:20])
            if len(files) > 20:
                names += f'\n... e mais {len(files) - 20} arquivo(s)'
            self._ct_list.setText(names)
            self._load_btn.setEnabled(True)
            self._log_msg(f'{len(files)} arquivo(s) .CT encontrado(s)')
        else:
            self._ct_list.setText('(nenhum arquivo .CT encontrado)')
            self._load_btn.setEnabled(False)
            self._log_msg('Nenhum .CT na pasta')

    def _on_load_ct(self):
        if not self._ct_files:
            return
        if len(self._ct_files) == 1:
            path = self._ct_files[0]
        else:
            from PyQt6.QtWidgets import QInputDialog, QDialog
            items = [os.path.basename(f) for f in self._ct_files]
            item, ok = QInputDialog.getItem(self, 'Selecionar .CT', 'Arquivo:', items, 0, False)
            if not ok or not item:
                return
            idx = items.index(item)
            path = self._ct_files[idx]

        self._current_ct = path
        self._log_msg(f'Carregando: {os.path.basename(path)}')
        try:
            entries = parse_ct(path)
            self._entries = entries
            self._build_cheat_list(entries)
            self._status_label.setText(f'Carregado: {os.path.basename(path)} — {len(entries)} entries')
            self._log_msg(f'{len(entries)} entries carregadas')
        except Exception as e:
            self._log_msg(f'Erro ao carregar .CT: {e}')
            QMessageBox.warning(self, 'Erro', f'Falha ao carregar .CT:\n{e}')

    def _build_cheat_list(self, entries):
        for i in reversed(range(self._cheat_layout.count())):
            w = self._cheat_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        self._entry_widgets.clear()

        if not entries:
            lbl = QLabel('(nenhum cheat encontrado)')
            lbl.setStyleSheet('color: gray; padding: 20px;')
            self._cheat_layout.addWidget(lbl)
            self._cheat_container.setVisible(True)
            return

        for entry in entries:
            if entry.is_group:
                gb = QGroupBox(entry.description or '(grupo)')
                gl = QVBoxLayout(gb)
                if entry.children:
                    for child in entry.children:
                        self._add_entry_widget(gl, child)
                self._cheat_layout.addWidget(gb)
            else:
                self._add_entry_widget(self._cheat_layout, entry)

        self._cheat_container.setVisible(True)

    def _add_entry_widget(self, parent_layout, entry):
        row = QHBoxLayout()
        row.setContentsMargins(4, 1, 4, 1)

        cb = QCheckBox(_trunc(entry.description or '(sem nome)', 50))
        cb.setStyleSheet(_STYLE_CHEAT_ITEM)
        cb.stateChanged.connect(lambda state, e=entry: self._on_toggle(e, state))

        if not self._ce.connected:
            cb.setEnabled(False)
            cb.setToolTip('Conecte a um processo primeiro')

        if entry.has_aa or entry.has_lua:
            cb.setEnabled(False)
            cb.setToolTip('Requer Cheat Engine para ativar (AA/Lua script)')
            lbl = QLabel('[AA/Lua]')
            lbl.setStyleSheet('color: orange; font-size: 10px;')
            row.addWidget(cb, 1)
            row.addWidget(lbl)
            self._entry_widgets[entry.id] = (cb, None)
        elif entry.has_value and entry.variable_type.lower() in ('float', 'double'):
            spin = QDoubleSpinBox()
            if entry.max_value is not None:
                spin.setRange(entry.min_value or 0, entry.max_value)
            else:
                spin.setRange(-999999, 999999)
            spin.setDecimals(1)
            spin.setValue(entry.default_value or 1.0)
            spin.setFixedWidth(100)
            row.addWidget(cb, 1)
            row.addWidget(spin)
            self._entry_widgets[entry.id] = (cb, spin)
        elif entry.has_value:
            spin = QSpinBox()
            if entry.max_value is not None:
                spin.setRange(entry.min_value or 0, int(entry.max_value))
            else:
                spin.setRange(0, 99999999)
            spin.setValue(int(entry.default_value or 9999))
            spin.setFixedWidth(100)
            row.addWidget(cb, 1)
            row.addWidget(spin)
            self._entry_widgets[entry.id] = (cb, spin)
        else:
            cb.setEnabled(False)
            cb.setToolTip('Apenas exibição')
            row.addWidget(cb, 1)
            self._entry_widgets[entry.id] = (cb, None)

        container = QWidget()
        container.setLayout(row)
        parent_layout.addWidget(container)

    def _on_toggle(self, entry, state):
        active = bool(state)
        if not self._ce.connected:
            cb, _ = self._entry_widgets.get(entry.id, (None, None))
            if cb:
                cb.setChecked(False)
            self._log_msg('Conecte a um processo primeiro')
            return

        addr = self._ce.resolve_address(entry.address)
        if addr is None:
            cb, _ = self._entry_widgets.get(entry.id, (None, None))
            if cb:
                cb.setChecked(False)
            self._log_msg(f'Não foi possível resolver endereço: {entry.address}')
            return

        if active and entry.has_value:
            val = entry.default_value or 9999
            if entry.id in self._entry_widgets:
                _, spin = self._entry_widgets[entry.id]
                val = spin.value()
            ok = self._ce.write_value(addr, entry.variable_type, val)
            if ok:
                self._log_msg(f'Ativado: {entry.description} = {val}')
            else:
                self._log_msg(f'Falha ao escrever: {entry.description}')
                cb, _ = self._entry_widgets.get(entry.id, (None, None))
                if cb:
                    cb.setChecked(False)
        elif not active:
            self._log_msg(f'Desativado: {entry.description}')

    def _refresh_toggle_states(self):
        connected = self._ce.connected
        for entry_id, (cb, _) in self._entry_widgets.items():
            entry = next((e for e in self._entries if e.id == entry_id), None)
            if entry and (entry.has_aa or entry.has_lua):
                cb.setEnabled(False)
                cb.setToolTip('Requer Cheat Engine para ativar (AA/Lua script)')
            elif entry:
                cb.setEnabled(connected)
                cb.setToolTip('' if connected else 'Conecte a um processo primeiro')

    def _on_connect_process(self):
        pid = find_game_process('')
        if pid is None:
            from PyQt6.QtWidgets import QInputDialog
            pid_str, ok = QInputDialog.getText(self, 'Conectar ao Processo',
                                               'PID do processo:')
            if not ok or not pid_str:
                return
            try:
                pid = int(pid_str)
            except ValueError:
                self._log_msg('PID inválido')
                return

        if self._ce.open_process(pid):
            self._process_pid = pid
            self._proc_status.setText(f'Processo: PID {pid}')
            self._proc_status.setStyleSheet('color: green;')
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(True)
            self._log_msg(f'Conectado ao PID {pid}')
            self._refresh_toggle_states()
        else:
            self._log_msg(f'Falha ao conectar ao PID {pid}')
            QMessageBox.warning(self, 'Erro', f'Não foi possível abrir o processo PID {pid}')

    def _on_disconnect(self):
        self._ce.close()
        self._process_pid = None
        self._proc_status.setText('Processo: desconectado')
        self._proc_status.setStyleSheet('color: gray;')
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._log_msg('Desconectado')
        self._refresh_toggle_states()
