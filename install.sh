#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_SRC="$SCRIPT_DIR/trainer_manager.desktop"
APP_DIR="$HOME/.local/share/applications"
DESKTOP_DST="$APP_DIR/trainer_manager.desktop"
DESKTOP_FILE="$HOME/Área de Trabalho/trainer_manager.desktop"

# Fallback para nomes comuns de desktop em português/inglês
if [ ! -d "$(dirname "$DESKTOP_FILE")" ]; then
    for d in "$HOME/Desktop" "$HOME/Área de Trabalho" "$HOME/Escritorio"; do
        if [ -d "$d" ]; then
            DESKTOP_FILE="$d/trainer_manager.desktop"
            break
        fi
    done
fi

mkdir -p "$APP_DIR"

# Gera .desktop com o caminho absoluto correto
cat > "$DESKTOP_DST" <<EOF
[Desktop Entry]
Categories=Game;Utility;
Comment[pt_BR]=Gerenciador de trainers .exe em prefixes Wine/Proton
Comment=Gerenciador de trainers .exe em prefixes Wine/Proton
Exec=python3 '$SCRIPT_DIR/trainer_manager.py'
GenericName[pt_BR]=
GenericName=
Icon=applications-games
MimeType=
Name[pt_BR]=Action Shark
Name=Action Shark
Path=
StartupNotify=true
Terminal=false
TerminalOptions=
Type=Application
X-KDE-SubstituteUID=false
X-KDE-Username=
EOF

chmod 755 "$DESKTOP_DST"
echo "✓ Atalho instalado no menu de aplicações: $DESKTOP_DST"

# Atalho opcional no desktop
if [ -d "$(dirname "$DESKTOP_FILE")" ]; then
    if [ ! -f "$DESKTOP_FILE" ]; then
        cp "$DESKTOP_DST" "$DESKTOP_FILE"
        chmod 755 "$DESKTOP_FILE"
        echo "✓ Atalho criado no desktop: $DESKTOP_FILE"
    else
        echo "→ Atalho no desktop já existe, pulando."
    fi
else
    echo "→ Pasta de desktop não encontrada, pulando atalho no desktop."
fi

echo "✓ Pronto! Action Shark instalado."
