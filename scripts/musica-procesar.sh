#!/usr/bin/env bash
# Abre una Konsole que procesa una carpeta de la biblioteca: espera a que Antra esté cerrado, junta las canciones
# sueltas si hace falta, SIMULA procesar_descarga.py y pregunta antes de ejecutar de verdad.
# Uso: musica-procesar.sh "<carpeta>" [juntar 0|1] [url]
# Lo usan el aviso de fin de descarga de Antra (musica-descarga-lista.sh) y el embudo de prueba (prueba.py, al adoptar
# un MP3 que nunca consiguió su FLAC). 30 sep 2026: separado del aviso para no repetirlo.
# OJO: este archivo NO puede tener "antra" en el nombre: procesar_descarga.py creería que Antra está abierto.
carpeta="$1"; juntar="${2:-0}"; url="${3:-}"
_repo="$(cd "$(dirname "$0")/../fonoteca" 2>/dev/null && pwd)"
TOOLS="${MUSIC_TOOLS:-${_repo:-$HOME/music-tools}}"   # carpeta de las herramientas
[[ -n "$carpeta" ]] || { echo "Uso: $0 \"<carpeta>\" [juntar 0|1] [url]" >&2; exit 2; }

# Konsole como unidad propia: si no, systemd la mata al terminar quien la lanzó (mismo cgroup).
exec systemd-run --user --collect --quiet konsole --hold -e bash -c '
  f="$1"; juntar="$2"; url="$3"   # $4: la carpeta de las herramientas
  cd "$4" || exit
  # la MISMA regla que usan los scripts (comun.antra_abierto: cualquier proceso con «antra» en el nombre, también el
  # AppImage); antes era `pgrep -x Antra` y el 25 sep la simulación arrancó con Antra todavía abierto y falló
  while python3 -c "import sys; from comun import antra_abierto; sys.exit(0 if antra_abierto() else 1)"; do
    echo -ne "\rEsperando a que cierres Antra... "; sleep 3
  done; echo
  if [[ "$juntar" == 1 ]]; then
    python3 juntar_descarga.py "$f" ${url:+--url "$url"} --execute
    case $? in
      0) echo; echo "(Solo se juntaron en «$f», como una descarga normal. Ahora la simulación:)"; echo ;;
      2) echo; echo "No encontré canciones sin procesar: quedó anotado en pendientes."; exit ;;
      *) echo; echo "No se pudo juntar (mira el mensaje de arriba)."; exit ;;
    esac
  fi
  python3 procesar_descarga.py "$f"; rc=$?
  echo
  if [[ $rc != 0 ]]; then   # 25 sep: falló y se preguntó igual «¿Ejecutar?» como si nada
    echo "════════ ⚠️  La SIMULACIÓN se detuvo o FALLÓ (código $rc). Lee el mensaje de arriba antes de seguir. ════════"
    read -r -p "¿Ejecutar igual? Escribe «si» para hacerlo (cualquier otra cosa = no) " r
    [[ "$r" == "si" ]] || { echo "No se ejecutó. Para hacerlo después:  python3 $PWD/procesar_descarga.py \"$f\" --execute"; exit; }
    python3 procesar_descarga.py "$f" --execute; exit
  fi
  echo "════════ Eso fue una SIMULACIÓN (no se tocó nada). Revísala arriba. ════════"
  read -r -p "¿Ejecutar ahora de verdad? (s/N) " r
  if [[ "$r" == [sS] ]]; then
    python3 procesar_descarga.py "$f" --execute
  else
    echo "No se ejecutó. Para hacerlo después:  python3 $PWD/procesar_descarga.py \"$f\" --execute"
  fi
' _ "$carpeta" "$juntar" "$url" "$TOOLS"
