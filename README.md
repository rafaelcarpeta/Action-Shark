# Action Shark

Gerenciador gráfico (PyQt6) para executar **trainers** (aplicativos que modificam o comportamento de jogos em tempo de execução, como vidas infinitas, dinheiro infinito, etc.) no Linux usando prefixes Wine/Proton. Detecta automaticamente jogos Steam e de vários launchers, além de integrar o **WeMod** completamente (download, instalação com .NET 4.8, launch e stop).

## Como funciona

O programa varre o sistema em busca de:

1. **Jogos Steam** via `protontricks -l` + `compatdata/`
2. **Processos Wine/Proton ativos** lendo `/proc/[pid]/environ` e `cmdline`
3. **Prefixes de launchers** lendo arquivos de configuração e pastas conhecidas
4. **Prefixes customizados** adicionados manualmente pelo usuário

Com um prefixo selecionado, você pode executar qualquer `.exe` (trainer) dentro dele com o Wine correto. A guia **Auto** permite monitorar um processo e disparar trainers automaticamente quando o jogo iniciar. A guia **WeMod** baixa, instala e gerencia o WeMod no prefixo desejado.

## Funcionalidades

- **Detecção automática** de jogos e prefixes Steam, Lutris, Bottles, Heroic, PortProton, PlayOnLinux
- **Execução de trainers** no Wine/Proton correto (detecta o binário wine automaticamente)
- **Monitor automático**: observe um processo e dispare trainers assim que ele aparecer
- **WeMod integrado**: download da versão mais recente, instalação (winetricks + .NET 4.8 + DXVK + VKD3D), login compartilhado entre prefixes, start/stop
- **Menu de contexto**: copiar WINEPREFIX, abrir pasta, remover prefixo
- **Prefixos customizados**: adicione qualquer prefixo manualmente

## Launchers suportados

| Launcher | Detecção |
|---|---|
| **Steam** | `protontricks -l` + `compatdata/<appid>/pfx` |
| **Lutris** | `~/.config/lutris/games/*.json` (campo `wine_prefix`) |
| **Bottles** | `~/.var/app/com.usebottles.bottles/data/bottles/` ou `~/.local/share/bottles/` |
| **Heroic Games Launcher** | `~/.config/heroic/config.json` + `GamesConfig/*.json` (Flatpak incluso) |
| **PortProton** | `~/.var/app/ru.linux_gaming.PortProton/data/prefixes/` ou `~/PortProton/prefixes/` |
| **PlayOnLinux** | `~/.PlayOnLinux/wineprefix/` |
| **WeMod** | Download + instalação integrada com `.desktop` próprio |
| **Custom (Não-Steam)** | `~/.wine`, `~/Games/`, `~/wineprefixes/`, ou adicionados manualmente |

## Distros Linux suportadas

Funciona em **qualquer distribuição Linux** com:

- **Python 3.10+**
- **PyQt6** (`python-pyqt6` no Arch, `python3-pyqt6` no Debian/Ubuntu, etc.)
- **protontricks** (para detecção Steam)
- **Wine / Proton** (para executar os trainers)

Testado em: **CachyOS (Arch Linux)**.

### Dependências (Arch Linux)

```bash
sudo pacman -S python-pyqt6 protontricks wine
```

### Dependências (Debian/Ubuntu)

```bash
sudo apt install python3-pyqt6 protontricks wine
```

### Dependências (Fedora)

```bash
sudo dnf install python3-qt6 protontricks wine
```

## Instalação

```bash
# Clone ou copie os arquivos
cd Linux\ Trainer\ Manager/

# Instale as dependências Python
pip install -r requirements.txt

# Execute diretamente
python3 trainer_manager.py
```

### Instalação com atalhos (recomendado)

```bash
./install.sh
```

O script `install.sh` instala o atalho no menu de aplicações (`~/.local/share/applications/`) e opcionalmente no desktop, ajustando automaticamente o caminho do executável para a pasta atual.

### Desinstalação

```bash
./uninstall.sh
```

Remove os atalhos do menu e desktop, com opção de apagar a pasta de configuração e cache.

## Estrutura

```
Action Shark/
├── trainer_manager.py      # Interface gráfica principal (PyQt6)
├── wemod_manager.py        # Gerenciamento do WeMod (download, instalação, start/stop)
├── trainer_manager.desktop # Atalho de menu (.desktop)
├── install.sh              # Script de instalação (atalhos menu + desktop)
├── uninstall.sh            # Script de desinstalação
├── requirements.txt        # Dependências Python
├── LICENSE                 # Licença de uso (Não-Comercial)
└── README.md
```

## Configuração

O config fica em `~/.config/trainer_manager/config.json`:

```json
{
  "trainers_folder": "/caminho/para/trainers",
  "custom_prefixes": [
    { "name": "Meu Jogo", "wineprefix": "/caminho/do/prefixo" }
  ],
  "hidden_prefixes": []
}
```

## WeMod

**WeMod** é uma plataforma que reúne milhares de trainers para jogos PC em um só lugar, com interface unificada e atualizações automáticas.

A integração baixa a versão estável mais recente da CDN oficial, instala as dependências necessárias (`.NET 4.8`, `DXVK`, `VKD3D`) via winetricks e gerencia o login compartilhado entre prefixes via symlinks. Requer `version.dll` (deleyload hook para Electron no Wine) — fornecido pelo [DeckCheatz/wemod-launcher](https://github.com/DeckCheatz/wemod-launcher).

> **Nota:** O WeMod requer uma conta gratuita ou **Pro** (paga) para funcionar. Crie uma em [wemod.com](https://www.wemod.com).

## Licença

Este projeto está licenciado sob uma licença **Custom Não-Comercial** (baseada no MIT).

Permitido:
- Uso pessoal, educacional e de pesquisa
- Modificação e distribuição do código

Vedado:
- Uso comercial (venda, licenciamento, incorporação em produtos comerciais, serviços remunerados)

Consulte o arquivo `LICENSE` para detalhes.

## Créditos

- **Criador:** RCarpetaBR
- **OpenCode:** [opencode.ai](https://opencode.ai) — assistente IA
- **Modelo:** DeepSeek V4 Flash Free
- **WeMod:** [wemod.com](https://www.wemod.com) — plataforma de trainers
- **wemod-launcher:** [DeckCheatz/wemod-launcher](https://github.com/DeckCheatz/wemod-launcher) — version.dll para Electron no Wine
