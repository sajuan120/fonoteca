#!/usr/bin/env bash
# Revisa si hay un release nuevo de Antra y ofrece descargarlo vía notificación.
APPIMAGE="$HOME/Applications/Antra-Linux.AppImage"
STATE="$HOME/.local/state/antra-update/version"
REPO="anandprtp/Antra"

latest=$(curl -fsS --max-time 20 "https://api.github.com/repos/$REPO/releases/latest" | jq -r .tag_name) || exit 0
[[ -z "$latest" || "$latest" == null ]] && exit 0

current=$(cat "$STATE" 2>/dev/null)
[[ "$latest" == "$current" ]] && exit 0

action=$(notify-send -a Antra -i software-update-available -A download="Descargar" -A skip="Ahora no" --wait \
  "Antra $latest disponible" "Tienes ${current:-una versión anterior}. ¿Descargar la nueva?")

if [[ "$action" == download ]]; then
  tmp=$(mktemp "$APPIMAGE.XXXXXX")
  if curl -fL --max-time 600 -o "$tmp" "https://github.com/$REPO/releases/download/$latest/Antra-Linux.AppImage"; then
    chmod +x "$tmp" && mv -f "$tmp" "$APPIMAGE" && echo "$latest" > "$STATE"
    notify-send -a Antra "Antra actualizado" "Versión $latest instalada. Reinicia la app si estaba abierta."
  else
    rm -f "$tmp"
    notify-send -a Antra -u critical "Antra: falló la descarga" "Se reintentará mañana."
  fi
fi
# Si elige "Ahora no" (o cierra la notificación), no se guarda la versión y se vuelve a avisar en el próximo chequeo.
