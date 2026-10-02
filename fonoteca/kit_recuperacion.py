#!/usr/bin/env python3
"""KIT DE RECUPERACIÓN de la biblioteca: todo lo necesario para rehacerla SIN el audio (que se vuelve a bajar con Antra).
Pensado para subirlo a la nube: NO lleva contraseñas, cookies ni tokens (se tachan o se excluyen).

Uso: kit_recuperacion.py [<carpeta destino>]      (por defecto rutas.kit de config.toml)
Se regenera completo cada vez (procesar_descarga.py lo actualiza al final). Contenido:
  canciones-spotify.txt      un enlace por canción de la biblioteca → pegar en UNA playlist de Spotify → Antra la baja entera
  canciones.tsv              spotify_id, artista, álbum, título, géneros, ruta (para leerlo)
  etiquetas.json.gz          TODAS las etiquetas de texto de cada canción (por spotify_id) → «tags_backup.py desde-kit» las devuelve
  playlists/                 cada playlist de _Playlists como enlaces de Spotify (y el .m3u original)
  navidrome/                 escuchas, estrellas y playlists por usuario (sin contraseñas) + docker-compose.yml
  antra/                     configuración de Antra con las claves tachadas
  music-tools.zip            scripts, listas, notas, historiales de Spotify (usuarios/) y caché de consultas
  sistema/                   avisos y chequeo semanal (rutas.scripts + unidades systemd), sin credenciales
  COMO-RECUPERAR.md          los pasos
"""
import csv, datetime, glob, gzip, json, os, re, shutil, sqlite3, sys, zipfile
from audio import abrir, es_audio
from comun import ROOT, HERE, es_de_album, KIT, NAVIDROME, ANTRA, SCRIPTS

DEST = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else KIT   # config.toml: rutas.kit
SECRETO = re.compile(r"(token|secret|pass|cookie|auth|key|sp_dc|sid|session|bearer)", re.I)
# 2 oct: al final se BORRA el kit anterior: solo si de verdad es un kit (una carpeta equivocada se perdía entera)
if os.path.exists(DEST) and not os.path.isfile(os.path.join(DEST, "COMO-RECUPERAR.md")):
    sys.exit(f"{DEST} existe y no es un kit de recuperación (no tiene COMO-RECUPERAR.md): no la toco. Revisa rutas.kit.")
tmp = DEST + ".nuevo"
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(os.path.join(tmp, "playlists")); os.makedirs(os.path.join(tmp, "navidrome"))
os.makedirs(os.path.join(tmp, "antra")); os.makedirs(os.path.join(tmp, "sistema"))

# ---------- canciones y etiquetas ----------
filas, etiquetas, por_ruta, seen = [], {}, {}, set()
for d, _, fs in os.walk(ROOT):
    for f in sorted(fs):
        p = os.path.join(d, f)
        if not es_audio(f) or not es_de_album(p):
            continue
        ino = os.stat(p).st_ino
        try:
            t = abrir(p)
        except Exception:
            continue
        sid = (t.get("spotify_id") or [""])[0]
        por_ruta[os.path.relpath(p, ROOT)] = sid
        if ino in seen or not sid:
            continue
        seen.add(ino)
        g = lambda k: (t.get(k) or [""])[0]
        filas.append((sid, g("albumartist") or g("artist"), g("album"), g("discnumber"), g("tracknumber"), g("title"),
                      "; ".join(t.get("genre") or []), os.path.relpath(p, ROOT)))
        etiquetas[sid] = {"ruta": os.path.relpath(p, ROOT), "tags": [[k, v] for k, v in (t.tags or [])]}
filas.sort(key=lambda r: (r[1].lower(), r[2].lower(), r[3].zfill(3), r[4].zfill(3)))
open(os.path.join(tmp, "canciones-spotify.txt"), "w").write("".join(f"https://open.spotify.com/track/{r[0]}\n" for r in filas))
with open(os.path.join(tmp, "canciones.tsv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh, delimiter="\t")
    w.writerow(["spotify_id", "artista", "álbum", "disco", "pista", "título", "géneros", "ruta"])
    w.writerows(filas)
with gzip.open(os.path.join(tmp, "etiquetas.json.gz"), "wt", encoding="utf-8") as fh:
    json.dump(etiquetas, fh, ensure_ascii=False)

# ---------- playlists ----------
for m in sorted(glob.glob(os.path.join(ROOT, "_Playlists", "*.m3u"))):
    shutil.copy2(m, os.path.join(tmp, "playlists", os.path.basename(m)))
    enlaces = []
    for l in open(m, encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#"):
            sid = por_ruta.get(os.path.relpath(os.path.normpath(os.path.join(ROOT, "_Playlists", l)), ROOT))
            if sid:
                enlaces.append(f"https://open.spotify.com/track/{sid}\n")
    open(os.path.join(tmp, "playlists", os.path.basename(m)[:-4] + " - spotify.txt"), "w").writelines(enlaces)

# ---------- Navidrome: escuchas, estrellas y playlists (sin la base: guarda contraseñas) ----------
ND = NAVIDROME
try:
    con = sqlite3.connect(f"file:{os.path.join(ND, 'data/navidrome.db')}?mode=ro", uri=True)
    mf = {i: p for i, p in con.execute("select id, path from media_file")}
    usuarios = {i: n for i, n in con.execute("select id, user_name from user")}
    esc = [{"usuario": usuarios.get(u, u), "spotify_id": por_ruta.get(mf.get(i, "")), "ruta": mf.get(i),
            "reproducciones": pc, "ultima": pd, "estrella": bool(st), "puntaje": rt}
           for u, i, pc, pd, st, rt in con.execute(
               "select user_id, item_id, play_count, play_date, starred, rating from annotation where item_type='media_file'")]
    pls = []
    for pid, name, owner, path in con.execute("select id, name, owner_id, path from playlist"):
        canc = [por_ruta.get(mf.get(x, "")) for (x,) in con.execute(
            "select media_file_id from playlist_tracks where playlist_id=? order by id", (pid,))]
        pls.append({"nombre": name, "dueño": usuarios.get(owner, owner), "archivo": path, "spotify_ids": canc})
    json.dump({"escuchas_y_estrellas": esc, "playlists": pls, "usuarios": sorted(usuarios.values())},
              open(os.path.join(tmp, "navidrome", "navidrome-datos.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
except Exception as e:
    print("⚠️ Navidrome: no pude exportar escuchas/playlists:", e)
dc = open(os.path.join(ND, "docker-compose.yml"), encoding="utf-8").read()
dc = "\n".join(re.sub(r"(:\s*|=)\S.*$", r"\1***", l) if SECRETO.search(l.split(":")[0].split("=")[0]) else l for l in dc.splitlines())
open(os.path.join(tmp, "navidrome", "docker-compose.yml"), "w").write(dc + "\n")

# ---------- Antra (claves tachadas) ----------
def tachar(x):
    if isinstance(x, dict):
        return {k: ("***" if SECRETO.search(k) and v not in (None, "", False, True) else tachar(v)) for k, v in x.items()}
    return x
try:
    cfg = json.load(open(os.path.join(ANTRA, "config.json")))
    json.dump(tachar(cfg), open(os.path.join(tmp, "antra", "config-sin-claves.json"), "w"), ensure_ascii=False, indent=1)
except Exception as e:
    print("⚠️ Antra: no pude copiar la configuración:", e)

# ---------- music-tools (sin credenciales ni respaldos pesados) ----------
FUERA = {"respaldos", "logs", "__pycache__", "planes"}
NUNCA = {".acoustid_key", ".qobuz_token"}   # claves: nunca al kit
with zipfile.ZipFile(os.path.join(tmp, "music-tools.zip"), "w", zipfile.ZIP_DEFLATED) as z:
    for d, dirs, fs in os.walk(HERE):
        dirs[:] = [x for x in dirs if x not in FUERA]
        for f in fs:
            if f in NUNCA or f.endswith(".pyc"):
                continue
            p = os.path.join(d, f)
            z.write(p, os.path.relpath(p, os.path.dirname(HERE)))

# ---------- sistema: avisos y chequeo semanal (sin el .env de Spotify) ----------
for p in glob.glob(os.path.join(SCRIPTS, "*")):
    n = os.path.basename(p)
    if n.endswith(".env") or not (n.startswith("musica-") or n.startswith("antra-")):
        continue
    shutil.copy2(p, os.path.join(tmp, "sistema", n))
for p in glob.glob(os.path.expanduser("~/.config/systemd/user/*")):
    n = os.path.basename(p)
    if os.path.isfile(p) and (n.startswith("musica-") or n.startswith("antra-")):
        shutil.copy2(p, os.path.join(tmp, "sistema", n))

# ---------- instrucciones ----------
hoy = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
open(os.path.join(tmp, "COMO-RECUPERAR.md"), "w", encoding="utf-8").write(f"""# Cómo recuperar la biblioteca de música

Kit generado: {hoy} · {len(filas)} canciones · generado por `~/music-tools/kit_recuperacion.py`.
El audio NO está aquí (ocupa ~200 GB): se vuelve a bajar con Antra usando los enlaces. Todo lo demás, sí.
Este kit NO trae contraseñas ni tokens: hay que volver a poner la clave de AcoustID
(.acoustid_key) y la sesión de Antra a mano.

## 1. Programas
Antra (AppImage de github.com/anandprtp/Antra), Navidrome con Docker (`navidrome/docker-compose.yml`), python3 +
mutagen, flac, ffmpeg y fpcalc (chromaprint).

## 2. Scripts
Descomprimir `music-tools.zip` en `~` (queda `~/music-tools/`). Todo está explicado en `~/music-tools/LEEME.md`.
Los avisos y el chequeo semanal están en `sistema/` (van en {SCRIPTS} y `~/.config/systemd/user/`).

## 3. Bajar la música
1. Spotify de escritorio → playlist nueva → pegar TODO `canciones-spotify.txt` (acepta miles de enlaces de un golpe).
2. Antra (con strict_matching activado, ver `antra/config-sin-claves.json`) → bajar esa playlist.
3. `python3 ~/music-tools/procesar_descarga.py "<carpeta que creó Antra>"` (simulación) y luego con `--execute`:
   la reparte en Artista/Año - Álbum y le pone géneros, fechas, IDs, letras y volumen parejo.
4. `python3 ~/music-tools/tags_backup.py desde-kit etiquetas.json.gz --execute`: devuelve a cada canción EXACTAMENTE
   las etiquetas que tenía (se identifica por su spotify_id).
Las que Antra no consiga quedan anotadas en la lista de pendientes (`revisar.py`).

## 4. Playlists y Navidrome
- `playlists/*.m3u` van a `{ROOT}/_Playlists/` (si las rutas no calzan, `playlists/* - spotify.txt` tiene las
  mismas canciones como enlaces).
- `navidrome/navidrome-datos.json`: usuarios, escuchas, estrellas y playlists de cada uno (para reconstruirlos).
""")

# ---------- reemplazar el kit anterior de una vez ----------
if os.path.exists(DEST):
    shutil.rmtree(DEST)
os.rename(tmp, DEST)
tam = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(DEST) for f in fs)
print(f"Kit listo: {DEST}  ({len(filas)} canciones, {tam / 1e6:.0f} MB)")
