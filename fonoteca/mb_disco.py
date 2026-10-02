#!/usr/bin/env python3
"""Completa el ID de DISCO de MusicBrainz (albumid, releasegroupid, releasetrackid, albumartistid) en canciones que
ya tienen ID de canción (musicbrainz_trackid) pero no disco. Reemplaza lo que antes hacía Picard (24 sep 2026).

Uso: mb_disco.py [<carpeta relativa a la biblioteca> ...] [--execute]   (sin carpetas = toda la biblioteca)
Cómo elige el disco: entre los discos de esa grabación en MusicBrainz, el que tenga el MISMO nombre que el tag ALBUM
(sin ediciones: "(Deluxe)", "- Remastered 2011"...), oficial y más antiguo primero. Si ninguno coincide, no toca nada.
1 consulta/s a MusicBrainz, con caché en mb-disco-cache.json. Sin carpetas: solo Artista/Álbum (no la de Antra en curso).
"""
import collections, json, os, sys
from audio import abrir, es_audio

from comun import ROOT, log_path, SKIP, base_disco, cerrojo
from red import Cache, pedir_json
HERE = os.path.dirname(os.path.abspath(__file__))
EXECUTE = "--execute" in sys.argv
if EXECUTE: cerrojo("mb_disco.py")
carpetas = [a for a in sys.argv[1:] if not a.startswith("--")] or ["."]
cache = Cache("mb-disco-cache.json")   # red.py

def get(url):
    """JSON de MusicBrainz con caché ({} si no existe o no hubo respuesta; la falla de red no se guarda: red.py)."""
    return pedir_json(url, cache) or {}

seen, obj = set(), []
for c in carpetas:
    for d, _, fs in os.walk(os.path.join(ROOT, c)):
        for f in fs:
            p = os.path.join(d, f)
            # sin carpetas explícitas: solo Artista/Álbum (no tocar la carpeta que Antra está bajando)
            if not es_audio(f) or os.path.relpath(p, ROOT).split(os.sep)[0] in SKIP or (carpetas == ["."] and os.path.relpath(p, ROOT).count(os.sep) < 2):
                continue
            ino = os.stat(p).st_ino
            if ino in seen:
                continue
            seen.add(ino)
            t = abrir(p)
            if t.get("musicbrainz_trackid") and not t.get("musicbrainz_releasegroupid"):
                obj.append((p, t["musicbrainz_trackid"][0], (t.get("album") or [""])[0]))
print(f"{len(obj)} canciones con ID de canción y sin ID de disco", flush=True)

stats, log = collections.Counter(), []
for k, (p, rec, album) in enumerate(obj, 1):
    rels = get(f"https://musicbrainz.org/ws/2/recording/{rec}?inc=releases&fmt=json").get("releases", [])
    cand = [r for r in rels if base_disco(r.get("title")) and base_disco(r.get("title")) == base_disco(album)]
    cand.sort(key=lambda r: (r.get("status") != "Official", r.get("date") or "9999"))
    if not cand:
        stats["sin disco con ese nombre en MB"] += 1
        continue
    rel = get(f"https://musicbrainz.org/ws/2/release/{cand[0]['id']}?inc=recordings+release-groups+artist-credits&fmt=json")
    tr = next((tr for m in rel.get("media", []) for tr in m.get("tracks", []) if tr["recording"]["id"] == rec), None)
    if not tr:
        stats["pista no encontrada en el disco"] += 1
        continue
    new = {"musicbrainz_albumid": [rel["id"]], "musicbrainz_releasetrackid": [tr["id"]],
           "musicbrainz_releasegroupid": [rel.get("release-group", {}).get("id", "")],
           "musicbrainz_albumartistid": [c["artist"]["id"] for c in rel.get("artist-credit", [])]}
    stats["disco encontrado"] += 1
    log.append({"path": p, "nuevo": new})
    if EXECUTE:
        t = abrir(p); t.update(new); t.save()
    if k % 50 == 0:
        print(f"  {k}/{len(obj)} {dict(stats)}", flush=True)

print(dict(stats))
if EXECUTE:
    out = log_path("mb-disco-log")
    json.dump(log, open(out, "w"), ensure_ascii=False, indent=0)
    print("ESCRITO. Log:", out, "(solo AGREGA tags; para deshacer basta quitar esas 4 claves)")
else:
    print("SIMULACIÓN: no se escribió nada. Usa --execute.")
