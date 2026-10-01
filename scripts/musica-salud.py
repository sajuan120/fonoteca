#!/usr/bin/env python3
"""Chequeo semanal de salud de la biblioteca de música (timer musica-salud.timer, domingos 12:00). SOLO LEE.

1. Navidrome arriba, con las mismas canciones que el disco y 0 "missing" (salvo las borradas que esperan re-descarga:
   se guardan a propósito con sus reproducciones; salen como información).
   (Si Antra está abierto no se comparan los conteos: está escribiendo canciones y la diferencia es normal.)
2. Descargas sin procesar (con Antra cerrado): carpetas de Antra en la raíz, y canciones sueltas en cualquier parte
   (fuera de Artista/Álbum/NN - Título.flac o sin ReplayGain: comun.sin_procesar).
3. Todas las rutas de _Playlists/*.m3u existen.
4. Espacio libre en el disco de la biblioteca.
No hace flac -t: la biblioteca completa se probó el 24 sep 2026 y cada descarga nueva se prueba en procesar_descarga.py.

Si todo está bien: solo agrega una línea a logs/salud.log (en la carpeta de las herramientas).
Si algo falla: aviso persistente + detalle en logs/salud-ultimo.txt.
"""
import collections, datetime, os, shutil, sqlite3, subprocess, sys
_repo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonoteca")   # en el repositorio: scripts/../fonoteca
sys.path.insert(0, os.environ.get("MUSIC_TOOLS") or (_repo if os.path.isdir(_repo) else os.path.expanduser("~/music-tools")))
from comun import HERE, ROOT, LOGS, antra_abierto, sin_procesar, esperando_rebajar, NAVIDROME_DB
from audio import EXT_AUDIO as AUDIO

DB = NAVIDROME_DB
MIN_LIBRE_GB = 100
problemas, info = [], []

# Navidrome ignora lo que liste un .ndignore (hoy no hay ninguno; se respeta por si vuelve a existir)
try:
    ignoradas = {l.strip().strip("/") for l in open(os.path.join(ROOT, ".ndignore")) if l.strip().endswith("/")}
except OSError:
    ignoradas = set()

rutas, prueba = [], 0
for d, _, files in os.walk(ROOT):
    top = os.path.relpath(d, ROOT).split(os.sep)[0]
    if top in ignoradas:
        continue
    if top == "_Prueba":   # MP3 de prueba de Octo-Fiesta (28 sep): se cuentan aparte, no son la biblioteca
        prueba += sum(1 for f in files if f.lower().endswith(AUDIO))
        continue
    rutas += [os.path.join(d, f) for f in files if f.lower().endswith(AUDIO)]   # 28 sep: todos los formatos
bajando = antra_abierto()

# 1. Navidrome
r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "navidrome"], capture_output=True, text=True)
if r.stdout.strip() != "true":
    problemas.append("Navidrome NO está corriendo (docker compose -f ~/navidrome/docker-compose.yml up -d)")
try:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    nd = con.execute("select count(*) from media_file where missing=0 and path not like '_Prueba/%'").fetchone()[0]
    faltan = [r[0] for r in con.execute("select path from media_file where missing=1 and path not like '_Prueba/%'")]
    con.close()
    esperan = set(esperando_rebajar()) & set(faltan)   # borradas que esperan re-descarga: guardan sus reproducciones
    missing = len(faltan) - len(esperan)
    info.append(f"Navidrome {nd} / disco {len(rutas)}" + (f" | prueba (Octo-Fiesta) {prueba}" if prueba else ""))
    if esperan:
        info.append(f"{len(esperan)} borradas esperando re-descarga")
    if bajando:
        info.append("Antra abierto: conteos sin comparar")
    elif nd != len(rutas):
        problemas.append(f"Navidrome tiene {nd} canciones y el disco {len(rutas)} (¿falta un escaneo?)")
    if missing:
        problemas.append(f"Navidrome marca {missing} canciones como perdidas (missing)")
except Exception as e:
    problemas.append(f"No pude leer la base de Navidrome: {e}")

# 2. descargas sin procesar
if not bajando:
    sp = [r for r in sin_procesar() if r.split(os.sep)[0] not in ignoradas]
    carpetas = collections.Counter(r.split(os.sep)[0] for r in sp if r.count(os.sep) == 1)   # Carpeta/archivo.flac
    sueltas = [r for r in sp if r.count(os.sep) != 1]
    if carpetas:
        problemas.append("Descarga(s) de Antra sin procesar: " + ", ".join(f"«{k}» ({v} canciones)" for k, v in carpetas.items())
                         + f" → python3 {HERE}/procesar_descarga.py \"<carpeta>\"")
    if sueltas:
        problemas.append(f"{len(sueltas)} canción(es) suelta(s) sin procesar → python3 {HERE}/juntar_descarga.py \"<nombre>\""
                         " --execute y luego procesar_descarga.py \"<nombre>\":\n" + "\n".join(f"  {r}" for r in sueltas[:30]))

# 3. playlists
pl_dir = os.path.join(ROOT, "_Playlists")
rotas = []
for m in sorted(os.listdir(pl_dir)) if os.path.isdir(pl_dir) else []:
    if m.endswith(".m3u"):
        for l in open(os.path.join(pl_dir, m), encoding="utf-8"):
            l = l.strip()
            if l and not l.startswith("#") and not os.path.exists(os.path.normpath(os.path.join(pl_dir, l))):
                rotas.append(f"  {m}: {l}")
if rotas:
    problemas.append(f"{len(rotas)} rutas rotas en playlists:\n" + "\n".join(rotas))

# 4. espacio
libre = shutil.disk_usage(ROOT).free / 1e9
info.append(f"{libre:.0f} GB libres")
if libre < MIN_LIBRE_GB:
    problemas.append(f"Quedan solo {libre:.0f} GB libres en el disco de la biblioteca")

# resultado
ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
estado = "OK" if not problemas else f"{len(problemas)} PROBLEMA(S)"
with open(os.path.join(LOGS, "salud.log"), "a") as log:
    log.write(f"{ahora}  {estado}  | {' | '.join(info)}\n")
if problemas:
    detalle = os.path.join(LOGS, "salud-ultimo.txt")
    with open(detalle, "w") as f:
        f.write(f"Chequeo de salud {ahora}\n\n" + "\n\n".join(problemas) + "\n")
    resumen = "\n".join(p.splitlines()[0] for p in problemas)
    subprocess.run(["notify-send", "-a", "Música", "-i", "dialog-warning", "-u", "critical", "-t", "0",
                    "Biblioteca de música: revisar", f"{resumen}\nDetalle: {LOGS}/salud-ultimo.txt"])
print(estado, "|", " | ".join(info))
if problemas:
    print("\n\n".join(problemas))
sys.exit(1 if problemas else 0)
