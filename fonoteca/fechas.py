#!/usr/bin/env python3
"""Paso 6 del procesado: una sola FECHA por disco (si las pistas de un disco tienen años distintos, Navidrome lo parte).

Uso: fechas.py [--execute]          sin --execute solo muestra (el plan queda en planes/plan-dates.json)
     fechas.py --revert <log>       deshace una corrida (logs/fechas-log-<fecha>.json)

Regla por carpeta Artista/AAAA - Álbum/:
  1. se toman los DATE de las canciones cuyo año == año de la carpeta;
  2. fecha del disco = la más frecuente de esas (conserva mes/día); si no hay ninguna, solo AAAA;
     carpeta sin año en el nombre: la fecha más frecuente entre sus canciones;
  3. a las canciones con DATE distinto se les pone esa fecha (y YEAR si lo tenían). ORIGINALDATE no se toca.
mutagen escribe en el mismo archivo (inodo), así que los hardlinks se mantienen.
"""
import json, os, re, sys
from collections import Counter
from audio import abrir, es_audio
from comun import ROOT, SKIP, plan_path, log_path, antra_abierto, cerrojo, guardar_json

if "--revert" in sys.argv:
    log = json.load(open(sys.argv[sys.argv.index("--revert") + 1]))
    for e in log:
        a = abrir(os.path.join(ROOT, e["path"]))
        for k in ("DATE", "YEAR"):
            if e["old"].get(k) is None:
                a.pop(k, None)
            else:
                a[k] = e["old"][k]
        a.save()
    sys.exit(f"revertidas {len(log)} canciones")
EXECUTE = "--execute" in sys.argv

# ---------- plan ----------
plan, carpetas, sin_anio, seen = [], 0, [], set()
for dp, dns, fns in os.walk(ROOT):
    rel = os.path.relpath(dp, ROOT)
    partes = rel.split(os.sep)
    if partes[0] in SKIP:
        dns[:] = []
        continue
    flacs = sorted(f for f in fns if es_audio(f))
    if not flacs or len(partes) < 2:   # solo Artista/Álbum (no la carpeta de una descarga)
        continue
    m = re.match(r"(\d{4}) - ", partes[-1])
    if not m:
        sin_anio.append(rel)
    fy = m.group(1) if m else None
    carpetas += 1
    fechas = {}
    for f in flacs:
        try:
            a = abrir(os.path.join(dp, f))
        except Exception:
            continue
        fechas[f] = (a.get("date", [""])[0], a.get("year", [""])[0])
    cand = [d for d, _ in fechas.values() if (d[:4] == fy if fy else d)]
    if not cand and not fy:
        continue
    destino = Counter(cand).most_common(1)[0][0] if cand else fy
    for f, (d, y) in fechas.items():
        ino = os.stat(os.path.join(dp, f)).st_ino
        if ino in seen:   # hardlink ya planificado
            continue
        seen.add(ino)
        if d != destino or (y and y[:4] != destino[:4]):
            plan.append({"path": os.path.join(rel, f), "old_date": d, "old_year": y, "new_date": destino, "folder_year": fy or ""})
guardar_json(plan_path("plan-dates.json"), plan, indent=1)

tipos = Counter("sin DATE" if not x["old_date"] else "año distinto" if x["old_date"][:4] != x["new_date"][:4]
                else "mismo año, otra fecha" for x in plan)
print(f"carpetas: {carpetas} (sin año en el nombre: {len(sin_anio)}) | canciones a cambiar: {len(plan)} "
      f"en {len({os.path.dirname(x['path']) for x in plan})} carpetas {dict(tipos)}")
if not EXECUTE:
    sys.exit(0)
if antra_abierto():
    sys.exit("Antra está abierto: ciérralo antes de escribir tags.")
cerrojo("fechas.py")

# ---------- aplicar ----------
LOG = log_path("fechas-log")
log, errores = [], []
for e in plan:
    try:
        a = abrir(os.path.join(ROOT, e["path"]))
        viejo = {"DATE": a["date"][0] if "date" in a else None, "YEAR": a["year"][0] if "year" in a else None}
        log.append({"path": e["path"], "old": viejo})
        guardar_json(LOG, log, indent=1)   # log antes de tocar
        a["DATE"] = e["new_date"]
        if viejo["YEAR"] is not None:
            a["YEAR"] = e["new_date"][:4]
        a.save()
    except Exception as ex:
        errores.append((e["path"], str(ex)))
mal = sum(1 for e in plan if abrir(os.path.join(ROOT, e["path"])).get("date", [""])[0] != e["new_date"])
print(f"ESCRITAS {len(plan)} canciones | errores: {len(errores)} | verificación fallida: {mal}" + (f" | log: {LOG}" if plan else ""))
for p, m in errores[:10]:
    print("  ERROR", p, m)
sys.exit(1 if errores or mal else 0)
