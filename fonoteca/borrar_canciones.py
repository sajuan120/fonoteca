#!/usr/bin/env python3
"""BORRA canciones malas (corruptas o con el audio equivocado) y las deja anotadas para volver a conseguirlas.
Regla (24 sep 2026): un archivo malo no se guarda; se borra y se re-baja.

Uso: borrar_canciones.py <lista.txt> --motivo corrupta|equivocada [--execute]
     lista.txt = rutas relativas a la biblioteca, una por línea. Deben estar TODOS los nombres (hardlinks) de cada audio.
Sin --execute solo muestra qué haría. Con --execute:
  1. borra cada audio (todos sus nombres) y las carpetas de álbum/artista que queden vacías;
  2. lo saca de .antra_state.json (respaldo en respaldos/) → al re-sincronizar, Antra lo vuelve a bajar;
  3. quita sus líneas de _Playlists/*.m3u (copia de la playlist original en el log; cuando se re-baja,
     devolver_playlists.py —paso 7e del procesado— la vuelve a poner en su lugar);
  4. lo anota en revisar_fallidas.tsv (la lista única de "conseguir a mano"), con las playlists donde estaba.
Log: logs/borradas-<fecha>/log.json
"""
import json, os, shutil, sys, time
from audio import abrir
from comun import ROOT, LOGS, antra_abierto, anotar_fallida, state_leer, state_guardar

args = sys.argv[1:]
EXECUTE = "--execute" in args
motivo = args[args.index("--motivo") + 1] if "--motivo" in args else None
if not args or motivo not in ("corrupta", "equivocada"):
    sys.exit(__doc__)
lista = args[0]
if antra_abierto():
    sys.exit("Antra está abierto: ciérralo y reintenta (tocaría su .antra_state.json).")

files = []
for line in open(lista, encoding="utf-8"):
    rel = line.strip().removeprefix("./")
    if rel:
        p = os.path.join(ROOT, rel)
        assert os.path.isfile(p), f"no existe: {rel}"
        files.append(p)
by_ino = {}
for p in files:
    by_ino.setdefault(os.stat(p).st_ino, []).append(p)
for ps in by_ino.values():
    assert os.stat(ps[0]).st_nlink == len(ps), f"faltan nombres (hardlinks) del mismo audio en la lista: {ps}"

state = state_leer()
targets = set(files)
drop = [k for k, v in state.items() if v in targets]
print(f"{len(by_ino)} audios ({len(files)} nombres) a BORRAR por {motivo}, {len(drop)} claves a quitar del state")
for ps in by_ino.values():
    print("  ", os.path.relpath(ps[0], ROOT))
if not EXECUTE:
    sys.exit("Simulación: no se tocó nada. Usa --execute.")

stamp = time.strftime("%Y%m%d-%H%M%S")
ldir = os.path.join(LOGS, f"borradas-{stamp}")
os.makedirs(ldir)

# 1. borrar (leyendo antes los tags para poder anotarla)
tags, log = {}, []
for ino, ps in by_ino.items():
    t = abrir(ps[0])
    tags[ino] = {k: (t.get(k) or [""])[0] for k in ("artist", "title", "album", "spotify_id")}
    for p in ps:
        os.unlink(p)
        log.append({"old": p, "ino": ino, "spotify_id": tags[ino]["spotify_id"]})   # devolver_playlists.py la busca por él
        d = os.path.dirname(p)
        while d != ROOT and not os.listdir(d):
            os.rmdir(d); d = os.path.dirname(d)

# 2. state (mismo formato que exige repartir.py)
removed = {k: state.pop(k) for k in drop}
state_guardar(state)   # con respaldo en respaldos/

# 3. playlists
pl_dir = os.path.join(ROOT, "_Playlists")
en_playlists = {}
for m in sorted(os.listdir(pl_dir)) if os.path.isdir(pl_dir) else []:
    if not m.endswith(".m3u"):
        continue
    mp = os.path.join(pl_dir, m)
    lines = open(mp, encoding="utf-8").read().splitlines(keepends=True)
    keep = []
    for l in lines:
        t = l.strip()
        full = os.path.normpath(os.path.join(pl_dir, t)) if t and not t.startswith("#") else None
        if full in targets:
            en_playlists.setdefault(full, []).append(m[:-4])
        else:
            keep.append(l)
    if len(keep) != len(lines):
        shutil.copy2(mp, os.path.join(ldir, m))
        open(mp, "w", encoding="utf-8").writelines(keep)

# 4. anotar en la lista única
for ino, g in tags.items():
    pls = sorted({p for x in log if x["ino"] == ino for p in en_playlists.get(x["old"], [])})
    origen = f"Borrada {time.strftime('%Y-%m-%d')}: {motivo}" + (f" (estaba en playlist {', '.join(pls)})" if pls else "")
    anotar_fallida(origen, g["artist"], g["title"], g["album"], f"spotify:track:{g['spotify_id']}" if g["spotify_id"] else "")

json.dump({"motivo": motivo, "borrados": log, "state_quitado": removed, "playlists": en_playlists},
          open(os.path.join(ldir, "log.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"Borrados y anotados en revisar_fallidas.tsv. Log: {ldir}")
