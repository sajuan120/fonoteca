#!/usr/bin/env python3
"""Paso 7 del procesado: NÚMEROS DE PISTA y de disco correctos, y archivos "NN - Título.flac" (o "D-NN - …").

Uso: numeros_pista.py [--execute]        sin --execute solo muestra (plan en planes/plan-tracknums.json/.txt)
     numeros_pista.py --revert <log>     deshace una corrida (logs/tracknums-log-<fecha>.json)
     numeros_pista.py --a-mano <carpeta> --deezer <id del disco> ["Título=N" | "Título=D-N" …] [--execute]
                                         numera UNA carpeta con el disco de Deezer que le digas (30 sep: antes había
                                         un puntual por disco): las que no se emparejan solas (otro título, otra
                                         edición) se dan con "Título=N"; si falta alguna muestra la lista del disco.

Regla (27 sep 2026): Deezer es la referencia (gratis, sin depender de Spotify).
Cada carpeta Artista/Álbum de 2 o más canciones se numera contra UNA edición que contenga TODAS sus canciones:
  1. un disco de Deezer (API pública, gratis) con el MISMO nombre que la etiqueta album. Candidatos: el disco del ISRC
     de cada canción y la búsqueda artista+disco. Cada canción se empareja por ISRC + duración (±max(7 s, 3%): el
     mismo master puede durar unos segundos más en otra tienda, Banquet +5 s; y la duración igual atrapa los ISRC
     equivocados: Clint Eastwood tenía el de otra versión, 74 s distinta) o por título (regla única,
     comun.clave_titulo) + duración (±max(3 s, 1%)). Si dos ediciones con ese nombre las contienen todas pero dan
     números distintos, es ambiguo y la carpeta no se toca;
  2. si Deezer no tiene el disco: un lanzamiento de MusicBrainz (de los de sus canciones) que contenga TODAS las grabaciones.
  Si ninguna edición las contiene todas, la carpeta NO se toca: se queda con los números que tiene y, si eso deja
  números repetidos o nombres que no cuadran con las etiquetas, sale en "a mano" (plan y documento de pendientes).
"D-NN" en el nombre solo si esa edición tiene más de un disco.
Por qué (26-27 sep): antes se numeraba contra el lanzamiento de MusicBrainz "mayoritario" de la carpeta. Esos IDs apuntan
a ediciones al azar (vinilo 8+8, CD japonés de 2 discos) y con un empate 1-1 ganaba el del PRIMER archivo en orden
alfabético → al renombrar cambiaba cuál era el primero → cada corrida renombraba las mismas carpetas (Bonnie Tyler,
Cerati, Pink Floyd…). Ahora ninguna elección depende del nombre de los archivos: la 2ª corrida no cambia nada.
Con --execute: TRACKNUMBER/DISCNUMBER (y los totales de pistas/discos si el archivo los tenía); renombra en la misma
carpeta (mismo inodo: los hardlinks siguen); actualiza .antra_state.json (respaldo en respaldos/) y _Playlists/*.m3u.
Log para revertir y para que Navidrome pase las reproducciones al nombre nuevo (nd_actualizar.py).
"""
import collections, json, os, re, sys, urllib.error, urllib.parse, urllib.request
from audio import abrir, es_audio
from comun import ROOT, SKIP, cache_path, plan_path, log_path, antra_abierto, clave_titulo, cambiar_rutas, plano
from red import Cache, pedir_json

STATE = os.path.join(ROOT, ".antra_state.json")
TAGS = ("tracknumber", "discnumber", "totaltracks", "tracktotal", "totaldiscs", "disctotal")
NUM = re.compile(r"^(?:(\d+)-)?(\d+) - (.+)$")

# ---------- MusicBrainz (respaldo cuando Deezer no tiene el disco) ----------
CACHE = cache_path("mb-release-cache.json")
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}

def release(rid):
    """{'discs': n, 'by_rt': {releasetrackid: (disc, pos, total)}, 'by_rec': {recording: (disc, pos, total)}}"""
    if rid not in cache:
        d = pedir_json(f"https://musicbrainz.org/ws/2/release/{rid}?inc=recordings&fmt=json", intentos=3)   # red.py: 1/s
        if d is None:
            return None
        by_rt, by_rec = {}, {}
        media = d.get("media", [])
        for m in media:
            tot = m.get("track-count") or len(m.get("tracks", []))
            for t in m.get("tracks", []):
                v = (m.get("position", 1), t.get("position"), tot)
                by_rt[t["id"]] = v
                by_rec.setdefault(t["recording"]["id"], v)
        cache[rid] = {"discs": len(media), "by_rt": by_rt, "by_rec": by_rec}
        if len(cache) % 50 == 0: json.dump(cache, open(CACHE, "w"))
    return cache[rid]

# ---------- Deezer (la referencia) ----------
dz = Cache("deezer-cache.json", solo_leer=True)                 # caché de enriquecer.py (solo se lee)
dzn = Cache("deezer-numeros.json", cada=100)                    # discos y búsquedas que pide este script

def dz_get(url):
    """API pública de Deezer (gratis, sin cuenta), con caché. None si no respondió: una falla de red NO se guarda
    (si no, un disco quedaría como "no existe" para siempre)."""
    if url in dzn: return dzn[url]
    if url in dz and "/search" not in url: return dz[url]
    return pedir_json(url, dzn)   # red.py: 50 cada 5 s, reintenta el «demasiadas consultas», la falla de red no se guarda

def dz_disco(aid):
    """(título, fecha, [(disco, pos, isrc, título, duración)]) de un disco de Deezer. None si no respondió (red);
    () si su lista está vacía o incompleta (no sirve para numerar)."""
    a = dz_get(f"https://api.deezer.com/album/{aid}")
    tr = dz_get(f"https://api.deezer.com/album/{aid}/tracks?limit=300")
    if a is None or tr is None: return None
    items, sig = list(tr.get("data") or []), tr.get("next")
    while sig and len(items) < 2000:
        t2 = dz_get(sig)
        if t2 is None: return None
        items += t2.get("data") or []; sig = t2.get("next")
    tracks = [(t.get("disk_number") or 1, t["track_position"], (t.get("isrc") or "").upper(), t.get("title") or "",
               t.get("duration") or 0) for t in items if t.get("track_position")]
    if not tracks or (a.get("nb_tracks") and len(tracks) < a["nb_tracks"]): return ()
    return a.get("title") or "", a.get("release_date") or "", tracks

def mas_comun(valores):
    """El valor más repetido; si empatan, el primero en orden alfabético (nunca depende del orden de los archivos)."""
    c = collections.Counter(valores)
    return min(c, key=lambda v: (-c[v], v)) if c else ""

def emparejar(info, tracks):
    """({i: (disco, pos)}, n emparejadas por ISRC) de las canciones de la carpeta que están en la lista del disco."""
    res, usados, nis = {}, set(), 0
    for i, x in enumerate(info):
        for j, (dn, pos, isrc, tit, du) in enumerate(tracks):
            if j not in usados and isrc and isrc in x["isrcs"] and du and abs(du - x["len"]) <= max(7, 0.03 * du):
                res[i] = (dn, pos); usados.add(j); nis += 1; break
    for i, x in enumerate(info):
        if i in res: continue
        for j, (dn, pos, isrc, tit, du) in enumerate(tracks):
            if j not in usados and clave_titulo(tit) == x["kt"] and du and abs(du - x["len"]) <= max(3, 0.01 * du):
                res[i] = (dn, pos); usados.add(j); break
    return res, nis

def firma(m, discos):
    return tuple(sorted((i, v[0], v[1]) for i, v in m.items())) + (discos > 1,)

def edicion(info):
    """(fuente, id, discos, {i: (disco, pos)}, {disco: pistas}) de la edición que contiene TODAS las canciones,
    o (None, motivo) si no hay una segura."""
    alb = mas_comun(x["alb"] for x in info)
    aa = mas_comun(x["aa"] for x in info)
    fecha = mas_comun(x["date"] for x in info)
    # 1. Deezer: discos con el mismo nombre
    aids, sin_red = set(), False
    for x in info:
        for isrc in sorted(x["isrcs"]):
            z = dz_get(f"https://api.deezer.com/track/isrc:{isrc}")
            if z is None: sin_red = True; continue
            al = z.get("album") or {}
            if al.get("id") and plano(al.get("title")) == plano(alb): aids.add(al["id"])
    s = dz_get("https://api.deezer.com/search/album?limit=50&q=" + urllib.parse.quote(f'artist:"{aa}" album:"{alb}"'))
    if s is None: sin_red = True
    for a in (s or {}).get("data") or []:
        if plano(a.get("title")) == plano(alb): aids.add(a["id"])
    opciones = []
    for aid in sorted(aids):
        dd = dz_disco(aid)
        if dd is None: sin_red = True; continue
        if not dd: continue
        _, fd, tracks = dd
        m, nis = emparejar(info, tracks)
        if len(m) == len(info):
            discos = max(t[0] for t in tracks)
            por_disco = collections.Counter(t[0] for t in tracks)
            opciones.append((-nis, fd != fecha, fd[:4] != fecha[:4], len(tracks), aid, discos, m, por_disco))
    if opciones:
        if len({firma(o[6], o[5]) for o in opciones}) > 1:
            return None, "Deezer tiene varias ediciones con este nombre y dan números distintos"
        o = min(opciones, key=lambda o: o[:5])
        return "deezer", o[4], o[5], o[6], o[7]
    if sin_red:   # sin Deezer completo no se cae a MusicBrainz: con red la próxima corrida numeraría distinto
        return None, "sin respuesta de Deezer (red): se reintenta en la próxima corrida"
    # 2. MusicBrainz: un lanzamiento (de los de estas canciones) que contenga todas las grabaciones
    cands = []
    for rid in sorted({x["rid"] for x in info if x["rid"]}):
        R = release(rid)
        if R and all(x["rec"] and x["rec"] in R["by_rec"] for x in info):
            m = {i: tuple(R["by_rec"][x["rec"]][:2]) for i, x in enumerate(info)}
            if len(set(m.values())) == len(info):
                tot = {R["by_rec"][x["rec"]][0]: R["by_rec"][x["rec"]][2] for x in info}
                cands.append(("mb", rid, R["discs"], m, tot))
    if cands:
        if len({firma(c[3], c[2]) for c in cands}) > 1:
            return None, "dos lanzamientos de MusicBrainz dan números distintos"
        return cands[0]
    return None, "ni Deezer ni MusicBrainz tienen una edición con todas sus canciones"

def problema_visible(info):
    """Por qué una carpeta que no se pudo numerar sí necesita arreglo (misma regla que auditoria.py), o ''."""
    pos = collections.Counter((x["dn"], x["tn"]) for x in info if x["tn"])
    if any(n > 1 for n in pos.values()): return "números repetidos"
    con = [bool(re.match(r"^\d+-\d+ - ", x["f"])) for x in info]
    pref = any(x["dn"] > 1 for x in info) or all(con)
    for x in info:
        if x["tn"] and not x["f"].startswith((f"{x['dn']}-" if pref else "") + f"{x['tn']:02d} - "):
            return "el nombre de algún archivo no cuadra con sus etiquetas"
    return ""

def rewrite_paths(pmap):
    """pmap: ruta absoluta vieja -> nueva. State de Antra, playlists, equivalencias.tsv e ids-mb-aceptados.json, con
    respaldo (comun.cambiar_rutas; 30 sep: antes solo state y playlists → equivalencias.tsv quedaba con rutas rotas)."""
    cambiar_rutas(pmap, "tracknums")   # 2 oct: deja el log pendiente para nd_actualizar.py
    return len(pmap)

if "--revert" in sys.argv:
    if antra_abierto(): sys.exit("Antra está abierto; ciérralo y reintenta.")
    log = json.load(open(sys.argv[sys.argv.index("--revert") + 1]))
    pmap, tmp = {}, []
    for i, c in enumerate(log["cambios"]):
        cur, old = c["new_path"], c["old_path"]
        if cur != old:
            tp = os.path.join(os.path.dirname(cur), f".tn-rev-{i}{os.path.splitext(cur)[1]}"); os.rename(cur, tp)
            tmp.append((tp, old)); pmap[cur] = old
    for tp, old in tmp:
        assert not os.path.exists(old), old
        os.rename(tp, old)
    for c in log["cambios"]:
        old = c["old_path"]
        t = abrir(old)
        for k, v in c["old_tags"].items():
            if v is None: t.pop(k, None)
            else: t[k] = v
        t.save()
    print("revertidas", len(log["cambios"]), "| rutas actualizadas:", rewrite_paths(pmap)); sys.exit()


# ---------- a mano: una carpeta con el disco de Deezer que se indica ----------
A_MANO = sys.argv[sys.argv.index("--a-mano") + 1] if "--a-mano" in sys.argv else None
DZ_ID = sys.argv[sys.argv.index("--deezer") + 1] if "--deezer" in sys.argv else None
POSICIONES = {}   # título → (disco, pista), de los argumentos "Título=N" o "Título=D-N"
for _x in sys.argv[1:]:
    if "=" in _x and not _x.startswith("--"):
        _t, _p = _x.rsplit("=", 1)
        _d, _, _n = _p.rpartition("-")
        POSICIONES[_t.strip()] = (int(_d) if _d else 1, int(_n))
if A_MANO and not DZ_ID:
    sys.exit("--a-mano necesita --deezer <id del disco> (el número que sale en deezer.com/album/<id>)")

def edicion_a_mano(info, aid):
    """Como edicion(), pero con el disco de Deezer que se indicó y las posiciones dadas a mano."""
    dd = dz_disco(aid)
    if not dd: return None, "Deezer no respondió o ese disco no tiene su lista completa"
    titulo, _, tracks = dd
    m, _ = emparejar(info, tracks)
    faltan = []
    for i, x in enumerate(info):
        if i in m: continue
        if x["titulo"] in POSICIONES: m[i] = POSICIONES[x["titulo"]]
        else: faltan.append(x["titulo"])
    if faltan:
        print(f"Disco de Deezer {aid} «{titulo}»:")
        for dn, pos, _, tit, du in tracks: print(f"   {dn}-{pos:02d}  {tit}  ({du} s)")
        sys.exit("No se emparejaron solas: " + " · ".join(faltan) + '\nDales su posición: "Título=N" (o "Título=D-N" si el disco tiene varios CD).')
    if len(set(m.values())) != len(m): return None, "dos canciones quedarían con la misma posición"
    return "deezer-a-mano", aid, max(t[0] for t in tracks), m, collections.Counter(t[0] for t in tracks)

# ---------- plan ----------
plan, manual, stats = [], [], collections.Counter()
folders = []
for artist in sorted(os.listdir(ROOT)):
    if artist in SKIP or not os.path.isdir(os.path.join(ROOT, artist)): continue
    for alb in sorted(os.listdir(os.path.join(ROOT, artist))):
        d = os.path.join(ROOT, artist, alb)
        if not os.path.isdir(d): continue
        fl = sorted(f for f in os.listdir(d) if es_audio(f))
        if A_MANO:
            if os.path.normpath(d) == os.path.normpath(A_MANO if os.path.isabs(A_MANO) else os.path.join(ROOT, A_MANO)):
                folders.append((d, fl))   # a mano también sirve para un disco de una sola canción
        elif len(fl) >= 2: folders.append((d, fl))
if A_MANO and not folders:
    sys.exit(f"No encuentro la carpeta {A_MANO}")

def num(v):
    m = re.match(r"\d+", v or "")
    return int(m.group()) if m else 0

for i, (d, fl) in enumerate(folders):
    info = []
    for f in fl:
        try:
            t = abrir(os.path.join(d, f))
        except Exception:
            continue
        g = lambda k: (t.get(k) or [""])[0]
        info.append(dict(f=f, titulo=g("title"), alb=g("album"), aa=g("albumartist") or g("artist"), date=g("date"),
                         isrcs={v.upper() for v in t.get("isrc") or []}, len=t.info.length, kt=clave_titulo(g("title")),
                         rid=g("musicbrainz_albumid"), rec=g("musicbrainz_trackid"),
                         tn=num(g("tracknumber")), dn=num(g("discnumber")) or 1))
    if len(info) < (1 if A_MANO else 2): continue
    e = edicion_a_mano(info, DZ_ID) if A_MANO else edicion(info)
    if e[0] is None:
        if A_MANO: sys.exit(f"No se pudo numerar {os.path.relpath(d, ROOT)}: {e[1]}")
        stats["sin resolver"] += 1
        prob = problema_visible(info)
        if prob: manual.append((d, f"{prob}; no se tocó: {e[1]}")); stats["carpetas a mano"] += 1
        continue
    fuente, eid, discos, m, por_disco = e
    stats[fuente] += 1
    for k, x in enumerate(info):
        dn, tn = m[k]
        mt = NUM.match(x["f"]); title = mt.group(3) if mt else x["f"]
        newf = (f"{dn}-{int(tn):02d} - " if discos > 1 else f"{int(tn):02d} - ") + title
        if tn != x["tn"] or dn != x["dn"] or newf != x["f"]:
            plan.append(dict(dir=os.path.relpath(d, ROOT), old=x["f"], new=newf, tn=int(tn), dn=int(dn),
                             tot=por_disco.get(dn), discos=discos, old_tn=x["tn"], old_dn=x["dn"], src=f"{fuente}:{eid}"))
    if i % 50 == 0: print(f"  {i}/{len(folders)} carpetas", flush=True)

json.dump(cache, open(CACHE, "w")); dzn.guardar()
# choques de nombre dentro de la carpeta tras renombrar
byd = collections.defaultdict(list)
for p in plan: byd[p["dir"]].append(p)
for dd, ps in byd.items():
    keep = set(os.listdir(os.path.join(ROOT, dd))) - {p["old"] for p in ps}
    news = [p["new"] for p in ps]
    if len(news) != len(set(news)) or keep & set(news):
        manual.append((os.path.join(ROOT, dd), "choque de nombres")); stats["carpetas a mano"] += 1
        plan = [p for p in plan if p["dir"] != dd]
byd = {k: v for k, v in byd.items() if any(p["dir"] == k for p in plan)}
json.dump(dict(plan=plan, manual=manual), open(plan_path("plan-tracknums.json"), "w"), ensure_ascii=False, indent=1)
with open(plan_path("plan-tracknums.txt"), "w") as o:
    for p in plan: o.write(f"{p['dir']}\n   {p['old']}  →  {p['new']}   [{p['src']}]\n")
    o.write("\nA MANO (no se pudieron numerar solas y tienen números repetidos o nombres que no cuadran):\n" +
            "".join(f"  {d}  ({why})\n" for d, why in manual))
print(dict(stats)); print(f"cambios: {len(plan)} canciones en {len(byd)} carpetas; a mano: {len(manual)}")


# ---------- aplicar ----------
problems = []
for p in plan:
    d = os.path.join(ROOT, p["dir"])
    if not os.path.isfile(os.path.join(d, p["old"])): problems.append(f"no existe: {p['dir']}/{p['old']}")
olds = {(p["dir"], p["old"]) for p in plan}
for p in plan:
    dst = (p["dir"], p["new"])
    if p["new"] != p["old"] and os.path.exists(os.path.join(ROOT, *dst)) and dst not in olds:
        problems.append(f"destino ocupado: {p['dir']}/{p['new']}")
if problems:
    print("\n".join(problems[:20])); sys.exit(f"{len(problems)} problemas; no se hace nada.")
print(f"plan OK: {len(plan)} canciones")
if "--execute" not in sys.argv or not plan: sys.exit(0)
if antra_abierto(): sys.exit("Antra está abierto; ciérralo y reintenta.")

log = {"cambios": []}; pmap = {}
# renombrar en dos pasos (a nombre temporal) para que los intercambios de número no choquen
tmp = []
for i, p in enumerate(plan):
    d = os.path.join(ROOT, p["dir"]); old = os.path.join(d, p["old"])
    t = abrir(old)
    oldtags = {k: (t.get(k) or None) for k in TAGS}
    t["tracknumber"] = [str(p["tn"])]; t["discnumber"] = [str(p["dn"])]
    for k, v in (("totaltracks", p["tot"]), ("tracktotal", p["tot"]), ("totaldiscs", p["discos"]), ("disctotal", p["discos"])):
        if v and t.get(k): t[k] = [str(v)]
    t.save()
    if p["new"] != p["old"]:
        tp = os.path.join(d, f".tn-tmp-{i}{os.path.splitext(old)[1]}"); os.rename(old, tp); tmp.append((tp, os.path.join(d, p["new"])))
    log["cambios"].append(dict(old_path=old, new_path=os.path.join(d, p["new"]), old_tags=oldtags))
for tp, new in tmp:
    assert not os.path.exists(new), new
    os.rename(tp, new)
for c in log["cambios"]:
    if c["old_path"] != c["new_path"]: pmap[c["old_path"]] = c["new_path"]
rewrite_paths(pmap)   # state, playlists, equivalencias y aceptados (con respaldo de lo que cambia)
out = log_path("tracknums-log")
json.dump(log, open(out, "w"), ensure_ascii=False, indent=1)
print(f"HECHO: {len(plan)} canciones, {len(pmap)} renombradas (rutas al día en state y listas). Log: {out}")
