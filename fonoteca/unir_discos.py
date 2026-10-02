#!/usr/bin/env python3
"""Une discos (o canciones sueltas) en UNO solo, sin perder escuchas ni playlists (30 sep 2026: reemplaza a los puntuales
que lo hacían con los casos escritos adentro: unir-ediciones, unir-ediciones-a-mano, unir-donda-wtt, unir-dawn-fm,
unir-come-play-arcane, sencillos-a-su-disco, mas-unificar, unificar-disco-nuevas).

Uso: unir_discos.py <destino> <otra> [<otra> …] [--execute] [--seguir]
     unir_discos.py --lista <grupos.tsv> [--execute] [--seguir]      (una línea por grupo: destino<TAB>otra<TAB>otra…)
  <destino>: la carpeta del disco que queda (la edición más completa: su nombre, sello y carátula).
  <otra>:    carpetas de otras ediciones del mismo disco, o canciones sueltas que son de ese disco.
  Rutas relativas a la biblioteca (o completas). Sin --execute solo muestra.

Regla (la de las ediciones del 27-28 sep):
  · Carpeta final «Artista/<año más antiguo del grupo> - <disco del destino>»: el disco queda con su AÑO ORIGINAL.
  · Las que llegan toman del destino: nombre del disco, sello, fecha y carátula; se les quitan los IDs de disco de
    MusicBrainz, código de barras, totales y ReplayGain de disco (los rehacen mb_disco.py y replaygain.py) y quedan
    con nombre provisional «9NN - Título» hasta que numeros_pista.py las numera con el disco de Deezer.
  · Una que YA está en el destino (misma grabación: ISRC + duración, o mismo título + duración ±3 s) no se repite: es
    una copia → va a respaldos y sus escuchas, playlists y state pasan a la del destino (como quitar_copia.py).
  · State de Antra, playlists .m3u y listas de decisiones al día (comun.cambiar_rutas); respaldo de las etiquetas en
    respaldos/tags-antes-unir-<hora>.json.
Después (con --seguir se hace solo, en este orden): numeros_pista.py --execute, mb_disco.py <carpetas> --execute,
replaygain.py <carpetas> --forzar --execute y nd_actualizar.py (aplica los logs pendientes: escuchas a la ruta nueva).
"""
import datetime, os, re, shutil, subprocess, sys
from audio import abrir, es_audio
from comun import HERE, ROOT, RESPALDOS, antra_abierto, cambiar_rutas, clave_titulo, dura_distinto, state_leer, guardar_json

args = sys.argv[1:]
EXECUTE, SEGUIR = "--execute" in args, "--seguir" in args
if not args or args[0] in ("-h", "--help"):
    sys.exit(__doc__)
A = lambda r: os.path.normpath(r if os.path.isabs(r) else os.path.join(ROOT, r))
BAD = str.maketrans({c: "_" for c in '/\\:*?"<>|'})
QUITAR = ("musicbrainz_albumid", "musicbrainz_releasegroupid", "musicbrainz_releasetrackid",
          "releasecountry", "releasestatus", "barcode", "catalognumber", "media", "script", "asin", "totaltracks",
          "tracktotal", "totaldiscs", "disctotal", "replaygain_album_gain", "replaygain_album_peak", "compilation")
grupos = []
if "--lista" in args:
    for l in open(args[args.index("--lista") + 1], encoding="utf-8"):
        c = [x for x in l.rstrip("\n").split("\t") if x]
        if len(c) >= 2 and not l.startswith("#"):
            grupos.append((A(c[0]), [A(x) for x in c[1:]]))
else:
    libres = [x for x in args if not x.startswith("--")]
    if len(libres) < 2:
        sys.exit("Hace falta el destino y al menos una carpeta o canción para unirle.")
    grupos.append((A(libres[0]), [A(x) for x in libres[1:]]))


def audios_de(p):
    return [p] if os.path.isfile(p) else sorted(os.path.join(p, f) for f in os.listdir(p) if es_audio(f))


def info(f):
    t = abrir(f); g = lambda k: (t.get(k) or [""])[0]
    return dict(f=f, t=t, titulo=g("title"), kt=clave_titulo(g("title")), isrcs={x.upper() for x in t.get("isrc") or []},
                dur=t.info.length, fecha=g("date"))


def misma(a, b):
    """Misma grabación: ISRC y duración, o el mismo título (regla única) y duración."""
    if dura_distinto(a["dur"], b["dur"]):
        return False
    return bool(a["isrcs"] & b["isrcs"]) or (a["kt"] and a["kt"] == b["kt"])


plan, problemas = [], []
for dest, otras in grupos:
    if not os.path.isdir(dest):
        problemas.append(f"el destino no es una carpeta: {dest}"); continue
    if not os.path.realpath(dest).startswith(os.path.realpath(ROOT) + os.sep):
        problemas.append(f"el destino no está dentro de la biblioteca: {dest}"); continue
    for o in otras:   # 2 oct: el destino también en OTRAS (escrito distinto) lo mandaba ENTERO a respaldos como «copia»
        if os.path.realpath(o) == os.path.realpath(dest) or os.path.realpath(o).startswith(os.path.realpath(dest) + os.sep):
            problemas.append(f"el destino no puede estar también en las otras: {o}"); continue
        if not os.path.realpath(o).startswith(os.path.realpath(ROOT) + os.sep):
            problemas.append(f"no está dentro de la biblioteca: {o}"); continue
        if not os.path.exists(o): problemas.append(f"no existe: {o}")
        elif os.path.isdir(o) and [f for f in os.listdir(o) if not es_audio(f) and not f.startswith(".")]:
            problemas.append(f"hay otros archivos (no audio) en {o}: revisar a mano")
    if problemas: continue
    ds = [info(f) for f in audios_de(dest)]
    if not ds:
        problemas.append(f"el destino no tiene canciones: {dest}"); continue
    llegan = [info(f) for o in otras for f in audios_de(o)]
    for x in ds + llegan:
        if os.stat(x["f"]).st_nlink > 1: problemas.append(f"tiene otros nombres (hardlink): {x['f']}")
    t0 = ds[0]["t"]
    album = (t0.get("album") or [""])[0]
    fecha = min((x["fecha"] for x in ds + llegan if x["fecha"]), default=ds[0]["fecha"])
    final = os.path.join(os.path.dirname(dest), f"{fecha[:4]} - {album.translate(BAD)}" if fecha[:4].isdigit() else album.translate(BAD))
    if final != dest and os.path.exists(final):
        problemas.append(f"la carpeta final ya existe (¿otro disco con el mismo nombre?): {final}")
    if len({x["f"] for x in llegan}) != len(llegan):
        problemas.append(f"una canción aparece dos veces en las otras: {dest}")
    copias = {x["f"]: next((d["f"] for d in ds if d["f"] != x["f"] and misma(x, d)), None) for x in llegan}
    plan.append(dict(dest=dest, otras=otras, final=final, fecha=fecha, album=album, ds=ds, llegan=llegan, copias=copias,
                     org=t0.get("organization"), pic=(t0.pictures or [None])[0],
                     # Navidrome agrupa el disco por artista del disco (y su ID de MusicBrainz), nombre y fecha: se copian
                     aa=t0.get("albumartist"), aaid=t0.get("musicbrainz_albumartistid")))
    print(f"\n  {os.path.relpath(final, ROOT)}   (año {fecha[:4]}; {len(ds)} del destino)")
    for x in llegan:
        q = copias[x["f"]]
        print(f"     {'= copia de ' + os.path.basename(q) if q else '← se une'}:  {os.path.relpath(x['f'], ROOT)}")
if problemas:
    sys.exit("\n".join(problemas))
if not EXECUTE:
    sys.exit(f"\nSimulación: {len(plan)} disco(s). Usa --execute (y --seguir para numerar, IDs de disco, ReplayGain y Navidrome).")
if antra_abierto():
    sys.exit("Antra está abierto: ciérralo y reintenta.")

state_leer()   # 2 oct: falla ANTES de mover nada si el state de Antra no tiene su formato
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
resp = os.path.join(RESPALDOS, f"quitadas-{stamp}")
mover, equiv, finales = {}, [], []
# 2 oct: el respaldo de las etiquetas se escribe ANTES de cambiar ninguna (antes, al final: un corte lo perdía)
antes = {x["f"]: list(x["t"].tags) for p in plan for x in p["ds"] + p["llegan"]}
guardar_json(os.path.join(RESPALDOS, f"tags-antes-unir-{stamp}.json"), antes)
try:
  for p in plan:
    fin = p["final"]; os.makedirs(fin, exist_ok=True); finales.append(fin)
    k = 900 + max([int(m.group(1)) - 900 for f in os.listdir(p["dest"]) for m in [re.match(r"^(9\d\d) - ", f)] if m] or [0])
    for x in p["ds"]:   # las del destino: la fecha original y, si cambió el año, su carpeta
        t = x["t"]
        t["date"] = [p["fecha"]]; t["year"] = [p["fecha"][:4]]   # sin YEAR Navidrome parte el disco
        t.save()
        n = os.path.join(fin, os.path.basename(x["f"]))
        if n != x["f"]: os.rename(x["f"], n); mover[x["f"]] = n
    destino_de = {x["f"]: mover.get(x["f"], x["f"]) for x in p["ds"]}
    for x in p["llegan"]:
        q = p["copias"][x["f"]]
        if q:   # ya está en el destino: copia → respaldo; todo lo suyo pasa a la del destino
            dst = os.path.join(resp, os.path.relpath(x["f"], ROOT)); os.makedirs(os.path.dirname(dst), exist_ok=True)
            sid = (x["t"].get("spotify_id") or [""])[0]
            if sid: equiv.append((sid, destino_de[q], f"misma grabación que «{os.path.basename(x['f'])}» (unir_discos {stamp[:8]})"))
            shutil.move(x["f"], dst); mover[x["f"]] = destino_de[q]
            continue
        t = x["t"]
        t["album"] = [p["album"]]; t["date"] = [p["fecha"]]; t["year"] = [p["fecha"][:4]]
        if p["org"]: t["organization"] = p["org"]
        for c in QUITAR: t.pop(c, None)
        for c, v in (("albumartist", p["aa"]), ("musicbrainz_albumartistid", p["aaid"])):
            if v: t[c] = v
            else: t.pop(c, None)
        if p["pic"]: t.clear_pictures(); t.add_picture(p["pic"])
        t.save()
        k += 1
        n = os.path.join(fin, re.sub(r"^(\d+-)?\d+ - ", f"{k} - ", os.path.basename(x["f"])) if re.match(r"^(\d+-)?\d+ - ", os.path.basename(x["f"]))
                         else f"{k} - {os.path.basename(x['f'])}")
        assert not os.path.exists(n), n
        os.rename(x["f"], n); mover[x["f"]] = n
    for o in [p["dest"]] + p["otras"]:   # carpetas que quedaron vacías
        d = o if os.path.isdir(o) else os.path.dirname(o)
        while d != ROOT and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d); d = os.path.dirname(d)
finally:   # 2 oct: también si se corta a mitad: lo ya movido queda anotado (state, playlists, listas, Navidrome)
    log = cambiar_rutas(mover, "unir-discos", equivalencias=equiv) if mover else None
print(f"HECHO: {len(mover)} canciones movidas o unidas en {len(finales)} disco(s). Log: {log}")
if not SEGUIR:
    print("Siguiente: numeros_pista.py --execute · mb_disco.py <carpetas> --execute · replaygain.py <carpetas> --forzar --execute"
          " · nd_actualizar.py   (o repetir con --seguir)")
    sys.exit()
rels = [os.path.relpath(f, ROOT) for f in finales]
t0 = datetime.datetime.now().timestamp()
for cmd in (["numeros_pista.py", "--execute"], ["mb_disco.py", *rels, "--execute"], ["replaygain.py", *finales, "--forzar", "--execute"]):
    print(f"\n=== {' '.join(cmd[:1])}", flush=True)
    if subprocess.run([sys.executable, os.path.join(HERE, cmd[0]), *cmd[1:]]).returncode != 0:
        sys.exit(f"Falló {cmd[0]}: sigue a mano desde ahí (nd_actualizar.py al final: los logs quedaron pendientes).")
subprocess.run([sys.executable, os.path.join(HERE, "nd_actualizar.py")])   # 2 oct: aplica todos los logs pendientes
