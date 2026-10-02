#!/usr/bin/env python3
"""Junta en UNA carpeta las canciones que Antra bajó sueltas, para procesarlas como cualquier descarga.

Cuándo: al bajar una canción (o un disco) desde su enlace, Antra no crea "<playlist>/": la guarda como
"<artistas>/<año> - <álbum>/<artistas> - <título>.flac" (así llegó el CANDY Remix el 25 sep 2026) y el aviso no
encontraba la carpeta. Este script las reúne en "<carpeta>/", igual que una descarga de playlist; después
procesar_descarga.py "<carpeta>" hace todo lo demás. El aviso (musica-descarga-lista.sh) lo llama solo.

Uso: juntar_descarga.py "<carpeta>" [--url <enlace que se bajó>] [--execute]
Qué junta: todo audio sin procesar (comun.sin_procesar) que bajó Antra (etiqueta ANTRA_DOWNLOADED) y que NO esté ya
en una carpeta de descarga de la raíz (Carpeta/archivo.flac: esas se procesan aparte, cada una con su nombre).
Lo sin procesar que no es de Antra (puesto a mano) no se toca: solo se avisa.
Sin --execute solo muestra. Con --execute (Antra cerrado): mueve (mismo disco, no copia), corrige sus rutas en
.antra_state.json (respaldo en respaldos/) y borra las carpetas que queden vacías. Log: logs/juntar-<fecha>.json.
Si no hay nada que juntar: con --url y --execute anota lo bajado en revisar_fallidas.tsv (sale en el documento de
pendientes y se quita sola cuando la canción entra a la biblioteca) y termina con código 2.
"""
import datetime, json, os, sys
from audio import abrir
from comun import ROOT, antra_abierto, anotar_fallida, cambiar_rutas, log_path, sin_procesar, state_leer

args = sys.argv[1:]
EXECUTE = "--execute" in args
url = args[args.index("--url") + 1] if "--url" in args and args.index("--url") + 1 < len(args) else ""
pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--url")]
if len(pos) != 1 or "/" in pos[0] or pos[0] in (".", ".."):
    sys.exit(__doc__)
carpeta = pos[0]
DEST = os.path.join(ROOT, carpeta)

if antra_abierto():
    sys.exit("Antra está abierto: ciérralo primero.")
if os.path.isdir(DEST) and any(os.path.isdir(os.path.join(DEST, x)) for x in os.listdir(DEST)):
    sys.exit(f"«{carpeta}» ya existe y tiene subcarpetas (¿es un artista?): usa otro nombre.")

# ---------- plan ----------
plan, ajenas, usados = [], [], set(os.listdir(DEST)) if os.path.isdir(DEST) else set()
for rel in sin_procesar():
    if rel.count(os.sep) == 1:   # Carpeta/archivo.flac = otra descarga de playlist: va aparte
        continue
    src = os.path.join(ROOT, rel)
    try:
        de_antra = bool(abrir(src).get("antra_downloaded"))
    except Exception:   # a medio escribir o dañado: no se toca
        de_antra = False
    if not de_antra:
        ajenas.append(rel)
        continue
    if os.stat(src).st_nlink > 1:
        print(f"  OJO: {rel} tiene otros nombres (hardlinks); no la muevo")
        continue
    stem, ext = os.path.splitext(os.path.basename(rel))
    nombre, n = stem + ext, 2
    while nombre in usados:   # dos sueltas con el mismo nombre de archivo
        nombre, n = f"{stem} ({n}){ext}", n + 1
    usados.add(nombre)
    plan.append((src, os.path.join(DEST, nombre)))

if ajenas:
    print(f"OJO: {len(ajenas)} sin procesar que no bajó Antra (no se tocan):", *ajenas[:10], sep="\n   ")
print(f"{len(plan)} canciones sueltas sin procesar → «{carpeta}/»")
for src, _ in plan:
    print("  ", os.path.relpath(src, ROOT))
if not plan:
    if url and EXECUTE:
        nuevo = anotar_fallida(f"Antra {datetime.date.today()}", "", f"(no encontré lo bajado de «{carpeta}»)", carpeta, url)
        print("Anotada en pendientes (revisar_fallidas.tsv → documento de pendientes)." if nuevo
              else "Ya estaba anotada en pendientes.")
    sys.exit(2)
if not EXECUTE:
    sys.exit("Simulación: no se movió nada. Usa --execute.")

# ---------- aplicar ----------
log = {"carpeta": carpeta, "url": url, "movidos": [], "carpetas_borradas": []}
state_leer()   # falla ANTES de mover nada si el state de Antra no tiene su formato de siempre
os.makedirs(DEST, exist_ok=True)
try:
    for src, dst in plan:
        if os.path.exists(dst):
            raise RuntimeError(f"ya existe {dst}")
        os.rename(src, dst)
        log["movidos"].append([src, dst])
    cambiar_rutas(dict(log["movidos"]), "juntar")   # state de Antra (con respaldo), listas y log pendiente para Navidrome
    for src, _ in plan:   # carpetas que Antra creó solo para estas canciones
        d = os.path.dirname(src)
        while d != ROOT and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            log["carpetas_borradas"].append(os.path.relpath(d, ROOT))
            d = os.path.dirname(d)
finally:
    out = log_path("juntar")
    json.dump(log, open(out, "w"), ensure_ascii=False, indent=1)
print(f"Movidas {len(log['movidos'])} (state al día) | carpetas vacías borradas: {len(log['carpetas_borradas'])}")
print(f"Log: {out}")
print(f'Siguiente: python3 ~/music-tools/procesar_descarga.py "{carpeta}"')
