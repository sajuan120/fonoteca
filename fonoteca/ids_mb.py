#!/usr/bin/env python3
"""IDs de MusicBrainz de cada canción: comprueba que sean los de SU grabación y corrige los ajenos (27 sep 2026).

Uso: ids_mb.py [<carpeta relativa a la biblioteca> ...] [--execute] [--sin-red]   (sin carpetas = toda la biblioteca)
     ids_mb.py --revert <logs/ids-mb-....json>
Por qué: Picard (21-23 sep) puso los IDs emparejando por POSICIÓN cuando los números de pista eran el orden de descarga de
Antra → ~160 canciones tenían el ID de otra (Billie Jean, el de «Thriller»). La auditoría solo veía las que chocaban.
Regla: comun.grabacion_corresponde (título + duración, o ISRC + duración; nunca por número de pista).
Por cada canción con ID de grabación (musicbrainz_trackid):
  1. Sus datos en MusicBrainz (búsqueda por lotes de 50 IDs; caché cache/ids-mb-grabaciones.json).
  2. Corresponde → no se toca (salvo que su pista o su disco no sean de esa grabación: se rehacen). Si varias canciones
     comparten ID con audio distinto, se lo queda la que mejor coincide y las otras siguen al paso 3.
  3. No corresponde → se busca la verdadera en: el disco de su carpeta (por título y duración), su ISRC, AcoustID (su
     huella; está contaminado, así que solo vale si además cumple la regla) y, si nada de eso da, la búsqueda por texto
     (artista + título). Gana la que cumple la regla y tiene más fuentes.
  4. Encontrada → grabación, artistas, pista y disco (uno que ya use la carpeta; si no, la regla de mb_disco: mismo nombre,
     oficial, el más antiguo) y las etiquetas de disco que ponía Picard (país, estado, escritura, código de barras, sello,
     ASIN, formato) con los datos de ESE disco. Sin disco con ese nombre: la grabación sola.
     No encontrada → se deja si AcoustID confirma el ID y dura igual (título escrito distinto) o si es la misma canción
     (MusicBrainz guarda otra duración); si no, se quitan todos sus IDs de MusicBrainz (mejor sin ID que con uno ajeno).
Sin --execute: simulación → planes/ids-mb.tsv. Con --execute: escribe y deja logs/ids-mb-<fecha>.json con los valores
anteriores (para --revert). MusicBrainz 1 consulta/s, AcoustID 3/s, todo con caché (cache/ids-mb-*.json). No usa Spotify.
"""
import base64, collections, json, os, re, subprocess, sys, urllib.error, urllib.parse, urllib.request
import numpy as np
from audio import abrir, es_audio
from comun import (ACOUSTID_KEY, decision, ROOT, cache_path, plan_path, log_path, es_de_album, antra_abierto, grabacion_corresponde,
                   base_disco, clave_titulo, clave_artista)
from red import pedir_json

args = sys.argv[1:]
MB_GRABACION = ("musicbrainz_trackid", "musicbrainz_artistid")
MB_DISCO = ("musicbrainz_albumid", "musicbrainz_releasetrackid", "musicbrainz_releasegroupid", "musicbrainz_albumartistid")
PICARD_DISCO = ("releasecountry", "releasestatus", "script", "barcode", "catalognumber", "asin", "media")

if "--revert" in args:
    lg = json.load(open(args[args.index("--revert") + 1], encoding="utf-8"))
    for rel, antes in lg["cambios"].items():
        t = abrir(os.path.join(ROOT, rel))
        for k, v in antes.items():
            if v is None: t.pop(k, None)
            else: t[k] = v
        t.save()
    sys.exit(f"revertidas {len(lg['cambios'])} canciones")

EXECUTE, SIN_RED = "--execute" in args, "--sin-red" in args
if EXECUTE and antra_abierto():
    sys.exit("Antra está abierto: ciérralo primero (puede estar escribiendo canciones sueltas en Artista/Álbum).")
carpetas = [a for a in args if not a.startswith("--")] or ["."]
def log(*a): print(*a, flush=True)

# ---------------------------------------------------------------- consultas (con caché; una falla de red no se guarda)
def cargar(nombre):
    p = cache_path(nombre)
    return (json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}), p
def guardar(d, p): json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
GRAB, GRAB_P = cargar("ids-mb-grabaciones.json")
DISCOS, DISCOS_P = cargar("ids-mb-discos.json")
ISRC, ISRC_P = cargar("ids-mb-isrc.json")
AID, AID_P = cargar("ids-mb-acoustid.json")
TEXTO, TEXTO_P = cargar("ids-mb-texto.json")
_viejo, _ = cargar("mb-isrc-cache.json")                     # las consultas por ISRC que ya hizo enriquecer.py
for url, d in _viejo.items():
    m = re.search(r"/isrc/([A-Z0-9]+)\?", url)
    if m and d is not None: ISRC.setdefault(m.group(1), d)
def http(url, cual="mb", data=None):
    """JSON de MusicBrainz (1/s, con su User-Agent) o AcoustID (3/s). None = falla de red."""
    if SIN_RED: return None
    return pedir_json(url, datos=data, intentos=6, timeout=60)   # red.py: su ritmo; 503 = ocupado → espera y reintenta

def _ac(xs): return [{"id": (c.get("artist") or {}).get("id"), "name": c.get("name") or (c.get("artist") or {}).get("name")} for c in xs or []]
def flaca(r):
    """Lo que se usa de una grabación de MusicBrainz: título, duración, ISRC, artistas y sus discos (con la pista)."""
    return {"id": r.get("id"), "title": r.get("title"), "length": r.get("length"), "isrcs": r.get("isrcs") or [], "ac": _ac(r.get("artist-credit")),
            "releases": [{"id": x.get("id"), "title": x.get("title"), "status": x.get("status"), "date": x.get("date"),
                          "country": x.get("country"), "rg": (x.get("release-group") or {}).get("id"), "ac": _ac(x.get("artist-credit")),
                          "tracks": [[m.get("position"), m.get("format"), t.get("id"), t.get("number")]
                                     for m in x.get("media") or [] for t in (m.get("track") or m.get("tracks") or [])]}
                         for x in r.get("releases") or []]}

def grabaciones(rids):
    """Trae a la caché las grabaciones que falten: búsqueda de 50 IDs por consulta; las que no salen (fusionadas), una por una."""
    falta = sorted({r for r in rids if r and r not in GRAB})
    for i in range(0, len(falta), 50):
        lote = falta[i:i + 50]
        d = http("https://musicbrainz.org/ws/2/recording/?" + urllib.parse.urlencode(
            {"query": " OR ".join(f"rid:{x}" for x in lote), "fmt": "json", "limit": 100}))
        for r in (d or {}).get("recordings", []):
            if r["id"] in lote: GRAB[r["id"]] = flaca(r)
        if i and i % 1000 == 0: log(f"  grabaciones {i}/{len(falta)}"); guardar(GRAB, GRAB_P)
    for x in [r for r in falta if r not in GRAB]:
        d = http(f"https://musicbrainz.org/ws/2/recording/{x}?inc=isrcs+artist-credits+releases+media&fmt=json")
        if d is None: continue
        GRAB[x] = flaca(d) if d else {"no_existe": True}
        if d and d.get("id") != x: GRAB[x]["fusionada_en"] = d.get("id")
    if falta: guardar(GRAB, GRAB_P)

def disco(aid, completo=False):
    """Un disco de MusicBrainz con sus pistas (completo=True: también sello y códigos, para escribir sus etiquetas)."""
    d = DISCOS.get(aid)
    if d is None or (completo and "label-info" not in d):
        n = http(f"https://musicbrainz.org/ws/2/release/{aid}?inc=recordings+isrcs+artist-credits+release-groups+labels&fmt=json")
        if n is not None:
            DISCOS[aid] = d = n; guardar(DISCOS, DISCOS_P)
    return d or {}

def por_isrc(isrc):
    if isrc not in ISRC:
        d = http(f"https://musicbrainz.org/ws/2/isrc/{isrc}?inc=artist-credits+releases&fmt=json")
        if d is None: return []
        ISRC[isrc] = d; guardar(ISRC, ISRC_P)
    return (ISRC[isrc] or {}).get("recordings") or []

KEY = ACOUSTID_KEY   # opcional: sin clave, AcoustID no es una de las fuentes
def acoustid(rel, x):
    """Grabaciones que AcoustID asocia a la huella (puntaje >= 0,8). Caché por archivo y largo exacto del audio."""
    k = f"{rel}|{x['muestras']}"
    if not KEY and k not in AID: return {}
    if k not in AID and rel in AID:                              # caché del análisis del 27 sep (por ruta)
        AID[k] = AID.pop(rel).get("results", [])
    if k not in AID:
        r = subprocess.run(["fpcalc", "-json", os.path.join(ROOT, rel)], capture_output=True, text=True)
        try: fp = json.loads(r.stdout)
        except ValueError: return {}
        d = http("https://api.acoustid.org/v2/lookup", "aid", urllib.parse.urlencode(
            {"client": KEY, "meta": "recordings", "duration": int(fp["duration"]), "fingerprint": fp["fingerprint"], "format": "json"}).encode())
        if d is None or d.get("status") != "ok": return {}
        AID[k] = [{"score": res.get("score"), "recordings": [{"id": rc.get("id"), "title": rc.get("title"), "duration": rc.get("duration"),
                   "artists": [a.get("name") for a in rc.get("artists") or []]} for rc in res.get("recordings") or []]}
                  for res in d.get("results", [])]
        guardar(AID, AID_P)
    return {rc["id"]: rc for res in AID[k] if (res.get("score") or 0) >= 0.8 for rc in res["recordings"] if rc.get("id") and rc.get("title")}

def por_texto(x):
    """Búsqueda por texto en MusicBrainz: título (sin paréntesis ni '- versión') y primer artista."""
    base = re.sub(r"\s*[\(\[].*?[\)\]]|\s+-\s+.*$", "", x["title"]).strip() or x["title"]
    a1 = re.split(r",|&|\bfeat\.?|\bft\.?|\bx\b", x["artist"])[0].strip() or x["artist"]
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    q = f'recording:"{esc(base)}" AND artist:"{esc(a1)}"'
    if q not in TEXTO:
        d = http("https://musicbrainz.org/ws/2/recording/?" + urllib.parse.urlencode({"query": q, "fmt": "json", "limit": 25}))
        if d is None: return []
        TEXTO[q] = [r["id"] for r in d.get("recordings", [])]
        for r in d.get("recordings", []): GRAB.setdefault(r["id"], flaca(r))
        guardar(TEXTO, TEXTO_P); guardar(GRAB, GRAB_P)
    return TEXTO[q]

# ---------------------------------------------------------------- audio de dos archivos (para IDs compartidos)
HUELLAS, _ = cargar("auditoria-huellas.json")                   # las de auditoria.py (fpcalc -raw, 120 s)
_POP = np.array([bin(i).count("1") for i in range(65536)], dtype=np.uint8)
def huella(rel):
    p = os.path.join(ROOT, rel); st = os.stat(p); c = HUELLAS.get(rel)
    if c and c[0] == st.st_size and c[1] == st.st_mtime_ns and c[2]:
        return np.frombuffer(base64.b64decode(c[2]), dtype=np.uint32)
    r = subprocess.run(["fpcalc", "-raw", "-json", "-length", "120", p], capture_output=True, text=True)
    try: return np.array(json.loads(r.stdout)["fingerprint"], dtype=np.uint32)
    except (ValueError, KeyError): return None
def parecido(a, b):
    """Mejor parecido (0-1) de dos huellas deslizando una sobre otra (el mismo cálculo de auditoria.py)."""
    if a is None or b is None or len(a) < 20 or len(b) < 20: return None
    lim, mejor = int(max(len(a), len(b)) * 0.3), 0.0
    for off in range(-lim, lim + 1, 2):
        sa, sb = (a[off:], b) if off >= 0 else (a, b[-off:])
        n = min(len(sa), len(sb))
        if n < 0.5 * min(len(a), len(b)): continue
        x = np.bitwise_xor(sa[:n], sb[:n])
        mejor = max(mejor, 1 - (int(_POP[x & 0xFFFF].sum()) + int(_POP[x >> 16].sum())) / (32 * n))
    return round(mejor, 3)

# ---------------------------------------------------------------- 1. leer la biblioteca
log("leyendo la biblioteca...")
X, vistos = {}, set()
for c in carpetas:
    for dp, dns, fns in os.walk(os.path.join(ROOT, c)):
        dns[:] = sorted(d for d in dns if not d.startswith("."))
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            if not es_audio(fn) or not es_de_album(p) or os.stat(p).st_ino in vistos: continue
            vistos.add(os.stat(p).st_ino)
            f = abrir(p); t = f.tags or {}
            g = lambda k: [v for v in (t.get(k) or []) if v.strip()]
            X[os.path.relpath(p, ROOT)] = {"title": (g("title") or [""])[0], "artist": (g("artist") or [""])[0], "album": (g("album") or [""])[0],
                "len": f.info.length, "muestras": f.info.total_samples, "isrc": g("isrc"), "rid": (g("musicbrainz_trackid") or [""])[0],
                "aid": (g("musicbrainz_albumid") or [""])[0], "rt": (g("musicbrainz_releasetrackid") or [""])[0]}
con_id = [r for r in X if X[r]["rid"]]
log(f"{len(X)} canciones, {len(con_id)} con ID de grabación")
grabaciones([X[r]["rid"] for r in con_id])
por_carpeta = collections.defaultdict(list)
for r in X: por_carpeta[os.path.dirname(r)].append(r)

def ver(rel, rec, en_acoustid=False):
    x = X[rel]
    return grabacion_corresponde(x["title"], x["artist"], x["len"], x["isrc"], rec.get("title"), (rec.get("length") or 0) / 1000 or None,
                                 rec.get("isrcs"), [a.get("name") for a in rec.get("ac") or []], en_acoustid)

# ---------------------------------------------------------------- 2. ¿cada ID es de su canción?
V = {}
for rel in con_id:
    rec = GRAB.get(X[rel]["rid"])
    V[rel] = (False, None, "el ID no existe en MusicBrainz") if not rec or rec.get("no_existe") else ver(rel, rec)
choque = set()                                                  # comparten ID, las dos "cumplen" pero su audio es distinto
por_id = collections.defaultdict(list)
for rel in con_id: por_id[X[rel]["rid"]].append(rel)
for rid, rs in por_id.items():
    buenos = [r for r in rs if V[r][0]]
    if len(buenos) < 2: continue
    L = (GRAB[rid].get("length") or 0) / 1000
    buenos.sort(key=lambda r: (-(V[r][1] or 0), abs(X[r]["len"] - L) if L else 0))
    for r in buenos[1:]:
        a, b = X[buenos[0]], X[r]
        misma = (clave_titulo(a["title"]) == clave_titulo(b["title"]) and clave_artista(a["artist"]) == clave_artista(b["artist"])
                 and abs(a["len"] - b["len"]) <= max(3, 0.02 * max(a["len"], b["len"])))
        if misma: continue                                      # misma canción y duración: otra masterización, misma grabación
        s = parecido(huella(buenos[0]), huella(r))              # (la misma regla que la sección «IDs equivocados» de auditoria.py)
        if s is not None and s < 0.75: choque.add(r)
malos = [r for r in con_id if not V[r][0]] + sorted(choque)
log(f"no corresponden: {len(malos) - len(choque)}, más {len(choque)} que comparten ID con otra canción de audio distinto")

# ---------------------------------------------------------------- 3. buscar la grabación verdadera
usados = collections.defaultdict(set)                           # ID → canciones que lo tienen bien (no se reparte dos veces)
for r in con_id:
    if V[r][0] and r not in choque: usados[X[r]["rid"]].add(r)
def discos_carpeta(rel):
    """Discos de MusicBrainz de la carpeta (los de sus canciones con ID bueno, más el del propio archivo: Picard solía
    acertar el disco aunque errara la pista), el más usado primero."""
    c = collections.Counter(X[r]["aid"] for r in por_carpeta[os.path.dirname(rel)] if X[r]["aid"] and V.get(r, (True,))[0] and r not in choque)
    if X[rel]["aid"] and X[rel]["aid"] not in c: c[X[rel]["aid"]] = 0
    return c

def discos_por_nombre(rel):
    """Discos de MusicBrainz con el nombre del álbum (sin ediciones) y el primer artista: búsqueda de discos (hasta 3)."""
    x = X[rel]; b = base_disco(x["album"])
    a1 = re.split(r",|&|\bfeat\.?|\bft\.?|\bx\b", x["artist"])[0].strip() or x["artist"]
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    nombre = re.sub(r"[()\[\]]", " ", x["album"]).strip()
    q = f'release:"{esc(nombre)}" AND artist:"{esc(a1)}"'
    k = "disco|" + q
    if k not in TEXTO:
        d = http("https://musicbrainz.org/ws/2/release/?" + urllib.parse.urlencode({"query": q, "fmt": "json", "limit": 10}))
        if d is None: return []
        TEXTO[k] = [r["id"] for r in d.get("releases", []) if r.get("score", 0) >= 80 and b and base_disco(r.get("title")) == b]
        guardar(TEXTO, TEXTO_P)
    return TEXTO[k][:3]

def candidatos(rel):
    """Grabaciones que cumplen la regla para este archivo, la mejor primero. Fuentes: disco de la carpeta, ISRC, AcoustID;
    si ninguna trae disco con el nombre del álbum, discos con ese nombre; si no hay nada, búsqueda por texto."""
    x, out = X[rel], {}
    aids = acoustid(rel, x)
    def add(rid, rec, fuente, disco_=None, pista=None, isrc_fuente=False):
        if not rid: return
        ok, nt, mot = ver(rel, rec, rid in aids)
        if not ok: return
        c = out.setdefault(rid, {"rid": rid, "title": rec.get("title"), "len": (rec.get("length") or 0) / 1000 or None, "fuentes": set(),
                                 "nt": nt, "mot": mot, "disco": None, "pista": None, "iok": False})
        c["fuentes"].add(fuente)
        c["iok"] |= isrc_fuente or bool(set(x["isrc"]) & set(rec.get("isrcs") or []))
        if disco_ and not c["disco"]: c["disco"], c["pista"] = disco_, pista
    def de_discos(aids_, fuente):
        for aid in aids_:
            d = disco(aid)
            for m in d.get("media") or []:
                for tr in m.get("tracks") or []:
                    rc = tr.get("recording") or {}
                    add(rc.get("id"), {"title": rc.get("title") or tr.get("title"), "length": rc.get("length") or tr.get("length"),
                                       "isrcs": rc.get("isrcs"), "ac": _ac(rc.get("artist-credit") or tr.get("artist-credit") or d.get("artist-credit"))},
                        fuente, aid, tr.get("id"))
    de_discos([a for a, _ in discos_carpeta(rel).most_common()], "disco de la carpeta")
    for i in x["isrc"]:
        for rc in por_isrc(i):
            add(rc.get("id"), {"title": rc.get("title"), "length": rc.get("length"), "isrcs": [i], "ac": _ac(rc.get("artist-credit"))},
                "ISRC", isrc_fuente=True)
    for rid, rc in aids.items():
        add(rid, {"title": rc["title"], "length": (rc.get("duration") or 0) * 1000, "isrcs": [], "ac": [{"name": a} for a in rc.get("artists") or []]},
            "AcoustID")
    grabaciones([c["rid"] for c in out.values()])
    for c in out.values():                                      # ¿tiene un disco con el nombre del álbum (o de la carpeta)?
        if not c["disco"]: c["disco"], c["pista"] = elegir_disco(rel, c["rid"])
    if not any(c["disco"] for c in out.values()):
        de_discos(discos_por_nombre(rel), "disco con su nombre")
    if not out:
        for rid in por_texto(x):
            add(rid, GRAB.get(rid) or {}, "búsqueda por texto")
        for c in out.values():
            if not c["disco"]: c["disco"], c["pista"] = elegir_disco(rel, c["rid"])
    for c in out.values():
        if c["rid"] in aids: c["fuentes"].add("AcoustID")
    cs = [c for c in out.values() if not (usados.get(c["rid"], set()) - {rel})]
    return sorted(cs, key=lambda c: (-bool(c["disco"]), -c["iok"], -("AcoustID" in c["fuentes"]), -(c["nt"] or 0),
                                     abs((c["len"] or x["len"]) - x["len"]), -len(c["fuentes"]))), aids

def elegir_disco(rel, rid, disco_=None, pista=None):
    """Disco y pista de esa grabación: los que ya traía el candidato; si no, uno que ya use la carpeta; si no, la regla de
    mb_disco (mismo nombre sin ediciones, oficial, el más antiguo). (None, None) si no hay."""
    if disco_ and pista: return disco_, pista
    rels = (GRAB.get(rid) or {}).get("releases") or []
    pista_de = lambda rl: next((t[2] for t in rl.get("tracks") or [] if t[2]), None)
    for aid, _ in discos_carpeta(rel).most_common():
        rl = next((r for r in rels if r["id"] == aid), None)
        if rl and pista_de(rl): return aid, pista_de(rl)
    b = base_disco(X[rel]["album"])
    cand = sorted((r for r in rels if b and base_disco(r.get("title")) == b and pista_de(r)),
                  key=lambda r: (r.get("status") != "Official", r.get("date") or "9999"))
    return (cand[0]["id"], pista_de(cand[0])) if cand else (None, None)

def etiquetas(rid, aid, pista):
    """Las etiquetas de MusicBrainz para esa grabación en ese disco (como las ponía Picard). None = se quita."""
    grabaciones([rid])                                          # las que salieron de la lista de un disco pueden no estar
    rec = GRAB.get(rid)
    if not rec: return None
    new = {"musicbrainz_trackid": [rid], "musicbrainz_artistid": [a["id"] for a in rec.get("ac") or [] if a.get("id")] or None}
    if not aid:
        new.update({k: None for k in MB_DISCO + PICARD_DISCO})
        return new
    d = disco(aid, completo=True)
    if "label-info" not in d: return None                      # sin red: no se escribe a medias
    fmt = next((m.get("format") for m in d.get("media") or [] if any(t.get("id") == pista for t in m.get("tracks") or [])), None)
    cat = sorted({li["catalog-number"] for li in d.get("label-info") or [] if li.get("catalog-number")})
    new.update({"musicbrainz_albumid": [aid], "musicbrainz_releasetrackid": [pista],
                "musicbrainz_releasegroupid": [(d.get("release-group") or {}).get("id")] if (d.get("release-group") or {}).get("id") else None,
                "musicbrainz_albumartistid": [c["artist"]["id"] for c in d.get("artist-credit") or [] if c.get("artist")] or None,
                "releasecountry": [d["country"]] if d.get("country") else None,
                "releasestatus": [d["status"].lower()] if d.get("status") else None,
                "script": [(d.get("text-representation") or {}).get("script")] if (d.get("text-representation") or {}).get("script") else None,
                "barcode": [d["barcode"]] if d.get("barcode") else None, "catalognumber": cat or None,
                "asin": [d["asin"]] if d.get("asin") else None, "media": [fmt] if fmt else None})
    return new

acciones = {}          # rel → (acción, etiquetas nuevas o None, tenía, queda, fuentes, motivo)
for n, rel in enumerate(malos, 1):
    if n % 25 == 0: log(f"  buscando {n}/{len(malos)}")
    x = X[rel]; actual = GRAB.get(x["rid"]) or {}
    cs, aids = candidatos(rel)
    confirma = (rel not in choque and x["rid"] in aids and actual.get("length")
                and abs(x["len"] - actual["length"] / 1000) <= max(4, 0.03 * x["len"]))
    if cs and cs[0]["rid"] == x["rid"]:
        acciones[rel] = ("dejar: el audio confirma el ID", None, actual.get("title"), "", " + ".join(sorted(cs[0]["fuentes"])), cs[0]["mot"])
    elif cs and (cs[0]["disco"] or not confirma):
        c = cs[0]
        acciones[rel] = ("cambiar", etiquetas(c["rid"], c["disco"], c["pista"]), actual.get("title"), c["title"], " + ".join(sorted(c["fuentes"])),
                         c["mot"] + ("" if c["disco"] else "; sin disco con ese nombre en MusicBrainz"))
        usados[c["rid"]].add(rel)
    elif confirma:
        acciones[rel] = ("dejar: el audio confirma el ID", None, actual.get("title"), "", "AcoustID", V[rel][2])
    elif rel not in choque and (V[rel][1] or 0) >= 2:
        acciones[rel] = ("dejar: misma canción, otra duración", None, actual.get("title"), "", "", V[rel][2])
    else:
        acciones[rel] = ("quitar", {k: None for k in MB_GRABACION + MB_DISCO + PICARD_DISCO}, actual.get("title"), "", "", V[rel][2])
# ID viejo: MusicBrainz fusionó esa grabación con otra (misma grabación, ID nuevo) → el nuevo
fusion = {rel: GRAB[X[rel]["rid"]]["fusionada_en"] for rel in con_id if rel not in acciones and V[rel][0] and GRAB[X[rel]["rid"]].get("fusionada_en")}
grabaciones(fusion.values())
for rel, nuevo_id in fusion.items():
    if nuevo_id in GRAB and not GRAB[nuevo_id].get("no_existe"):
        aid, pista = elegir_disco(rel, nuevo_id)
        acciones[rel] = ("cambiar", etiquetas(nuevo_id, aid, pista), GRAB[X[rel]["rid"]].get("title"), GRAB[nuevo_id].get("title"),
                         "MusicBrainz", "ID viejo: MusicBrainz lo fusionó en otro")
# grabación bien pero su pista o su disco son de otra grabación → se rehacen
for rel in con_id:
    x = X[rel]
    if rel in acciones or not V[rel][0] or rel in choque or not x["aid"]: continue
    rl = next((r for r in GRAB[x["rid"]].get("releases") or [] if r["id"] == x["aid"]), None)
    if rl and any(t[2] == x["rt"] for t in rl.get("tracks") or []): continue
    aid, pista = elegir_disco(rel, x["rid"])
    acciones[rel] = ("rehacer pista y disco", etiquetas(x["rid"], aid, pista), GRAB[x["rid"]].get("title"), GRAB[x["rid"]].get("title"),
                     "", "su pista/disco era de otra grabación" + ("" if aid else "; sin disco con ese nombre: se quitan"))

# ---------------------------------------------------------------- 4. escribir (o simular)
# Las que se dejan a propósito (el título no coincide pero el audio confirma el ID, o misma canción con otra duración):
# auditoria.py las lee para no marcarlas en cada corrida (ella no consulta AcoustID).
ACEPTADOS_P = decision("ids-mb-aceptados.json")      # decisión (no caché): con los datos, como revisar_fallidas.tsv
ACEPTADOS = json.load(open(ACEPTADOS_P, encoding="utf-8")) if os.path.exists(ACEPTADOS_P) else {}
if EXECUTE:
    for rel in X:
        ACEPTADOS.pop(rel, None)
    for rel, (acc, *_ ) in acciones.items():
        if acc.startswith("dejar"): ACEPTADOS[rel] = {"rid": X[rel]["rid"], "motivo": acc}
    guardar(ACEPTADOS, ACEPTADOS_P)
cambios, sin_red, detalle = {}, [], {}
for rel, (acc, new, *_ ) in sorted(acciones.items()):
    if acc.startswith("dejar"): continue
    if new is None: sin_red.append(rel); continue
    t = abrir(os.path.join(ROOT, rel))
    antes = {k: (list(t[k]) if k in t else None) for k in new}
    if all((antes[k] or None) == v for k, v in new.items()): continue
    cambios[rel] = antes
    detalle[rel] = {k: [antes[k], v] for k, v in new.items() if (antes[k] or None) != v}
    if EXECUTE:
        for k, v in new.items():
            if v is None: t.pop(k, None)
            else: t[k] = v
        t.save()
json.dump(detalle, open(plan_path("ids-mb-etiquetas.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)   # antes → después
with open(plan_path("ids-mb.tsv"), "w", encoding="utf-8") as o:
    o.write("acción\tarchivo\ttenía (título de su ID)\tqueda\tfuentes\tmotivo\n")
    for rel, (acc, new, tenia, queda, fuentes, mot) in sorted(acciones.items(), key=lambda kv: (kv[1][0], kv[0])):
        o.write(f"{acc}\t{rel}\t{tenia}\t{queda}\t{fuentes}\t{mot}\n")
cuenta = collections.Counter(a[0] for a in acciones.values())
log(f"\n{len(con_id) - len(malos)} ya estaban bien. " + " | ".join(f"{k}: {v}" for k, v in sorted(cuenta.items())))
for rel, (acc, new, tenia, queda, fuentes, mot) in sorted(acciones.items()):
    if acc != "cambiar": log(f"  {acc:38} {rel}  (tenía: {tenia})")
if sin_red: log(f"⚠️ {len(sin_red)} sin cambiar por falta de red (volver a correr): {sin_red[:5]}")
log(f"plan: {plan_path('ids-mb.tsv')}")
if EXECUTE:
    out = log_path("ids-mb")
    json.dump({"cambios": cambios}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    log(f"ESCRITO: {len(cambios)} canciones. Log (para --revert): {out}")
else:
    log(f"SIMULACIÓN: cambiaría {len(cambios)} canciones. Nada escrito (usa --execute).")
