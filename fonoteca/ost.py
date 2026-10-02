#!/usr/bin/env python3
"""BANDAS SONORAS por obra: un disco «Soundtrack <Obra>» por franquicia (30 sep 2026: reemplaza a los puntuales
ost-por-franquicia, ost-chicas-a-su-disco, ost-persona-atlus y ost-persona-a-va).

Uso: ost.py [--execute] [--seguir]
Mapa (lo decide cada biblioteca): decisiones/ost-franquicias.json = {"<Obra>": ["<Artista>/<Año> - <Disco>", …], …}
  p. ej. «Hades»: los discos de Hades y de Hades II; «Persona»: todos los de Persona. Covers de fans NO son banda sonora.

Reglas (decididas el 28 y el 30 sep):
  · MÍNIMO 3 canciones por obra: con 1 o 2 no es un soundtrack, se quedan en su disco con su artista.
  · Carpeta «Soundtracks/<año más antiguo> - Soundtrack <Obra>», artista del disco «Soundtracks» (una sola página de
    artista); cada canción CONSERVA su artista y su fecha (en ORIGINALDATE); números 1..N por orden de publicación
    (fecha, disco, pista); YEAR = año del disco (sin YEAR Navidrome parte el disco); carátula del disco que más aporta;
    sin los IDs de disco de MusicBrainz, código de barras, totales ni ReplayGain de disco (replaygain.py lo rehace).
  · Géneros: los de SU artista + «Soundtrack» (generos.py), para que salgan en los mixes de su género.
  · Si la obra YA tiene su «Soundtrack <Obra>», las canciones nuevas se SUMAN y se renumera todo por fecha.
  · Lo que ya está agrupado o no existe se salta solo: correrlo de nuevo no cambia nada.
State de Antra, playlists y listas al día (comun.cambiar_rutas); respaldo de las etiquetas en respaldos/tags-antes-ost-<hora>.json.
Después (con --seguir se hace solo): replaygain.py <carpetas> --forzar --execute, generos.py --execute y nd_actualizar.py (aplica los logs pendientes).
"""
import datetime, glob, json, os, re, subprocess, sys
from audio import abrir, es_audio
from comun import HERE, ROOT, RESPALDOS, LOGS, antra_abierto, cambiar_rutas, decision, state_leer, guardar_json

EXECUTE, SEGUIR = "--execute" in sys.argv, "--seguir" in sys.argv
if any(a in ("-h", "--help") for a in sys.argv[1:]):
    sys.exit(__doc__)
AA, MINIMO = "Soundtracks", 3
BAD = str.maketrans({c: "_" for c in '/\\:*?"<>|'})
QUITAR = ("musicbrainz_albumid", "musicbrainz_albumartistid", "musicbrainz_releasegroupid", "musicbrainz_releasetrackid",
          "releasecountry", "releasestatus", "barcode", "catalognumber", "media", "script", "asin", "totaltracks",
          "tracktotal", "totaldiscs", "disctotal", "replaygain_album_gain", "replaygain_album_peak", "compilation")
MAPA_P = decision("ost-franquicias.json")
if not os.path.exists(MAPA_P):
    sys.exit(f"Falta el mapa de obras: {MAPA_P} (ver el ejemplo en ejemplos/decisiones/).")
MAPA = json.load(open(MAPA_P, encoding="utf-8"))
num = lambda v: int(re.match(r"\d+", (v or ["0"])[0]).group()) if re.match(r"\d+", (v or ["0"])[0]) else 0
ST = os.path.join(ROOT, AA)
EN_CURSO = os.path.join(LOGS, "ost-en-curso.json")   # 2 oct: los renombres pendientes, por si se corta a mitad


def recuperar():
    """Un agrupado cortado entre los dos pasos del renombrado dejaba archivos .ost-tmp-N que nadie veía (2 oct): si quedó
    ost-en-curso.json se terminan esos renombres y se anotan; un .ost-tmp-N sin registro recibe el nombre de sus etiquetas."""
    if os.path.exists(EN_CURSO):
        ec = json.load(open(EN_CURSO, encoding="utf-8"))
        print(f"⚠️ Quedó un agrupado a medias ({ec.get('fecha', '?')}): termino los renombres.")
        mover = {}
        for viejo, tp, n in ec["tmp"]:
            if os.path.exists(tp) and not os.path.exists(n):
                os.makedirs(os.path.dirname(n), exist_ok=True); os.rename(tp, n)
            if os.path.exists(n) and not os.path.exists(viejo): mover[viejo] = n
        if mover: cambiar_rutas(mover, "ost-recuperado")
        os.remove(EN_CURSO); print(f"   terminado: {len(mover)} canciones.")
    for tp in [os.path.join(d, f) for d, _, fs in os.walk(ROOT) for f in fs if re.match(r"^\.ost-tmp-\d+\.", f)]:
        try:
            t = abrir(tp); g = lambda k: (t.get(k) or [""])[0]
            n = os.path.join(os.path.dirname(tp), f"{num(t.get('tracknumber')):02d} - {(g('title') or 'sin titulo').translate(BAD)}{os.path.splitext(tp)[1]}")
            if os.path.exists(n): print(f"   ⚠️ {tp}: no lo renombro, ya existe {n}"); continue
            os.rename(tp, n); cambiar_rutas({tp: n}, "ost-recuperado")
            print(f"   ⚠️ archivo escondido recuperado: {os.path.relpath(n, ROOT)} (su ruta anterior no se conoce)")
        except Exception as e:
            print(f"   ⚠️ no pude recuperar {tp}: {e}")


recuperar()


def existente(obra):
    """La carpeta «Soundtrack <Obra>» que ya hay (por la etiqueta album de sus canciones), o None."""
    for d in sorted(glob.glob(os.path.join(glob.escape(ST), "*"))):
        fs = [f for f in os.listdir(d) if es_audio(f)] if os.path.isdir(d) else []
        if fs and (abrir(os.path.join(d, fs[0])).get("album") or [""])[0] == f"Soundtrack {obra}":
            return d
    return None


plan, errores = [], []
for obra, carpetas in sorted(MAPA.items()):
    ya = existente(obra)
    nuevas, aporta = [], {}
    for c in carpetas:
        d = os.path.join(ROOT, c)
        if not os.path.isdir(d) or os.path.normpath(d) == os.path.normpath(ya or ""):
            continue   # ya agrupada (la carpeta vieja no existe) o es la del soundtrack
        fs = sorted(f for f in os.listdir(d) if es_audio(f))
        otros = [f for f in os.listdir(d) if not es_audio(f) and not f.startswith(".")]
        if otros: errores.append(f"otros archivos en {c}: {otros}")
        for f in fs:
            p = os.path.join(d, f)
            if os.stat(p).st_nlink > 1: errores.append(f"hardlink: {c}/{f}"); continue
            nuevas.append(p); aporta[c] = aporta.get(c, 0) + 1
    if not nuevas:
        continue
    viejas = [os.path.join(ya, f) for f in sorted(os.listdir(ya)) if es_audio(f)] if ya else []
    if len(viejas) + len(nuevas) < MINIMO:
        print(f"  (se queda suelta: {obra}, {len(nuevas)} canción(es) — mínimo {MINIMO})")
        continue
    canc = []
    for p in viejas + nuevas:
        t = abrir(p); g = lambda k: (t.get(k) or [""])[0]
        canc.append(dict(p=p, vieja=p in viejas, fecha=(g("originaldate") if p in viejas else "") or g("date") or "9999",
                         disco=num(t.get("discnumber")), pista=num(t.get("tracknumber")), titulo=g("title") or os.path.splitext(os.path.basename(p))[0]))
    canc.sort(key=lambda x: (x["fecha"][:10], not x["vieja"], os.path.dirname(x["p"]), x["disco"], x["pista"], x["titulo"]))
    fecha = canc[0]["fecha"]
    album = f"Soundtrack {obra}"
    final = os.path.join(ST, f"{fecha[:4]} - {album.translate(BAD)}")
    if not ya and os.path.exists(final): errores.append(f"ya existe y no es de esta obra: {final}")
    ancho = 3 if len(canc) >= 100 else 2
    for i, x in enumerate(canc, 1):
        x.update(i=i, n=os.path.join(final, f"{i:0{ancho}d} - {x['titulo'].translate(BAD)}{os.path.splitext(x['p'])[1].lower()}"))
    if len({x["n"] for x in canc}) != len(canc): errores.append(f"dos canciones con el mismo nombre en {obra}")
    portada = (max(aporta, key=aporta.get) if not ya else None)
    plan.append(dict(obra=obra, album=album, final=final, ya=ya, fecha=fecha, canc=canc, portada=portada))
    print(f"  {os.path.relpath(final, ROOT)}  ({len(viejas)} ya estaban + {len(nuevas)} nuevas de {len(aporta)} disco(s))")
print(f"\n{len(plan)} disco(s) «Soundtrack X» a armar o completar")
if errores: sys.exit("\n".join(errores))
if not EXECUTE: sys.exit("Simulación: no se tocó nada. Usa --execute (y --seguir para ReplayGain, géneros y Navidrome).")
if antra_abierto(): sys.exit("Antra está abierto: ciérralo y reintenta.")

state_leer()   # 2 oct: falla ANTES de tocar nada si el state de Antra no tiene su formato
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
mover, finales = {}, []
# 2 oct: respaldo de etiquetas y plan de renombres ANTES de tocar nada (antes iban al final: un corte los perdía)
antes = {x["p"]: list(abrir(x["p"]).tags) for p in plan for x in p["canc"]}
guardar_json(os.path.join(RESPALDOS, f"tags-antes-ost-{stamp}.json"), antes)
renombres = [(x["p"], os.path.join(os.path.dirname(x["p"]), f".ost-tmp-{x['i']}{os.path.splitext(x['p'])[1]}"), x["n"])
             for p in plan for x in p["canc"] if x["n"] != x["p"]]
guardar_json(EN_CURSO, {"fecha": datetime.datetime.now().isoformat(timespec="seconds"), "tmp": renombres}, indent=1)
try:
  for p in plan:
    if p["portada"]:
        pd = os.path.join(ROOT, p["portada"])
        pic = next((abrir(os.path.join(pd, f)).pictures[0] for f in sorted(os.listdir(pd))
                    if es_audio(f) and abrir(os.path.join(pd, f)).pictures), None)
    else:   # se suma a un soundtrack que ya existe: su carátula
        pic = next((abrir(x["p"]).pictures[0] for x in p["canc"] if x["vieja"] and abrir(x["p"]).pictures), None)
    tmp = []
    for x in p["canc"]:
        t = abrir(x["p"])
        if not x["vieja"] and not t.get("originaldate") and t.get("date"): t["originaldate"] = t["date"]
        t["album"] = [p["album"]]; t["albumartist"] = [AA]; t["date"] = [p["fecha"]]; t["year"] = [p["fecha"][:4]]
        t["tracknumber"] = [str(x["i"])]; t["discnumber"] = ["1"]
        for q in QUITAR: t.pop(q, None)
        if pic and not x["vieja"]: t.clear_pictures(); t.add_picture(pic)
        t.save()
        if x["n"] != x["p"]:   # en dos pasos: renumerar un soundtrack que ya existe no choca consigo mismo
            tp = os.path.join(os.path.dirname(x["p"]), f".ost-tmp-{x['i']}{os.path.splitext(x['p'])[1]}")
            os.rename(x["p"], tp); tmp.append((tp, x["n"])); mover[x["p"]] = x["n"]
    os.makedirs(p["final"], exist_ok=True); finales.append(p["final"])
    for tp, n in tmp:
        assert not os.path.exists(n), n
        os.rename(tp, n)
    for d in {os.path.dirname(x["p"]) for x in p["canc"]}:
        while d != ROOT and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d); d = os.path.dirname(d)
except BaseException as e:   # 2 oct: también Ctrl+C / DETENER: lo ya movido queda anotado; los .ost-tmp-N los termina recuperar()
    hecho = {v: n for v, _, n in renombres if os.path.exists(n) and not os.path.exists(v)}
    if hecho: cambiar_rutas(hecho, "ost")
    print(f"\n⚠️ Se cortó ({e!r}): {len(hecho)} canciones ya en su sitio quedaron anotadas; lo que quedó con nombre .ost-tmp-N se "
          "termina solo en la próxima corrida de ost.py.")
    raise
os.remove(EN_CURSO)
log = cambiar_rutas(mover, "ost")
print(f"HECHO: {len(mover)} canciones en {len(plan)} disco(s) «Soundtrack X». Log: {log}")
if not SEGUIR:
    print("Siguiente: replaygain.py <carpetas> --forzar --execute · generos.py --execute · nd_actualizar.py   (o --seguir)")
    sys.exit()
for cmd in (["replaygain.py", *finales, "--forzar", "--execute"], ["generos.py", "--execute"]):
    print(f"\n=== {cmd[0]}", flush=True)
    if subprocess.run([sys.executable, os.path.join(HERE, cmd[0]), *cmd[1:]]).returncode != 0:
        sys.exit(f"Falló {cmd[0]}: sigue a mano desde ahí (nd_actualizar.py al final: los logs quedaron pendientes).")
subprocess.run([sys.executable, os.path.join(HERE, "nd_actualizar.py")])   # 2 oct: aplica todos los logs pendientes
