#!/usr/bin/env python3
"""Canciones de PRUEBA de Octo-Fiesta (MP3 128 de Deezer gratis) en <ROOT>/_Prueba/ — 28 sep 2026.

  prueba.py marcar [--todo]    GÉNEROS «<los reales (hasta 2)>; Prueba» a lo que no los tenga (se distinguen de la biblioteca:
                               Géneros → Prueba). El real (30 sep: el Instant Mix de GO GHOST solo daba canciones de
                               prueba — Navidrome rellena el mix con canciones AL AZAR DEL MISMO GÉNERO, y con «Prueba»
                               solo, eran todas de prueba): el del artista si ya está en la biblioteca (el más común en
                               Navidrome), si no el del disco en Deezer traducido con generos_reglas.py; sin ninguno
                               queda solo «Prueba». Lo consultado se guarda en prueba-generos.json (no repregunta).
                               Solo archivos con más de 60 s (no tocar uno que Octo-Fiesta está escribiendo). No cambia
                               IDs de Navidrome (el género no está en ND_PID_*), ni escuchas, ni nombres.
                               Timer musica-prueba-marcar (cada 5 min).
  prueba.py revisar [--execute] EL EMBUDO (timer musica-prueba-embudo, diario). Sin --execute solo muestra.
      · PROMOVER: 3+ escuchas en los últimos 28 días (suma de todos los usuarios; tabla «scrobbles» de Navidrome) →
        su enlace de Deezer va a <carpeta de listas>/PARA-FLAC.txt (+ «(con nombres).tsv») para pegarlo en Antra.
        Se queda en la lista hasta que el FLAC llega a la biblioteca.
      · REEMPLAZAR: si la canción YA ESTÁ en la biblioteca (procesada, cualquier formato; mismo ISRC, o mismo
        artista+título con duración a ±3 s) → se borra el MP3 y sus escuchas, estrellas, historial y playlists pasan a la
        copia de la biblioteca (nd_actualizar.py con el log de cambios; para y arranca Navidrome unos segundos). Si Antra
        está abierto, espera. Vale para TODAS las de prueba (30 sep: alguien bajó sin querer desde Octo-Fiesta el
        disco de Hades II y Coral Crown ya estaba en «Soundtrack Hades» → nunca dos copias), no solo para las promovidas
        cuando llega su FLAC. ISRC: el del MP3 o, si no trae, el de Deezer (se guarda en el estado: 1 consulta por canción).
      · BORRAR: sin escuchas en 6 semanas (desde la última escucha, o desde que se bajó) → AVISO a las 5 semanas y se
        borra si sigue igual al menos 7 días después del aviso (2 oct: el MP3 va a respaldos/prueba-<fecha>/, no se borra). Las que tienen ESTRELLA no se borran nunca. Si se vuelve
        a escuchar después del aviso, el aviso se anula.
      · ADOPTAR (30 sep):
        promovida hace 14+ días y su FLAC no llegó → entra a la biblioteca EN MP3: se le escriben su ISRC y DEEZER_ID
        (Octo-Fiesta no los pone) y ORIGEN, sale de _Prueba a «Adoptadas MP3 <fecha>/» (escuchas, estrellas, historial y
        playlists la siguen: comun.cambiar_rutas + nd_actualizar) y llega el aviso para procesarla como una descarga
        (musica-procesar.sh: simular → ¿ejecutar?). Queda en «~/Documents/Música - conseguir en FLAC.md» (revisar.py) hasta
        que llegue su FLAC: Antra la baja igual (no está en su state) y duplicados.py se queda con el FLAC (sin pérdida
        primero) pasándole las escuchas.
      Aviso en el escritorio (notify-send) solo cuando pasa algo. Estado en prueba-estado.json, log en logs/prueba-*.json.
_Prueba está en comun.SKIP: el procesado, la auditoría y la salud no la tocan. Octo-Fiesta: ~/octo-fiesta/.
"""
import collections, datetime, json, os, re, shutil, sqlite3, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mutagen import File as MFile
from audio import abrir, es_audio
from comun import dura_distinto
from comun import ROOT, HERE, LOGS, SKIP, antra_abierto, cambiar_rutas, clave_artista, clave_titulo, es_de_album, sin_procesar, NAVIDROME_DB, LISTAS, SCRIPTS
from red import Cache, pedir_json

PRUEBA = os.path.join(ROOT, "_Prueba")
AUDIO = (".mp3", ".flac", ".m4a", ".ogg", ".opus")
GENERO = "Prueba"
DB = NAVIDROME_DB
# 2 oct: bajo DATOS (= HERE en uso normal): en modo prueba se pisaba el estado REAL del embudo
from comun import DATOS, RESPALDOS, guardar_json
ESTADO = os.path.join(DATOS, "prueba-estado.json")
GENEROS_CACHE = os.path.join(DATOS, "prueba-generos.json")   # carpeta del disco → [género real] ([] = no se supo)
REVISAR_TODO = "--todo" in sys.argv   # marcar --todo: recalcula también las que ya tienen géneros (tras cambiar reglas)
MAPPINGS = os.path.join(PRUEBA, ".mappings.json")
SALIDA = os.path.join(LISTAS, "PARA-FLAC")
DIAS_VENTANA, MIN_ESCUCHAS = 28, 3          # promover: 3+ escuchas en 4 semanas
DIAS_AVISO, DIAS_BORRAR, DIAS_GRACIA = 35, 42, 7   # borrar: 6 semanas sin escuchas, avisando al menos 7 días antes
DIAS_ADOPTAR = 14                           # adoptar en MP3: promovida hace 14 días y sin FLAC
PROCESAR = os.path.join(SCRIPTS, "musica-procesar.sh")
DIA = 86400


def audios_prueba():
    for d, dirs, fs in os.walk(PRUEBA):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x != "playlists")
        for f in sorted(fs):
            if f.lower().endswith(AUDIO):
                yield os.path.join(d, f)


def etiquetas(p):
    a = MFile(p, easy=True)
    g = lambda k: ((a.get(k) or [""])[0] if a is not None else "")
    return dict(title=g("title"), artist=g("artist"), isrc=g("isrc").upper(), genre=g("genre"),
                dur=(a.info.length if a is not None else 0))


def mapa_generos():
    """G2 (género de Deezer → uno de los 20) y los FIJOS por artista (clave_artista → género): generos_reglas.py."""
    from generos_reglas import G2, fijos
    return G2, {clave_artista(a): g for a, g in fijos().items()}


def generos_biblioteca():
    """clave de artista → sus géneros en la biblioteca (Navidrome, sin _Prueba): la combinación más común entre sus
    canciones (generos.py da hasta 2 por artista). «Soundtrack» no cuenta: es el 3º que llevan las bandas sonoras."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    votos = collections.defaultdict(collections.Counter)
    for art, tags in con.execute("select artist, tags from media_file where missing=0 and substr(path, 1, 8) != '_Prueba/'"):
        gs = tuple(x["value"] for x in (json.loads(tags or "{}").get("genre") or []) if x["value"] not in (GENERO, "Soundtrack"))
        if gs:
            votos[clave_artista(art or "")][gs] += 1
    return {a: list(c.most_common(1)[0][0]) for a, c in votos.items()}


_dz = None
def deezer(url):
    """API pública de Deezer con la caché compartida (red.py). None si no hubo respuesta."""
    global _dz
    if _dz is None:
        _dz = Cache("deezer-cache.json")
    return pedir_json(url, _dz)


def genero_deezer(dz, g2):
    """Género del DISCO de esta canción en Deezer, traducido a la lista corta ('' si no hay o no se conoce; None sin red:
    se reintenta en la próxima pasada)."""
    t = deezer(f"https://api.deezer.com/track/{dz}")
    alb = (t or {}).get("album", {}).get("id")
    a = deezer(f"https://api.deezer.com/album/{alb}") if alb else {}
    if t is None or a is None:
        return None
    gs = [x["name"] for x in (a.get("genres") or {}).get("data", [])]
    return next((g2[g] for g in gs if g in g2), "")


def marcar():
    hechos, ahora = [], time.time()
    cache = json.load(open(GENEROS_CACHE, encoding="utf-8")) if os.path.exists(GENEROS_CACHE) else {}
    cache = {k: (v if isinstance(v, list) else [v] if v else []) for k, v in cache.items()}   # antes: un solo género
    datos = None   # se cargan solo si hay algo que marcar
    mapeo = {}
    for p in audios_prueba():
        if ahora - os.path.getmtime(p) < 60:
            continue
        try:
            a = MFile(p, easy=True)   # misma interfaz para MP3 (ID3), FLAC, M4A y Ogg
            if a is None:
                continue
            actual = list(a.get("genre") or [])
            carpeta = os.path.relpath(os.path.dirname(p), PRUEBA)
            if GENERO in actual and actual[-1] == GENERO and (len(actual) > 1 or cache.get(carpeta) == []) and not REVISAR_TODO:
                continue   # ya tiene «real(es); Prueba», o se buscó y no hay género real
            if datos is None:
                g2, fijos = mapa_generos()
                datos = (g2, fijos, generos_biblioteca())
                if os.path.exists(MAPPINGS):
                    mapeo = {(m.get("LocalPath") or "").replace("/app/downloads", PRUEBA, 1): m.get("ExternalId")
                             for m in json.load(open(MAPPINGS, encoding="utf-8")).values() if m.get("ExternalProvider") == "deezer"}
            g2, fijos, bib = datos
            k = clave_artista((a.get("artist") or [""])[0])
            real = ([fijos[k]] if k in fijos else None) or bib.get(k) or cache.get(carpeta)
            if real is None and mapeo.get(p):
                real = genero_deezer(mapeo[p], g2)
                if real is not None:
                    cache[carpeta] = real = [real] if real else []
            nuevo = (real or [])[:2] + [GENERO]
            if actual == nuevo:
                continue
            a["genre"] = nuevo
            a.save()
            hechos.append((os.path.relpath(p, PRUEBA), " · ".join(nuevo)))
        except Exception as e:
            print(f"no pude marcar {os.path.relpath(p, PRUEBA)}: {e}", file=sys.stderr)
    json.dump(cache, open(GENEROS_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for h, g in hechos:
        print(f"géneros {g}:", h)
    return hechos


def fecha_utc(s):
    """«2026-09-29T00:53:23.3322766Z» (Octo-Fiesta, 7 decimales) → timestamp; None si no se entiende."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})", s or "")
    return datetime.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}+00:00").timestamp() if m else None


def isrc_deezer(dz):
    """ISRC de una canción de Deezer por su ID (API pública). Octo-Fiesta v0.11 NO lo escribe en el MP3 (28 sep)."""
    return ((deezer(f"https://api.deezer.com/track/{dz}") or {}).get("isrc") or "").upper()


def iso(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def avisar(titulo, cuerpo):
    subprocess.run(["notify-send", "-a", "Música", "-i", "folder-music", "-t", "0", titulo, cuerpo], check=False)


def indice_biblioteca():
    """Biblioteca procesada, CUALQUIER formato (sin _Prueba ni descargas a medias): ISRC → ruta y (artista, título) → [(ruta, dur)]."""
    pendientes = set(sin_procesar())
    por_isrc, por_clave = {}, {}
    for d, dirs, fs in os.walk(ROOT):
        if d == ROOT:
            dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
        for f in fs:
            if not es_audio(f):
                continue
            p = os.path.join(d, f)
            if not es_de_album(p) or os.path.relpath(p, ROOT) in pendientes:
                continue
            try:
                a = abrir(p)
                g = lambda k: (a.get(k) or [""])[0]
                t = dict(title=g("title"), artist=g("artist"), isrc=g("isrc").upper(), dur=a.info.length)
            except Exception:
                continue
            if t["isrc"]:
                por_isrc.setdefault(t["isrc"], (p, t["dur"]))
            por_clave.setdefault((clave_artista(t["artist"]), clave_titulo(t["title"])), []).append((p, t["dur"]))
    return por_isrc, por_clave


def adoptar_mp3(adoptar, hoy, estado, log):
    """Las promovidas cuyo FLAC no llegó entran a la biblioteca en MP3: ISRC, DEEZER_ID y ORIGEN en sus etiquetas, fuera
    el género «Prueba», y a la carpeta «Adoptadas MP3 <fecha>» de la raíz para procesarla como una descarga (el aviso la
    ofrece). Devuelve (log de rutas para nd_actualizar, nombre de la carpeta)."""
    carpeta = f"Adoptadas MP3 {hoy}"
    destino = os.path.join(ROOT, carpeta)
    os.makedirs(destino, exist_ok=True)
    mover = {}
    for c in adoptar:
        e = c["e"]
        isrc = c["t"]["isrc"] or e.get("isrc") or (isrc_deezer(c["dz"]) if c["dz"] else "")
        t = abrir(c["p"])
        if isrc: t["isrc"] = [isrc]
        if c["dz"]: t["deezer_id"] = [str(c["dz"])]
        t["origen"] = [f"MP3 128 de Deezer (Octo-Fiesta, prueba): ganó el FLAC el {e['promovida']} y no llegó; adoptada "
                       f"el {hoy} — buscar el FLAC"]
        gs = [g for g in (t.get("genre") or []) if g != GENERO]
        if gs: t["genre"] = gs
        else: t.pop("genre", None)
        t.save()
        n = os.path.basename(c["p"]); dst = os.path.join(destino, n); k = 2
        while os.path.exists(dst):
            dst = os.path.join(destino, f"{os.path.splitext(n)[0]} ({k}){os.path.splitext(n)[1]}"); k += 1
        shutil.move(c["p"], dst); mover[c["p"]] = dst
        estado.pop(c["rel"], None)
        log["adoptadas"].append({"prueba": c["rel"], "ahora": os.path.relpath(dst, ROOT), "deezer": c["dz"], "isrc": isrc})
    return cambiar_rutas(mover, "prueba-adoptadas"), carpeta


def revisar(execute):
    ahora = time.time()
    estado = json.load(open(ESTADO, encoding="utf-8")) if os.path.exists(ESTADO) else {}
    mapeo = {}   # ruta en el disco → (id de Deezer, fecha de descarga)
    if os.path.exists(MAPPINGS):
        for m in json.load(open(MAPPINGS, encoding="utf-8")).values():
            lp = (m.get("LocalPath") or "").replace("/app/downloads", PRUEBA, 1)
            mapeo[lp] = (m.get("ExternalId") if m.get("ExternalProvider") == "deezer" else None, fecha_utc(m.get("DownloadedAt")))
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    canciones = []
    for p in audios_prueba():
        rel = os.path.relpath(p, ROOT)
        t = etiquetas(p)
        fila = con.execute("select id, created_at from media_file where path=? and missing=0", (rel,)).fetchone()
        mid = fila[0] if fila else None
        esc = con.execute("select count(*), max(submission_time) from scrobbles where media_file_id=? and submission_time>=?",
                          (mid, ahora - DIAS_VENTANA * DIA)).fetchone() if mid else (0, None)
        ultima = con.execute("select max(submission_time) from scrobbles where media_file_id=?", (mid,)).fetchone()[0] if mid else None
        estrella = bool(con.execute("select 1 from annotation where item_type='media_file' and item_id=? and starred=1",
                                    (mid,)).fetchone()) if mid else False
        dz, bajada = mapeo.get(p, (None, None))
        if not bajada and fila:
            bajada = datetime.datetime.fromisoformat(fila[1][:19]).replace(tzinfo=datetime.timezone.utc).timestamp()
        bajada = bajada or os.path.getctime(p)
        e = estado.setdefault(rel, {})
        if dz: e["deezer"] = dz
        canciones.append(dict(p=p, rel=rel, t=t, mid=mid, esc28=esc[0], ultima=ultima, estrella=estrella,
                              bajada=bajada, dz=e.get("deezer"), e=e))
    # fuera del estado lo que ya no existe (borrado o reemplazado)
    vivas = {c["rel"] for c in canciones}
    for rel in [r for r in estado if r not in vivas]:
        del estado[rel]

    promover, reemplazar, avisos, borrar, anular = [], [], [], [], []
    indice = None
    for c in canciones:
        e = c["e"]
        # ¿ya está en la biblioteca? (la promovida cuyo FLAC llegó, o una que se bajó estando ya) → reemplazar
        if not c["t"]["isrc"] and c["dz"]:   # sin ISRC en el MP3: el de Deezer (se guarda en el estado)
            e["isrc"] = e.get("isrc") or isrc_deezer(c["dz"])
            c["t"]["isrc"] = e["isrc"]
        if indice is None:
            indice = indice_biblioteca()
        por_isrc, por_clave = indice
        # 2 oct: ISRC + duración (la regla de siempre: un ISRC solo no alcanza, p. ej. Shakedown At Night 401 s vs 255 s)
        x = por_isrc.get(c["t"]["isrc"]) if c["t"]["isrc"] else None
        flac = x[0] if x and not dura_distinto(c["t"]["dur"], x[1]) else None
        if x and not flac:
            print(f"  ≠ mismo ISRC pero otra duración (no se reemplaza): {c['rel']} vs {os.path.relpath(x[0], ROOT)}")
        if not flac:
            cand = [p for p, dur in por_clave.get((clave_artista(c["t"]["artist"]), clave_titulo(c["t"]["title"])), [])
                    if abs(dur - c["t"]["dur"]) <= 3]
            flac = cand[0] if len(cand) == 1 else None
        if flac:
            reemplazar.append((c, flac))
            continue
        if not e.get("promovida") and c["esc28"] >= MIN_ESCUCHAS:
            promover.append(c)
        if e.get("promovida") or c in promover:
            continue
        if c["estrella"]:
            continue
        sin_escuchar = (ahora - (c["ultima"] or c["bajada"])) / DIA
        if e.get("avisada"):
            if sin_escuchar < DIAS_AVISO:
                anular.append(c)            # se volvió a escuchar después del aviso
            elif sin_escuchar >= DIAS_BORRAR and ahora - e["avisada_ts"] >= DIAS_GRACIA * DIA:
                borrar.append(c)
        elif sin_escuchar >= DIAS_AVISO:
            avisos.append(c)

    ya_reemplazo = {id(c) for c, _ in reemplazar}
    adoptar = [c for c in canciones if c["e"].get("promovida") and id(c) not in ya_reemplazo
               and ahora - datetime.datetime.fromisoformat(c["e"]["promovida"]).timestamp() >= DIAS_ADOPTAR * DIA]
    nombre = lambda c: f"{c['t']['artist']} – {c['t']['title']}"
    print(f"{len(canciones)} canciones de prueba | promover {len(promover)} | reemplazar por FLAC {len(reemplazar)} | "
          f"aviso de borrado {len(avisos)} | borrar {len(borrar)} | avisos anulados {len(anular)} | adoptar en MP3 {len(adoptar)}")
    for c in promover: print(f"  ⬆ promover ({c['esc28']} escuchas en {DIAS_VENTANA} días): {nombre(c)}")
    for c, f in reemplazar: print(f"  ⇄ reemplazar ({'llegó su FLAC' if c['e'].get('promovida') else 'ya estaba en la biblioteca'}): "
                                  f"{c['rel']}\n        por {os.path.relpath(f, ROOT)}")
    for c in avisos: print(f"  ⚠ aviso (se borra en {DIAS_GRACIA}+ días si no se escucha): {nombre(c)}")
    for c in borrar: print(f"  ✗ borrar: {nombre(c)}")
    for c in anular: print(f"  ✓ aviso anulado (se volvió a escuchar): {nombre(c)}")
    for c in adoptar: print(f"  ⬇ adoptar en MP3 (promovida {c['e']['promovida']}, su FLAC no llegó): {nombre(c)}")
    pend = [c for c in canciones if (c["e"].get("promovida") or c in promover) and id(c) not in ya_reemplazo and c not in adoptar]
    for c in pend:
        if c not in promover: print(f"  … esperando su FLAC (promovida {c['e']['promovida']}): {nombre(c)}")
    if not execute:
        print("SIMULACIÓN: no se tocó nada. Usa --execute.")
        return

    hoy = iso(ahora)
    for c in promover: c["e"]["promovida"] = hoy
    for c in avisos: c["e"]["avisada"] = hoy; c["e"]["avisada_ts"] = ahora
    for c in anular: c["e"].pop("avisada", None); c["e"].pop("avisada_ts", None)
    # lista para Antra: todas las promovidas que siguen esperando su FLAC
    faltan = [c for c in pend]
    if faltan:
        os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
        links = [f"https://www.deezer.com/track/{c['dz']}" for c in faltan if c["dz"]]
        open(SALIDA + ".txt", "w").write("\n".join(links) + "\n")
        with open(SALIDA + " (con nombres).tsv", "w", encoding="utf-8") as f:
            f.write("artista\ttítulo\tescuchas (28 días)\tpromovida\tenlace Deezer\n")
            for c in faltan:
                f.write(f"{c['t']['artist']}\t{c['t']['title']}\t{c['esc28']}\t{c['e']['promovida']}\t"
                        f"{'https://www.deezer.com/track/' + c['dz'] if c['dz'] else '(sin enlace: buscar a mano)'}\n")
    else:
        for ext in (".txt", " (con nombres).tsv"):
            if os.path.exists(SALIDA + ext): os.remove(SALIDA + ext)
    log = {"fecha": hoy, "promovidas": [c["rel"] for c in promover], "avisos": [c["rel"] for c in avisos],
           "borradas": [c["rel"] for c in borrar], "reemplazos": [], "anulados": [c["rel"] for c in anular], "adoptadas": [],
           "respaldo": None, "estado": "en curso"}
    if (reemplazar or adoptar) and antra_abierto():
        print("Antra está abierto: los reemplazos y adopciones quedan para la próxima revisión.")
        reemplazar, adoptar = [], []
    # 2 oct: el log ANTES de tocar nada (un corte en medio dejaba MP3 borrados sin rastro); los MP3 no se borran: van a
    # respaldos/prueba-<fecha>/; y los cambios de ruta los anota comun.cambiar_rutas (state, playlists, listas y el log
    # pendiente para Navidrome), que antes este script repetía a medias
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    lp = os.path.join(LOGS, f"prueba-{stamp}.json")
    resp = os.path.join(RESPALDOS, f"prueba-{stamp}")
    log["respaldo"] = resp if borrar or reemplazar else None
    for c, flac in reemplazar:
        log["reemplazos"].append({"mp3": c["rel"], "flac": os.path.relpath(flac, ROOT)})
    guardar_json(lp, log, indent=1)
    mover = {}   # MP3 de prueba → su copia de la biblioteca (reemplazo) o None (borrada a propósito)
    try:
        for c in borrar + [c for c, _ in reemplazar]:
            dst = os.path.join(resp, c["rel"]); os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(c["p"], dst); estado.pop(c["rel"], None)
        for c in borrar: mover[c["p"]] = None
        for c, flac in reemplazar: mover[c["p"]] = flac
        log["cambios"] = [{"old_path": o, "new_path": n} for o, n in mover.items() if n]
        if mover:
            log["log_nd"] = cambiar_rutas(mover, "prueba")   # playlists (p. ej. Descubrir.m3u) y log pendiente para Navidrome
        log_adopcion, carpeta_adopcion = adoptar_mp3(adoptar, hoy, estado, log) if adoptar else (None, None)
        for d, dirs, fs in os.walk(PRUEBA, topdown=False):   # carpetas que quedaron vacías
            if d != PRUEBA and os.path.basename(d) != "playlists" and not os.listdir(d):
                os.rmdir(d)
        log["estado"] = "hecho"
    finally:
        guardar_json(ESTADO, estado, indent=1)
        guardar_json(lp, log, indent=1)
    cambios = log["cambios"]
    if cambios or log_adopcion:   # escuchas, estrellas, historial y playlists → su ruta nueva (los logs quedaron pendientes)
        # 2 oct: antes se ignoraba el resultado (y un Navidrome caído a las 12:30 perdía las escuchas en silencio); para
        # las solo borradas no se corre nada: su log pendiente las purga en la próxima corrida de nd_actualizar.py
        r = subprocess.run([sys.executable, os.path.join(HERE, "nd_actualizar.py")], check=False)
        if r.returncode != 0:
            avisar("Música de prueba: Navidrome NO quedó al día",
                   f"nd_actualizar.py terminó con error {r.returncode}. Los MP3 están en {resp} y los logs quedaron en "
                   f"logs/nd-pendientes/: se aplican en la próxima corrida (o con NAVIDROME AL DÍA en el panel).")
            print(f"HECHO con error en Navidrome (código {r.returncode}). Log: {lp}")
            sys.exit(1)
    if carpeta_adopcion:   # aviso con botón: Konsole que simula el procesado y pregunta (lo mismo que tras Antra)
        lista = "\n".join(nombre(c) for c in adoptar[:8])
        subprocess.Popen(["systemd-run", "--user", "--collect", "--quiet", "bash", "-c",
                          'a=$(notify-send -a Música -i folder-music -u critical -t 0 -A simular="Simular procesado" '
                          '-A skip="Ahora no" --wait "$1" "$2"); [[ "$a" == simular ]] && exec "$3" "$4"',
                          "_", f"🎵 {len(adoptar)} canción(es) de prueba entran a la biblioteca en MP3",
                          f"{lista}\n\nSu FLAC no llegó en {DIAS_ADOPTAR} días. Quedan en «Música - conseguir en FLAC».\n"
                          f"Procesa la carpeta «{carpeta_adopcion}».", PROCESAR, carpeta_adopcion])
    if promover:
        avisar(f"🎵 {len(promover)} canción(es) de prueba ganaron el FLAC",
               "\n".join(nombre(c) for c in promover[:8]) + f"\n\nPega «PARA-FLAC.txt» ({LISTAS}) en Antra.")
    if avisos:
        avisar(f"⚠ {len(avisos)} canción(es) de prueba se borrarán en {DIAS_GRACIA} días",
               "No se escuchan hace 5 semanas:\n" + "\n".join(nombre(c) for c in avisos[:8]) +
               "\n\nEscúchalas o dales estrella para quedártelas.")
    if borrar or cambios:
        avisar("Música de prueba: limpieza hecha",
               f"{len(cambios)} reemplazada(s) por la copia de la biblioteca · {len(borrar)} borrada(s) por no escucharse "
               f"(los MP3 quedaron en {resp})")
    print(f"HECHO. Log: {lp}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["marcar"]:
        marcar()
    elif a[:1] == ["revisar"]:
        try:
            marcar()
            revisar("--execute" in a)
        except SystemExit:
            raise
        except BaseException as e:   # 2 oct: corre por timer: un error solo se veía en journalctl
            avisar("Música de prueba: el embudo falló", f"{e!r}\nMira: journalctl --user -u musica-prueba-embudo")
            raise
    else:
        sys.exit(__doc__)
