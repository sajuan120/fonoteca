#!/usr/bin/env python3
"""Pone a Navidrome al día después de mover/renombrar/borrar canciones (paso 8 de procesar_descarga.py).

Uso: nd_actualizar.py [<log.json> ...] [--usuario <Nombre>]
  <log.json>: logs con {"cambios": [{"old_path", "new_path"}]} (tracknums-log, duplicados-...): las reproducciones,
              estrellas, historial y entradas de playlist de la ruta vieja pasan a la nueva (migrar(), abajo;
              30 sep: antes era otro script, nd_migrar_ids.py, que solo llamaba este).
              Se unen EN ORDEN en uno solo (A→B y luego B→C queda A→C): migrarlos por separado perdía las
              escuchas de A, porque B ya no existe cuando Navidrome escanea.
  --usuario:  la playlist _Playlists/<Nombre>.m3u queda a nombre de ese usuario y privada.
Orden: escaneo completo → detener Navidrome → migrar IDs → dueño de la playlist → borrar "faltantes" → arrancar → escaneo.
Canciones borradas por borrar_canciones.py (corruptas/equivocadas): mientras esperan re-descarga, su "faltante" NO se
borra (guarda reproducciones y estrellas; al volver a la misma ruta Navidrome la recupera sola); si vuelven con otra
ruta, sus reproducciones pasan a la nueva (se agregan a la migración). Antes se perdían en el primer procesado.
"""
import datetime, json, os, sqlite3, subprocess, sys
from comun import HERE, LOGS, PRUEBA, ROOT, RESPALDOS, NAVIDROME_DB, borradas, rutas_por_sid, NAVIDROME

ND = NAVIDROME   # config.toml: rutas.navidrome
args = sys.argv[1:]
if any(a in ("-h", "--help") for a in args):
    sys.exit(__doc__)
if PRUEBA:   # banco de pruebas o una prueba aislada (MUSIC_ROOT): el Navidrome de verdad no se toca nunca
    sys.exit("(modo prueba: Navidrome no se toca)")
user = args[args.index("--usuario") + 1] if "--usuario" in args else None
logs = [a for a in args if a.endswith(".json") and os.path.exists(a)]

def migrar(lg):
    """Con Navidrome DETENIDO y después de un escaneo: pasa reproducciones, estrellas, ratings, historial (tabla scrobbles)
    y entradas de playlist de cada canción vieja (missing) a la nueva, según los pares old_path → new_path del log.
    Copia de la db en respaldos/navidrome/ antes de escribir."""
    import shutil
    raiz = ROOT + "/"
    pares = [(c["old_path"].removeprefix(raiz), c["new_path"].removeprefix(raiz))
             for c in json.load(open(lg, encoding="utf-8"))["cambios"] if c["old_path"] != c["new_path"]]
    con = sqlite3.connect(NAVIDROME_DB)
    ids = {}
    for mid, path, missing in con.execute("select id, path, missing from media_file"):
        ids.setdefault(path, []).append((mid, missing))
    mp = {}
    for old, new in pares:
        o = [m for m, miss in ids.get(old, []) if miss]; nw = [m for m, miss in ids.get(new, []) if not miss]
        if o and nw and o[0] != nw[0]: mp[o[0]] = nw[0]
    q = ",".join("?" * len(mp))
    ann = con.execute(f"select count(*) from annotation where item_type='media_file' and item_id in ({q})", list(mp)).fetchone()[0] if mp else 0
    pl = con.execute(f"select count(*) from playlist_tracks where media_file_id in ({q})", list(mp)).fetchone()[0] if mp else 0
    print(f"   pares viejo→nuevo: {len(mp)} de {len(pares)} | anotaciones a mover: {ann} | entradas de playlist: {pl}")
    os.makedirs(os.path.join(RESPALDOS, "navidrome"), exist_ok=True)
    shutil.copy2(NAVIDROME_DB, os.path.join(RESPALDOS, "navidrome", f"navidrome.db.antes-migrar-{datetime.datetime.now():%Y%m%d-%H%M%S}"))
    with con:
        for o, nw in mp.items():
            # si la nueva ya tiene anotación del mismo usuario, se suman reproducciones y se conserva la estrella
            for uid, pc, pd, st, sa, rt in con.execute("select user_id, play_count, play_date, starred, starred_at, rating from annotation "
                                                        "where item_type='media_file' and item_id=?", (o,)).fetchall():
                ex = con.execute("select play_count from annotation where item_type='media_file' and item_id=? and user_id=?", (nw, uid)).fetchone()
                if ex:
                    con.execute("update annotation set play_count=play_count+?, starred=max(starred,?), rating=max(rating,?), "
                                "play_date=max(coalesce(play_date,''),coalesce(?,'')) where item_type='media_file' and item_id=? and user_id=?",
                                (pc, st, rt, pd, nw, uid))
                    con.execute("delete from annotation where item_type='media_file' and item_id=? and user_id=?", (o, uid))
                else:
                    con.execute("update annotation set item_id=? where item_type='media_file' and item_id=? and user_id=?", (nw, o, uid))
            con.execute("update playlist_tracks set media_file_id=? where media_file_id=?", (nw, o))
            # historial con fecha (tabla scrobbles): antes quedaba huérfano al borrar la fila vieja (la cascada de la tabla
            # no se aplica sin PRAGMA foreign_keys) — 28 sep: 72 huérfanos reparados
            con.execute("update scrobbles set media_file_id=? where media_file_id=?", (nw, o))
            con.execute("delete from media_file where id=?", (o,))
    con.close()
    print("   migrado.")

def unir_logs(logs):
    """Un solo log con las rutas finales: si un archivo pasó A→B y después B→C, queda A→C (y B→C)."""
    m = {}
    for lg in logs:
        for c in json.load(open(lg, encoding="utf-8"))["cambios"]:
            o, n = c["old_path"], c["new_path"]
            for k in [k for k, v in m.items() if v == o]:
                m[k] = n
            m.setdefault(o, n)
    out = os.path.join(LOGS, f"nd-cambios-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
    json.dump({"cambios": [{"old_path": o, "new_path": n} for o, n in m.items()], "de": logs},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out

# borradas: las que esperan re-descarga se quedan como "faltantes"; las que volvieron con otra ruta se migran
_bs = borradas()
_hoy = rutas_por_sid({b["sid"] for b in _bs})
esperando = sorted({os.path.relpath(b["old"], ROOT) for b in _bs if b["sid"] not in _hoy})
_rebajadas = [{"old_path": b["old"], "new_path": _hoy[b["sid"]]} for b in _bs
              if b["sid"] in _hoy and _hoy[b["sid"]] != b["old"]]
if _rebajadas:
    _lr = os.path.join(LOGS, f"nd-rebajadas-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
    json.dump({"cambios": _rebajadas}, open(_lr, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    logs.insert(0, _lr)   # primero: los renombres de esta corrida van después (unir_logs encadena A→B→C)

def borrar_faltantes():
    con = sqlite3.connect(os.path.join(ND, "data/navidrome.db"))
    with con:
        con.execute("delete from media_file where missing=1" +
                    (f" and path not in ({','.join('?' * len(esperando))})" if esperando else ""), esperando)
    quedan = con.execute("select count(*) from media_file where missing=1").fetchone()[0]
    con.close()
    if quedan:
        print(f"   {quedan} faltantes se quedan: borradas que esperan re-descarga (conservan reproducciones y estrellas)")

ESCANEO = os.path.join(LOGS, f"nd-escaneo-{datetime.datetime.now():%Y%m%d-%H%M%S}.log")

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
        sys.exit(f"Falló: {title}")

def sql(q):
    return subprocess.run(["sqlite3", os.path.join(ND, "data/navidrome.db"), q], capture_output=True, text=True, check=True).stdout

compose = ["docker", "compose", "-f", os.path.join(ND, "docker-compose.yml")]
run("escaneo completo", ["docker", "exec", "navidrome", "/app/navidrome", "scan", "--full"], a_log=True)
run("detener Navidrome", compose + ["stop"])
try:
    if logs:
        lg = unir_logs(logs)
        print(f"\n--- migrar reproducciones/playlists ({len(logs)} logs unidos → {os.path.basename(lg)})", flush=True)
        migrar(lg)
    if user:
        sql(f"update playlist set owner_id=(select id from user where user_name='{user}'), public=0 "
            f"where path='/music/_Playlists/{user}.m3u';")
        print(sql(f"select name, song_count from playlist where path='/music/_Playlists/{user}.m3u';"))
    borrar_faltantes()
finally:
    run("arrancar Navidrome", compose + ["up", "-d"])
run("escaneo final", ["docker", "exec", "navidrome", "/app/navidrome", "scan", "--full"], a_log=True)
print("\nNavidrome al día.")
