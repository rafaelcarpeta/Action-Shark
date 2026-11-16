#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || pwd)"
REPO_URL="https://github.com/rafaelcarpeta/Action-Shark.git"
DEFAULT_INSTALL_DIR="$HOME/.local/share/Action-Shark"

# Se executado dentro do repositório já clonado, usa o diretório atual;
# caso contrário (ex: via curl ... | bash), baixa o repositório em ~/.local/share/Action-Shark
if [ -f "$SCRIPT_DIR/trainer_manager.py" ]; then
    TARGET_DIR="$SCRIPT_DIR"
else
    TARGET_DIR="$DEFAULT_INSTALL_DIR"
    echo "→ Baixando/Atualizando Action Shark em $TARGET_DIR..."
    if [ -d "$TARGET_DIR/.git" ]; then
        git -C "$TARGET_DIR" pull --quiet
    else
        mkdir -p "$(dirname "$TARGET_DIR")"
        git clone --depth 1 "$REPO_URL" "$TARGET_DIR"
    fi
fi

APP_DIR="$HOME/.local/share/applications"
DESKTOP_DST="$APP_DIR/trainer_manager.desktop"
DESKTOP_FILE="$HOME/Área de Trabalho/trainer_manager.desktop"

# Fallback para nomes comuns de desktop em português/inglês
if [ ! -d "$(dirname "$DESKTOP_FILE")" ]; then
    for d in "$HOME/Desktop" "$HOME/Área de trabalho" "$HOME/Escritorio"; do
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
Comment=Wine/Proton prefixes .exe trainer manager
Comment[pt_BR]=Gerenciador de trainers .exe em prefixes Wine/Proton
Comment[es]=Gestor de trainers .exe en prefijos Wine/Proton
Exec=python3 "$TARGET_DIR/trainer_manager.py"
GenericName=Trainer Manager
GenericName[pt_BR]=Gerenciador de Trainers
GenericName[es]=Gestor de Trainers
Icon=$TARGET_DIR/images/action-shark.svg
MimeType=
Name[pt_BR]=Action Shark
Name=Action Shark
Path=$TARGET_DIR
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

# Instala dependências Python se requirements.txt existir e pip estiver disponível
if command -v pip3 &>/dev/null || command -v pip &>/dev/null; then
    PIP_CMD="$(command -v pip3 2>/dev/null || command -v pip 2>/dev/null)"
    if [ -f "$TARGET_DIR/requirements.txt" ]; then
        echo "→ Verificando dependências Python..."
        "$PIP_CMD" install -q -r "$TARGET_DIR/requirements.txt" 2>/dev/null || true
    fi
fi

echo "✓ Pronto! Action Shark instalado com sucesso."
