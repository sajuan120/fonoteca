#!/usr/bin/env python3
"""Genera ~/Documents/Música - cosas por revisar.md a partir del estado ACTUAL de la biblioteca (paso 9 de
procesar_descarga.py; también se puede correr solo). Solo lee la música; lo ya resuelto desaparece solo.
Fuentes: la biblioteca, revisar_fallidas.tsv (canciones a conseguir a mano), revisar_dudosas.tsv (canciones presentes
pero dudosas) y revisar_notas.md (notas a mano, se pegan al final).
También escribe ~/Documents/Música - conseguir en FLAC.md (30 sep): las canciones de la biblioteca que
están CON PÉRDIDA (MP3/AAC/Opus: descargas a mano o MP3 de prueba adoptados) y las de prueba que ganaron el FLAC y lo
esperan, con su enlace para Antra. Cada una desaparece sola cuando llega su FLAC (duplicados.py se queda con el FLAC)."""
import collections, json, os
from audio import abrir, audios

from comun import ROOT, HERE, DOC as OUT, NOTAS, DOC_FLAC, decision
from audio import con_perdida
from comun import FALLIDAS, DUDOSAS, clave_titulo, clave_artista
from comun import SKIP as PLAYLIST_DIRS, es_de_album, sin_procesar, plan_path

names, info = collections.defaultdict(list), {}
for f in sorted(audios(ROOT)):
    if not es_de_album(f):   # la carpeta de una descarga en curso o sin procesar no cuenta
        continue
    rel = os.path.relpath(f, ROOT); ino = os.stat(f).st_ino
    names[ino].append(rel)
    if ino in info: continue
    try:
        a = abrir(f); t = a.tags
    except Exception:
        t = None
    if t is None:
        continue
    g = lambda k: (t.get(k) or [""])[0]
    info[ino] = dict(artist=g("artist"), aa=g("albumartist") or g("artist"), title=g("title"), album=g("album"),
                     date=g("date") or g("year"), genre=g("genre"), pic=bool(a.pictures),
                     lyr=bool(g("lyrics") or g("syncedlyrics") or g("lrclib_instrumental")), mbid=bool(g("musicbrainz_trackid")),
                     sid=g("spotify_id"), isrc=g("isrc").upper(), rgid=g("musicbrainz_releasegroupid"),
                     secs=round(a.info.length), perdida=con_perdida(f), origen=g("origen"), dz=g("deezer_id"),
                     kbps=round((getattr(a.info, "bitrate", 0) or (os.path.getsize(f) * 8 / a.info.length if a.info.length else 0)) / 1000))

def where(ino):   # nombre "de álbum" si existe, si no el de playlist
    ns = names[ino]
    return next((x for x in ns if x.split("/")[0] not in PLAYLIST_DIRS), ns[0])

have_key = {(clave_artista(x["artist"]), clave_titulo(x["title"])) for x in info.values()} | \
           {(clave_artista(x["aa"]), clave_titulo(x["title"])) for x in info.values()}
have_sid = {x["sid"] for x in info.values()}
# equivalencias.tsv: la canción está con OTRO spotify_id (28 sep: la copia de Wiping All Out que se quitó volvía a
# «a conseguir» aunque su audio sigue en la biblioteca)
_eq = decision("equivalencias.tsv")
if os.path.isfile(_eq):
    for _l in open(_eq, encoding="utf-8"):
        _c = _l.rstrip("\n").split("\t")
        if not _l.startswith("#") and len(_c) >= 2 and os.path.isfile(os.path.join(ROOT, _c[1])):
            have_sid.add(_c[0])

L = []
w = L.append
w("# Música — cosas por revisar\n")
w(f"Generado por `{HERE}/revisar.py` a partir del estado actual de `{ROOT}` "
  f"({len(info)} canciones únicas). Lo que ya se resolvió no aparece; para actualizar, volver a correrlo.\n")

# 0. bajadas por Antra pero sin procesar (solo sale si hay)
sp = sin_procesar()
if sp:
    w(f"## 0. Descargas sin procesar ({len(sp)})\n")
    w("Antra las bajó pero no pasaron por el procesado (no cuentan en lo de abajo). Carpeta de playlist: "
      "`python3 ~/music-tools/procesar_descarga.py \"<carpeta>\"`. Canciones sueltas: "
      "`python3 ~/music-tools/juntar_descarga.py \"<nombre>\" --execute` y después procesar esa carpeta.\n")
    for r in sp[:50]:
        w(f"- `{r}`")
    if len(sp) > 50:
        w(f"- … y {len(sp) - 50} más")
    w("")

# 1. no se pudieron bajar
pend = []
if os.path.exists(FALLIDAS):
    for line in open(FALLIDAS, encoding="utf-8"):
        if not line.strip() or line.startswith("#"): continue
        origen, art, tit, alb, uri = (line.rstrip("\n").split("\t") + [""] * 5)[:5]
        if uri.split(":")[-1] in have_sid or (clave_artista(art), clave_titulo(tit)) in have_key: continue
        pend.append((origen, art, tit, alb, uri))
w(f"## 1. Canciones a conseguir a mano ({len(pend)})\n")
w("Antra no las bajó (sin fuente lossless o sin versión exacta con strict), o se borraron por corruptas/audio equivocado. "
  "Opciones: re-sincronizar la playlist en Antra más adelante, buscar otra edición del mismo tema en Spotify, o conseguirlas por otro lado. "
  "Desaparecen solas de aquí cuando la canción entra a la biblioteca.\n")
w("| Playlist | Artista | Canción | Álbum | URI |\n|---|---|---|---|---|")
for p in sorted(pend, key=lambda p: (p[0], p[1].lower())):
    w("| " + " | ".join(x.replace("|", "/") for x in p) + " |")
w("")

def section(title, desc, pred, cols=("Artista", "Canción", "Álbum", "Archivo")):
    rows = [(i, x) for i, x in info.items() if pred(x)]
    w(f"## {title} ({len(rows)})\n"); w(desc + "\n")
    if not rows: w("Nada pendiente.\n"); return
    w("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols))
    for i, x in sorted(rows, key=lambda r: (r[1]["aa"].lower(), r[1]["album"].lower(), r[1]["title"].lower())):
        w(f"| {x['artist']} | {x['title']} | {x['album']} | `{where(i)}` |".replace("\n", " "))
    w("")

section("2. Sin carátula", "Ni embebida ni `cover.jpg`/`folder.jpg`. Hay que conseguir la imagen.", lambda x: not x["pic"])
section("3. Sin ID de MusicBrainz",
        "No salen en las playlists de ListenBrainz; en Navidrome suenan normal. Casi todas son remixes/hardstyle, covers o grabaciones locales que no están en MusicBrainz.",
        lambda x: not x["mbid"])
section("4. Sin género", "Ni Antra ni Deezer traen género; se puede poner a mano (uno de la lista de 20).", lambda x: not x["genre"])
section("5. Sin fecha", "Al reorganizar quedan en carpeta de álbum sin año.", lambda x: not x["date"])

# 6. letras: por álbum (son muchas)
nolyr = collections.Counter((x["aa"], x["album"]) for x in info.values() if not x["lyr"])
w(f"## 6. Sin letra embebida ({sum(nolyr.values())} canciones)\n")
w("El plugin nd-lyrics las busca en lrclib al reproducir, así que muchas igual muestran letra. Agrupado por álbum:\n")
w("| Artista del álbum | Álbum | Canciones sin letra |\n|---|---|---|")
for (aa, al), c in sorted(nolyr.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1].lower())):
    w(f"| {aa} | {al} | {c} |")
w("")

# 7. álbumes con año distinto entre pistas (se partirían)
yrs = collections.defaultdict(set)
for x in info.values():
    yrs[(x["aa"], x["album"])].add((x["date"] or "")[:4])
mix = {k: v for k, v in yrs.items() if len(v) > 1}
w(f"## 7. Álbumes con años distintos entre sus canciones ({len(mix)})\n")
w("Navidrome podría mostrarlos partidos. `fechas.py` los corrige solo si están en la misma carpeta; estos quedaron en carpetas distintas.\n")
w("| Artista del álbum | Álbum | Años |\n|---|---|---|")
for (aa, al), v in sorted(mix.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1].lower())):
    w(f"| {aa} | {al} | {', '.join(sorted(y or '—' for y in v))} |")
w("")

# 8. duplicados: la misma grabación (mismo ISRC) en archivos distintos
por_isrc = collections.defaultdict(list)
for i, x in info.items():
    if x["isrc"]: por_isrc[x["isrc"]].append(i)
dups = {k: v for k, v in por_isrc.items() if len(v) > 1 and max(info[i]["secs"] for i in v) - min(info[i]["secs"] for i in v) <= 3}
w(f"## 8. Duplicados: la misma grabación en {sum(len(v) for v in dups.values())} archivos ({len(dups)} grupos)\n")
w("Mismo ISRC y misma duración en archivos distintos. Se resuelven solos al procesar una descarga (`duplicados.py`: queda la "
  "copia del disco con más canciones o la más escuchada). Si siguen aquí es porque tienen TÍTULO distinto: revisar a mano "
  "(¿otra versión o audio equivocado?) y, si es duplicado, `duplicados.py --tambien <ISRC> --execute`.\n")
if dups:
    w("| ISRC | Canción | Archivos |\n|---|---|---|")
    for k, v in sorted(dups.items(), key=lambda kv: info[kv[1][0]]["aa"].lower()):
        w(f"| {k} | {info[v[0]]['artist']} — {info[v[0]]['title']} | " + "<br>".join(f"`{where(i)}`" for i in v) + " |")
w("")

# 9. dudosas: canciones presentes que hay que revisar (se identifican por spotify_id; si ya no están, no salen)
por_sid = {x["sid"]: i for i, x in info.items() if x["sid"]}
dud = []
if os.path.exists(DUDOSAS):
    for line in open(DUDOSAS, encoding="utf-8"):
        if not line.strip() or line.startswith("#"): continue
        fecha, motivo, sid, art, tit, det = (line.rstrip("\n").split("\t") + [""] * 6)[:6]
        if sid in por_sid: dud.append((motivo, art, tit, det, where(por_sid[sid]), fecha))
w(f"## 9. Canciones dudosas ({len(dud)})\n")
w("Están en la biblioteca pero algo no cuadra (p. ej. AcoustID no reconoce el audio y dura distinto a su versión oficial). Escuchar: si está mal, borrarla con `borrar_canciones.py --motivo equivocada`.\n")
if dud:
    w("| Motivo | Canción | Detalle | Archivo | Desde |\n|---|---|---|---|---|")
    for m, a, t, d, pth, fe in sorted(dud):
        w(f"| {m} | {a} — {t} | {d} | `{pth}` | {fe} |")
w("")

# 10. géneros fuera de la lista corta (generos.MAPA); los arregla el paso 6 de procesar_descarga
from generos_reglas import MAPA
fuera = collections.Counter(x["genre"] for x in info.values() if x["genre"] and x["genre"] not in MAPA)
w(f"## 10. Géneros fuera de la lista de 20 ({sum(fuera.values())} canciones)\n")
w("Se corrigen con `generos.py --execute` (lo hace solo el procesado). Si un género nuevo de Deezer no está en el mapa, agregarlo a MAPA en `generos.py`.\n")
for g, c in fuera.most_common():
    w(f"- {g}: {c}")
w("")

# 11. discos que numeros_pista.py no pudo numerar solo (su última corrida, planes/plan-tracknums.json)
try:
    a_mano = json.load(open(plan_path("plan-tracknums.json"), encoding="utf-8")).get("manual", [])
except (OSError, ValueError):
    a_mano = []
w(f"## 11. Discos con números de pista a revisar a mano ({len(a_mano)})\n")
w("`numeros_pista.py` numera cada disco con una edición de Deezer (o MusicBrainz) que tenga TODAS sus canciones. Estos no la "
  "tienen y quedaron con números repetidos o nombres que no cuadran. Casi siempre una canción es otra versión (dura distinto): "
  "escucharla; si está mal, `borrar_canciones.py --motivo equivocada`; si está bien, numerar el disco a mano.\n")
for d, why in a_mano:
    w(f"- `{os.path.relpath(d, ROOT)}` — {why}")
w("")

if os.path.exists(NOTAS):
    w(open(NOTAS, encoding="utf-8").read())

# ---------- documento aparte: conseguir en FLAC ----------
F = []
def enlace(dz, sid, buscar=""):
    import urllib.parse
    return (f"[Deezer](https://www.deezer.com/track/{dz})" if dz else "") + (" · " if dz and sid else "") + \
           (f"[Spotify](https://open.spotify.com/track/{sid})" if sid else "") or \
           (f"[buscar en Deezer](https://www.deezer.com/search/{urllib.parse.quote(buscar)})" if buscar else "—")
perd = sorted(((i, x) for i, x in info.items() if x["perdida"]), key=lambda r: (r[1]["aa"].lower(), r[1]["title"].lower()))
F.append("# Música — conseguir en FLAC\n")
F.append("Generado por `~/music-tools/revisar.py` (lo corre el procesado; también se puede correr solo). Cuando consigas una: "
         "pega su enlace en Antra (acepta Deezer y Spotify) y procésala como siempre; el procesado se queda con el FLAC, le "
         "pasa las escuchas y la canción desaparece de aquí sola.\n")
F.append(f"## 1. En la biblioteca con pérdida ({len(perd)})\n")
F.append("Entraron así porque no había FLAC: descargas a mano (AAC/Opus) o MP3 de prueba que se escucharon mucho (ganaron "
         "el FLAC) y Antra no lo consiguió en 14 días.\n")
if perd:
    F.append("| Artista | Canción | Disco | Formato | Origen | Buscar |\n|---|---|---|---|---|---|")
    for i, x in perd:
        ext = os.path.splitext(where(i))[1].lstrip(".").upper()
        F.append(f"| {x['artist']} | {x['title']} | {x['album']} | {ext} {x['kbps']} kbps | {x['origen'] or '—'} | "
                 f"{enlace(x['dz'], x['sid'], x['artist'] + ' ' + x['title'])} |".replace("\n", " "))
else:
    F.append("Nada: todo está sin pérdida.")
F.append("")
try:
    est = json.load(open(os.path.join(HERE, "prueba-estado.json"), encoding="utf-8"))
except (OSError, ValueError):
    est = {}
esperan = sorted((r, e) for r, e in est.items() if e.get("promovida"))
F.append(f"## 2. De prueba: ganaron el FLAC y lo esperan ({len(esperan)})\n")
F.append("Están en `_Prueba` (MP3 128). Su enlace también está en `PARA-FLAC.txt` (carpeta de listas). Si a los 14 "
         "días de ganarlo no llegó, entran a la biblioteca en MP3 y pasan a la sección 1.\n")
if esperan:
    import datetime as _dt
    F.append("| Canción (archivo de prueba) | Ganó el FLAC | Entra en MP3 el | Buscar |\n|---|---|---|---|")
    for r, e in esperan:
        dia = (_dt.date.fromisoformat(e["promovida"]) + _dt.timedelta(days=14)).isoformat()
        F.append(f"| `{r}` | {e['promovida']} | {dia} | {enlace(e.get('deezer'), '')} |")
else:
    F.append("Ninguna por ahora.")
open(DOC_FLAC, "w", encoding="utf-8").write("\n".join(F) + "\n")
print(f"Escrito: {DOC_FLAC} ({len(perd)} con pérdida, {len(esperan)} de prueba esperando el FLAC)")
open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
print(f"Escrito: {OUT}")
print(f"  a conseguir {len(pend)} | dudosas {len(dud)} | duplicados {len(dups)} grupos | géneros fuera de lista {sum(fuera.values())} | sin carátula {sum(not x['pic'] for x in info.values())} | sin MBID {sum(not x['mbid'] for x in info.values())} | "
      f"sin género {sum(not x['genre'] for x in info.values())} | sin fecha {sum(not x['date'] for x in info.values())} | "
      f"sin letra {sum(nolyr.values())} | álbumes con años mezclados {len(mix)}")
