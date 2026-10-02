#!/usr/bin/env python3
"""Pone a Navidrome al día después de mover, renombrar o quitar canciones (paso 8 de procesar_descarga.py).

Uso: nd_actualizar.py [<log.json> ...] [--usuario <Nombre>] [--purgar-huerfanas]
  Aplica TODOS los logs pendientes de logs/nd-pendientes/ (2 oct 2026: los deja comun.cambiar_rutas, es decir, todo lo
  que mueve o quita canciones: repartir, duplicados, numeros_pista, quitar_copia, unir_discos, ost, el embudo…), en
  orden, más los <log.json> que se le pasen. Un log es {"cambios": [{"old_path", "new_path"}], "quitadas": [...]}: las
  reproducciones, estrellas, ratings, historial (tabla scrobbles) y entradas de playlist de la ruta vieja pasan a la
  nueva; las «quitadas» (declaradas a propósito: una copia sin reemplazo, un MP3 de prueba borrado) se purgan.
  Se unen EN ORDEN en uno solo (A→B y luego B→C queda A→C): migrarlos por separado perdía las escuchas de A.
  Los logs pendientes pasan a logs/nd-aplicados/ SOLO si todo terminó bien; si no, quedan y la próxima corrida los
  vuelve a aplicar (migrar dos veces no hace daño).
  --usuario:  la playlist _Playlists/<Nombre>.m3u queda a nombre de ese usuario y privada.
Reglas (2 oct):
  · NUNCA se purga lo que ningún log explica. Si queda alguna canción «faltante» sin explicación (movida a mano, un
    corte sin log, una ruta nueva que Navidrome no ve), no se purga NADA, se avisa (notify-send) y termina con error;
    la lista queda en logs/nd-sin-explicar-<fecha>.txt. Se revisa (¿dónde está hoy? → un log a mano, o
    `navidrome missing fix`) o, si de verdad se borró a propósito, --purgar-huerfanas.
  · Las borradas por borrar_canciones.py (corruptas/equivocadas) que esperan re-descarga se quedan «faltantes» con sus
    reproducciones; si vuelven con otra ruta, sus reproducciones pasan a la nueva.
  · Si la biblioteca parece vacía o desmontada (sin audio en el disco, o mucho menos que lo que Navidrome tiene), no se
    escanea siquiera: un escaneo así marca TODO como faltante.
  · Antes de escribir en la base, siempre una copia en respaldos/navidrome/.
Orden: comprobar la biblioteca → escaneo completo → detener Navidrome → copia de la base → migrar → dueño de la
playlist → purgar lo explicado → arrancar → escaneo → mover los logs a aplicados.
"""
import datetime, glob, json, os, shutil, sqlite3, subprocess, sys
from comun import (HERE, LOGS, PRUEBA, ROOT, RESPALDOS, SKIP, NAVIDROME_DB, NAVIDROME, ND_PENDIENTES, ND_APLICADOS,
                   borradas, rutas_por_sid, guardar_json, cerrojo)
from audio import es_audio

ND = NAVIDROME   # config.toml: rutas.navidrome
args = sys.argv[1:]
if any(a in ("-h", "--help") for a in args):
    sys.exit(__doc__)
if PRUEBA:   # banco de pruebas o una prueba aislada (MUSIC_ROOT): el Navidrome de verdad no se toca nunca
    print("(modo prueba: Navidrome no se toca; los logs quedan en nd-pendientes)")
    sys.exit(0)
user = args[args.index("--usuario") + 1] if "--usuario" in args else None
cerrojo("nd_actualizar.py")   # 2 oct: dos a la vez cruzaban stop/up de Navidrome y escrituras en la base
PURGAR_HUERFANAS = "--purgar-huerfanas" in args
STAMP = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"
RAIZ = ROOT + "/"
rel = lambda p: p.removeprefix(RAIZ)


def avisar(titulo, cuerpo):
    try:
        subprocess.run(["notify-send", "-a", "Música", "-i", "dialog-warning", "-u", "critical", "-t", "0", titulo, cuerpo], check=False)
    except OSError:
        pass


def fallo(msg):
    print(f"\n⛔ {msg}", flush=True)
    avisar("Navidrome NO quedó al día", msg)
    sys.exit(1)


# ---------- 1. qué logs y qué cambios ----------
explicitos = [os.path.abspath(a) for a in args if a.endswith(".json")]
for a in explicitos:
    if not os.path.isfile(a):
        fallo(f"no existe el log {a}")
pendientes = sorted(glob.glob(os.path.join(ND_PENDIENTES, "*.json")))   # el nombre empieza por la fecha: orden = tiempo
logs = sorted(explicitos, key=os.path.getmtime) + pendientes


def leer(lg):
    try:
        d = json.load(open(lg, encoding="utf-8"))
    except (OSError, ValueError) as e:
        fallo(f"no puedo leer el log {lg}: {e}")
    return [(c["old_path"], c["new_path"]) for c in d.get("cambios", []) if c.get("old_path") and c.get("new_path")], \
           [q for q in d.get("quitadas", []) if q]


mapa, quitadas = {}, []   # ruta vieja → ruta final (absolutas), rutas quitadas a propósito
_bs = borradas()
_hoy = rutas_por_sid({b["sid"] for b in _bs})
esperando = sorted({rel(b["old"]) for b in _bs if b["sid"] not in _hoy})
for b in _bs:   # borradas que volvieron con otra ruta: primero (los renombres de después encadenan encima)
    if b["sid"] in _hoy and _hoy[b["sid"]] != b["old"]:
        mapa[b["old"]] = _hoy[b["sid"]]
for lg in logs:
    cambios, qs = leer(lg)
    for o, n in cambios:
        if o == n:
            continue
        for k in [k for k, v in mapa.items() if v == o]:
            mapa[k] = n
        mapa.setdefault(o, n)
    for q in qs:
        for k in [k for k, v in mapa.items() if v == q]:   # movida y después quitada: la vieja también se quita
            quitadas.append(k); del mapa[k]
        mapa.pop(q, None)
        quitadas.append(q)
quitadas = sorted(set(quitadas) - set(mapa))
print(f"logs: {len(pendientes)} pendientes + {len(explicitos)} explícitos → {len(mapa)} cambios de ruta, {len(quitadas)} quitadas, "
      f"{len(esperando)} borradas esperando re-descarga")
if logs:
    guardar_json(os.path.join(LOGS, f"nd-cambios-{STAMP}.json"),
                 {"cambios": [{"old_path": o, "new_path": n} for o, n in mapa.items()], "quitadas": quitadas, "de": logs}, indent=1)


# ---------- 2. la biblioteca está (no se escanea una biblioteca desmontada) ----------
def en_disco():
    n = 0
    for d, dirs, fs in os.walk(ROOT):
        if d == ROOT:
            dirs[:] = [x for x in dirs if not x.startswith(".") and x not in SKIP]
        n += sum(1 for f in fs if es_audio(f))
    return n


def con_db(ro=True):
    return sqlite3.connect(f"file:{NAVIDROME_DB}?mode=ro", uri=True) if ro else sqlite3.connect(NAVIDROME_DB)


disco = en_disco()
try:
    con = con_db()
    nd_antes = con.execute("select count(*) from media_file where missing=0 and path not like '_Prueba/%'").fetchone()[0]
    con.close()
except sqlite3.Error as e:
    fallo(f"no puedo leer la base de Navidrome ({NAVIDROME_DB}): {e}")
print(f"en el disco: {disco} audios | en Navidrome: {nd_antes}")
if disco == 0 or (nd_antes >= 20 and disco < nd_antes * 0.5):
    fallo(f"la biblioteca parece vacía o desmontada ({disco} audios en {ROOT}; Navidrome tiene {nd_antes}): no escaneo ni toco nada.")


# ---------- 3. Navidrome ----------
ESCANEO = os.path.join(LOGS, f"nd-escaneo-{STAMP}.log")


def run(title, cmd, check=True, a_log=False):
    print(f"\n--- {title}\n$ {' '.join(cmd)}", flush=True)
    if a_log:   # el escaneo imprime una línea por carpeta: llenaba la terminal y tapaba los pasos anteriores
        with open(ESCANEO, "a", encoding="utf-8") as f:
            r = subprocess.run(cmd, cwd=HERE, stdout=f, stderr=subprocess.STDOUT)
        fin = [l for l in open(ESCANEO, encoding="utf-8", errors="replace").read().splitlines() if l.strip()][-2:]
        print(*["   " + l[:160] for l in fin], f"   (salida completa en logs/{os.path.basename(ESCANEO)})", sep="\n")
    else:
        r = subprocess.run(cmd, cwd=HERE)
    if check and r.returncode != 0:
        fallo(f"falló: {title}")
    return r.returncode


def migrar(con, pares):
    """Con Navidrome DETENIDO y después de un escaneo: pasa reproducciones, estrellas, ratings, historial (tabla
    scrobbles) y entradas de playlist de cada canción vieja (missing) a la nueva. Devuelve (migradas, {vieja: motivo}
    de las que no se pudieron: la nueva no está en Navidrome)."""
    ids = {}
    for mid, path, missing in con.execute("select id, path, missing from media_file"):
        ids.setdefault(path, []).append((mid, missing))
    mp, sin_par = {}, {}
    for old, new in pares:
        o = [m for m, miss in ids.get(old, []) if miss]
        if not o:
            continue   # Navidrome no la tiene como faltante: ya la reconoció movida, o nunca la vio
        nw = [m for m, miss in ids.get(new, []) if not miss]
        if not nw:
            sin_par[old] = f"la ruta nueva no está en Navidrome: {new}"
        elif o[0] != nw[0]:
            mp[o[0]] = nw[0]
    q = ",".join("?" * len(mp))
    ann = con.execute(f"select count(*) from annotation where item_type='media_file' and item_id in ({q})", list(mp)).fetchone()[0] if mp else 0
    pl = con.execute(f"select count(*) from playlist_tracks where media_file_id in ({q})", list(mp)).fetchone()[0] if mp else 0
    print(f"   pares viejo→nuevo: {len(mp)} de {len(pares)} | anotaciones a mover: {ann} | entradas de playlist: {pl}")
    with con:
        for o, nw in mp.items():
            # si la nueva ya tiene anotación del mismo usuario, se suman reproducciones y se conserva la estrella
            for uid, pc, pd, st, sa, rt in con.execute("select user_id, play_count, play_date, starred, starred_at, rating from annotation "
                                                        "where item_type='media_file' and item_id=?", (o,)).fetchall():
                ex = con.execute("select play_count from annotation where item_type='media_file' and item_id=? and user_id=?", (nw, uid)).fetchone()
                if ex:
                    con.execute("update annotation set play_count=coalesce(play_count,0)+?, starred=max(coalesce(starred,0),?), "
                                "rating=max(coalesce(rating,0),?), play_date=max(coalesce(play_date,''),coalesce(?,'')), "
                                "starred_at=coalesce(starred_at, ?) where item_type='media_file' and item_id=? and user_id=?",
                                (pc or 0, st or 0, rt or 0, pd, sa, nw, uid))
                    con.execute("delete from annotation where item_type='media_file' and item_id=? and user_id=?", (o, uid))
                else:
                    con.execute("update annotation set item_id=? where item_type='media_file' and item_id=? and user_id=?", (nw, o, uid))
            con.execute("update playlist_tracks set media_file_id=? where media_file_id=?", (nw, o))
            # historial con fecha (tabla scrobbles): antes quedaba huérfano al borrar la fila vieja (la cascada de la tabla
            # no se aplica sin PRAGMA foreign_keys) — 28 sep: 72 huérfanos reparados
            con.execute("update scrobbles set media_file_id=? where media_file_id=?", (nw, o))
            con.execute("delete from media_file where id=?", (o,))
    print("   migrado.")
    return len(mp), sin_par


compose = ["docker", "compose", "-f", os.path.join(ND, "docker-compose.yml")]
run("escaneo completo", ["docker", "exec", "navidrome", "/app/navidrome", "scan", "--full"], a_log=True)
run("detener Navidrome", compose + ["stop"])
bien, problema = True, ""
try:
    os.makedirs(os.path.join(RESPALDOS, "navidrome"), exist_ok=True)   # copia de la base ANTES de escribir, siempre
    resp = os.path.join(RESPALDOS, "navidrome", f"navidrome.db.antes-{STAMP}")
    shutil.copy2(NAVIDROME_DB, resp)
    print(f"\n--- copia de la base: {resp}")
    con = con_db(ro=False)
    pares = [(rel(o), rel(n)) for o, n in mapa.items()]
    print(f"\n--- migrar reproducciones/playlists ({len(pares)} cambios de ruta)", flush=True)
    migradas, sin_par = migrar(con, pares) if pares else (0, {})
    if user:
        with con:
            con.execute("update playlist set owner_id=(select id from user where user_name=?), public=0 where path=?",
                        (user, f"/music/_Playlists/{user}.m3u"))
        print(con.execute("select name, song_count from playlist where path=?", (f"/music/_Playlists/{user}.m3u",)).fetchall())
    # qué queda «faltante» y por qué
    faltantes = [p for (p,) in con.execute("select path from media_file where missing=1")]
    explicadas = {rel(q) for q in quitadas}
    sin_explicar = sorted(p for p in faltantes if p not in explicadas and p not in esperando and p not in sin_par)
    print(f"\n--- faltantes en Navidrome: {len(faltantes)} = quitadas a propósito {sum(1 for p in faltantes if p in explicadas)}"
          f" + esperando re-descarga {sum(1 for p in faltantes if p in esperando)} + sin ruta nueva {len(sin_par)} + SIN EXPLICAR {len(sin_explicar)}")
    for o, m in sorted(sin_par.items()):
        print(f"   ⚠️ {o}: {m}")
    if sin_explicar or sin_par:
        lista = os.path.join(LOGS, f"nd-sin-explicar-{STAMP}.txt")
        open(lista, "w", encoding="utf-8").write("".join(f"{p}\n" for p in sin_explicar) +
                                                  "".join(f"{o}\t{m}\n" for o, m in sorted(sin_par.items())))
        for p in sin_explicar[:15]:
            print(f"   ❓ {p}")
        if PURGAR_HUERFANAS:
            print(f"   --purgar-huerfanas: se purgan también estas {len(sin_explicar) + len(sin_par)} (lista en {lista})")
        else:
            bien, problema = False, (f"{len(sin_explicar)} canción(es) faltantes que ningún log explica y {len(sin_par)} sin ruta nueva: "
                                     f"NO se purgó nada. Lista: {lista}. Si de verdad se borraron, nd_actualizar.py --purgar-huerfanas.")
    if bien:
        a_purgar = [p for p in faltantes if p not in esperando and (p in explicadas or PURGAR_HUERFANAS)]
        if a_purgar:
            with con:
                con.executemany("delete from media_file where missing=1 and path=?", [(p,) for p in a_purgar])
        print(f"   purgadas: {len(a_purgar)} | se quedan faltantes (esperan re-descarga): {sum(1 for p in faltantes if p in esperando)}")
    con.close()
except Exception as e:
    bien, problema = False, f"error al escribir en la base de Navidrome: {e!r} (copia en respaldos/navidrome/)"
finally:
    run("arrancar Navidrome", compose + ["up", "-d"], check=False)
run("escaneo final", ["docker", "exec", "navidrome", "/app/navidrome", "scan", "--full"], a_log=True, check=False)
if not bien:
    print(f"\n(los {len(pendientes)} logs pendientes se quedan en nd-pendientes/ para la próxima corrida)")
    fallo(problema)
os.makedirs(ND_APLICADOS, exist_ok=True)
for lg in pendientes:
    shutil.move(lg, os.path.join(ND_APLICADOS, os.path.basename(lg)))
print(f"\nNavidrome al día. Logs aplicados: {len(pendientes)} → logs/nd-aplicados/")
