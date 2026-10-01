#!/usr/bin/env python3
"""Paso 6 del procesado: GÉNEROS normalizados a una lista corta de 20 (la app Android de Navidrome navega por género).

Uso: generos.py [--execute] [--sin-respaldo]       sin --execute solo muestra (plan en planes/plan-generos.json)
     generos.py --votos-de <respaldo de tags>       solo informa los votos de un respaldo viejo (no planea nada)
     generos.py --sembrar <respaldo de tags>        toma el género original de Deezer de ese respaldo (se usó 1 vez, 24 sep)
Con --execute respalda antes todos los tags (salvo --sin-respaldo: procesar_descarga ya respaldó en su paso 2).

Por qué: Deezer asigna el género por DISCO y se equivoca (Bad Bunny = Lullabies, Rawayana = African Music).
Reglas (24 sep 2026):
  - votos = el género ORIGINAL de Deezer de cada canción, guardado en GENRE_DEEZER (normalizar GENRE no los borra);
  - cada género de Deezer se traduce con MAPA; por artista (ALBUMARTIST) gana el que tenga más canciones;
  - reglas latinas: Deezer mete el reggaetón en Hip Hop/Latin y la salsa/bachata en Latin (ver código);
  - hasta 2 géneros: el 2º si tiene >=20% y >=3 de las canciones del artista; FIJOS (decisiones/generos-fijos.tsv) = uno solo;
  - "Various Artists" se clasifica por DISCO, no por artista.
  - Bandas sonoras (ALBUMARTIST «Soundtracks», 30 sep): cada canción lleva los géneros de SU artista (los de sus propios
    discos; hasta 2) + «Soundtrack» de 3º → salen en los mixes de su género. Sus votos no cuentan para el artista (una
    OST no le pone «Soundtrack» a sus discos). Artista que solo está en bandas sonoras → por sus votos (suele ser
    «Soundtrack» solo).
Nunca usar "/" en un nombre de género: Navidrome lo parte en dos.
"""
import collections, json, os, re, subprocess, sys, time
from audio import abrir, es_audio

from comun import ROOT, HERE, log_path, RESPALDOS, SKIP
from generos_reglas import G2, fijos
# la lista de 20, la traducción de los géneros de Deezer/Apple y los fijos por artista: generos_reglas.py (30 sep)
FIJOS = fijos()   # decisiones/generos-fijos.tsv

# Votos: el género ORIGINAL de Deezer/Antra de cada canción. Se guarda en GENRE_DEEZER (Navidrome no lo usa) para que
# normalizar GENRE nunca borre los votos. Canciones sin GENRE_DEEZER: se toma de --sembrar <respaldo de tags> (por inodo)
# o, si no, de su GENRE actual (en una descarga nueva todavía es el de Deezer).
SEMBRAR = sys.argv[sys.argv.index("--sembrar") + 1] if "--sembrar" in sys.argv else None
VOTOS_DE = sys.argv[sys.argv.index("--votos-de") + 1] if "--votos-de" in sys.argv else None
def generos_de_respaldo(ruta):
    r = {}
    for ino, x in json.load(open(ruta, encoding="utf-8")).items():
        r[int(ino)] = [v for k, v in x["tags"] if k.lower() == "genre"]
    return r
semilla = generos_de_respaldo(SEMBRAR) if SEMBRAR else {}
VA = {"variousartists", "variosartistas"}
OST = "Soundtracks"   # artista del disco de las bandas sonoras (2026-09-28-ost-por-franquicia.py)
def es_va(a): return re.sub(r"[^\w]", "", (a or "").lower()) in VA

seen, arch = set(), []
votos = collections.defaultdict(collections.Counter)   # clave (artista, o ("VA", álbum)) → votos por género
sin_mapa = collections.Counter()
for d, _, fs in os.walk(ROOT):
    for f in fs:
        if not es_audio(f):
            continue
        p = os.path.join(d, f)
        # solo Artista/Álbum/archivo: no tocar la carpeta que Antra está bajando (ni _Prueba: su género es «Prueba»)
        if os.path.relpath(p, ROOT).count(os.sep) < 2 or os.path.relpath(p, ROOT).split(os.sep)[0] in SKIP:
            continue
        ino = os.stat(p).st_ino
        if ino in seen:
            continue
        seen.add(ino)
        try:
            t = abrir(p)
        except Exception:
            continue
        gs = t.get("genre") or []
        deezer = t.get("genre_deezer") or semilla.get(ino) or gs
        guardar_deezer = deezer if not t.get("genre_deezer") and deezer else None
        a = (t.get("albumartist") or t.get("artist") or ["?"])[0]
        clave = ("VA", (t.get("album") or [""])[0]) if es_va(a) else a
        if a == OST:
            clave = ("OST", (t.get("artist") or ["?"])[0])
        g0 = deezer[0] if deezer else ""
        n = G2.get(g0)
        if g0 and not n:
            sin_mapa[g0] += 1
        if n:
            votos[clave][n] += 1
        arch.append((p, clave, gs, guardar_deezer))

if VOTOS_DE:   # solo informar los votos de un respaldo viejo
    votos = collections.defaultdict(collections.Counter)
    for x in json.load(open(VOTOS_DE, encoding="utf-8")).values():
        tg = {}
        for k, v in x["tags"]:
            tg.setdefault(k.lower(), []).append(v)
        a = (tg.get("albumartist") or tg.get("artist") or ["?"])[0]
        clave = ("VA", (tg.get("album") or [""])[0]) if es_va(a) else a
        for g_ in (tg.get("genre") or [])[:1]:
            if G2.get(g_): votos[clave][G2[g_]] += 1

# Regla (24 sep 2026): hasta 2 géneros. 1º = mayoría (con reglas latinas y FIJOS); 2º = el siguiente si tiene
# >=20% de las canciones y >=3 canciones (20% para que Gorillaz, 24%, entre). Various Artists: por DISCO, no por "artista".
SEGUNDO_MIN_FRAC, SEGUNDO_MIN_N = 0.20, 3
IGNORAR_2DO = {"Reggaeton": {"Hip Hop", "Latin"}, "Tropical": {"Latin", "Pop"}}   # sesgos de Deezer, no géneros reales
genero, dudosos = {}, []
for clave, c in votos.items():
    top, k = c.most_common(1)[0]
    # Deezer mete el reggaetón en "Rap/Hip Hop" y "Latin Music", y la salsa/bachata en "Latin Music"
    if c["Reggaeton"] and top in ("Hip Hop", "Latin"):
        top = "Reggaeton"
    elif c["Tropical"] and top in ("Latin", "Pop"):
        top = "Tropical"
    if isinstance(clave, str) and clave in FIJOS:
        genero[clave] = [FIJOS[clave]]
        continue
    tot = sum(c.values())
    resto = [(g, n) for g, n in c.most_common() if g != top and g not in IGNORAR_2DO.get(top, ())]
    seg = resto[0] if resto and resto[0][1] >= SEGUNDO_MIN_N and resto[0][1] / tot >= SEGUNDO_MIN_FRAC else None
    genero[clave] = [top] + ([seg[0]] if seg else [])
    if len(c) > 1 and c[top] / tot < 0.7 and tot >= 3:
        dudosos.append((clave, dict(c.most_common())))
for a, g in FIJOS.items():
    genero.setdefault(a, [g])
for clave in [k for k in genero if isinstance(k, tuple) and k[0] == "OST"]:
    base = [g for g in (genero.get(clave[1]) or genero[clave]) if g != "Soundtrack"][:2]
    genero[clave] = base + ["Soundtrack"]

plan, total, dos = [], collections.Counter(), collections.Counter()
for p, clave, gs, guardar_deezer in arch:
    nuevo = genero.get(clave) or ([G2[gs[0]]] if gs and gs[0] in G2 else [])
    for g in nuevo: total[g] += 1
    if not nuevo: total["(sin género)"] += 1
    if len(nuevo) >= 2: dos[clave if isinstance(clave, str) else ("Various Artists: " if clave[0] == "VA" else "OST: ") + clave[1]] += 1
    if (nuevo and gs != nuevo) or guardar_deezer:
        plan.append({"path": p, "antes": gs, "despues": nuevo or gs, "deezer": guardar_deezer})
if VOTOS_DE:
    plan = []
json.dump(plan, open(__import__("comun").plan_path("plan-generos.json"), "w"), ensure_ascii=False, indent=0)

print(f"{len(arch)} audios | {len(plan)} cambiarían | con 2 géneros: {len(dos)} artistas/discos ({sum(dos.values())} canciones)")
for g, n in total.most_common():
    print(f"  {n:5d} {g}")
if sin_mapa:
    print("\nSin traducción en MAPA:", dict(sin_mapa))
print("\nArtistas con 2 géneros (los que más canciones tienen):")
for a, n in dos.most_common(25):
    g_ = genero.get(a) or genero.get(("OST", a[5:])) or genero.get(("VA", a[17:])) or []
    print(f"  {a[:40]:40s} {' + '.join(g_)}  ({n} canc.)")
print(f"\nDudosos (mayoría <70%, >=3 canciones): {len(dudosos)}")
for a, c in sorted(dudosos, key=lambda x: -sum(x[1].values()))[:40]:
    print(f"  {str(a)[:34]:34s} → {' + '.join(genero[a]):24s} {c}")


# ---------- aplicar ----------
if "--execute" not in sys.argv or not plan:
    sys.exit(0)
from audio import abrir as _abrir
if "--sin-respaldo" not in sys.argv:
    subprocess.run(["python3", os.path.join(HERE, "tags_backup.py"), "dump",
                    os.path.join(RESPALDOS, f"tags-antes-generos-{time.strftime('%Y%m%d-%H%M%S')}.json")], check=True)
hechos, errores = [], []
for x in plan:
    try:
        t = _abrir(x["path"])
        t["genre"] = x["despues"]
        if x.get("deezer"):
            t["genre_deezer"] = x["deezer"]
        t.save()
        if _abrir(x["path"]).get("genre") != x["despues"]:
            raise RuntimeError("verificación fallida")
        hechos.append(x)
    except Exception as e:
        errores.append({**x, "error": str(e)})
LOG = log_path("generos-log")
json.dump({"hechos": hechos, "errores": errores}, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print(f"ESCRITAS {len(hechos)} | errores {len(errores)} | log {LOG}")
for e in errores[:10]:
    print("  ", e["path"], e["error"])
sys.exit(1 if errores else 0)
