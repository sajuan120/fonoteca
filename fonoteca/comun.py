"""Constantes y utilidades compartidas por los scripts de música (24 sep 2026).

Antes cada script repetía ROOT, sus carpetas a saltar (con nombres de carpetas que ya no existían) y su propio
chequeo de "Antra abierto". Todo lo común vive aquí; los scripts hacen `from comun import ...`.
"""
import datetime, os, tomllib

HERE = os.path.dirname(os.path.abspath(__file__))              # carpeta de los scripts (y de su caché)
# Configuración (30 sep 2026): todo lo de cada instalación (rutas, contacto, usuarios) va en config.toml, que es
# PRIVADO; config.example.toml es la versión pública. Sin config.toml se usan los valores genéricos de abajo.
_CONF_P = os.environ.get("MUSIC_CONFIG", os.path.join(HERE, "config.toml"))
CONF = tomllib.load(open(_CONF_P, "rb")) if os.path.exists(_CONF_P) else {}
def ruta(clave, defecto):
    """Una ruta de [rutas] en config.toml (con ~ expandido), o el valor genérico."""
    return os.path.expanduser(CONF.get("rutas", {}).get(clave, defecto))

# MODO PRUEBA (banco de pruebas): con MUSIC_ROOT y MUSIC_DATOS todo apunta a carpetas temporales
# y no se toca la biblioteca real, ni los logs/listas reales, ni Navidrome. En uso normal no se definen.
PRUEBA = "MUSIC_ROOT" in os.environ
ROOT = os.environ.get("MUSIC_ROOT", ruta("biblioteca", "~/Music"))   # biblioteca
DATOS = os.environ.get("MUSIC_DATOS", HERE)                    # logs, planes, respaldos y listas
LOGS = os.path.join(DATOS, "logs")            # logs de cada paso (para revisar o revertir)
CACHE = os.path.join(HERE, "cache")           # respuestas de Deezer / MusicBrainz / LRCLIB guardadas (se comparte)
RESPALDOS = os.path.join(DATOS, "respaldos")  # respaldos de tags y del state de Antra
PLANES = os.path.join(DATOS, "planes")        # último plan de cada paso (para mirar qué haría o qué hizo)
# 2 oct: cada cambio de ruta deja un log en nd-pendientes/; nd_actualizar.py los aplica TODOS, en orden, y los pasa a
# nd-aplicados/ solo si terminó bien. Así un paso 8 fallido, un corte o una herramienta corrida desde la terminal no
# pierden las escuchas de Navidrome (antes cada script le pasaba «sus» logs y lo que no se pasaba se purgaba).
ND_PENDIENTES = os.path.join(LOGS, "nd-pendientes")
ND_APLICADOS = os.path.join(LOGS, "nd-aplicados")
SKIP = {"_Playlists", "_Prueba"}              # carpetas de la raíz que NO son Artista/Álbum (_Prueba: MP3 de Octo-Fiesta, 28 sep)
FALLIDAS = os.path.join(DATOS, "revisar_fallidas.tsv")  # ÚNICA lista de canciones a conseguir a mano
NOTAS = os.path.join(HERE, "revisar_notas.md")          # notas a mano (solo se leen)
# DECISIONES de curación de esta biblioteca (30 sep: antes sueltas en la carpeta o escritas dentro del código):
# equivalencias.tsv, ids-mb-aceptados.json, generos-fijos.json, discos-distintos.json, artistas-distintos.json,
# artistas-nombres.json, caratulas-elegidas.tsv, caratulas-no-tocar.txt, duplicados-verificados.txt, ost-franquicias.json
DECISIONES = os.path.join(DATOS, "decisiones")
def decision(nombre):
    """Ruta de un archivo de decisiones (puede no existir: cada script sigue sin él)."""
    return os.path.join(DECISIONES, nombre)
# en modo prueba los documentos también van a la carpeta de prueba (1 oct: el banco pisaba el «conseguir en FLAC»
# real con sus canciones de mentira, porque solo redirigía el de pendientes)
DOCUMENTOS = os.path.join(DATOS, "documentos") if PRUEBA else ruta("documentos", "~/Documents")
DOC = os.environ.get("MUSIC_DOC", os.path.join(DOCUMENTOS, "Música - cosas por revisar.md"))
DOC_FLAC = os.environ.get("MUSIC_DOC_FLAC", os.path.join(DOCUMENTOS, "Música - conseguir en FLAC.md"))   # 30 sep
DOC_AUDITORIA = os.path.join(DOCUMENTOS, "Música - auditoría.md")
ANTRA = ruta("antra", "~/.local/share/Antra")                  # history.json y config.json de Antra
ANTRA_HISTORY = os.environ.get("ANTRA_HISTORY", os.path.join(ANTRA, "history.json"))
LISTAS = os.environ.get("MUSIC_LISTAS", ruta("listas", "~/Music-listas"))   # listas .txt de enlaces para Antra
NAVIDROME = ruta("navidrome", "~/navidrome")                   # docker-compose.yml y data/
NAVIDROME_DB = os.path.join(NAVIDROME, "data", "navidrome.db")
OCTO = ruta("octo_fiesta", "~/octo-fiesta")
_scripts_repo = os.path.normpath(os.path.join(HERE, "..", "scripts"))   # en el repositorio: fonoteca/../scripts
SCRIPTS = ruta("scripts", _scripts_repo if os.path.isdir(_scripts_repo) else "~/.config/fonoteca")   # avisos y salud semanal
KIT = ruta("kit", "~/Respaldo-musica")                         # kit de recuperación
PORTADAS_IA = ruta("portadas_ia", "~/portadas-IA")
BANCO = ruta("banco", "/tmp/fonoteca-banco")                   # banco de pruebas
if PRUEBA:   # 2 oct: en modo prueba lo que se ESCRIBE va a la carpeta de prueba (el panel de prueba rehacía el kit REAL)
    KIT, PORTADAS_IA = os.path.join(DATOS, "kit"), os.path.join(DATOS, "portadas-IA")
    if "MUSIC_LISTAS" not in os.environ:
        LISTAS = os.path.join(DATOS, "listas")
for _d in (LOGS, ND_PENDIENTES, ND_APLICADOS, CACHE, RESPALDOS, PLANES, DECISIONES, *([DOCUMENTOS] if PRUEBA else [])):   # (sin archivos de decisiones todo funciona igual)
    os.makedirs(_d, exist_ok=True)

def log_path(nombre, ext="json"):
    """logs/<nombre>-<fecha>.<ext>, sin pisar uno que ya exista (dos corridas en el mismo segundo: -2, -3…)."""
    base = os.path.join(LOGS, f"{nombre}-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    p, n = f"{base}.{ext}", 2
    while os.path.exists(p):
        p, n = f"{base}-{n}.{ext}", n + 1
    return p

def log_pendiente(nombre, mover, extra=None):
    """Deja en logs/nd-pendientes/ un log para nd_actualizar.py: {"cambios": [{old_path, new_path}], "quitadas": [...]}
    (rutas absolutas; `mover` = {ruta vieja: ruta nueva, o None si se quitó sin reemplazo}). Lo aplica la próxima corrida
    de nd_actualizar.py, la llame quien la llame. Devuelve la ruta del log (None si no hay nada que anotar)."""
    cambios = [{"old_path": o, "new_path": n} for o, n in mover.items() if n and o != n]
    quitadas = [o for o, n in mover.items() if not n]
    if not cambios and not quitadas:
        return None
    os.makedirs(ND_PENDIENTES, exist_ok=True)
    base = os.path.join(ND_PENDIENTES, f"{datetime.datetime.now():%Y%m%d-%H%M%S-%f}-{nombre}")
    lp, k = base + ".json", 2
    while os.path.exists(lp):
        lp, k = f"{base}-{k}.json", k + 1
    guardar_json(lp, {"de": nombre, "fecha": datetime.datetime.now().isoformat(timespec="seconds"),
                      "cambios": cambios, "quitadas": quitadas, **(extra or {})})
    return lp

def leer_json(ruta, defecto=None):
    """Lee un JSON de estado o caché. Si está roto (un corte al escribirlo, antes de guardar_json), lo aparta a
    <ruta>.roto-<fecha>, avisa y devuelve `defecto`: ningún timer se queda muerto por un archivo truncado (2 oct)."""
    import json, sys
    if not os.path.exists(ruta):
        return defecto
    try:
        return json.load(open(ruta, encoding="utf-8"))
    except ValueError as e:
        roto = f"{ruta}.roto-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        os.replace(ruta, roto)
        print(f"⚠️ {os.path.basename(ruta)} estaba roto ({e}): apartado a {roto}; se sigue sin él.", file=sys.stderr, flush=True)
        return defecto

CERROJO = os.path.join(DATOS, ".cerrojo")   # 2 oct: un solo proceso escribe en la biblioteca o en Navidrome a la vez
_CERROJO_FD = []

def cerrojo(quien, esperar=900):
    """Toma el cerrojo común (fcntl.flock sobre DATOS/.cerrojo) antes de escribir en la biblioteca, el state de Antra,
    las playlists o Navidrome: así el embudo de las 12:30, el panel, una Konsole y un timer no se pisan. Espera hasta
    `esperar` segundos (avisando quién lo tiene) y si no, sale con error. Los procesos que lanza quien ya lo tiene
    (procesar_descarga.py → sus pasos, --seguir, el panel → sus scripts) lo heredan por FONOTECA_CERROJO y no esperan.
    Se suelta solo al terminar el proceso (también si lo matan)."""
    import fcntl, sys, time
    if os.environ.get("FONOTECA_CERROJO") or _CERROJO_FD:
        return
    fd = open(CERROJO, "a+", encoding="utf-8")
    t0, avisado = time.time(), False
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            fd.seek(0); dueno = fd.read().strip() or "otro proceso"
            if not avisado:
                print(f"Esperando el cerrojo de la biblioteca (lo tiene {dueno})…", flush=True); avisado = True
            if time.time() - t0 > esperar:
                sys.exit(f"No pude tomar el cerrojo de la biblioteca en {esperar} s: lo tiene {dueno}. Cuando termine, reintenta.")
            time.sleep(2)
    fd.seek(0); fd.truncate()
    fd.write(f"{quien} (pid {os.getpid()}, desde {datetime.datetime.now():%Y-%m-%d %H:%M})"); fd.flush()
    os.environ["FONOTECA_CERROJO"] = str(os.getpid())
    _CERROJO_FD.append(fd)   # abierto hasta que el proceso termina: ahí el sistema lo suelta

def guardar_json(ruta, datos, **kw):
    """Escribe un JSON entero o no lo escribe (archivo temporal + os.replace): un corte nunca deja un JSON truncado."""
    import json
    tmp = f"{ruta}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=kw.pop("ensure_ascii", False), **kw)
    os.replace(tmp, ruta)

def cache_path(nombre):
    return os.path.join(CACHE, nombre)

def plan_path(nombre):
    return os.path.join(PLANES, nombre)

def antra_abierto():
    """True si Antra está corriendo. Se mira /proc/*/comm (no `pgrep -f antra`: encuentra sesiones 'claude antra').
    Ningún script de estos puede tener 'antra' en su nombre de proceso. En modo prueba no importa (no hay state real)."""
    if PRUEBA:
        return False
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) == os.getpid():
            continue
        try:
            if "antra" in open(f"/proc/{pid}/comm").read().lower():
                return True
        except OSError:
            pass
    return False

STATE = os.path.join(ROOT, ".antra_state.json")   # {clave de Antra: ruta absoluta del archivo}

def state_leer():
    """El state de Antra. Falla si su formato no se reproduce byte a byte (así nunca se reescribe distinto de como lo
    deja Antra). {} si no existe. (30 sep: antes cada script que lo tocaba repetía este código.)"""
    import json
    if not os.path.exists(STATE):
        return {}
    text = open(STATE, encoding="utf-8").read()
    state = json.loads(text)
    assert json.dumps(state, indent=2, ensure_ascii=True) == text, "formato del state de Antra no reproducible: no lo toco"
    return state

def state_guardar(state, respaldo=True):
    """Escribe el state de Antra en su mismo formato (archivo temporal + reemplazo: nunca queda a medias). Con respaldo,
    antes copia el actual a respaldos/antra_state-backup-<hora>.json. Devuelve la ruta del respaldo (o None)."""
    import json, shutil
    bak = None
    if respaldo and os.path.exists(STATE):
        bak = os.path.join(RESPALDOS, f"antra_state-backup-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy2(STATE, bak)
    tmp = STATE + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(state, indent=2, ensure_ascii=True))
    os.replace(tmp, STATE)
    return bak

def es_de_album(path):
    """True si el archivo está en Artista/Álbum/archivo (no en la carpeta que Antra está bajando ni en _Playlists)."""
    rel = os.path.relpath(path, ROOT)
    return rel.count(os.sep) >= 2 and rel.split(os.sep)[0] not in SKIP

def borradas():
    """Canciones borradas por borrar_canciones.py (corruptas/equivocadas), de logs/borradas-*/log.json (los dos formatos
    de log): [{"ldir", "old" (ruta absoluta que tenía), "sid", "playlists": [...]}]. Sin spotify_id no se puede seguir."""
    import glob, json
    res = []
    for lj in sorted(glob.glob(os.path.join(LOGS, "borradas-*", "log.json"))):
        l = json.load(open(lj, encoding="utf-8"))
        state = l.get("state_quitado") or l.get("state_removed") or {}
        for x in l.get("borrados") or l.get("moved") or []:
            sid = x.get("spotify_id") or next((k.split(":", 2)[2] for k, v in state.items()
                                               if v == x["old"] and k.startswith("TRACK:spotify:")), "")
            if sid:
                res.append({"ldir": os.path.dirname(lj), "old": x["old"], "sid": sid,
                            "playlists": (l.get("playlists") or {}).get(x["old"]) or []})
    return res

def rutas_por_sid(sids):
    """{spotify_id: ruta absoluta} de las canciones de la biblioteca (Artista/Álbum) con esos spotify_id, o que
    equivalencias.tsv dice que son esa canción con otro spotify_id."""
    from audio import abrir, audios
    res = {}
    if sids:
        for f in sorted(audios(ROOT)):
            if es_de_album(f):
                try:
                    sid = (abrir(f).get("spotify_id") or [""])[0]
                except Exception:
                    continue
                if sid in sids:
                    res.setdefault(sid, f)
        # equivalencias.tsv: la canción está con OTRO spotify_id (27 sep: se re-bajó desde el enlace del disco y no desde
        # el de la canción → sin esto no volvía a sus playlists ni recuperaba sus escuchas en Navidrome)
        p = decision("equivalencias.tsv")
        if os.path.isfile(p):
            for l in open(p, encoding="utf-8"):
                c = l.rstrip("\n").split("\t")
                if not l.startswith("#") and len(c) >= 2 and c[0] in sids and c[0] not in res \
                        and os.path.isfile(os.path.join(ROOT, c[1])):
                    res[c[0]] = os.path.join(ROOT, c[1])
    return res

def cambiar_rutas(mover, nombre, equivalencias=()):
    """Las canciones de `mover` ({ruta vieja: ruta nueva}, absolutas) YA se movieron, renombraron o quitaron (copia que
    sobra → la que queda): actualiza todo lo que guarda rutas y deja el log para Navidrome. Es el bloque que repetía cada
    script que mueve canciones (30 sep 2026): state de Antra (formato intacto), playlists .m3u (sin repetir una canción
    que la playlist ya tenía) y equivalencias.tsv. `equivalencias`: filas nuevas (spotify_id, ruta[, nota]) — p. ej. el
    spotify_id de una copia quitada → la que queda. Respaldos en respaldos/ con la hora. Devuelve la ruta del log que
    deja en logs/nd-pendientes/ (2 oct: SIEMPRE, con `nombre` o «cambios»): la próxima corrida de nd_actualizar.py pasa
    escuchas, estrellas, historial y playlists a la ruta nueva y purga las quitadas, sin que nadie tenga que pasárselo.
    Ruta nueva None = la canción se QUITÓ sin reemplazo: sale del state, de las playlists y de las listas, y Navidrome
    la purga (una canción BORRADA que se va a re-bajar no pasa por aquí: borrar_canciones.py la guarda «faltante»)."""
    import shutil
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    state = state_leer()
    if any(v in mover for v in state.values()):
        state_guardar({k: mover.get(v, v) for k, v in state.items() if mover.get(v, v) is not None})
    pl_dir = os.path.join(ROOT, "_Playlists")
    for m in sorted(os.listdir(pl_dir)) if os.path.isdir(pl_dir) else []:
        if not m.endswith(".m3u"): continue
        mp = os.path.join(pl_dir, m)
        lineas = open(mp, encoding="utf-8").read().split("\n"); out, ya = [], set()
        for l in lineas:
            ab = os.path.normpath(os.path.join(pl_dir, l)) if l and not l.startswith("#") else None
            if ab in mover:
                ab = mover[ab]
                if ab is None: continue   # quitada sin reemplazo: fuera de la playlist
                l = os.path.relpath(ab, pl_dir)
            if ab and ab in ya: continue
            if ab: ya.add(ab)
            out.append(l)
        if out != lineas:
            shutil.copy2(mp, os.path.join(RESPALDOS, f"{m}.{stamp}"))
            open(mp, "w", encoding="utf-8").write("\n".join(out))
    eq_p = decision("equivalencias.tsv")
    if os.path.isfile(eq_p) or equivalencias:
        os.makedirs(DECISIONES, exist_ok=True)
        rel = {os.path.relpath(o, ROOT): (os.path.relpath(n, ROOT) if n else None) for o, n in mover.items()}
        eq = open(eq_p, encoding="utf-8").read().split("\n") if os.path.isfile(eq_p) else ["# spotify_id\truta"]
        nuevo = []
        for l in eq:
            c = l.split("\t")
            if len(c) > 1 and not l.startswith("#") and c[1] in rel:
                if rel[c[1]] is None: continue   # quitada sin reemplazo
                c[1] = rel[c[1]]
            nuevo.append("\t".join(c))
        while nuevo and nuevo[-1] == "": nuevo.pop()
        for sid, r, *nota in equivalencias:
            if sid: nuevo.append("\t".join([sid, os.path.relpath(r, ROOT) if os.path.isabs(r) else r] + nota))
        if nuevo != eq:
            if os.path.isfile(eq_p): shutil.copy2(eq_p, os.path.join(RESPALDOS, f"equivalencias.tsv.{stamp}"))
            open(eq_p, "w", encoding="utf-8").write("\n".join(nuevo) + "\n")
    # ids-mb-aceptados.json también guarda rutas (30 sep: el agrupado de OST del 28 sep no lo actualizó y 2 canciones
    # perdieron su aceptación al moverse → la auditoría volvió a marcarlas)
    ac_p = decision("ids-mb-aceptados.json")
    if os.path.isfile(ac_p):
        rel = {os.path.relpath(o, ROOT): (os.path.relpath(n, ROOT) if n else None) for o, n in mover.items()}
        ac = leer_json(ac_p, {})
        nuevo = {rel.get(k, k): v for k, v in ac.items() if rel.get(k, k) is not None}
        if nuevo != ac:
            shutil.copy2(ac_p, os.path.join(RESPALDOS, f"ids-mb-aceptados.json.{stamp}"))
            guardar_json(ac_p, nuevo, separators=(",", ":"))   # como ids_mb.py
    return log_pendiente(nombre or "cambios", mover)

def esperando_rebajar():
    """Rutas (relativas a ROOT) de canciones borradas que todavía no se re-bajaron: Navidrome las guarda como
    "faltantes" con sus reproducciones y estrellas; al volver a la misma ruta las recupera solas."""
    bs = borradas()
    hoy = rutas_por_sid({b["sid"] for b in bs})
    return sorted({os.path.relpath(b["old"], ROOT) for b in bs if b["sid"] not in hoy})

def _embed(sid):
    """Lee la página embed pública de la canción (sin la Web API ni su cuota; la API por lotes da 403 desde sep 2026)
    y guarda en caché su duración (ms) y el enlace de su vista previa de 30 s. False si no se pudo (no se guarda nada)."""
    import re
    from red import pagina   # 1 cada 1,5 s
    h = pagina(f"https://open.spotify.com/embed/track/{sid}")
    m = re.search(r'"duration":(\d+)', h)
    if not m:
        return False   # sin red o sin respuesta: se reintenta la próxima vez
    pv = re.search(r'"audioPreview":\{"url":"([^"]+)"', h)
    for nombre, valor in (("spotify-embed-duracion.json", int(m.group(1))), ("spotify-embed-preview.json", pv and pv.group(1))):
        c = cache_path(nombre)
        cache = leer_json(c, {})
        cache[sid] = valor
        guardar_json(c, cache)
    return True

def _pagina_publica(url):
    """HTML de una página pública de open.spotify.com (sin la Web API: no necesita Premium ni cuota). 1 cada 1,5 s."""
    from red import pagina
    return pagina(url)

def _cache_publico(clave, leer):
    c = cache_path("spotify-publico.json")
    cache = leer_json(c, {})
    if clave not in cache:
        v = leer()
        if v is None:
            return None   # sin red o sin respuesta: no se guarda (se reintenta la próxima vez)
        cache = leer_json(c, {})
        cache[clave] = v
        guardar_json(c, cache)
    return cache[clave]

def _texto(s):
    import html
    return html.unescape(html.unescape(s or ""))   # Spotify guarda «&apos;» literal (Salgo Pa&apos; la Calle) y la página lo escapa otra vez

def spotify_cancion(sid):
    """Datos públicos de una canción de Spotify, de su página (30 sep 2026: reemplaza a la Web API, que exige Premium al
    dueño de la app): {"titulo", "artistas": [...], "disco", "disco_id", "anio", "duracion" (s)}. Caché en
    cache/spotify-publico.json. None si no se pudo (sin red, o la canción ya no existe)."""
    import re
    def leer():
        h = _pagina_publica(f"https://open.spotify.com/track/{sid}")
        meta = dict(re.findall(r'<meta (?:property|name)="([^"]+)" content="([^"]*)"', h))
        alb = re.search(r"open\.spotify\.com/album/([A-Za-z0-9]+)", meta.get("music:album", ""))
        if not meta.get("og:title") or not alb:
            return None
        partes = [_texto(x) for x in meta.get("og:description", "").split(" · ")]   # «Artistas · Disco · Song · Año»
        return {"titulo": _texto(meta["og:title"]), "artistas": [a.strip() for a in partes[0].split(",")] if partes else [],
                "disco": partes[1] if len(partes) > 1 else "", "disco_id": alb.group(1),
                "anio": partes[3] if len(partes) > 3 else "", "duracion": int(meta.get("music:duration") or 0)}
    return _cache_publico("track:" + sid, leer) if sid else None

def spotify_disco(album_id):
    """Canciones de un disco de Spotify, de su página embed pública (trae el disco entero: 59 de 59 probado):
    {"nombre", "artista", "canciones": [{"id", "titulo", "artista" (el primero), "duracion" (s), "pista"}]}. None si no se pudo."""
    import json, re
    def leer():
        h = _pagina_publica(f"https://open.spotify.com/embed/album/{album_id}")
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', h, re.S)
        try:
            e = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
        except (AttributeError, KeyError, TypeError, ValueError):
            return None
        return {"nombre": _texto(e.get("name")), "artista": _texto(e.get("subtitle")),
                "canciones": [{"id": t["uri"].split(":")[-1], "titulo": _texto(t.get("title")),
                               "artista": _texto(t.get("subtitle")).replace("\xa0", " ").split(",")[0].strip(),
                               "duracion": round((t.get("duration") or 0) / 1000), "pista": i}
                              for i, t in enumerate(e.get("trackList") or [], 1) if t.get("uri", "").startswith("spotify:track:")]}
    return _cache_publico("album:" + album_id, leer) if album_id else None

def duracion_spotify(sid):
    """Duración (s) de la canción EXACTA de Spotify (la que se bajó), del embed público. None si no se pudo."""
    c = cache_path("spotify-embed-duracion.json")
    cache = leer_json(c, {})
    if sid and sid not in cache and _embed(sid):
        cache = leer_json(c, {})
    return cache[sid] / 1000 if sid in cache else None

def parecido_spotify(sid, ruta):
    """Cuánto se parece el archivo a la vista previa de 30 s de la canción EXACTA de Spotify (huellas de Chromaprint):
    ~1.0 = contiene ese mismo audio; ~0.5-0.65 = otro audio. Calibrado el 25 sep 2026: correctas 0,89-0,99, equivocadas
    0,54-0,64; ojo: un remix que comparte partes con el original da ~0,93. None si Spotify no tiene vista previa o falló.
    Caché: la huella de la vista previa (no el audio) en cache/spotify-preview-huella.json."""
    import json, subprocess, tempfile
    def huella(p):
        r = subprocess.run(["fpcalc", "-raw", "-json", "-length", "0", p], capture_output=True, text=True)
        try:
            return json.loads(r.stdout)["fingerprint"]
        except (ValueError, KeyError):
            return None
    if not sid:
        return None
    c = cache_path("spotify-preview-huella.json")
    cache = leer_json(c, {})
    if sid not in cache:
        cu = cache_path("spotify-embed-preview.json")
        urls = leer_json(cu, {})
        if sid not in urls:
            if not _embed(sid):
                return None
            urls = leer_json(cu, {})
        hp = None
        if urls.get(sid):   # 2 oct: -f (un 403/404 ya no llega como «archivo») y una huella fallida NO se guarda
            with tempfile.NamedTemporaryFile(suffix=".mp3") as t:
                if subprocess.run(["curl", "-fsS", "--max-time", "30", "-o", t.name, urls[sid]]).returncode != 0:
                    return None
                hp = huella(t.name)
            if not hp:
                return None   # se reintenta la próxima vez; «sin vista previa» se guarda solo si Spotify no la tiene
        cache = leer_json(c, {})
        cache[sid] = hp
        guardar_json(c, cache)
    corto, largo = cache[sid], huella(ruta)
    if not corto or not largo:
        return None
    mejor = 0.0
    for off in range(0, max(1, len(largo) - len(corto) + 1)):   # la vista previa deslizada sobre toda la canción
        seg = largo[off:off + len(corto)]
        if len(seg) < len(corto) * 0.9:
            break
        mejor = max(mejor, sum(32 - bin(a ^ b).count("1") for a, b in zip(corto, seg)) / (32 * len(seg)))
    return round(mejor, 3)

def dura_distinto(archivo_s, referencia_s):
    """True si el audio no es la misma versión que la referencia: más de 3 s de diferencia (1% en temas de más de 5 min).
    El mismo master dura lo mismo (±1 s) en cualquier tienda; otro edit/remix/versión suele diferir varios segundos
    (el CANDY Remix equivocado del 25 sep duraba 8 s menos)."""
    return abs(archivo_s - referencia_s) > max(3, 0.01 * referencia_s)

def sin_procesar():
    """Audios que NO pasaron por procesar_descarga.py, estén donde estén (rutas relativas a ROOT): fuera de
    Artista/Álbum/NN - Título.flac, o sin ReplayGain (el paso 7d se lo pone a todo; Antra no). Incluye las carpetas
    de descarga de la raíz (Carpeta/archivo.flac) y las canciones sueltas que Antra deja como
    "<artistas>/<año> - <álbum>/<artistas> - <título>.flac" (25 sep 2026: toda la biblioteca cumplía, 0 excepciones)."""
    import re
    from audio import abrir, es_audio, RE_EXT
    nombre_ok = re.compile(r"^(\d+-)?\d+ - .+" + RE_EXT + "$", re.I)   # 28 sep: cualquier formato
    malos = []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if not x.startswith(".") and not (d == ROOT and x in SKIP)]
        for f in files:
            if not es_audio(f):
                continue
            p = os.path.join(d, f)
            rel = os.path.relpath(p, ROOT)
            if rel.count(os.sep) != 2 or not nombre_ok.match(f):
                malos.append(rel)
                continue
            try:
                if not abrir(p).get("replaygain_track_gain"):
                    malos.append(rel)
            except Exception:   # a medio escribir o dañado
                malos.append(rel)
    return sorted(malos)

def anotar_fallida(origen, artista, titulo, album, uri):
    """Agrega una canción a conseguir a revisar_fallidas.tsv: UNA fila por URI (28 sep: cada descarga que no la bajaba
    agregaba otra con su origen). Si ya está, solo se reemplaza cuando la nueva es «Borrada …» (avisa que Antra trae otro
    audio). revisar.py la muestra en el documento de pendientes y la quita sola cuando aparece en la biblioteca."""
    uri = uri or ""
    if uri and "open.spotify.com/track/" in uri:
        uri = "spotify:track:" + uri.rsplit("/", 1)[-1].split("?")[0]
    fila = "\t".join(str(x or "").replace("\t", " ").replace("\n", " ") for x in (origen, artista, titulo, album, uri))
    if os.path.exists(FALLIDAS):
        lineas = open(FALLIDAS, encoding="utf-8").read().splitlines()
        for i, l in enumerate(lineas):
            c = l.split("\t")
            if len(c) >= 5 and not l.startswith("#") and (c[4] == uri if uri else c[:3] == [origen, artista, titulo]):
                if not (uri and str(origen).startswith("Borrada")) or l == fila:
                    return False
                lineas[i] = fila
                open(FALLIDAS, "w", encoding="utf-8").write("\n".join(lineas) + "\n")
                return True
    else:
        open(FALLIDAS, "w", encoding="utf-8").write("# origen\tartista\ttítulo\tálbum\turi\n")
    with open(FALLIDAS, "a", encoding="utf-8") as f:
        f.write(fila + "\n")
    return True

DUDOSAS = os.path.join(DATOS, "revisar_dudosas.tsv")   # canciones que SÍ están pero hay que revisar (audio/ID dudoso)

def anotar_dudosa(motivo, spotify_id, artista, titulo, detalle=""):
    """Anota una canción presente pero dudosa (p. ej. AcoustID no la conoce, ID de disco de MusicBrainz ajeno).
    Se identifica por su spotify_id (no cambia al renombrar/mover); revisar.py muestra dónde está hoy y la
    quita sola si la canción ya no existe."""
    if not spotify_id:
        return False
    fila = "\t".join(str(x or "").replace("\t", " ").replace("\n", " ")
                     for x in (datetime.date.today(), motivo, spotify_id, artista, titulo, detalle))
    if os.path.exists(DUDOSAS):
        for l in open(DUDOSAS, encoding="utf-8"):
            c = l.rstrip("\n").split("\t")
            if len(c) >= 3 and c[1] == motivo and c[2] == spotify_id:
                return False
    else:
        open(DUDOSAS, "w", encoding="utf-8").write("# fecha\tmotivo\tspotify_id\tartista\ttítulo\tdetalle\n")
    with open(DUDOSAS, "a", encoding="utf-8") as f:
        f.write(fila + "\n")
    return True

# ---------- "¿es la misma canción?" (una sola regla para todos los scripts) ----------
import re as _re, unicodedata as _ud
# Calificadores que NO cambian la grabación: se ignoran al comparar títulos.
_MISMA = _re.compile(r"^((\d{4} )?(digital(ly)? )?remaster(ed|izad[oa])?( \d{4})?( version)?|radio edit|edit|single version"
                     r"|album version|albm version|version (del )?album|original( mix| version)?|mono|stereo|explicit|clean"
                     r"|bonus( track)?|from .*|feat\.? .*|ft\.? .*|with .*|con .*)$")

def _plano(s):
    s = _ud.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not _ud.combining(c))

# Texto comparable (30 sep 2026: antes había 3 variantes de estas funciones copiadas en 7 scripts, con el nombre «n»).
def plano(s):
    """Minúsculas, sin acentos ni signos: 'Pa-Kum-Pa!' → 'pakumpa'."""
    return _re.sub(r"[^\w]", "", _plano(s))

def sin_parentesis(s):
    """Como plano(), sin lo que va entre paréntesis o corchetes: 'Thriller (Deluxe)' → 'thriller'."""
    return plano(_re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", _plano(s)))

def titulo_base(s):
    """Como sin_parentesis(), y además sin lo que sigue a « - »: 'Bohemian Rhapsody - Remastered 2011' → 'bohemianrhapsody'."""
    s = _re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", _plano(s))
    return plano(_re.sub(r"\s+-\s+.*$", "", s))

def primer_artista(a, y=False):
    """El primer nombre de una lista de artistas, TAL CUAL (para buscar en Deezer, LRCLIB, AcoustID…):
    'Wisin & Yandel, Daddy Yankee' → 'Wisin & Yandel'… → 'Wisin'. Corta en , & feat ft x con (y en « y » con y=True).
    Para COMPARAR artistas está clave_artista(). (30 sep: antes copiada en 4 scripts con el nombre «first»)."""
    sep = r"\s*(?:,|&|feat\.?|ft\.?| x | con " + ("| y " if y else "") + r")\s*"
    return _re.split(sep, a or "", flags=_re.I)[0]

def clave_titulo(titulo):
    """Título comparable. Ignora remaster/radio edit/single version/'From X'/feat., pero CONSERVA lo que es otra
    versión: remix, en vivo, acústica, regrabación, instrumental, sped up...
    'Bohemian Rhapsody - Remastered 2011' == 'Bohemian Rhapsody';  'Shaky Shaky - Remix' != 'Shaky Shaky'."""
    s = _plano(titulo)
    calif = _re.findall(r"[\(\[]([^\)\]]*)[\)\]]", s)
    s = _re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", s)
    partes = [x.strip() for x in s.split(" - ")]
    base, calif = partes[0], calif + partes[1:]
    quedan = sorted({_re.sub(r"[^\w]", "", c) for c in (x.strip() for x in calif) if c and not _MISMA.match(c)})
    return _re.sub(r"[^\w]", "", base) + ("|" + "|".join(quedan) if quedan else "")

def clave_artista(artista):
    """Primer artista, comparable: 'Wisin & Yandel, Daddy Yankee' → 'wisin' ... (corta en , & feat x con)."""
    a = _re.split(r"\s*(?:,|&|\bfeat\.?|\bft\.?|\bx\b|\bcon\b|\by\b)\s*", _plano(artista))[0]
    return _re.sub(r"[^\w]", "", a)

# ---------- "¿este ID de MusicBrainz es de esta canción?" (27 sep 2026: ids_mb.py, enriquecer.py) ----------
# Picard puso IDs por POSICIÓN (el número de descarga de Antra) → ~160 canciones con el ID de otra (Billie Jean tenía el
# de «Thriller»). Una grabación corresponde a un archivo por título + duración, o ISRC + duración; nunca por número de pista.
# Clave de AcoustID (opcional, acoustid.org → «API key»): en .acoustid_key junto a los scripts, nunca en el código.
# Sin ella, el procesado compara las sospechosas solo con la canción de Spotify (30 sep: antes se detenía).
_ak = os.path.join(HERE, ".acoustid_key")
ACOUSTID_KEY = open(_ak).read().strip() if os.path.exists(_ak) else None

# MusicBrainz exige un User-Agent con un contacto: [contacto] user_agent en config.toml (red.py lo usa en todo)
UA = {"User-Agent": CONF.get("contacto", {}).get("user_agent", "fonoteca/1.0 (configura tu contacto en config.toml)")}
_ROMANOS = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}
_VERSION = _re.compile(r"remix|rmx|mix|edit|version|live|envivo|directo|instrumental|acoustic|acustic|extended|dub|club"
                       r"|radio|rework|bootleg|cover|demo|reprise|sped|slowed|orchestral")
_EDICION = _re.compile(r"\s*[\(\[][^\)\]]*[\)\]]|\s+-\s+.*$|\b(deluxe|expanded|remaster(ed)?|anniversary|edition|version"
                       r"|bonus|special|super)\b.*$", _re.I)

def base_disco(s):
    """Nombre de disco sin ediciones ('Thriller (25th Anniversary)' → 'thriller'): la misma regla de mb_disco.py."""
    s = _plano(_EDICION.sub("", s or ""))
    return _re.sub(r"[^\w]", "", s)

_LIGADURAS = str.maketrans({"œ": "oe", "æ": "ae", "ß": "ss", "ø": "o", "ł": "l", "đ": "d"})
def _norm_mb(s):
    s = _re.sub(r"\bpt\.?\s*", "part ", _plano(s).translate(_LIGADURAS))          # Pt. 2 → part 2; Phœnix → phoenix
    return _re.sub(r"\b(part|parte|vol|no|chapter|act)\.?\s+(i{1,3}|iv|vi{0,3}|ix|x)\b",
                   lambda m: m.group(1) + " " + _ROMANOS[m.group(2)], s)             # Part II → part 2
def _ct(t): return clave_titulo(_norm_mb(t))
def _pl(t): return _re.sub(r"[^\w]", "", _norm_mb(t))
def _base(t): return _ct(t).split("|")[0]
def _calif(t):
    """Calificadores de VERSIÓN del título (remix, mix, edit, en vivo...), sin repetir el título ('X - X Club Edit' → 'clubedit')."""
    b = _base(t)
    qs = [c[len(b):] if b and c.startswith(b) else c for c in _ct(t).split("|")[1:] if c]
    return [q for q in qs if q and _VERSION.search(q)]
def _partes(t): return [_ct(p) for p in _re.split(r"\s+-\s+|:\s+|\s+/\s+|／", t) if p.strip()]
def _no_latinas(s): return sum(1 for c in s if c.isalpha() and "LATIN" not in _ud.name(c, "LATIN"))

def nivel_titulo(a, b):
    """Cuánto coinciden dos títulos: 3 = el mismo (con la regla de clave_titulo); 2 = uno es parte del otro ('Spirited Away -
    One Summer's Day') o casi igual (transliteraciones); 1 = mismo título base, puede ser otra versión; 0 = distintos
    (también si tienen números distintos, Part 4 ≠ Part 5, o versiones distintas, Tanzen Vision remix ≠ Tecno Fez remix);
    None = alfabetos distintos (japonés o árabe contra latino): no se pueden comparar."""
    import difflib
    pa_, pb_ = _re.split(r"\s+=\s+", a), _re.split(r"\s+=\s+", b)          # títulos bilingües de MusicBrainz: 'حبايبنا = Habayebna'
    if (len(pa_) > 1 or len(pb_) > 1) and any(_ct(x) and _ct(x) == _ct(y) for x in pa_ for y in pb_):
        return 2
    if (_no_latinas(a) >= 2) != (_no_latinas(b) >= 2):
        return None
    ca, cb = _ct(a), _ct(b)
    if ca == cb:
        return 3
    na, nb = set(_re.findall(r"\d+", _norm_mb(a))), set(_re.findall(r"\d+", _norm_mb(b)))
    if na - nb and nb - na:
        return 0
    qa, qb = _calif(a), _calif(b)
    if qa and qb and not any(difflib.SequenceMatcher(None, x, y).ratio() >= 0.6 for x in qa for y in qb):
        return 0
    tope = 1 if bool(qa) != bool(qb) else 2          # 'Best Friends - Remix' vs 'Best Friends': como mucho 1 (pide duración)
    pa, pb = _partes(a), _partes(b)
    if ca in pb or cb in pa or (len(pa) > 1 and len(pb) > 1 and pa[-1] == pb[-1]):
        return tope
    la, lb = _pl(a), _pl(b)
    if la and lb and difflib.SequenceMatcher(None, la, lb).ratio() >= 0.85:
        return tope
    ba, bb = _base(a), _base(b)
    if ba and bb and (ba == bb or difflib.SequenceMatcher(None, ba, bb).ratio() >= 0.85):
        return 1
    return 0

def grabacion_corresponde(titulo, artista, duracion, isrcs, rec_titulo, rec_duracion, rec_isrcs, rec_artistas, en_acoustid=False):
    """¿La grabación de MusicBrainz (rec_*) es la de este archivo? → (sí/no, nivel de título, motivo).
    Sí con: ISRC + duración (±4 s o 3%: un error por posición nunca coincide en ISRC); título (nivel >= 1) + duración;
    título casi igual (nivel >= 2) + ISRC aunque la duración difiera (MusicBrainz a veces guarda la de otra edición), o sin
    duración en MusicBrainz; alfabetos distintos: duración + (ISRC o AcoustID; el artista no alcanza: en un disco del mismo
    artista otra canción puede durar casi lo mismo, FXXK IT ≈ BANG BANG BANG). rec_duracion en segundos o None."""
    nt = nivel_titulo(titulo, rec_titulo or "")
    iok = bool(set(isrcs or []) & set(rec_isrcs or []))
    dok = bool(rec_duracion) and abs(duracion - rec_duracion) <= max(4, 0.03 * duracion)
    if iok and dok:
        return True, nt, "ISRC y duración"
    if nt is None:
        return bool(dok and (iok or en_acoustid)), nt, "otro alfabeto" + (" y duración" if dok else ", duración distinta")
    if nt >= 1 and dok:
        return True, nt, f"título ({nt}) y duración"
    if nt >= 2 and not rec_duracion:
        return True, nt, f"título ({nt}); MusicBrainz no sabe la duración"
    if nt >= 2 and iok:
        return True, nt, f"título ({nt}) e ISRC, duración distinta"
    return False, nt, f"título ({nt}), duración {'ok' if dok else ('?' if not rec_duracion else 'distinta')}, ISRC {'sí' if iok else 'no'}"

def indice_biblioteca():
    """Índice para buscar canciones de Spotify en la biblioteca: {"sid": {spotify_id: ruta}, "clave": {(clave_artista,
    clave_titulo): ruta} (por artista y por artista del disco), "eq": equivalencias.tsv}. Rutas relativas a ROOT; con
    hardlinks cuenta una sola copia; con claves repetidas gana la primera ruta en orden alfabético (siempre la misma)."""
    from audio import abrir, audios
    by_sid, by_key, seen, rels = {}, {}, set(), set()
    for f in sorted(audios(ROOT)):
        rel = os.path.relpath(f, ROOT)
        if not es_de_album(f): continue
        ino = os.stat(f).st_ino
        if ino in seen: continue
        seen.add(ino); rels.add(rel)
        t = abrir(f); g = lambda k: (t.get(k) or [""])[0]
        if g("spotify_id"): by_sid.setdefault(g("spotify_id"), rel)
        for a in {g("artist"), g("albumartist")}:
            if a: by_key.setdefault((clave_artista(a), clave_titulo(g("title"))), rel)
    eq = {}
    p = decision("equivalencias.tsv")
    if os.path.isfile(p):
        for l in open(p, encoding="utf-8"):
            c = l.rstrip("\n").split("\t")
            if l.startswith("#") or len(c) < 2: continue
            if c[1] in rels: eq[c[0]] = c[1]          # solo si el archivo está (en modo prueba no está)
    return {"sid": by_sid, "clave": by_key, "eq": eq, "_claves": {}}

def buscar(indice, sid, artista, titulo):
    """Ruta relativa de una canción de Spotify en la biblioteca, o None. Orden: equivalencias.tsv (revisadas a mano),
    spotify_id exacto, y (primer artista, título) con la regla única de "misma canción"."""
    r = indice["eq"].get(sid) or indice["sid"].get(sid)
    if r: return r
    k = (artista, titulo)
    if k not in indice["_claves"]: indice["_claves"][k] = (clave_artista(artista), clave_titulo(titulo))
    return indice["clave"].get(indice["_claves"][k])

def a_conseguir(ind=None):
    """Las canciones de revisar_fallidas.tsv que todavía NO están en la biblioteca, sin repetir:
    [(origen, artista, título, álbum, spotify_id)]. La usan buscar_fuentes.py e importar_manual.py."""
    ind = ind or indice_biblioteca()
    filas, vistos = [], set()
    if not os.path.exists(FALLIDAS):
        return filas
    for l in open(FALLIDAS, encoding="utf-8"):
        if not l.strip() or l.startswith("#"): continue
        origen, art, tit, alb, uri = (l.rstrip("\n").split("\t") + [""] * 5)[:5]
        sid = uri.rsplit(":", 1)[-1] if uri.startswith("spotify:track:") else ""
        if buscar(ind, sid, art, tit):
            continue   # ya está en la biblioteca
        k = sid or (clave_artista(art), clave_titulo(tit))
        if k in vistos: continue
        vistos.add(k); filas.append((origen, art, tit, alb, sid))
    return filas

def historial_en_biblioteca(zpath, ind=None):
    """Canciones del historial extendido de Spotify (zip) que están en la biblioteca. Cada escucha se busca con
    comun.buscar (su propio ID de Spotify va a su propio archivo); si su ID no está, va al archivo que tienen las
    otras escuchas con el mismo (artista, título) según la regla de "misma canción". No cambia de una corrida a otra.
    Devuelve {ruta relativa: {"plays": escuchas >=30 s, "last": ts de la última escucha >=30 s (UTC, ISO; "" si
    nunca)}}; incluye las que están pero solo tienen saltos (plays 0). ind: un indice_biblioteca() ya hecho."""
    import collections, json, zipfile
    ind = ind or indice_biblioteca()
    entradas, grupo = [], collections.defaultdict(collections.Counter)
    with zipfile.ZipFile(zpath) as z:
        for n in sorted(z.namelist()):
            if not (n.endswith(".json") and "Audio" in n): continue
            for e in json.load(z.open(n)):
                uri, tr = e.get("spotify_track_uri"), e.get("master_metadata_track_name")
                if not uri or not tr: continue
                a = e.get("master_metadata_album_artist_name")
                rel = buscar(ind, uri.split(":")[-1], a, tr)
                k = ind["_claves"].get((a, tr)) or (clave_artista(a), clave_titulo(tr))
                if rel: grupo[k][rel] += 1
                entradas.append((rel, k, e.get("ms_played") or 0, e["ts"]))
    elegido = {k: min(c, key=lambda r: (-c[r], r)) for k, c in grupo.items()}   # el más escuchado; empate: alfabético
    found = {}
    for rel, k, ms, ts in entradas:
        rel = rel or elegido.get(k)
        if not rel: continue
        d = found.setdefault(rel, {"plays": 0, "last": ""})
        if ms >= 30000:
            d["plays"] += 1; d["last"] = max(d["last"], ts)
    return found
