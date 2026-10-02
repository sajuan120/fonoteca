#!/usr/bin/env python3
"""Quita una canción de la biblioteca SIN perder nada de lo que tenía (30 sep 2026: reemplaza a 7 puntuales que hacían
lo mismo con los casos escritos adentro: quitar-copias-mismo-audio, quitar-copia-enemy/-war-rocky/-wiping-all-out,
quitar-versiones-fotos, quitar-no-satisfaction y parte de arreglos-finales).

Uso: quitar_copia.py <sobra> <queda> [<sobra> <queda> …] [--execute]
     quitar_copia.py --lista <pares.tsv> [--execute]          (una línea por par: sobra<TAB>queda; # = comentario)
     quitar_copia.py --sin-reemplazo <archivo> [<archivo> …] [--execute]
Rutas relativas a la biblioteca (o completas). Sin --execute solo muestra.

Dos usos:
  · COPIA (sobra → queda): el mismo audio en dos archivos (la auditoría lo marca como audio_igual / copias; duplicados.py
    resuelve solo los que tienen el mismo título). Este comando no decide cuál se queda: la regla de siempre es la del
    disco con más canciones, y si empatan la más escuchada. La que queda recibe:
      - las escuchas, estrellas, historial y entradas de playlist de Navidrome (log pendiente → nd_actualizar.py);
      - el state de Antra, las playlists .m3u (sin repetirla si ya estaba) y las listas de decisiones (comun.cambiar_rutas);
      - el ISRC de la otra si no tenía (así la auditoría las reconoce) y una fila en decisiones/equivalencias.tsv con el
        spotify_id de la que sobra (Antra no la vuelve a bajar y sus playlists de Spotify la encuentran).
  · SIN REEMPLAZO: la canción no se quiere (p. ej. un remix que Antra bajó en lugar de otra): sale del state de Antra, de
    las playlists y de las listas. NO se anota para re-bajar (para un archivo MALO que hay que volver a bajar está
    borrar_canciones.py).
Lo quitado va a respaldos/quitadas-<hora>/ (no se borra: se borra a mano una vez aprobado).
"""
import datetime, os, shutil, sys
from audio import abrir
from comun import ROOT, RESPALDOS, antra_abierto, cambiar_rutas, state_leer

args = sys.argv[1:]
EXECUTE = "--execute" in args
if not args or args[0] in ("-h", "--help"):
    sys.exit(__doc__)
A = lambda r: r if os.path.isabs(r) else os.path.join(ROOT, r)
pares = []   # (sobra, queda o None)
if "--lista" in args:
    for l in open(args[args.index("--lista") + 1], encoding="utf-8"):
        c = l.rstrip("\n").split("\t")
        if l.strip() and not l.startswith("#"):
            pares.append((A(c[0]), A(c[1]) if len(c) > 1 and c[1] else None))
elif "--sin-reemplazo" in args:
    pares = [(A(x), None) for x in args[args.index("--sin-reemplazo") + 1:] if not x.startswith("--")]
else:
    libres = [x for x in args if not x.startswith("--")]
    if len(libres) % 2:
        sys.exit("Faltan argumentos: van de a pares, <sobra> <queda>. Para quitar sin reemplazo: --sin-reemplazo <archivo>.")
    pares = [(A(libres[i]), A(libres[i + 1])) for i in range(0, len(libres), 2)]

problemas = []
for s, q in pares:
    if not os.path.isfile(s): problemas.append(f"no existe: {s}")
    elif os.stat(s).st_nlink > 1: problemas.append(f"tiene otros nombres (hardlink): {s}")
    if q and not os.path.isfile(q): problemas.append(f"no existe la que queda: {q}")
    if q and s == q: problemas.append(f"es el mismo archivo: {s}")
for s, q in pares:
    print(f"  sobra  {os.path.relpath(s, ROOT)}\n  {'queda  ' + os.path.relpath(q, ROOT) if q else '(sin reemplazo: no se quiere)'}")
if problemas:
    sys.exit("\n".join(problemas))
if not EXECUTE:
    sys.exit(f"\nSimulación: {len(pares)} canción(es). Usa --execute.")
if antra_abierto():
    sys.exit("Antra está abierto: ciérralo y reintenta.")

state_leer()   # 2 oct: falla ANTES de mover nada si el state de Antra no tiene su formato (antes, después de mover y sin log)
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
resp = os.path.join(RESPALDOS, f"quitadas-{stamp}")
mover, equiv = {}, []
try:
  for s, q in pares:
    ts = abrir(s)
    if q:
        tq = abrir(q)
        if not tq.get("isrc") and ts.get("isrc"):
            tq["isrc"] = ts["isrc"]; tq.save()
        sid = (ts.get("spotify_id") or [""])[0]
        if sid:
            equiv.append((sid, q, f"misma grabación que «{os.path.basename(s)}» (copia quitada {stamp[:8]})"))
    dst = os.path.join(resp, os.path.relpath(s, ROOT))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(s, dst)
    mover[s] = q
    d = os.path.dirname(s)
    while d != ROOT and os.path.isdir(d) and not os.listdir(d):   # carpetas que quedaron vacías
        os.rmdir(d); d = os.path.dirname(d)
finally:   # 2 oct: también si se corta a mitad: lo ya movido queda anotado (state, playlists, listas, Navidrome)
    log = cambiar_rutas(mover, "quitadas", equivalencias=equiv) if mover else None
print(f"HECHO: {len(pares)} canción(es) a {resp}. Log pendiente para Navidrome: {log}\nSiguiente (pasa sus escuchas a la que queda): python3 nd_actualizar.py")
