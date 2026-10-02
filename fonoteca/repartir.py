#!/usr/bin/env python3
"""Paso 5 del procesado: REPARTIR una carpeta de Antra en Artista/Año - Álbum/NN - Título.flac y quitar la carpeta.

Uso: repartir.py "<carpeta>" [--execute] [--log <ruta>]     sin --execute solo muestra (plan en planes/plan-reparto.json/.txt)

Reglas (formato de Antra):
  - Artista = primer ALBUMARTIST (reusa la carpeta de artista existente si coincide sin mayúsculas).
  - Carpeta de álbum = "Año - Álbum" (sin año: "Álbum"); reusa la carpeta existente del álbum.
  - Archivo = "NN - Título.flac" (otro formato: su extensión) con el número de pista del ÁLBUM ("D-NN" si el álbum tiene varios discos).
  - Caracteres / \\ : * ? " < > |  ->  "_".  Carpetas viejas "Álbum (Año)" se renombran a "Año - Álbum".
  - Cada audio (inodo) recibe su nombre de álbum como hardlink; después se quita su nombre en la carpeta de Antra.
  - Colisión (ya existe otro archivo con ese nombre): esa canción NO se mueve y queda en la carpeta (se avisa).
Con --execute, en orden: renombrar carpetas → hardlinks (nunca sobrescribe) → quitar los nombres de la carpeta de
Antra (solo si el destino existe con el mismo inodo) → borrar la carpeta vacía y su .m3u → reescribir
.antra_state.json (respaldo en respaldos/) y las demás listas con rutas (playlists, equivalencias: comun.cambiar_rutas).
Log de todo en logs/reorg-<fecha>.json.
"""
import collections
import json
import os
import re

from audio import abrir, es_audio

from comun import ROOT, antra_abierto, RESPALDOS, SKIP
import sys, shutil, time
ARGS = sys.argv[1:]
EXECUTE = "--execute" in ARGS
LOG = ARGS[ARGS.index("--log") + 1] if "--log" in ARGS else __import__("comun").log_path("reorg")
DISSOLVE = {os.path.normpath(a) for i, a in enumerate(ARGS) if not a.startswith("--") and (i == 0 or ARGS[i - 1] != "--log")}
if any(os.path.isabs(d) or os.sep in d or d.startswith("..") for d in DISSOLVE):   # 2 oct: «Carpeta/» o rutas raras
    sys.exit(f"Las carpetas a repartir van sin «/» (una descarga de la raíz): {sorted(DISSOLVE)}")
PLAYLISTS = sorted(DISSOLVE)   # carpetas-playlist de Antra (se disuelven al final)
OUT = __import__("comun").plan_path("plan-reparto")
BAD = str.maketrans({c: "_" for c in '/\\:*?"<>|'})
OLD_STYLE = re.compile(r"^(.+) \((\d{4})\)$")


def vals(tags, key):
    return [v for k, v in tags if k.lower() == key and v.strip()] if tags else []


def clean_file(s):
    return s.translate(BAD).strip() or "_"


def clean_dir(s):
    return s.translate(BAD).strip().rstrip(". ") or "_"


def year_of(tags):
    for key in ("date", "year"):
        for v in vals(tags, key):
            m = re.match(r"\d{4}", v.strip())
            if m:
                return m.group(0)
    return None


def num(v):
    m = re.match(r"\d+", v.strip()) if v else None
    return int(m.group(0)) if m else None


def top(rel):
    return rel.split(os.sep)[0]


# ---------- leer todo ----------
names = collections.defaultdict(list)     # ino -> [rel]
tags_of = {}                              # ino -> tags
for dirpath, dirnames, filenames in os.walk(ROOT):
    # _Prueba (MP3 de Octo-Fiesta) no es la biblioteca: si se leyera, un FLAC promovido podía ir a parar ahí
    dirnames[:] = [d for d in dirnames if not d.startswith(".Trash") and not (dirpath == ROOT and d in SKIP)]
    for name in sorted(filenames):
        if es_audio(name):
            path = os.path.join(dirpath, name)
            ino = os.stat(path).st_ino
            names[ino].append(os.path.relpath(path, ROOT))
            if ino not in tags_of:
                try:
                    tags_of[ino] = abrir(path).tags
                except Exception:   # archivo a medio escribir: se ignora (y no se toca)
                    names[ino].remove(os.path.relpath(path, ROOT))
                    if not names[ino]:
                        del names[ino]

# ---------- renombres de carpetas de álbum existentes ----------
dir_rename = {}   # "Artista/Álbum (Año)" -> "Artista/Año - Álbum"
for artist in sorted(os.listdir(ROOT)):
    ap = os.path.join(ROOT, artist)
    if artist in PLAYLISTS or artist in SKIP or artist.startswith(".") or not os.path.isdir(ap):
        continue
    for album in sorted(os.listdir(ap)):
        m = OLD_STYLE.match(album)
        if m and os.path.isdir(os.path.join(ap, album)):
            new = f"{m.group(2)} - {m.group(1)}"
            dir_rename[os.path.join(artist, album)] = os.path.join(artist, new)
for old, new in dir_rename.items():
    assert not os.path.exists(os.path.join(ROOT, new)), f"ya existe {new}"


def mapped(rel):
    parts = rel.split(os.sep)
    if len(parts) >= 3:
        d = os.path.join(parts[0], parts[1])
        if d in dir_rename:
            return os.path.join(dir_rename[d], *parts[2:])
    return rel


# ---------- carpetas existentes: artista y álbum ----------
def album_key(tags):
    aa = (vals(tags, "albumartist") or vals(tags, "artist") or ["Unknown Artist"])[0]
    al = (vals(tags, "album") or ["Unknown Album"])[0]
    return aa.lower(), al.lower()


artist_dir, album_dir = {}, {}
artist_cnt = collections.defaultdict(collections.Counter)   # artista del disco -> carpetas donde están sus canciones
album_ino = {}   # ino -> nombre en carpeta de álbum (ya con renombre aplicado)
for ino, rels in names.items():
    for rel in rels:
        if top(rel) in PLAYLISTS or len(rel.split(os.sep)) < 3:
            continue
        m = mapped(rel)
        p = m.split(os.sep)
        g = album_key(tags_of[ino])
        artist_cnt[g[0]][p[0]] += 1
        album_dir.setdefault(g, os.path.join(p[0], p[1]))
        album_ino.setdefault(ino, m)
# la carpeta del artista = donde está la MAYORÍA de sus canciones (empate → orden alfabético). Antes era la PRIMERA que
# aparecía: con Dawn FM mal guardado en Swedish House Mafia, lo nuevo de The Weeknd se iba ahí (27 sep; igual Bad Bunny
# → Yandel y Various Artists → Uyama Hiroto)
artist_dir = {k: min(c, key=lambda a: (-c[a], a)) for k, c in artist_cnt.items()}

# ---------- año y discos por álbum, nombre canónico de artista ----------
variants = collections.defaultdict(collections.Counter)
grp_years = collections.defaultdict(collections.Counter)
grp_maxdisc = collections.defaultdict(int)
for ino, tags in tags_of.items():
    g = album_key(tags)
    aa = (vals(tags, "albumartist") or vals(tags, "artist") or ["Unknown Artist"])[0]
    variants[g[0]][aa] += 1
    y = year_of(tags)
    if y:
        grp_years[g][y] += 1
    grp_maxdisc[g] = max(grp_maxdisc[g], num((vals(tags, "discnumber") or [""])[0]) or 1)
canon = {k: artist_dir.get(k) or c.most_common(1)[0][0] for k, c in variants.items()}


def group_year(g):
    c = grp_years.get(g)
    if not c:
        return None
    best = max(c.values())
    return min(y for y, n in c.items() if n == best)


# ---------- calcular operaciones ----------
links, drops, collisions, notes = [], [], [], collections.defaultdict(list)
claimed = {}
state_map = {}
for ino in sorted(names, key=lambda i: sorted(names[i])[0]):
    rels = sorted(names[ino])
    tags = tags_of[ino]
    if ino not in album_ino and not any(top(r) in DISSOLVE for r in rels):
        continue   # 2 oct: de OTRA descarga pendiente (o suelta): no entra sin pasar por su propio procesado
    if ino in album_ino:
        dst, new_name = album_ino[ino], False
    else:
        g = album_key(tags)
        aa_raw = (vals(tags, "albumartist") or vals(tags, "artist") or ["Unknown Artist"])[0]
        al_raw = (vals(tags, "album") or ["Unknown Album"])[0]
        title = (vals(tags, "title") or [os.path.splitext(os.path.basename(rels[0]))[0]])[0]
        trk = num((vals(tags, "tracknumber") or [""])[0])
        dsc = num((vals(tags, "discnumber") or [""])[0]) or 1
        if g in album_dir:
            adir = album_dir[g]
        else:
            y = group_year(g)
            adir = os.path.join(clean_dir(canon[g[0]]), clean_dir(f"{y} - {al_raw}" if y else al_raw))
        if trk is None:
            notes["sin número de pista"].append(rels[0])
        nn = f"{trk:02d}" if trk is not None else "00"
        prefix = f"{dsc}-{nn}" if grp_maxdisc[g] > 1 else nn
        stem = clean_file(f"{prefix} - {title}")
        ext = os.path.splitext(rels[0])[1].lower()   # 28 sep: cada formato conserva su extensión
        while len((stem + ext).encode()) > 250:
            stem = stem[:-1]
            notes["nombre recortado"].append(rels[0])
        dst, new_name = os.path.join(adir, stem.rstrip() + ext), True
    if new_name:
        if os.path.exists(os.path.join(ROOT, dst)) or dst in claimed:
            collisions.append({"src": rels[0], "dst": dst, "ino": ino,
                               "choca_con": claimed.get(dst, "archivo existente")})
            continue
        claimed[dst] = ino
        links.append({"op": "link", "src": rels[0], "dst": dst, "ino": ino,
                      "album_existente": os.path.dirname(dst) in album_dir.values()})
    for rel in rels:
        if top(rel) in DISSOLVE:
            drops.append({"op": "drop", "src": rel, "dst": dst, "ino": ino})
            state_map[os.path.join(ROOT, rel)] = os.path.join(ROOT, dst)
        elif mapped(rel) != rel:
            state_map[os.path.join(ROOT, rel)] = os.path.join(ROOT, mapped(rel))

# ---------- salida ----------
new_albums = sorted({os.path.dirname(o["dst"]) for o in links if not o["album_existente"]})
stats = {"audios_unicos": len(names), "link": len(links), "drop": len(drops),
         "renombrar_carpetas": len(dir_rename), "colisiones": len(collisions),
         "state_map": len(state_map), "albumes_nuevos": len(new_albums)}
json.dump({"root": ROOT, "dissolve": sorted(DISSOLVE), "dir_rename": dir_rename, "links": links, "drops": drops,
           "collisions": collisions, "state_map": state_map, "stats": stats},
          open(OUT + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open(OUT + ".txt", "w", encoding="utf-8") as f:
    for a, b in dir_rename.items():
        f.write(f"rename-dir {a}\n      -> {b}\n")
    for o in links:
        f.write(f"link      {o['src']}\n      -> {o['dst']}\n")
    for o in drops:
        f.write(f"drop      {o['src']}   (queda en {o['dst']})\n")
    if collisions:
        f.write("\n=== COLISIONES (no se tocan) ===\n")
        for c in collisions:
            f.write(f"{c['src']}\n      -> {c['dst']}  (choca con {c['choca_con']})\n")

print(stats)
for k, v in notes.items():
    print(f"{k}: {len(v)}", *v[:5], sep="\n   ")
for c in collisions[:20]:
    print("COLISIÓN", c["src"], "->", c["dst"], "| choca con:", c["choca_con"])
print("Renombres de carpeta:", *[f"{a} -> {b}" for a, b in dir_rename.items()], sep="\n   ")
print(f"Listado: {OUT}.txt")


# ==================== aplicar ====================
plan = json.load(open(OUT + ".json", encoding="utf-8"))
root = plan["root"]
STATE = os.path.join(root, ".antra_state.json")
DISSOLVE_DIRS = plan.get("dissolve", [])
P = lambda rel: os.path.join(root, rel)

# ---------- 0. chequeos ----------
if EXECUTE and antra_abierto():
    sys.exit("Antra está corriendo. Ciérralo y reintenta. No se hace nada.")

for a, b in plan["dir_rename"].items():
    if not os.path.isdir(P(a)) or os.path.exists(P(b)):
        sys.exit(f"Renombre imposible: {a} -> {b}")
for o in plan["links"]:
    if os.stat(P(o["src"])).st_ino != o["ino"]:
        sys.exit(f"El inode de {o['src']} cambió; regenera el plan.")
    if os.path.exists(P(o["dst"])):
        sys.exit(f"El destino ya existe: {o['dst']}; regenera el plan.")
for o in plan["drops"]:
    if not os.path.exists(P(o["src"])):
        sys.exit(f"Falta {o['src']}; regenera el plan.")
    if os.stat(P(o["src"])).st_ino != o["ino"]:
        sys.exit(f"El inode de {o['src']} cambió; regenera el plan.")

text = open(STATE, encoding="utf-8").read()
state = json.loads(text)
if json.dumps(state, indent=2, ensure_ascii=True) != text:
    sys.exit("El formato del state no se reproduce byte a byte; no lo toco. No se hace nada.")

print(f"{'EJECUTANDO' if EXECUTE else 'SIMULACIÓN (no se escribe nada)'}: "
      f"{len(plan['dir_rename'])} renombres, {len(plan['links'])} hardlinks, {len(plan['drops'])} nombres a quitar, "
      f"{len(plan['state_map'])} rutas del state")
if plan["collisions"]:
    print(f"⚠️ {len(plan['collisions'])} canciones chocan con un archivo existente: se quedan en la carpeta de Antra (revisar a mano)")
if not EXECUTE:
    sys.exit(0)

log = {"renames": [], "links": [], "drops": [], "state_backup": None, "m3u_borrado": None}


def save_log(extra=None):
    if extra:
        log.update(extra)
    json.dump(log, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


try:
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = os.path.join(RESPALDOS, f"antra_state-backup-{ts}.json")
    shutil.copy2(STATE, bak)
    log["state_backup"] = bak
    print("Copia del state:", bak)

    # 1. renombrar carpetas
    for a, b in plan["dir_rename"].items():
        os.rename(P(a), P(b))
        log["renames"].append([a, b])
    print(f"Carpetas renombradas: {len(log['renames'])}")

    # 2. hardlinks
    for n, o in enumerate(plan["links"], 1):
        src, dst = P(o["src"]), P(o["dst"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        nl = os.stat(src).st_nlink
        os.link(src, dst)
        st = os.stat(dst)
        if st.st_ino != o["ino"] or st.st_nlink != nl + 1:
            raise RuntimeError(f"verificación falló tras enlazar {o['dst']}")
        log["links"].append([o["src"], o["dst"]])
        if n % 300 == 0:
            print(f"  hardlinks {n}/{len(plan['links'])}")
    print(f"Hardlinks creados: {len(log['links'])}")

    # 3. quitar nombres de playlists a disolver
    for n, o in enumerate(plan["drops"], 1):
        src, dst = P(o["src"]), P(o["dst"])
        if not os.path.exists(dst) or os.stat(dst).st_ino != o["ino"] or os.stat(src).st_ino != o["ino"]:
            raise RuntimeError(f"no quito {o['src']}: el destino no está o no coincide")
        os.unlink(src)
        if os.stat(dst).st_ino != o["ino"] or os.stat(dst).st_nlink < 1:
            raise RuntimeError(f"algo raro tras quitar {o['src']}")
        log["drops"].append([o["src"], o["dst"]])
    print(f"Nombres quitados: {len(log['drops'])}")

    # 4. carpetas vacías y m3u
    for d in DISSOLVE_DIRS:
        left = os.listdir(P(d)) if os.path.isdir(P(d)) else []
        if os.path.isdir(P(d)) and not left:
            os.rmdir(P(d))
            print(f"rmdir {d}")
        elif left:
            print(f"OJO: {d}/ no está vacía, quedan {len(left)} archivos; la dejo: {left[:5]}")
        m3u = P(d + ".m3u")   # el que Antra deja en la raíz: apunta a la carpeta disuelta, ya no sirve
        if os.path.exists(m3u):
            os.remove(m3u)
            log["m3u_borrado"] = d + ".m3u"
            print(f"borrado {d}.m3u (sus rutas ya no existen)")

    # 5. state (último paso)
    smap = plan["state_map"]
    changed = 0
    for k, v in state.items():
        if k.startswith("TRACK") and v in smap:
            state[k] = smap[v]
            changed += 1
    new_text = json.dumps(state, indent=2, ensure_ascii=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_text)
    os.replace(tmp, STATE)
    print(f"State reescrito: {changed} rutas cambiadas")
    # playlists .m3u, equivalencias.tsv e ids-mb-aceptados.json también guardan rutas (30 sep: una canción de prueba
    # adoptada en MP3 está en «Descubrir» y al repartirla su línea quedaba rota)
    from comun import cambiar_rutas
    cambiar_rutas(smap, "reorg")   # 2 oct: deja el log pendiente para nd_actualizar.py
    save_log()
except Exception as e:
    save_log({"error": repr(e)})
    print(f"\nFALLO: {e}\nEl log parcial está en {LOG}. No se borró nada sin verificar.")
    sys.exit(1)

# verificación final del state
state = json.load(open(STATE, encoding="utf-8"))
tracks = {k: v for k, v in state.items() if k.startswith("TRACK")}
missing = sorted({v for v in tracks.values() if not os.path.exists(v)})
en_disueltas = sorted({v for v in tracks.values() if any(f"/{d}/" in v for d in DISSOLVE_DIRS)})
print(f"State: {len(tracks)} TRACK, rutas inexistentes: {len(missing)}, apuntando a carpetas disueltas: {len(en_disueltas)}")
for v in missing[:10]:
    print("   falta:", v)
print("Log:", LOG)
