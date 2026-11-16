# Action Shark v1.2

[English](README.md) | [Português](README.pt.md) | [Español](README.es.md)

Graphical manager (PyQt6) to run **trainers** (applications that modify game runtime behavior, such as infinite health, infinite currency, etc.) on Linux using Wine/Proton prefixes. Automatically detects Steam games and titles from various launchers, and provides complete **WeMod** integration (download, install via pre-configured prefix, launch, and stop).

![Action Shark — validated UI](images/ui_real_validada.png)

> **Notice:** The files attached to releases (e.g. `GE-Proton10.1.zip`) are **pre-configured Wine/Proton prefixes** designed for use with Action Shark. **They are not the application itself.** The app must be cloned or downloaded separately from the repository.

## How It Works

The program scans the system for:

1. **Steam Games** via `protontricks -l` + `compatdata/`
2. **Active Wine/Proton Processes** by reading `/proc/[pid]/environ` and `cmdline`
3. **Launcher Prefixes** by parsing configuration files and standard directory paths
4. **Custom Prefixes** added manually by the user

With a prefix selected, you can run any `.exe` (trainer) inside it using the appropriate Wine environment. The **Trainer/CE** tab allows selecting a prefix and executing a trainer or Cheat Engine (Windows version) directly. The **WeMod** tab downloads, installs, and manages WeMod within any desired prefix.

## Features

- **Automatic detection** of games and prefixes across Steam, Lutris, Bottles, Heroic, PortProton, PlayOnLinux, and Hydra
- **Run trainers** using the correct Wine/Proton setup (auto-detects the Wine binary)
- **Prefix selection**: pick a prefix and a trainer to execute directly from the Trainer/CE tab
- **Integrated Cheat Engine**: configure your Cheat Engine (Windows) executable path and launch it directly into the selected prefix
- **Backup & Restore**: create prefix backups and restore them whenever needed
- **Save as Standard Prefix**: export a prefix as a `.zip` archive to `~/.config/trainer_manager/built_prefixes/`
- **Prefix Merging**: install a standard prefix on top of an existing prefix while preserving game data
- **Hide prefixes**: hide unwanted or unneeded prefixes from the list
- **Delete prefixes**: permanently remove prefixes from disk
- **Integrated WeMod**: download the latest version, install using a pre-configured prefix, shared login across prefixes, start/stop
- **Context menu**: copy WINEPREFIX, open directory, backup, restore, save as standard, hide, remove
- **Multi-language support**: English (default), Portuguese, and Spanish selectable in Settings

## Supported Launchers

| Launcher | Detection Method |
|---|---|
| **Steam** | `protontricks -l` + `compatdata/<appid>/pfx` |
| **Lutris** | `~/.config/lutris/games/*.json` (`wine_prefix` field) |
| **Bottles** | `~/.var/app/com.usebottles.bottles/data/bottles/` or `~/.local/share/bottles/` |
| **Heroic Games Launcher** | `~/.config/heroic/config.json` + `GamesConfig/*.json` (Flatpak included) |
| **PortProton** | `~/.var/app/ru.linux_gaming.PortProton/data/prefixes/` or `~/PortProton/prefixes/` |
| **PlayOnLinux** | `~/.PlayOnLinux/wineprefix/` |
| **Hydra** | `~/.config/hydralauncher/wine-prefixes/<appid>/` |
| **WeMod** | Download + integrated installation with dedicated `.desktop` |
| **Custom (Non-Steam)** | `~/.wine`, `~/Games/`, `~/wineprefixes/`, or manually added prefixes |

## Supported Linux Distributions

Works on **any Linux distribution** with:

- **Python 3.10+**
- **PyQt6** (`python-pyqt6` on Arch, `python3-pyqt6` on Debian/Ubuntu, etc.)
- **protontricks** (for Steam detection)
- **Wine / Proton** (to execute trainers)

Tested on: **CachyOS (Arch Linux)**.

### Dependencies (Arch Linux)

```bash
sudo pacman -S python-pyqt6 protontricks wine
```

### Dependencies (Debian/Ubuntu)

```bash
sudo apt install python3-pyqt6 protontricks wine
```

### Dependencies (Fedora)

```bash
sudo dnf install python3-qt6 protontricks wine
```

## Installation

### Quick Install (One-liner)

Run in your terminal to automatically download and install Action Shark with desktop shortcuts:

```bash
curl -fsSL https://raw.githubusercontent.com/rafaelcarpeta/Action-Shark/main/install.sh | bash
```

### Manual Installation

```bash
# Clone repository
git clone https://github.com/rafaelcarpeta/Action-Shark.git
cd Action-Shark/

# Install Python dependencies
pip install -r requirements.txt

# Run directly
python3 trainer_manager.py
```

### Uninstallation

```bash
./uninstall.sh
```

Removes desktop and menu shortcuts, with an option to clean up configuration and cache directories.

## Project Structure

```
Action Shark/
├── trainer_manager.py      # Main graphical interface (PyQt6)
├── ui_components.py        # UI dialogs, banners, and components
├── i18n.py                 # Multi-language support (EN, PT, ES)
├── wemod_manager.py        # WeMod management (download, installation, start/stop)
├── wemod_built_prefix.py   # Pre-configured prefixes (merge, download, scan)
├── install.sh              # Installation script (menu + desktop shortcuts)
├── uninstall.sh            # Uninstallation script
├── requirements.txt        # Python dependencies
├── LICENSE                 # License (Non-Commercial)
└── README.md
```

### Built Prefixes

Standard prefixes saved as `.zip` archives under `~/.config/trainer_manager/built_prefixes/`. Used to install or restore prefixes rapidly without downloading.

## Configuration

Configuration is stored in `~/.config/trainer_manager/config.json`:

```json
{
  "language": "en",
  "trainers_folder": "/path/to/trainers",
  "custom_prefixes": [
    { "name": "My Game", "wineprefix": "/path/to/prefix" }
  ],
  "hidden_prefixes": []
}
```

Supported languages: `"en"` (English - default), `"pt"` (Português), `"es"` (Español).

## WeMod

**WeMod** brings thousands of trainers for PC games into a single application, featuring a unified interface and automatic updates.

The integration uses a **pre-configured Wine/Proton prefix** (available in the repository releases) with all necessary dependencies pre-installed (.NET 4.8, DXVK, VKD3D). Simply download the prefix and import it via Action Shark. User login is shared across prefixes through symlinks.

> **Note:** WeMod requires a free or **Pro** (paid) account. Create an account at [wemod.com](https://www.wemod.com).

> **Note regarding merge on prefixes with secondary launchers (EA App, Ubisoft Connect, etc.):** When merging the WeMod prefix into a prefix containing secondary launchers like EA App, WeMod will function properly, but the secondary launcher might require repair (re-running its launcher installer). It is recommended to back up the prefix prior to merging.

## License

This project is licensed under a **Custom Non-Commercial License** (based on MIT).

Allowed:
- Personal, educational, and research use
- Modification and redistribution of the source code

Prohibited:
- Commercial use (selling, licensing, embedding in commercial products, paid services)

See `LICENSE` for details.

## Credits

- **Creator:** RCarpetaBR
- **OpenCode:** [opencode.ai](https://opencode.ai) — AI assistant
- **Model:** DeepSeek V4 Flash Free
- **WeMod:** [wemod.com](https://www.wemod.com) — trainer platform
- **wemod-launcher:** [DeckCheatz/wemod-launcher](https://github.com/DeckCheatz/wemod-launcher) — version.dll for Electron on Wine
