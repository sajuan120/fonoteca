#!/usr/bin/env python3
"""Devuelve a sus playlists las canciones que se borraron (corruptas o equivocadas) y ya se volvieron a bajar.

Por qué (25 sep 2026): borrar_canciones.py saca la canción de _Playlists/*.m3u, pero al re-bajarla nadie la devolvía
(el CANDY Remix se repuso a mano). Paso 7e de procesar_descarga.py; también se puede correr solo.

Uso: devolver_playlists.py [--execute]      sin --execute solo muestra
Cómo: lee logs/borradas-*/log.json (qué se borró, su spotify_id y en qué playlists estaba, más la copia de cada
playlist antes del borrado). Si una canción con ese spotify_id vuelve a estar en la biblioteca, la inserta en cada
playlist donde estaba, junto a sus mismas vecinas de antes (si ya no están, al final). Nunca la repite.
Lo devuelto queda en logs/playlists-devueltas.json (no se vuelve a insertar si después la quitas a mano).
"""
import datetime, os, shutil, sys
from comun import ROOT, LOGS, RESPALDOS, borradas as leer_borradas, rutas_por_sid, leer_json, guardar_json, cerrojo

EXECUTE = "--execute" in sys.argv
PL = os.path.join(ROOT, "_Playlists")
HECHAS = os.path.join(LOGS, "playlists-devueltas.json")
hechas = leer_json(HECHAS, {})

# canciones borradas que estaban en alguna playlist, y dónde están hoy (por spotify_id)
borradas = [(b["ldir"], b["old"], b["sid"], b["playlists"]) for b in leer_borradas() if b["playlists"]]
hoy = rutas_por_sid({b[2] for b in borradas})

cambios = {}   # playlist → líneas nuevas (se escriben al final)
def lineas(m):
    if m not in cambios:
        cambios[m] = open(os.path.join(PL, m + ".m3u"), encoding="utf-8").read().splitlines()
    return cambios[m]

n = 0
for ldir, old, sid, pls in borradas:
    if sid not in hoy:
        continue   # todavía no se re-bajó
    nueva = os.path.relpath(hoy[sid], PL)
    vieja = os.path.relpath(old, PL)
    for m in pls:
        clave = f"{os.path.basename(ldir)}|{sid}|{m}"
        if clave in hechas or not os.path.exists(os.path.join(PL, m + ".m3u")):
            continue
        L = lineas(m)
        if nueva in L:
            hechas[clave] = {"fecha": datetime.date.today().isoformat(), "linea": nueva, "nota": "ya estaba"}
            continue
        # vecinas de antes (copia de la playlist que guardó borrar_canciones.py)
        pos = len(L)
        copia = os.path.join(ldir, m + ".m3u")
        if os.path.exists(copia):
            orig = open(copia, encoding="utf-8").read().splitlines()
            if vieja in orig:
                i = orig.index(vieja)
                antes = next((L.index(v) + 1 for v in reversed(orig[max(0, i - 10):i]) if v in L and not v.startswith("#")), None)
                despues = next((L.index(v) for v in orig[i + 1:i + 11] if v in L and not v.startswith("#")), None)
                pos = antes if antes is not None else despues if despues is not None else len(L)
        L.insert(pos, nueva)
        hechas[clave] = {"fecha": datetime.date.today().isoformat(), "linea": nueva, "posicion": pos + 1}
        n += 1
        print(f"  {m}: + {nueva}  (línea {pos + 1})")

print(f"{n} canciones a devolver a sus playlists" + ("" if EXECUTE else " (simulación: no se escribió nada)"))
if EXECUTE and cambios:
    cerrojo("devolver_playlists.py")
    bak = os.path.join(RESPALDOS, f"playlists-antes-devolver-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    os.makedirs(bak)
    for m, L in cambios.items():
        mp = os.path.join(PL, m + ".m3u")
        shutil.copy2(mp, bak)
        open(mp, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"Copia de las playlists antes del cambio: {bak}")
if EXECUTE:
    guardar_json(HECHAS, hechas, indent=1)
