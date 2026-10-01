#!/usr/bin/env bash
# Avisa cuando Antra termina una descarga (Antra agrega una entrada a history.json al acabar cada una)
# y ofrece abrir la simulación de procesar_descarga.py. El --execute sigue siendo manual.
# Canción suelta o disco (enlace de canción/álbum): Antra no crea "<título>/" sino "<artistas>/<año> - <álbum>/…";
# juntar_descarga.py las reúne en "<título>/" (con Antra cerrado) y se procesan igual. Lo que Antra no pudo bajar
# queda anotado en pendientes (revisar_fallidas.tsv).
# OJO: este archivo NO puede tener "antra" en el nombre: procesar_descarga.py creería que Antra está abierto.
HISTORY="${HISTORY:-$HOME/.local/share/Antra/history.json}"
STATE="${STATE:-$HOME/.local/state/musica-descarga/ultimo}"
# carpeta de las herramientas: MUSIC_TOOLS, o la del repositorio (scripts/../fonoteca), o ~/music-tools
_repo="$(cd "$(dirname "$0")/../fonoteca" 2>/dev/null && pwd)"
TOOLS="${MUSIC_TOOLS:-${_repo:-$HOME/music-tools}}"
MUSIC="${MUSIC:-$(cd "$TOOLS" && python3 -c 'from comun import ROOT; print(ROOT)')}"   # la biblioteca (config.toml)

read -r date title total ok failed skipped url < <(jq -r '.[0] | [.date, (.title|@base64), .total, .downloaded, .failed, .skipped, (.url // "-")] | @tsv' "$HISTORY") || exit 0
[[ -z "$date" || "$date" == "$(cat "$STATE" 2>/dev/null)" ]] && exit 0
echo "$date" > "$STATE"   # un aviso por descarga, aunque elija "Ahora no"
title=$(base64 -d <<<"$title")
[[ "$url" == "-" ]] && url=""

nl=$'\n'
body="$ok bajadas · $failed fallidas · $skipped ya estaban (de $total)"
carpeta="${title//\//_}"
juntar=0
playlist=0   # sin enlace en el historial se asume playlist, como antes
[[ -z "$url" || "$url" == *"/playlist/"* || "$url" == *"/collection/"* ]] && playlist=1
if [[ "$playlist" == 0 || ! -d "$MUSIC/$carpeta" ]]; then
  juntar=1   # canción suelta o disco: no hay carpeta de playlist
  [[ -e "$MUSIC/$carpeta" ]] && carpeta="$carpeta (descarga)"   # no usar la carpeta de un artista con el mismo nombre
  if [[ "$ok" == 0 ]]; then   # no bajó nada: si falló, a pendientes; si ya estaba, nada que hacer
    if [[ "$failed" != 0 && -n "$url" ]]; then
      python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from comun import anotar_fallida; anotar_fallida(*sys.argv[2:])' \
        "$TOOLS" "Antra $(date +%F)" "" "(Antra no pudo bajarla)" "$title" "$url"
      body="$body${nl}No se pudo bajar: quedó anotada en pendientes."
    fi
    notify-send -a "Música" -i folder-music -t 0 "Antra terminó: $title" "$body"
    exit 0
  fi
fi

if [[ "$juntar" == 1 ]]; then
  msg="Canción suelta: al procesar se junta en «$carpeta». Cierra Antra y procesa."
else
  msg="Cierra Antra y procesa la carpeta."
fi
action=$(notify-send -a "Música" -i folder-music -u critical -t 0 -A simular="Simular procesado" -A skip="Ahora no" --wait \
  "Antra terminó: $title" "$body${nl}$msg")
[[ "$action" == simular ]] || exit 0

exec "$(dirname "$0")/musica-procesar.sh" "$carpeta" "$juntar" "$url"   # Konsole: simular → ¿ejecutar? (30 sep: script aparte)
