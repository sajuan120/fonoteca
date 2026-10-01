#!/usr/bin/env python3
"""Entra a la biblioteca canciones bajadas A MANO, fuera de Antra, en cualquier formato (30 sep 2026: reemplaza a los
puntuales importar-faltantes-manual y volver-formato-original).

Uso: importar_manual.py "<carpeta con las descargas>" [--execute]
     Sin --execute solo muestra. Después: procesar_descarga.py "<carpeta que dice>" (simular → ejecutar), como una
     descarga de Antra: el procesado hace lo de siempre (MusicBrainz, géneros, números, letras, ReplayGain…).

Por cada archivo (FLAC, MP3, M4A, Ogg/Opus):
  1. ¿Es una de las que FALTABAN? Se busca entre las «a conseguir» (revisar_fallidas.tsv) por artista + canción, y se
     compara con la canción EXACTA de Spotify: misma duración (±max(3 s, 1 %)) y su vista previa de 30 s (parecido ≥ 0,85;
     sin vista previa, basta la duración). Si lo es → se le pone su spotify_id: vuelve a sus playlists y sale de «a
     conseguir». Si no (otra versión, un cover) → entra igual, con su nombre real y SIN spotify_id (regla del 28 sep:
     «agregar sin reemplazar»).
  2. Se completa lo que el procesado necesita y no siempre trae: disco, artista del disco, fecha, número de pista y disco,
     sello y carátula (Deezer por su ISRC; la fecha, si no, de la página de Spotify).
  3. Se COPIA (el original queda donde estaba) a «<biblioteca>/manual-<fecha>/» en su MISMO formato (regla del 29 sep:
     una descarga con pérdida no se convierte a FLAC: no gana calidad) con la etiqueta ORIGEN. Si es con pérdida, sale
     en «Música - conseguir en FLAC» hasta que aparezca la versión sin pérdida.
"""
import datetime, os, re, shutil, subprocess, sys, tempfile
from mutagen.flac import Picture
from audio import abrir, con_perdida, es_audio
from comun import (ROOT, a_conseguir, antra_abierto, clave_artista, clave_titulo, dura_distinto, duracion_spotify,
                   parecido_spotify, spotify_cancion)
from red import Cache, pedir_bytes, pedir_json

args = sys.argv[1:]
if not args or args[0].startswith("-"):
    sys.exit(__doc__)
SRC = os.path.abspath(os.path.expanduser(args[0]))
EXECUTE = "--execute" in args
HOY = datetime.date.today().isoformat()
DEST = os.path.join(ROOT, f"manual-{HOY}")
dz = Cache("deezer-cache.json")
if not os.path.isdir(SRC):
    sys.exit(f"No existe la carpeta {SRC}")
archivos = sorted(os.path.join(d, f) for d, _, fs in os.walk(SRC) for f in fs if es_audio(f))
if not archivos:
    sys.exit("No hay audio en esa carpeta.")
faltan = a_conseguir()
por_clave = {}
for origen, art, tit, alb, sid in faltan:
    if sid:
        for a in re.split(r",\s*|\s+&\s+|\s+feat\.?\s+", art):
            por_clave.setdefault((clave_artista(a), clave_titulo(tit)), []).append((sid, art, tit))


def es_la_que_faltaba(p, artistas, titulo):
    """(spotify_id, artista, título, motivo) si el archivo ES una de las que faltaban; (None, …, motivo) si no."""
    dur = abrir(p).info.length
    for a in artistas:
        for sid, art, tit in por_clave.get((clave_artista(a), clave_titulo(titulo)), []):
            sp = duracion_spotify(sid)
            if sp is not None and dura_distinto(dur, sp):
                return None, art, tit, f"otra versión: dura {dur - sp:+.0f} s distinto a la de Spotify"
            sim = parecido_spotify(sid, p)
            if sim is not None and sim < 0.85:
                return None, art, tit, f"otro audio que la de Spotify (parecido {sim})"
            return sid, art, tit, f"ES la que faltaba ({'parecido ' + str(sim) if sim is not None else 'sin vista previa; misma duración'})"
    return None, "", "", "no está entre las que faltaban"


def datos_deezer(isrc):
    tr = (pedir_json(f"https://api.deezer.com/track/isrc:{isrc}", dz) or {}) if isrc else {}
    if not tr.get("id"):
        return {}
    al = pedir_json(f"https://api.deezer.com/album/{tr['album']['id']}", dz) or {}
    return dict(album=al.get("title", ""), albumartist=(al.get("artist") or {}).get("name", ""), date=al.get("release_date", ""),
                track=tr.get("track_position"), disc=tr.get("disk_number"), cover=al.get("cover_xl", ""), label=al.get("label", ""))


plan = []
for p in archivos:
    t = abrir(p); g = lambda k: (t.get(k) or [""])[0]
    titulo = g("title") or re.sub(r"^\d+\s*-\s*", "", os.path.splitext(os.path.basename(p))[0])
    artistas = [a for v in (t.get("artist") or []) for a in re.split(r";\s*", v) if a] or [g("albumartist")]
    isrc = g("isrc").upper()
    sid, art_f, tit_f, motivo = es_la_que_faltaba(p, artistas, titulo)
    d = datos_deezer(isrc)
    # la del archivo; si no, el año de su canción de Spotify (el que pondría Antra); si no, la del disco en Deezer (puede ser
    # una reedición: «Talento de Barrio» sale 2025)
    fecha = g("date") or ((spotify_cancion(sid) or {}).get("anio") if sid else "") or d.get("date")
    plan.append(dict(src=p, sid=sid, motivo=motivo, titulo=titulo, artistas=artistas, isrc=isrc,
                     album=g("album") or d.get("album") or titulo, albumartist=g("albumartist") or d.get("albumartist") or artistas[0],
                     fecha=fecha, pista=g("tracknumber") or d.get("track") or 1, disco=g("discnumber") or d.get("disc") or 1,
                     sello=g("organization") or d.get("label", ""), cover=d.get("cover", ""), perdida=con_perdida(p),
                     dest=os.path.join(DEST, os.path.basename(p))))
for x in plan:
    print(f"{'✓' if x['sid'] else '·'} {' / '.join(x['artistas'])} – {x['titulo']}   [{x['motivo']}]\n"
          f"      disco «{x['album']}» ({x['albumartist']}, {x['fecha'] or 'SIN FECHA'}, pista {x['pista']})"
          f"{' · con pérdida (entra en su formato)' if x['perdida'] else ''}")
sin_fecha = [x["titulo"] for x in plan if not x["fecha"]]
if sin_fecha:
    sys.exit("Les falta la fecha (ponla en el archivo y repite): " + ", ".join(sin_fecha))
if not EXECUTE:
    sys.exit(f"\nSimulación: {len(plan)} archivo(s), {sum(1 for x in plan if x['sid'])} eran de las que faltaban. Usa --execute.")
if antra_abierto():
    sys.exit("Antra está abierto: ciérralo y reintenta.")
os.makedirs(DEST, exist_ok=True)
for x in plan:
    n, dst = 2, x["dest"]
    while os.path.exists(dst):
        dst = f"{os.path.splitext(x['dest'])[0]} ({n}){os.path.splitext(x['dest'])[1]}"; n += 1
    shutil.copy2(x["src"], dst)
    t = abrir(dst)
    t["title"] = [x["titulo"]]; t["artist"] = x["artistas"]; t["album"] = [x["album"]]; t["albumartist"] = [x["albumartist"]]
    t["date"] = [x["fecha"]]; t["tracknumber"] = [str(x["pista"]).split("/")[0]]; t["discnumber"] = [str(x["disco"]).split("/")[0]]
    if x["isrc"]: t["isrc"] = [x["isrc"]]
    if x["sello"]: t["organization"] = [x["sello"]]
    if x["sid"]: t["spotify_id"] = [x["sid"]]
    t["origen"] = [f"descarga a mano {HOY} (fuera de Antra)"]
    if not t.pictures:   # sin carátula: la del archivo con ffmpeg (a veces viene como pista de video) o la de Deezer
        data = None
        with tempfile.TemporaryDirectory() as tmp:
            cov = os.path.join(tmp, "cover.jpg")
            if subprocess.run(["ffmpeg", "-v", "error", "-i", x["src"], "-an", "-c:v", "copy", cov]).returncode == 0 and os.path.getsize(cov) > 0:
                data = open(cov, "rb").read()
        data = data or (pedir_bytes(x["cover"]) if x["cover"] else None)
        if data:
            pc = Picture(); pc.type = 3; pc.mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"; pc.data = data
            t.add_picture(pc)
    t.save()
    print("   →", os.path.relpath(dst, ROOT))
dz.guardar()
print(f'HECHO: {len(plan)} en {DEST}. Siguiente: python3 procesar_descarga.py "{os.path.basename(DEST)}"')
