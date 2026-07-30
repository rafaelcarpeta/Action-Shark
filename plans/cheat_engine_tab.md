# Plano: Aba Cheat Engine no Action Shark

## Objetivo
Adicionar uma aba "Cheat Engine" no `trainer_manager.py` que:
- Seleciona pasta com arquivos `.CT`
- Lista cheats da table em uma UI plana (não árvore)
- Ativa/desativa cheats com toggle switches
- Entradas com valor usam default (9999, max/min)
- Usa CheatEngineLinux77 como backend para executar Lua/AA

## Arquitetura

```
trainer_manager.py
  └── cheat_engine_tab.py     ← Nova aba PyQt6
        ├── ct_parser.py      ← Parse de .CT XML
        └── ce_backend.py     ← Controle do CE via TCP
                                │
                    ┌──────────▼──────────┐
                    │ CheatEngineLinux77   │
                    │  └── autorun/        │
                    │    └── ce_control.lua│ ← Script Lua TCP server
                    └─────────────────────┘
```

## Componentes

### 1. `ct_parser.py` — Parser de .CT

Parseia XML da `.CT` → lista plana de `CheatEntry`:
- id, description, variable_type, address
- has_lua, has_aa, has_value flags
- default_value, min_value, max_value

### 2. `ce_backend.py` — Controle remoto do CE

Classe `CEController`:
- `start(ce_path)` → inicia CE com autorun script TCP
- `load_table(path)` → loadTable() via TCP
- `activate(id)`, `deactivate(id)` → toggle
- `set_value(id, val)` → escreve valor
- `get_status(id)` → {active, value}
- `stop()` → finaliza CE

Script Lua `ce_control.lua` (colocado em autorun/ do CE):
- Abre TCP server em 127.0.0.1:34567
- Aceita comandos JSON
- Executa via CE Lua API (loadTable, getAddressList, etc.)
- Retorna JSON

### 3. `cheat_engine_tab.py` — UI PyQt6

Layout:
- Seletor de pasta com .CTs
- Lista de .CT files
- Ao carregar: lista plana de cheats
- Toggle switch (QCheckBox estilizado) para ativar/desativar
- QSpinBox/QDoubleSpinBox para cheats com valor
- Status bar (CE conectado, PID do jogo)

### 4. Fluxo

1. Usuário seleciona pasta com .CTs
2. Action Shark escaneia e lista os .CT files
3. Usuário clica "Carregar"
4. ct_parser.py parseia o XML da .CT
5. UI exibe lista plana de cheats
6. ce_backend.py: inicia CE (se necessário), conecta TCP, loadTable()
7. Usuário ativa/desativa → ce_backend envia comandos
8. Entries com valor: ce_backend envia setValue()

### Tratamento de erros

- CE não instalado → mensagem
- CE não iniciou → timeout, fallback
- Conexão perdida → reconectar/reiniciar
- .CT malformada → log, pula entries inválidas
- Entry complexa → falha no toggle, mostra erro

### Dependências

- Novos arquivos: `ct_parser.py`, `ce_backend.py`, `cheat_engine_tab.py`
- Externas: CheatEngineLinux77
- Script Lua: `ce_control.lua` em autorun/
- Python: stdlib (xml.etree.ElementTree, socket, json, subprocess)
