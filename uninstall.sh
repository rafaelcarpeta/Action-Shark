#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$APP_DIR/trainer_manager.desktop"
CONFIG_DIR="$HOME/.config/trainer_manager"

echo "Removendo atalho do menu de aplicações..."
if [ -f "$DESKTOP_FILE" ]; then
    rm "$DESKTOP_FILE"
    echo "  Removido: $DESKTOP_FILE"
else
    echo "  Nada a remover."
fi

# Atalhos no desktop
for d in "$HOME/Desktop" "$HOME/Área de Trabalho" "$HOME/Escritorio"; do
    f="$d/trainer_manager.desktop"
    if [ -f "$f" ]; then
        rm "$f"
        echo "  Removido: $f"
    fi
done

echo ""
echo "Deseja remover também a pasta de configuração ($CONFIG_DIR)?"
echo "Isso apagará configurações, cache do WeMod e dados de login."
read -r -p "[s/N] " resp
if [[ "$resp" =~ ^[sSyY] ]]; then
    if [ -d "$CONFIG_DIR" ]; then
        rm -rf "$CONFIG_DIR"
        echo "  Removido: $CONFIG_DIR"
    else
        echo "  Nada a remover."
    fi
fi

echo ""
echo "Pronto! Action Shark desinstalado."
