#!/usr/bin/env python3
"""Enriquece los FLAC de una carpeta recién bajada por Antra (paso 3 de procesar_descarga.py).

Uso: enriquecer.py <carpeta relativa a la biblioteca> [--execute]
Sin --execute solo muestra qué haría. Con --execute escribe tags y deja log con los valores anteriores
(enriquecer-log-<carpeta>-<fecha>.json; revertir con --revert <log>).

Por canción:
  1. Duración vs la grabación de su ISRC (Deezer). Más de 3 s de diferencia, o Deezer sin dato = sospechosa
     (Antra pudo bajar otra versión con el mismo título) → se reporta, no se toca; el paso 3b (AcoustID + duración
     exacta en Spotify) decide. Antes eran 10 s: el CANDY Remix equivocado (8 s menos, 25 sep 2026) se coló.
  2. GENRE: si está vacío, género del álbum en Deezer; si Deezer no tiene, el género más común de ese artista en la
     biblioteca. (La traducción a la lista corta de 20 géneros la hace generos.py, paso 6 de procesar_descarga.)
  3. IDs de MusicBrainz por ISRC: grabación cuyo artista coincide con el del archivo y que es ESTA canción
     (comun.grabacion_corresponde: duración, y el título no puede ser otro; desde el 27 sep: MusicBrainz a veces tiene
     el ISRC puesto en otra canción, «Como Yo» → «Medicine for My Soul»); si además uno de sus discos se llama como el
     álbum del archivo, también IDs de disco/pista. (Las que queden solo con ID de canción las completa mb_disco.py, 3c.)
     Si la canción ya tiene musicbrainz_trackid no se toca.
  4. YEAR desde DATE si falta (Navidrome parte álbumes sin YEAR).
"""
import collections, datetime, json, os, sys
from audio import abrir, audios

from comun import ROOT, LOGS, SKIP, grabacion_corresponde, titulo_base, primer_artista, base_disco
from red import Cache, pedir_json

dz, mb = Cache("deezer-cache.json"), Cache("mb-isrc-cache.json")   # red.py: caché compartida, se guarda sola

def revert(logp):
    log = json.load(open(logp))
    for path, old in log["cambios"].items():
        t = abrir(path)
        for k, v in old.items():
            if v is None: t.pop(k, None)
            else: t[k] = v
        t.save()
    print(f"revertidos {len(log['cambios'])} archivos")

if "--revert" in sys.argv:
    revert(sys.argv[sys.argv.index("--revert") + 1]); sys.exit()

folder = sys.argv[1]; EXECUTE = "--execute" in sys.argv   # "." = toda la biblioteca
files, _seen = [], set()
for _f in sorted(audios(os.path.join(ROOT, folder))):
    if os.path.relpath(_f, ROOT).split("/")[0] in SKIP or os.stat(_f).st_ino in _seen: continue
    _seen.add(os.stat(_f).st_ino); files.append(_f)
assert files, f"no hay audio en {folder}"

# género más común por artista en el resto de la biblioteca (respaldo del paso 2). Se calcula solo si hace falta.
_art_genre = None
def genero_del_artista(artista):
    global _art_genre
    if _art_genre is None:
        _art_genre = collections.defaultdict(collections.Counter)
        for f in audios(ROOT):
            rel = os.path.relpath(f, ROOT)
            if rel.split("/")[0] in SKIP or (folder != "." and rel.split("/")[0] == folder): continue
            try:
                t = abrir(f)
            except Exception:
                continue
            for g in (t.get("genre_deezer") or t.get("genre") or [])[:1]:
                _art_genre[titulo_base(primer_artista((t.get("artist") or [""])[0]))][g] += 1
    c = _art_genre[titulo_base(primer_artista(artista))]
    return c.most_common(1)[0][0] if c else None

cambios, sospechosas, stats = {}, [], collections.Counter()
for i, f in enumerate(files):
    t = abrir(f); g = lambda k: (t.get(k) or [""])[0]
    new = {}
    isrc, artist, album = g("isrc"), g("artist"), g("album")
    trk = (pedir_json(f"https://api.deezer.com/track/isrc:{isrc}", dz) or {}) if isrc else {}
    # 1. duración
    if not trk.get("duration"):
        sospechosas.append(dict(archivo=os.path.relpath(f, ROOT), dif=None, isrc_es="(Deezer no tiene su ISRC)"))
    elif abs(t.info.length - trk["duration"]) > 3:
        sospechosas.append(dict(archivo=os.path.relpath(f, ROOT), dif=round(abs(t.info.length - trk["duration"])),
                                isrc_es=f"{trk.get('artist', {}).get('name')} — {trk.get('title')}"))
    # 2. género
    genres = t.get("genre") or []
    ng = list(dict.fromkeys(genres))
    if not ng and trk.get("album", {}).get("id"):
        alb = pedir_json(f"https://api.deezer.com/album/{trk['album']['id']}", dz) or {}
        ng = list(dict.fromkeys(x["name"] for x in alb.get("genres", {}).get("data", [])))
        if ng: stats["género de Deezer"] += 1
    if not ng and genero_del_artista(artist):
        ng = [genero_del_artista(artist)]; stats["género del artista"] += 1
    if ng != genres: new["genre"] = ng
    if not ng: stats["sin género"] += 1
    # 3. MusicBrainz por ISRC
    if not g("musicbrainz_trackid") and isrc:
        d = pedir_json(f"https://musicbrainz.org/ws/2/isrc/{isrc}?inc=artist-credits+releases&fmt=json", mb) or {}
        recs = [r for r in d.get("recordings", [])
                if titulo_base(primer_artista(artist))[:6] and titulo_base(primer_artista(artist))[:6] in titulo_base("".join(c["name"] for c in r["artist-credit"]))]
        def es_esta(r):   # por ISRC el ISRC siempre coincide: además el título no puede ser el de otra canción
            ok, nt, _ = grabacion_corresponde(g("title"), artist, t.info.length, [isrc], r.get("title"),
                                              (r.get("length") or 0) / 1000 or None, [isrc], [c["name"] for c in r["artist-credit"]])
            return ok and nt != 0
        if recs and not any(es_esta(r) for r in recs):
            stats["MB descartada (otro título o duración)"] += 1
        recs = [r for r in recs if es_esta(r)]
        if recs:
            # varias grabaciones del mismo artista con ese ISRC (estudio/en vivo/remaster): la de duración más parecida
            recs.sort(key=lambda r: abs((r.get("length") or 0) / 1000 - t.info.length) if r.get("length") else 9999)
            r = recs[0]
            new["musicbrainz_trackid"] = [r["id"]]
            new["musicbrainz_artistid"] = [c["artist"]["id"] for c in r["artist-credit"]]
            # Spotify y MusicBrainz nombran distinto las ediciones ("Thriller (Deluxe)", "... - Remastered 2011"):
            # primero igualdad exacta; si no, igualdad sin paréntesis/ediciones
            rels = [x for x in r.get("releases", []) if titulo_base(x.get("title")) == titulo_base(album)] or \
                   [x for x in r.get("releases", []) if base_disco(x.get("title")) and base_disco(x.get("title")) == base_disco(album)]
            rels.sort(key=lambda x: (x.get("status") != "Official", x.get("date") or "9999"))
            if rels:
                rel = pedir_json(f"https://musicbrainz.org/ws/2/release/{rels[0]['id']}?inc=recordings+release-groups+artist-credits&fmt=json", mb) or {}
                for m in rel.get("media", []):
                    for tr in m.get("tracks", []):
                        if tr["recording"]["id"] == r["id"]:
                            new["musicbrainz_albumid"] = [rel["id"]]
                            new["musicbrainz_releasetrackid"] = [tr["id"]]
                            new["musicbrainz_releasegroupid"] = [rel.get("release-group", {}).get("id", "")]
                            new["musicbrainz_albumartistid"] = [c["artist"]["id"] for c in rel.get("artist-credit", [])]
                stats["MB grabación + disco"] += 1
            else:
                stats["MB solo grabación"] += 1
        else:
            stats["MB no encontrada"] += 1
    elif g("musicbrainz_trackid"):
        stats["ya tenía MB"] += 1
    else:
        stats["sin ISRC"] += 1
    # 4. YEAR
    if not g("year") and g("date")[:4].isdigit(): new["year"] = [g("date")[:4]]
    new = {k: v for k, v in new.items() if v and v != [""]}
    if new:
        cambios[f] = {k: (t.get(k) or None) for k in new}
        if EXECUTE:
            for k, v in new.items(): t[k] = v
            t.save()
    if i % 50 == 0:
        print(f"  {i}/{len(files)}", flush=True)
        dz.guardar(); mb.guardar()

dz.guardar(); mb.guardar()
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
tag = "log" if EXECUTE else "simulacion"
out = os.path.join(LOGS, f"enriquecer-{tag}-{'biblioteca' if folder == '.' else folder.replace('/', '_')}-{stamp}.json")
json.dump(dict(carpeta=folder, cambios=cambios, sospechosas=sospechosas, stats=stats), open(out, "w"), ensure_ascii=False, indent=1)
print(f"{len(files)} canciones | con cambios: {len(cambios)} | {dict(stats)}")
print(f"posibles canciones equivocadas (>3 s distinto a su ISRC, o sin dato): {len(sospechosas)}")
for s in sospechosas: print(f"   Δ{s['dif'] if s['dif'] is not None else '?'}s  {s['archivo']}  (el ISRC es: {s['isrc_es']})")
print(("ESCRITO. " if EXECUTE else "SIMULACIÓN, no se escribió nada. ") + f"Log: {out}")
