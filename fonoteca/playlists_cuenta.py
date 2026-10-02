#!/usr/bin/env python3
"""Pasa a Navidrome las playlists propias de alguien, desde sus "Datos de la cuenta" de Spotify (26 sep 2026).

Uso: playlists_cuenta.py <zip de datos de la cuenta o PlaylistN.json> <usuario> [--solo "Nombre 1,Nombre 2"] [--execute]
  Cada playlist va al .m3u de _Playlists/ que ya tenga ese título y sea de <usuario> en Navidrome (se actualiza en su
  sitio); si no hay, a _Playlists/<usuario> - <nombre>.m3u con #PLAYLIST:<nombre> (Navidrome muestra ese nombre).
  Mismo orden que en Spotify, sin repetidas; solo lo que está en la biblioteca (comun.buscar: equivalencias.tsv,
  spotify_id, artista+título). Lo que falta se lista y entra solo si se vuelve a correr después de bajarlo.
  Las playlists vacías se saltan.
  Sin --execute solo muestra qué cambiaría. Con --execute: respalda los .m3u que cambian (respaldos/), los escribe,
  escanea Navidrome, lo detiene, deja a nombre de <usuario> y privadas esas playlists y todas las
  _Playlists/<usuario> - *.m3u, y lo arranca; si nada cambia no toca Navidrome.
  OJO: usa la exportación de ese día; si la persona cambia sus playlists, pedir datos nuevos y volver a correrla.
"""
import datetime, glob, json, os, re, shutil, sqlite3, subprocess, sys, zipfile

from comun import ROOT, DATOS, indice_biblioteca, buscar, log_path, NAVIDROME, cerrojo

src, user = sys.argv[1], sys.argv[2]
SOLO = [x.strip() for x in sys.argv[sys.argv.index("--solo") + 1].split(",")] if "--solo" in sys.argv else None
EXECUTE = "--execute" in sys.argv
ND = NAVIDROME   # config.toml: rutas.navidrome
DB = os.path.join(ND, "data/navidrome.db")
PL = os.path.join(ROOT, "_Playlists")

playlists = []
if src.endswith(".zip"):
    with zipfile.ZipFile(src) as z:
        for n in sorted(z.namelist()):
            if re.search(r"Playlist\d+\.json$", n): playlists += json.load(z.open(n))["playlists"]
else:
    playlists = json.load(open(src))["playlists"]
if SOLO:
    faltan = [s for s in SOLO if s not in {p["name"] for p in playlists}]
    if faltan: sys.exit(f"No están en los datos: {faltan}")
    playlists = [p for p in playlists if p["name"] in SOLO]

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
uid = (con.execute("select id from user where user_name=?", (user,)).fetchone() or [None])[0]
if not uid: sys.exit(f"No existe el usuario {user} en Navidrome")
duenos = dict(con.execute("select path, owner_id from playlist where path != ''"))
con.close()

def titulo(f):
    for l in open(f, encoding="utf-8"):
        if l.startswith("#PLAYLIST:"): return l[10:].strip()
    return os.path.basename(f)[:-4]
suyos = {titulo(f): f for f in sorted(glob.glob(os.path.join(PL, "*.m3u")))
         if duenos.get("/music/_Playlists/" + os.path.basename(f)) == uid}

ind = indice_biblioteca()
cambios = []
for p in playlists:
    tracks = [i["track"] for i in p["items"] if i.get("track")]
    if not tracks: continue
    rutas, faltan = [], []
    for t in tracks:
        r = buscar(ind, t["trackUri"].split(":")[-1], t["artistName"], t["trackName"])
        if not r: faltan.append(f"{t['artistName']} — {t['trackName']}")
        elif r not in rutas: rutas.append(r)
    f = suyos.get(p["name"]) or os.path.join(PL, f"{user} - {p['name'].replace('/', '_')}.m3u")
    antes = [l.strip()[3:] for l in open(f, encoding="utf-8") if l.strip() and not l.startswith("#")] if os.path.exists(f) else None
    print(f"== {p['name']} → {os.path.basename(f)} ({'existe' if antes is not None else 'NUEVA'})")
    print(f"   Spotify {len(tracks)} | en la biblioteca {len(rutas)} | en el .m3u hoy {len(antes) if antes is not None else '-'}")
    for r in rutas:
        if antes is not None and r not in antes: print("   + ", r)
    for r in antes or []:
        if r not in rutas: print("   - ", r)
    if antes is not None and [r for r in antes if r in rutas] != [r for r in rutas if r in antes]:
        print("   (cambia el orden: queda el de Spotify)")
    for x in faltan: print("   no está:", x)
    if rutas != antes: cambios.append((f, p["name"], rutas))
print(f"\n{len(cambios)} .m3u por escribir")
if not EXECUTE:
    print("(simulación: agrega --execute)"); sys.exit()
ajenas = [f for f in glob.glob(os.path.join(PL, f"{user} - *.m3u"))       # suyas por nombre pero aún no a su nombre
          if duenos.get("/music/_Playlists/" + os.path.basename(f)) != uid]
if not cambios and not ajenas:
    print("nada que cambiar"); sys.exit()
cerrojo("playlists_cuenta.py")

ts = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"
rdir = os.path.join(DATOS, "respaldos", f"playlists-cuenta-{ts}")
for f, name, rutas in cambios:
    if os.path.exists(f):
        os.makedirs(rdir, exist_ok=True); shutil.copy2(f, rdir)
    with open(f, "w", encoding="utf-8") as o:
        o.write(f"#EXTM3U\n#PLAYLIST:{name}\n" + "".join(f"../{r}\n" for r in rutas))
    print("escrito:", os.path.basename(f))
esc = log_path("nd-escaneo", "log")
with open(esc, "w") as o:
    subprocess.run(["docker", "exec", "navidrome", "/app/navidrome", "scan"], stdout=o, stderr=subprocess.STDOUT, check=True)
compose = ["docker", "compose", "-f", os.path.join(ND, "docker-compose.yml")]
subprocess.run(compose + ["stop"], check=True)
try:
    paths = {"/music/_Playlists/" + os.path.basename(f) for f, _, _ in cambios}
    paths |= {"/music/_Playlists/" + os.path.basename(f) for f in glob.glob(os.path.join(PL, f"{user} - *.m3u"))}
    con = sqlite3.connect(DB)
    with con:
        for pth in sorted(paths):
            con.execute("update playlist set owner_id=?, public=0 where path=?", (uid, pth))
    filas = con.execute(f"select name, song_count, path from playlist where path in ({','.join('?' * len(paths))})", sorted(paths)).fetchall()
    con.close()
finally:
    subprocess.run(compose + ["up", "-d"], check=True)
print("\nEn Navidrome (a nombre de", user + "):")
for name, n, pth in filas:
    lineas = sum(1 for l in open(os.path.join(PL, os.path.basename(pth)), encoding="utf-8") if l.strip() and not l.startswith("#"))
    print(f"   {name}: {n} canciones" + ("" if n == lineas else f"  ⚠️ el .m3u tiene {lineas}"))
print("escaneo:", esc, "| respaldo:", rdir if os.path.isdir(rdir) else "(no había .m3u previos)")
