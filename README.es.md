# Action Shark v1.2

[English](README.md) | [Português](README.pt.md) | [Español](README.es.md)

Administrador gráfico (PyQt6) para ejecutar **trainers** (aplicaciones que modifican el comportamiento de los juegos en tiempo de ejecución, como vidas infinitas, dinero infinito, etc.) en Linux utilizando prefijos Wine/Proton. Detecta automáticamente juegos de Steam y de múltiples lanzadores, además de integrar **WeMod** por completo (descarga, instalación mediante prefijo preconfigurado, inicio y detención).

![Action Shark — interfaz validada](images/ui_real_validada.png)

> **Aviso:** Los archivos adjuntos en los releases (ej.: `GE-Proton10.1.zip`) son **prefijos Wine/Proton preconfigurados** para usar con Action Shark. **No son la aplicación en sí.** La aplicación debe clonarse o descargarse por separado desde el repositorio.

## Cómo funciona

El programa escanea el sistema en busca de:

1. **Juegos de Steam** mediante `protontricks -l` + `compatdata/`
2. **Procesos activos de Wine/Proton** leyendo `/proc/[pid]/environ` y `cmdline`
3. **Prefijos de lanzadores** leyendo archivos de configuración y carpetas conocidas
4. **Prefijos personalizados** añadidos manualmente por el usuario

Con un prefijo seleccionado, puedes ejecutar cualquier `.exe` (trainer) dentro de él con el Wine correcto. La pestaña **Trainer/CE** te permite seleccionar un prefijo y ejecutar un trainer o Cheat Engine (versión de Windows) directamente. La pestaña **WeMod** descarga, instala y administra WeMod en el prefijo deseado.

## Características

- **Detección automática** de juegos y prefijos de Steam, Lutris, Bottles, Heroic, PortProton, PlayOnLinux, Hydra
- **Ejecución de trainers** en el Wine/Proton correcto (detecta el binario de wine automáticamente)
- **Selección de prefijo**: selecciona un prefijo y un trainer para ejecutar directamente en la pestaña Trainer/CE
- **Cheat Engine integrado**: define la ruta al ejecutable de Cheat Engine (Windows) y ejecútalo en el prefijo seleccionado
- **Copia de seguridad y restauración**: guarda copias de seguridad de los prefijos y restáuralas cuando sea necesario
- **Guardar como Prefijo Estándar**: exporta un prefijo como zip en `~/.config/trainer_manager/built_prefixes/`
- **Fusión de prefijos**: instala un prefijo estándar sobre uno existente preservando tus datos
- **Ocultar prefijos**: oculta prefijos no deseados de la lista
- **Eliminar prefijos**: elimina prefijos del disco permanentemente
- **WeMod integrado**: descarga de la última versión, instalación mediante prefijo preconfigurado, inicio de sesión compartido entre prefijos, iniciar/detener
- **Menú contextual**: copiar WINEPREFIX, abrir carpeta, copia de seguridad, restaurar, guardar como estándar, ocultar, eliminar
- **Soporte multiidioma**: Inglés (predeterminado), Portugués y Español seleccionables en la configuración

## Lanzadores compatibles

| Lanzador | Detección |
|---|---|
| **Steam** | `protontricks -l` + `compatdata/<appid>/pfx` |
| **Lutris** | `~/.config/lutris/games/*.json` (campo `wine_prefix`) |
| **Bottles** | `~/.var/app/com.usebottles.bottles/data/bottles/` o `~/.local/share/bottles/` |
| **Heroic Games Launcher** | `~/.config/heroic/config.json` + `GamesConfig/*.json` (Flatpak incluido) |
| **PortProton** | `~/.var/app/ru.linux_gaming.PortProton/data/prefixes/` o `~/PortProton/prefixes/` |
| **PlayOnLinux** | `~/.PlayOnLinux/wineprefix/` |
| **Hydra** | `~/.config/hydralauncher/wine-prefixes/<appid>/` |
| **WeMod** | Descarga + instalación integrada con `.desktop` propio |
| **Personalizado (No-Steam)** | `~/.wine`, `~/Games/`, `~/wineprefixes/`, o añadidos manualmente |

## Distribuciones Linux compatibles

Funciona en **cualquier distribución Linux** con:

- **Python 3.10+**
- **PyQt6** (`python-pyqt6` en Arch, `python3-pyqt6` en Debian/Ubuntu, etc.)
- **protontricks** (para detección de Steam)
- **Wine / Proton** (para ejecutar los trainers)

Probado en: **CachyOS (Arch Linux)**.

### Dependencias (Arch Linux)

```bash
sudo pacman -S python-pyqt6 protontricks wine
```

### Dependencias (Debian/Ubuntu)

```bash
sudo apt install python3-pyqt6 protontricks wine
```

### Dependencias (Fedora)

```bash
sudo dnf install python3-qt6 protontricks wine
```

## Instalación

### Instalación Rápida (One-liner)

Ejecuta en tu terminal para descargar e instalar Action Shark automáticamente con accesos directos:

```bash
curl -fsSL https://raw.githubusercontent.com/rafaelcarpeta/Action-Shark/main/install.sh | bash
```

### Instalación Manual

```bash
# Clona el repositorio
git clone https://github.com/rafaelcarpeta/Action-Shark.git
cd Action-Shark/

# Instala las dependencias de Python
pip install -r requirements.txt

# Ejecuta directamente
python3 trainer_manager.py
```

### Instalación con accesos directos (desde la carpeta clonada)

```bash
./install.sh
```

El script `install.sh` instala el acceso directo en el menú de aplicaciones (`~/.local/share/applications/`) y opcionalmente en el escritorio, configurando automáticamente la ruta al ejecutable.

### Desinstalación

```bash
./uninstall.sh
```

Elimina los accesos directos del menú y del escritorio, con opción de borrar la carpeta de configuración y la caché.

## Estructura

```
Action Shark/
├── trainer_manager.py      # Interfaz gráfica principal (PyQt6)
├── ui_components.py        # Diálogos, banners y componentes de interfaz
├── i18n.py                 # Soporte de internacionalización (EN, PT, ES)
├── wemod_manager.py        # Gestión de WeMod (descarga, instalación, iniciar/detener)
├── wemod_built_prefix.py   # Gestión de prefijos preconfigurados (fusión, descarga, escaneo)
├── install.sh              # Script de instalación (accesos directos menú + escritorio)
├── uninstall.sh            # Script de desinstalación
├── requirements.txt        # Dependencias de Python
├── LICENSE                 # Licencia de uso (No comercial)
└── README.md
```

### Prefijos Preconfigurados (Built)

Prefijos estándar guardados como `.zip` en `~/.config/trainer_manager/built_prefixes/`. Utilizados para instalar o restaurar prefijos rápidamente sin necesidad de descargas.

## Configuración

El archivo de configuración se encuentra en `~/.config/trainer_manager/config.json`:

```json
{
  "language": "es",
  "trainers_folder": "/ruta/a/los/trainers",
  "custom_prefixes": [
    { "name": "Mi Juego", "wineprefix": "/ruta/al/prefijo" }
  ],
  "hidden_prefixes": []
}
```

## WeMod

**WeMod** es una plataforma que reúne miles de trainers para juegos de PC en un solo lugar, con una interfaz unificada y actualizaciones automáticas.

La integración utiliza un **prefijo Wine/Proton preconfigurado** (disponible en las releases del repositorio) con todas las dependencias ya instaladas (.NET 4.8, DXVK, VKD3D). Basta con descargar el prefijo e importarlo a través de Action Shark. El inicio de sesión se comparte entre prefijos mediante enlaces simbólicos.

> **Nota:** WeMod requiere una cuenta gratuita o **Pro** (de pago) para funcionar. Crea una en [wemod.com](https://www.wemod.com).

> **Nota sobre la fusión en prefijos con lanzadores secundarios (EA App, Ubisoft Connect, etc.):** Al fusionar el prefijo de WeMod en un prefijo que ya tiene lanzadores como EA App, WeMod funcionará correctamente, pero es posible que sea necesario reparar el lanzador secundario (re-ejecutar su instalador). Se recomienda hacer una copia de seguridad del prefijo antes de fusionar.

## Licencia

Este proyecto está licenciado bajo una licencia **Personalizada No Comercial** (basada en MIT).

Permitido:
- Uso personal, educativo y de investigación
- Modificación y distribución del código

Prohibido:
- Uso comercial (venta, licenciamiento, incorporación en productos comerciales, servicios remunerados)

Consulta el archivo `LICENSE` para más detalles.

## Créditos

- **Creador:** RCarpetaBR
- **OpenCode:** [opencode.ai](https://opencode.ai) — asistente de IA
- **Modelo:** DeepSeek V4 Flash Free
- **WeMod:** [wemod.com](https://www.wemod.com) — plataforma de trainers
- **wemod-launcher:** [DeckCheatz/wemod-launcher](https://github.com/DeckCheatz/wemod-launcher) — version.dll para Electron en Wine
