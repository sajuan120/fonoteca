#!/usr/bin/env python3
"""Clasifica canciones sospechosas de ser "otra canción" por su huella de audio (AcoustID). SOLO LEE.

Uso: acoustid_check.py <lista.txt>   (rutas relativas a la biblioteca, una por línea)
Resultado por canción:
  OK         → AcoustID dice que es la misma canción que dicen los tags (falsa alarma)
  EQUIVOCADA → el audio es otra canción/artista (se dice cuál)
  DESCONOCIDA→ AcoustID no la conoce
Salida: acoustid-resultado-<fecha>.json. Clave en .acoustid_key junto a los scripts (opcional: sin ella, todas salen
«DESCONOCIDA» y el procesado las compara solo con la canción de Spotify).
"""
import json, os, re, subprocess, sys, unicodedata, urllib.parse, urllib.request
from audio import abrir

from comun import ROOT, ACOUSTID_KEY as KEY, LOGS, log_path, titulo_base, primer_artista
from red import pedir_json

VERSIONES = ("remix", "rmx", "live", "en vivo", "directo", "instrumental", "acoustic", "acustic", "demo", "sped up",
             "slowed", "extended")
def version(s):
    """Qué versión dice el título (remix, en vivo, instrumental…); remaster/edit no cuentan (misma grabación o solo duración)."""
    s = unicodedata.normalize("NFKD", (s or "").lower()); s = "".join(c for c in s if not unicodedata.combining(c))
    return {w for w in VERSIONES if re.search(rf"\b{w}{'s?' if w in ('remix', 'instrumental', 'demo') else ''}\b", s)}

from concurrent.futures import ThreadPoolExecutor
PARTIAL = os.path.join(LOGS, "acoustid-parcial.json")
res = json.load(open(PARTIAL)) if os.path.exists(PARTIAL) else {}
paths = [l.strip() for l in open(sys.argv[1]) if l.strip() and l.strip() not in res]
if not KEY:   # sin clave de AcoustID: nada que consultar; el procesado decide con la canción de Spotify
    print("Sin clave de AcoustID (.acoustid_key): no se consulta; las sospechosas se comparan solo con Spotify.")
    for rel in paths:
        res[rel] = dict(veredicto="DESCONOCIDA", tags="", audio_es="(sin clave de AcoustID)")
    out = log_path("acoustid-resultado")
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"{dict(__import__('collections').Counter(v['veredicto'] for v in res.values()))} → {out}")
    sys.exit(0)
def fpcalc(rel):
    p = subprocess.run(["fpcalc", "-json", os.path.join(ROOT, rel)], capture_output=True, text=True)
    try: return json.loads(p.stdout)
    except ValueError:
        print(f"  fpcalc falló ({p.returncode}): {rel} {p.stderr.strip()[:150]}", flush=True); return None
pool = ThreadPoolExecutor(12)
fps = pool.map(fpcalc, paths)
for i, (rel, fp) in enumerate(zip(paths, fps)):
    f = os.path.join(ROOT, rel); t = abrir(f); g = lambda k: (t.get(k) or [""])[0]
    if not fp:
        res[rel] = dict(veredicto="DESCONOCIDA", tags=f"{g('artist')} — {g('title')}", audio_es="(fpcalc falló)"); continue
    data = urllib.parse.urlencode({"client": KEY, "meta": "recordings", "duration": int(fp["duration"]),
                                   "fingerprint": fp["fingerprint"], "format": "json"}).encode()
    r = pedir_json("https://api.acoustid.org/v2/lookup", datos=data)   # red.py: 3 por segundo, reintentos
    if r is None:
        r = {"results": [], "error": "sin respuesta"}; print("  AcoustID no respondió", flush=True)
    recs = [(x["score"], rc) for x in r.get("results", []) if x["score"] >= 0.7 for rc in x.get("recordings", []) if rc.get("title")]
    ta, tt = titulo_base(primer_artista(g("artist"), y=True)), titulo_base(g("title"))
    my_rec, my_art = set(t.get("musicbrainz_trackid") or []), set(t.get("musicbrainz_artistid") or [])
    def same_name(rc):
        arts = titulo_base("".join(a["name"] for a in rc.get("artists", [])))
        return titulo_base(rc["title"]) == tt and ta[:6] and (ta[:6] in arts or arts[:6] in ta)
    def same_id(rc):
        return rc.get("id") in my_rec or (titulo_base(rc["title"]) == tt and bool(my_art & {a.get("id") for a in rc.get("artists", [])}))
    mismas = [(sc, rc) for sc, rc in recs if same_id(rc) or same_name(rc)]
    if not recs: v, who = "DESCONOCIDA", ""
    elif any(rc.get("id") in my_rec for _, rc in recs): v, who = "OK", ""   # la grabación exacta (ID de MusicBrainz)
    elif any(version(rc["title"]) == version(g("title")) for _, rc in mismas): v, who = "OK", ""
    elif mismas:   # misma canción pero otra versión (titulo_base() ignora "- Remix", "(Live)"…: así pasó por buena el CANDY original)
        sc, rc = max(mismas, key=lambda x: x[0])
        v, who = "OTRA VERSIÓN", f"{' & '.join(a['name'] for a in rc.get('artists', []))} — {rc['title']} ({sc:.2f})"
    else:
        sc, rc = max(recs, key=lambda x: x[0])
        who = f"{' & '.join(a['name'] for a in rc.get('artists', []))} — {rc['title']} ({sc:.2f})"
        # mismo título, otro artista y sin ID de MB en el archivo para desempatar → revisar
        v = "REVISAR" if titulo_base(rc["title"]) == tt and not my_rec else "EQUIVOCADA"
    res[rel] = dict(veredicto=v, tags=f"{g('artist')} — {g('title')}", audio_es=who,
                    crudo=[(sc_, {"id": rc_.get("id"), "title": rc_["title"],
                                  "artists": [(x.get("id"), x["name"]) for x in rc_.get("artists", [])]}) for sc_, rc_ in recs[:8]])
    if v != "OK": print(f"{v:11} {rel[:70]:70} {('→ ' + who) if who else ''}", flush=True)
    if i % 100 == 0:
        json.dump(res, open(PARTIAL, "w"), ensure_ascii=False); print(f"  ... {i}/{len(paths)}", flush=True)
out = log_path("acoustid-resultado")
json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
if os.path.exists(PARTIAL): os.remove(PARTIAL)
from collections import Counter
print(dict(Counter(x["veredicto"] for x in res.values())), "→", out)
