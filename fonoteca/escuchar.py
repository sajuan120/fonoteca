#!/usr/bin/env python3
"""Playlist para ESCUCHAR y comparar en VLC: cada archivo seguido de la vista previa de 30 s de su canción EXACTA de
Spotify. Solo lee la biblioteca; escribe planes/escuchar-<tema>.m3u (27 sep 2026; antes se armaban a mano).

Uso: escuchar.py <tema> <lista.txt>
  lista.txt: rutas relativas a la biblioteca (o completas, p. ej. una copia en respaldos/), una por línea. Una línea
  "# texto" pone ese rótulo a las que siguen.
Por cada canción muestra su duración, la de Spotify y el parecido con la vista previa (correctas 0,89-0,99; otro audio
0,50-0,75). No gasta cuota de la API: todo sale del embed público (comun.duracion_spotify / comun.parecido_spotify).
Si Spotify no tiene vista previa, pone el enlace de la canción.
"""
import json, os, sys
from audio import abrir
from comun import ROOT, PLANES, cache_path, duracion_spotify, parecido_spotify

tema, lista = sys.argv[1], sys.argv[2]
filas, grupo = [], ""
for l in open(lista, encoding="utf-8"):
    l = l.strip()
    if l.startswith("#"): grupo = l.lstrip("# ").strip()
    elif l: filas.append((grupo, l))

def vista_previa(sid):
    c = cache_path("spotify-embed-preview.json")
    return (json.load(open(c)) if os.path.exists(c) else {}).get(sid)

out = ["#EXTM3U"]
for n, (grupo, rel) in enumerate(filas, 1):
    p = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)       # ruta completa: p. ej. una copia en respaldos/
    t = abrir(p); g = lambda k: (t.get(k) or [""])[0]
    sid, largo = g("spotify_id"), t.info.length
    ds, par = duracion_spotify(sid), parecido_spotify(sid, p)
    nombre = f"{g('artist')} - {g('title')}"
    info = f"{largo:.0f} s" + (f"; en Spotify {ds:.0f} s" if ds else "") + (f"; parecido {par}" if par is not None else "; sin vista previa")
    print(f"{n:2}. [{grupo}] {nombre} — {info}", flush=True)
    out += [f"#EXTINF:{largo:.0f},{n}a {grupo + ' · ' if grupo else ''}TU ARCHIVO · {nombre} ({info})", p]
    if vista_previa(sid):
        out += [f"#EXTINF:30,{n}b VISTA PREVIA DE SPOTIFY (30 s) · {nombre}", vista_previa(sid)]
    elif sid:
        out += [f"#EXTINF:0,{n}b SIN VISTA PREVIA: ABRIR EN SPOTIFY · {nombre}", f"https://open.spotify.com/track/{sid}"]
dest = os.path.join(PLANES, f"escuchar-{tema}.m3u")
open(dest, "w", encoding="utf-8").write("\n".join(out) + "\n")
print("→", dest)
