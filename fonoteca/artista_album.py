#!/usr/bin/env python3
"""Paso 4 del procesado: ARTISTA DEL ÁLBUM unificado, para que Navidrome no parta un disco en varios
(los soundtracks y recopilatorios traen como ALBUMARTIST el artista de cada pista).

Uso: artista_album.py [--execute]      (sin --execute solo muestra; el plan queda en planes/plan-albumartist.json)

Cómo: agrupa las canciones por disco de MusicBrainz (MUSICBRAINZ_RELEASEGROUPID, lo pone mb_disco.py) + nombre de álbum.
Si un disco tiene ALBUMARTIST distintos, a todas sus pistas se les pone el artista oficial del disco en MusicBrainz
(NOMBRE: nombre preferido para algunos, decisiones/artistas-nombres.tsv). También a las pistas del mismo álbum SIN ese ID que
estén en la MISMA carpeta (nunca a otro disco homónimo de otra carpeta).
"""
import collections, json, os, sys
from audio import abrir, es_audio
from comun import ROOT, plan_path, SKIP, plano, decision
from red import Cache, pedir_json

EXECUTE = "--execute" in sys.argv
# artista del disco que MusicBrainz escribe distinto → nombre en la biblioteca: decisiones/artistas-nombres.tsv
_np = decision("artistas-nombres.tsv")
NOMBRE = dict(l.rstrip("\n").split("\t")[:2] for l in open(_np, encoding="utf-8")
              if l.strip() and not l.startswith("#")) if os.path.exists(_np) else {}
cache = Cache("mb-release-artista.json", cada=1)   # red.py (release_id → artista del disco)

def artista_oficial(release_id):
    """Artista del disco según MusicBrainz (red.py: 1 consulta/s, con caché; sin respuesta no se guarda nada)."""
    if release_id not in cache:
        d = pedir_json(f"https://musicbrainz.org/ws/2/release/{release_id}?inc=artist-credits&fmt=json")
        if d and d.get("artist-credit"):
            cache.poner(release_id, "".join(c["name"] + c.get("joinphrase", "") for c in d["artist-credit"]))
    return cache.get(release_id)

# ---------- plan ----------
seen, grupos = set(), collections.defaultdict(list)
for d, _, fs in os.walk(ROOT):
    for f in fs:
        p = os.path.join(d, f)
        if not es_audio(f) or os.path.relpath(p, ROOT).split(os.sep)[0] in SKIP:   # _Prueba: MP3 de Octo-Fiesta
            continue
        ino = os.stat(p).st_ino
        if ino in seen:
            continue
        seen.add(ino)
        try:
            t = abrir(p).tags
        except Exception:
            t = None
        if t is None:   # archivo a medio escribir o sin tags
            continue
        g = lambda k: (t.get(k) or [""])[0]
        if g("musicbrainz_releasegroupid"):
            grupos[(g("musicbrainz_releasegroupid"), plano(g("album")))].append(
                dict(path=p, albumartist=g("albumartist"), release=g("musicbrainz_albumid"), album=g("album")))

plan = []
for (rg, _), items in grupos.items():
    actuales = collections.Counter(i["albumartist"] for i in items)
    if len(actuales) < 2:
        continue
    release = collections.Counter(i["release"] for i in items).most_common(1)[0][0]
    oficial = artista_oficial(release)
    propuesta = NOMBRE.get(oficial or "", oficial) or actuales.most_common(1)[0][0]
    carpetas = {os.path.dirname(i["path"]) for i in items}
    en_disco = {i["path"] for i in items}
    hermanas = []   # pistas del mismo álbum SIN ID de disco, solo en las mismas carpetas
    for c in carpetas:
        for x in os.listdir(c):
            px = os.path.join(c, x)
            if es_audio(x) and px not in en_disco:
                tx = abrir(px).tags
                if not tx.get("musicbrainz_releasegroupid") and plano((tx.get("album") or [""])[0]) == plano(items[0]["album"]):
                    hermanas.append(px)
    cambios = [(p, (abrir(p).tags.get("albumartist") or [""])[0]) for p in sorted(en_disco) + hermanas]
    plan.append(dict(album=items[0]["album"], releasegroup=rg, propuesta=propuesta, actual=dict(actuales),
                     cambios=[(p, a) for p, a in cambios if a != propuesta]))
json.dump(plan, open(plan_path("plan-albumartist.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

n_cambios = sum(len(p["cambios"]) for p in plan)
print(f"Discos con ALBUMARTIST mezclado: {len(plan)} | canciones a cambiar: {n_cambios}")
for p in sorted(plan, key=lambda p: p["album"].lower()):
    print(f"  {p['album'][:48]:48s} → «{p['propuesta']}»  (cambian {len(p['cambios'])})  hoy: {p['actual']}")
if not EXECUTE:
    sys.exit(0)

# ---------- aplicar ----------
for p in plan:
    for path, _ in p["cambios"]:
        t = abrir(path); t["albumartist"] = [p["propuesta"]]; t.save()
print(f"Hecho: {n_cambios} canciones.")
