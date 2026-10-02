#!/usr/bin/env python3
"""Arma una playlist .m3u con las canciones del historial de Spotify de alguien que están en la biblioteca.

Uso: playlist_historial.py <zip del historial> <nombre> [--min-plays N] [--sin-escuchar DIAS] [--titulo T] [--execute]
  Una "escucha" = >=30 s. Busca cada canción por spotify_id y, si no, por (primer artista, título) con la regla
  única de comun.py (un remix o una versión en vivo NO cuentan como la original).
  --sin-escuchar DIAS: solo canciones que no sonaron en los últimos DIAS días del historial ("olvidadas").
  --titulo T: nombre que muestra Navidrome (línea #PLAYLIST:), para que el archivo se llame distinto, p. ej.
    "<Persona> - Rescate" con título "Rescate" (si otra persona ya tiene un Rescate.m3u).
  Orden: más escuchadas primero. Sin --execute solo muestra números.
  Escribe <biblioteca>/_Playlists/<nombre>.m3u (rutas ../Artista/Año - Álbum/…).
"""
import collections, datetime, os, sys

from comun import ROOT, historial_en_biblioteca, cerrojo   # regla única de "misma canción"
zpath, name = sys.argv[1], sys.argv[2]
MIN = int(sys.argv[sys.argv.index("--min-plays") + 1]) if "--min-plays" in sys.argv else 0
DIAS = int(sys.argv[sys.argv.index("--sin-escuchar") + 1]) if "--sin-escuchar" in sys.argv else None
TITULO = sys.argv[sys.argv.index("--titulo") + 1] if "--titulo" in sys.argv else None
EXECUTE = "--execute" in sys.argv

found = [(d["plays"], d["last"], rel) for rel, d in historial_en_biblioteca(zpath).items()]
hist = collections.Counter(min(p, 5) for p, _, _ in found)
print(f"en la biblioteca: {len(found)} | por escuchas (5 = 5 o más): {dict(sorted(hist.items()))}")
sel = [x for x in found if x[0] >= MIN]
if DIAS is not None:
    fin = datetime.datetime.fromisoformat(max(l for _, l, _ in found).replace("Z", "+00:00"))
    corte = (fin - datetime.timedelta(days=DIAS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sel = [x for x in sel if x[1] < corte]
    print(f"sin escuchar desde {corte[:10]}")
sel.sort(key=lambda x: (-x[0], x[1]))
print(f"con >= {MIN} escuchas: {len(sel)}")
if EXECUTE:
    cerrojo("playlist_historial.py")
    out = os.path.join(ROOT, "_Playlists", f"{name}.m3u")
    with open(out, "w", encoding="utf-8") as o:
        o.write("#EXTM3U\n" + (f"#PLAYLIST:{TITULO}\n" if TITULO else "") + "".join(f"../{r}\n" for _, _, r in sel))
    print("escrito:", out)
