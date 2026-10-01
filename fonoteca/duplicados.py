#!/usr/bin/env python3
"""Deja UNA sola copia de cada grabación (reglas del 24 sep 2026). Solo toca Artista/Álbum, nunca una descarga en curso.

Uso: duplicados.py [--execute] [--tambien <ISRC> ...]
  Sin --execute solo muestra el plan.

Duplicado = mismo ISRC, misma duración (±3 s), archivos distintos, y el mismo título (regla única de comun.clave_titulo).
  Si los títulos difieren (p. ej. una traducción) NO se toca: puede ser otra versión o un audio equivocado. Se revisa a
  mano y, si es duplicado, su ISRC se agrega a duplicados_verificados.txt (o se fuerza una vez con --tambien <ISRC>).
Cuál se queda: 1) la del disco del que tenemos más canciones; 2) si empatan, la más escuchada en los historiales de
  Spotify de todos (usuarios/*); 3) la que pertenece a un disco más largo (TRACKTOTAL); 4) el título más corto.
Con --execute:
  - las copias sobrantes se MUEVEN a respaldos/duplicados-<fecha>/ (se borran a mano, una vez aprobado);
  - .antra_state.json y _Playlists/*.m3u pasan a apuntar a la copia que queda;
  - si los dos discos son el MISMO (mismo disco de MusicBrainz, p. ej. nombre en japonés y en inglés), las demás
    canciones del disco chico (las que no sobran) se mueven al grande y toman sus tags de disco (se UNEN sin repetir nada);
  - si la copia borrada era de una edición más antigua, la que queda recibe ORIGINALDATE (ej. Clapton 1992 vs 2013);
  - log para nd_actualizar.py (las reproducciones y estrellas de Navidrome pasan a la copia que queda).
"""
import collections, datetime, glob, json, os, shutil, sys, zipfile
from audio import abrir, es_audio, con_perdida
from comun import ROOT, HERE, RESPALDOS, LOGS, LISTAS, antra_abierto, es_de_album, clave_titulo, cambiar_rutas, decision

args = sys.argv[1:]
EXECUTE = "--execute" in args
TAMBIEN = {args[i + 1].upper() for i, a in enumerate(args) if a == "--tambien" and i + 1 < len(args)}
_verif = decision("duplicados-verificados.txt")   # ISRC revisados a mano: siempre cuentan como duplicados
if os.path.exists(_verif):
    TAMBIEN |= {l.split("#")[0].strip().upper() for l in open(_verif, encoding="utf-8") if l.split("#")[0].strip()}
if EXECUTE and antra_abierto():
    sys.exit("Antra está abierto: ciérralo (este script toca .antra_state.json).")

def g(t, k):
    return (t.get(k) or [""])[0]

# ---------- biblioteca ----------
por_isrc, por_album, seen = collections.defaultdict(list), collections.Counter(), set()
for d, _, fs in os.walk(ROOT):
    for f in fs:
        p = os.path.join(d, f)
        if not es_audio(f) or not es_de_album(p):
            continue
        ino = os.stat(p).st_ino
        if ino in seen:
            continue
        seen.add(ino)
        try:
            t = abrir(p)
        except Exception:
            continue
        por_album[clave_titulo(g(t, "album"))] += 1
        if g(t, "isrc"):
            por_isrc[g(t, "isrc").upper()].append(dict(path=p, secs=t.info.length, titulo=g(t, "title"), album=g(t, "album"),
                                                      rg=g(t, "musicbrainz_releasegroupid"), date=g(t, "date"),
                                                      total=int((g(t, "tracktotal") or g(t, "totaltracks") or "0").split("/")[0] or 0)))

# ---------- historiales (todas las personas) ----------
escuchas = collections.Counter()
def contar(eventos):
    for e in eventos:
        if (e.get("ms_played") or 0) >= 30000 and e.get("master_metadata_track_name"):
            escuchas[(clave_titulo(e.get("master_metadata_album_album_name")), clave_titulo(e["master_metadata_track_name"]))] += 1
leidos = set()
for f in glob.glob(os.path.join(HERE, "usuarios", "*", "**", "Streaming_History_Audio_*.json"), recursive=True):
    contar(json.load(open(f, encoding="utf-8"))); leidos.add(f.split("/usuarios/")[1].split("/")[0].lower())
for z in glob.glob(os.path.join(LISTAS, "**", "*.zip"), recursive=True):
    if os.path.basename(os.path.dirname(z)).lower() in leidos:
        continue
    with zipfile.ZipFile(z) as zz:
        for n in zz.namelist():
            if "Streaming_History_Audio_" in n and n.endswith(".json"):
                contar(json.load(zz.open(n)))

# ---------- plan ----------
plan, revisar = [], []
for isrc, v in por_isrc.items():
    if len(v) < 2 or max(x["secs"] for x in v) - min(x["secs"] for x in v) > 3:
        continue
    if len({clave_titulo(x["titulo"]) for x in v}) > 1 and isrc not in TAMBIEN:
        revisar.append((isrc, [os.path.relpath(x["path"], ROOT) for x in v]))
        continue
    for x in v:
        x["score"] = (por_album[clave_titulo(x["album"])], escuchas[(clave_titulo(x["album"]), clave_titulo(x["titulo"]))],
                      x["total"], -len(x["titulo"]))
    v.sort(key=lambda x: (not con_perdida(x["path"]), x["score"]), reverse=True)   # 28 sep: la SIN pérdida (FLAC) primero
    plan.append({"isrc": isrc, "queda": v[0], "sobran": v[1:]})

print(f"{len(plan)} grabaciones con copias de más ({sum(len(p['sobran']) for p in plan)} archivos sobrantes)")
for p in plan:
    q = p["queda"]
    print(f"  QUEDA  {os.path.relpath(q['path'], ROOT)[:100]}   (disco con {q['score'][0]} canc., {q['score'][1]} escuchas)")
    for s in p["sobran"]:
        print(f"   sobra {os.path.relpath(s['path'], ROOT)[:100]}   (disco con {s['score'][0]} canc., {s['score'][1]} escuchas)")
if revisar:
    print(f"\nMismo ISRC y duración pero TÍTULO distinto ({len(revisar)}): no se tocan (¿otra versión o audio equivocado?):")
    for isrc, ps in revisar:
        print(f"  {isrc}: " + " | ".join(ps))
if not EXECUTE:
    sys.exit("\nSIMULACIÓN: no se tocó nada. Usa --execute.")
if not plan:
    sys.exit(0)

# ---------- ejecutar ----------
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
dest = os.path.join(RESPALDOS, f"duplicados-{stamp}")
sobrantes = {s["path"] for p in plan for s in p["sobran"]}   # al unir discos NO se arrastran: se quitan en su turno
mover = {}   # ruta vieja → ruta nueva (la copia que queda, o donde se movió al unir discos)
DISCO = ("album", "albumartist", "date", "year", "musicbrainz_albumid", "musicbrainz_releasegroupid", "musicbrainz_albumartistid")
for p in plan:
    q = p["queda"]
    for s in p["sobran"]:
        rel = os.path.relpath(s["path"], ROOT)
        os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
        shutil.move(s["path"], os.path.join(dest, rel))
        mover[s["path"]] = q["path"]
        if s["date"] and q["date"] and s["date"][:4] < q["date"][:4]:   # edición más antigua → ORIGINALDATE
            t = abrir(q["path"])
            if not t.get("originaldate"):
                for f in [os.path.join(os.path.dirname(q["path"]), x) for x in os.listdir(os.path.dirname(q["path"])) if es_audio(x)]:
                    tt = abrir(f); tt["originaldate"] = [s["date"]]; tt.save()
        # mismo disco con otro nombre → unir: las demás canciones del disco chico pasan al grande
        chica, grande = os.path.dirname(s["path"]), os.path.dirname(q["path"])
        if chica != grande and s["rg"] and s["rg"] == q["rg"] and os.path.isdir(chica):
            tq = abrir(q["path"])
            for f in sorted(os.listdir(chica)):
                src = os.path.join(chica, f)
                if not es_audio(f) or src in sobrantes or g(abrir(src), "musicbrainz_releasegroupid") != q["rg"]:
                    continue
                t = abrir(src)
                for k in DISCO:
                    if tq.get(k): t[k] = tq[k]
                t.save()
                dst = os.path.join(grande, f)
                n = 2
                while os.path.exists(dst):
                    dst = os.path.join(grande, os.path.splitext(f)[0] + f" ({n})" + os.path.splitext(f)[1]); n += 1
                shutil.move(src, dst)
                mover[src] = dst
        d = os.path.dirname(s["path"])
        while d != ROOT and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d); d = os.path.dirname(d)

# state de Antra, playlists (sin repetir la que queda), equivalencias.tsv e ids-mb-aceptados.json → la ruta nueva
# (30 sep: comun.cambiar_rutas; antes este script tenía su propia copia sin equivalencias ni aceptados)
cambiar_rutas(mover, None)
log = os.path.join(LOGS, f"duplicados-{stamp}.json")
json.dump({"cambios": [{"old_path": a, "new_path": b} for a, b in mover.items()], "respaldo": dest},
          open(log, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\nHECHO: {len(mover)} rutas movidas (sobrantes → {dest}); state, playlists y listas al día.")
print(f"Log para Navidrome (nd_actualizar.py): {log}")
