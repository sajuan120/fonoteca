#!/usr/bin/env python3
"""Letras embebidas para Navidrome (A2). Uso: letras.py [--execute] | --revert <log>

Navidrome 0.64 lee el tag LYRICS (y UNSYNCEDLYRICS), NO SYNCEDLYRICS; si LYRICS trae marcas [mm:ss.xx]
la muestra sincronizada. Antra escribe LYRICS=texto plano + SYNCEDLYRICS=LRC → se ven sin sincronizar.

1. Mejora: si SYNCEDLYRICS tiene marcas de tiempo y LYRICS no → LYRICS = SYNCEDLYRICS.
2. Faltantes (sin LYRICS ni SYNCEDLYRICS): busca en LRCLIB (lrclib.net):
     /api/get (artista, título, álbum, duración ±2 s) → con título limpio (sin " - Remastered…", paréntesis)
     → /api/search (título + artista) eligiendo duración ±3 s.
   Sincronizada → LYRICS y SYNCEDLYRICS = LRC; solo texto → LYRICS; instrumental → LRCLIB_INSTRUMENTAL=1.
Log con valores anteriores: letras-log-<fecha>.json (revertible).
"""
import collections, datetime, json, os, re, sys, urllib.parse, urllib.request
from audio import abrir, audios

from comun import ROOT, log_path, es_de_album, primer_artista, cerrojo
from red import Cache, pedir_json
TS = re.compile(r"^\[\d+:\d+(?:[.:]\d+)?\]", re.M)
KEYS = ("lyrics", "syncedlyrics", "lrclib_instrumental")

if "--revert" in sys.argv:
    log = json.load(open(sys.argv[sys.argv.index("--revert") + 1]))
    for p, old in log["cambios"].items():
        t = abrir(p)
        for k, v in old.items():
            if v is None: t.pop(k, None)
            else: t[k] = v
        t.save()
    sys.exit(f"revertidos {len(log['cambios'])}")

EXECUTE = "--execute" in sys.argv
if EXECUTE: cerrojo("letras.py")
cache = Cache("lrclib-cache.json", cada=200)   # red.py

FALLOS = dict(cache.get("__no_encontradas__") or {})   # url → fecha en que LRCLIB no la tenía
REINTENTAR_DIAS = 30                                   # LRCLIB crece: las no encontradas se vuelven a buscar cada 30 días

def api(path, **q):
    url = f"https://lrclib.net/api/{path}?" + urllib.parse.urlencode(q)
    hoy = datetime.date.today()
    if url in FALLOS and (hoy - datetime.date.fromisoformat(FALLOS[url])).days >= REINTENTAR_DIAS:
        cache.quitar(url); FALLOS.pop(url); cache.poner("__no_encontradas__", FALLOS)
    if url not in cache:
        d = pedir_json(url, intentos=3)
        if d is None:
            return None   # falla de red: NO se guarda (antes quedaba como "no existe" para siempre)
        cache.poner(url, d)
        if not d:   # 404: LRCLIB no la tiene → se vuelve a buscar en REINTENTAR_DIAS días
            FALLOS[url] = hoy.isoformat(); cache.poner("__no_encontradas__", FALLOS)
    return cache[url]

def clean(t):
    t = re.sub(r"\s+-\s+.*$", "", t or ""); t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", t)
    return t.strip()

def lookup(artist, title, album, dur):
    for tt in dict.fromkeys([title, clean(title)]):
        if not tt: continue
        d = api("get", artist_name=primer_artista(artist), track_name=tt, album_name=album, duration=dur)
        if d: return d, "get"
    res = api("search", track_name=clean(title) or title, artist_name=primer_artista(artist)) or []
    res = [r for r in res if r.get("duration") and abs(r["duration"] - dur) <= 3]
    res.sort(key=lambda r: (not r.get("syncedLyrics"), not r.get("plainLyrics"), abs(r["duration"] - dur)))
    return (res[0], "search") if res else (None, None)

seen, files = set(), []
for f in sorted(audios(ROOT)):
    if not es_de_album(f) or os.stat(f).st_ino in seen: continue   # solo Artista/Álbum (nunca una descarga en curso)
    seen.add(os.stat(f).st_ino); files.append(f)

cambios, stats = {}, collections.Counter()
for i, f in enumerate(files):
    t = abrir(f); g = lambda k: (t.get(k) or [""])[0]
    lyr, syn = g("lyrics"), g("syncedlyrics")
    new = {}
    if syn and TS.search(syn) and not TS.search(lyr):
        new["lyrics"] = [syn]; stats["mejorada a sincronizada"] += 1
    elif not lyr and not syn and not g("lrclib_instrumental"):
        d, how = lookup(g("artist"), g("title"), g("album"), round(t.info.length))
        if not d: stats["no encontrada"] += 1
        elif d.get("syncedLyrics"):
            new["lyrics"] = [d["syncedLyrics"]]; new["syncedlyrics"] = [d["syncedLyrics"]]; stats[f"nueva sincronizada ({how})"] += 1
        elif d.get("plainLyrics"):
            new["lyrics"] = [d["plainLyrics"]]; stats[f"nueva solo texto ({how})"] += 1
        elif d.get("instrumental"):
            new["lrclib_instrumental"] = ["1"]; stats["instrumental"] += 1
        else:
            stats["no encontrada"] += 1
    elif TS.search(lyr): stats["ya sincronizada"] += 1
    elif lyr: stats["ya tenía texto (sin versión sincronizada)"] += 1
    if new:
        cambios[f] = {k: (t.get(k) or None) for k in new}
        if EXECUTE:
            for k, v in new.items(): t[k] = v
            t.save()
    if i % 200 == 0:
        print(f"  {i}/{len(files)}", flush=True); cache.guardar()
cache.guardar()
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
out = log_path(f"letras-{'log' if EXECUTE else 'simulacion'}")
json.dump(dict(cambios=cambios, stats=stats), open(out, "w"), ensure_ascii=False)
print(f"{len(files)} canciones | {dict(stats)}")
print(("ESCRITO. " if EXECUTE else "SIMULACIÓN, no se escribió nada. ") + f"Log: {out}")
