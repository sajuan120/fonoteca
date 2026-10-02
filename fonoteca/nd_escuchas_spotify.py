#!/usr/bin/env python3
"""Carga las escuchas del historial de Spotify en las reproducciones de un usuario de Navidrome (26 sep 2026).

Uso: nd_escuchas_spotify.py <zip del historial> <usuario> [--execute]
  Empareja con comun.historial_en_biblioteca (misma regla que playlist_historial.py). Por cada canción:
  play_count += escuchas de Spotify (>=30 s) y play_date = la más reciente de las dos. Igual que un scrobble de
  Navidrome, suma también al álbum y a cada artista que participa (artista + artista del álbum).
  Sin --execute solo simula. Con --execute: detiene Navidrome, respalda la db en respaldos/navidrome/, escribe,
  guarda log (logs/) y vuelve a arrancar. Para deshacer: parar Navidrome y restaurar el respaldo que indica el log.
  Se puede volver a correr (p. ej. después de bajar canciones nuevas): cada log guarda qué canciones había en la
  biblioteca (rutas y spotify_id) y la siguiente vez solo se cargan las que llegaron después; una canción vieja que
  cambió de ruta (renumerada, duplicado) se reconoce por su spotify_id y no suma dos veces.
"""
import collections, datetime, glob, json, os, shutil, sqlite3, subprocess, sys

from comun import DATOS, historial_en_biblioteca, indice_biblioteca, log_path, NAVIDROME, cerrojo

zpath, user = sys.argv[1], sys.argv[2]
EXECUTE = "--execute" in sys.argv
ND = NAVIDROME   # config.toml: rutas.navidrome
DB = os.path.join(ND, "data/navidrome.db")
MARCA = f"nd-escuchas-spotify-{user}"

ya, ya_sid = set(), set()   # canciones que había en la biblioteca en cargas anteriores: ya tienen sus escuchas
for l in sorted(glob.glob(os.path.join(DATOS, "logs", f"{MARCA}-*.json"))):
    previo = json.load(open(l))
    if "biblioteca" not in previo or "sids" not in previo:
        sys.exit(f"{l} no dice qué canciones había: no puedo saber cuáles ya se cargaron (sumaría doble).")
    ya |= set(previo["biblioteca"]); ya_sid |= set(previo["sids"])

ind = indice_biblioteca()
sid_de = {r: s for s, r in ind["sid"].items()}
found = historial_en_biblioteca(zpath, ind)
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
uid = con.execute("select id from user where user_name=?", (user,)).fetchone()
if not uid: sys.exit(f"No existe el usuario {user}")
uid = uid[0]
mf = {p: (i, al, json.loads(pa or "{}")) for i, p, al, pa in
      con.execute("select id, path, album_id, participants from media_file where missing=0")}

def fecha(ts):   # '2025-08-20T12:00:00Z' → formato de Navidrome
    return ts.replace("T", " ").replace("Z", "") + ".000000000+00:00"

delta = collections.defaultdict(lambda: [0, ""])   # (tipo, id) → [escuchas, última fecha]
sin_nd = cargadas = 0
for rel, d in found.items():
    if not d["plays"]: continue
    if rel in ya or sid_de.get(rel) in ya_sid:
        cargadas += 1; continue
    if rel not in mf:
        sin_nd += 1; continue
    i, al, pa = mf[rel]
    artistas = {a["id"] for rol in ("artist", "albumartist") for a in pa.get(rol, [])}
    for key in [("media_file", i), ("album", al)] + [("artist", a) for a in artistas]:
        delta[key][0] += d["plays"]; delta[key][1] = max(delta[key][1], fecha(d["last"]))

por_tipo = collections.Counter(t for t, _ in delta)
print(f"canciones con escuchas: {por_tipo['media_file']} | álbumes: {por_tipo['album']} | artistas: {por_tipo['artist']}")
print(f"escuchas a cargar: {sum(v[0] for (t, _), v in delta.items() if t == 'media_file')} | en la biblioteca pero no en Navidrome: {sin_nd}"
      + (f" | ya cargadas antes: {cargadas} canciones" if ya else ""))
antes = con.execute("select sum(play_count) from annotation where user_id=? and item_type='media_file'", (uid,)).fetchone()[0]
print(f"reproducciones de {user} hoy en Navidrome: {antes or 0}")
top = sorted(((v[0], k[1]) for k, v in delta.items() if k[0] == "media_file"), reverse=True)[:5]
nombre = {i: p for p, (i, _, _) in mf.items()}
for n, i in top: print(f"  {n:4d}  {nombre[i]}")
con.close()
if not EXECUTE:
    print("\n(simulación: agrega --execute)"); sys.exit()
if not delta:
    print("nada nuevo que cargar"); sys.exit()
cerrojo("nd_escuchas_spotify.py")

compose = ["docker", "compose", "-f", os.path.join(ND, "docker-compose.yml")]
subprocess.run(compose + ["stop"], check=True)
try:
    rdir = os.path.join(DATOS, "respaldos", "navidrome"); os.makedirs(rdir, exist_ok=True)
    resp = os.path.join(rdir, f"navidrome.db.antes-escuchas-spotify-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(DB, resp)
    con = sqlite3.connect(DB)
    with con:
        for (t, i), (n, last) in delta.items():
            con.execute("insert into annotation (user_id, item_id, item_type, play_count, play_date) values (?,?,?,?,?) "
                        "on conflict (user_id, item_id, item_type) do update set play_count = play_count + excluded.play_count, "
                        "play_date = max(coalesce(play_date, ''), excluded.play_date)", (uid, i, t, n, last))
    despues = con.execute("select sum(play_count) from annotation where user_id=? and item_type='media_file'", (uid,)).fetchone()[0]
    con.close()
    log = log_path(MARCA)
    json.dump({"usuario": user, "zip": zpath, "respaldo_db": resp, "por_tipo": por_tipo,
               "reproducciones_antes": antes, "reproducciones_despues": despues,
               "biblioteca": sorted(mf), "sids": sorted(sid_de[r] for r in mf if r in sid_de)},
              open(log, "w"), indent=1, ensure_ascii=False)
    print(f"hecho: {antes or 0} → {despues} reproducciones | respaldo: {resp} | log: {log}")
finally:
    subprocess.run(compose + ["up", "-d"], check=True)
