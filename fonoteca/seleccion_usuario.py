#!/usr/bin/env python3
"""Qué canciones bajar para una persona, a partir de su historial de Spotify (+ sus playlists y discos). SOLO LEE la música.
Es el ÚNICO comando ANTES de descargar (junta lo que se hizo con las primeras cuatro personas, 20-24 sep 2026).

Uso:
  seleccion_usuario.py <Nombre> [--zip <my_spotify_data.zip>] [--propias <ids>] [--playlists <ids>] [--albumes]
    <Nombre>      carpeta ~/music-tools/usuarios/<Nombre>/ (con --zip se crea/extrae ahí el historial)
    --propias     playlists PROPIAS de la persona: se bajan completas (lo que falte en la biblioteca)
    --playlists   playlists que SIGUE: cuentan si las usa (>=20 escuchas); se bajan las canciones que oyó >=2 veces y terminó >=1
    --albumes     discos que escucha "como disco" (>=70% del disco, en >=3 días, >=4 canciones): se completan (páginas
                  públicas de Spotify: sin Premium ni cuota, 30 sep 2026)
    <ids> = archivo de texto con enlaces o IDs de playlists de Spotify (uno por línea), o una lista separada por comas.

Criterio v4 (23 sep 2026; escucha = >=30 s). Entra si cumple CUALQUIERA:
  1. >=10 escuchas   2. >=3 escuchas en >=3 días distintos   3. elegida a propósito (clickrow/playbtn/backbtn) en >=2 días
  4. artista suyo (>=4 canciones con >=2 escuchas en SU historial) + >=2 escuchas en >=2 días, y vigente
  5. descubierta en los últimos 60 días del historial con >=3 escuchas
  Se excluye si termina <25% de las veces y nunca la eligió.
Salida: <carpeta de listas>/<Nombre>/<NOMBRE>-<n>.txt (enlaces para pegar en una playlist de Spotify → Antra)
        + usuarios/<Nombre>/seleccion.json (cada canción con su motivo).
"""
import collections, datetime, glob, json, os, re, sys, urllib.parse, urllib.request, zipfile
from audio import abrir, es_audio
from comun import ROOT, HERE, LISTAS, cache_path, es_de_album, clave_titulo, clave_artista
from red import Cache, pagina, pedir_json

args = sys.argv[1:]
if not args or args[0].startswith("--"):
    sys.exit(__doc__)
nombre = args[0]
def opt(k): return args[args.index(k) + 1] if k in args else None
SP = os.path.join(__import__("comun").DATOS, "usuarios", nombre)   # 2 oct: DATOS (= HERE en uso normal; aparte en modo prueba)
if opt("--zip"):
    os.makedirs(SP, exist_ok=True)
    zipfile.ZipFile(opt("--zip")).extractall(SP)
HIST = glob.glob(os.path.join(SP, "**", "Streaming_History_Audio_*.json"), recursive=True)
if not HIST:
    sys.exit(f"No hay historial en {SP} (usa --zip <archivo.zip>)")
DELIB = {"clickrow", "playbtn", "backbtn"}
tid = lambda u: u.strip().rstrip("/").split("/")[-1].split(":")[-1].split("?")[0]

# ---------- biblioteca: qué ya tenemos ----------
lib_sid, lib_key = set(), set()
for d, _, fs in os.walk(ROOT):
    for f in fs:
        p = os.path.join(d, f)
        if not es_audio(f) or not es_de_album(p):
            continue
        try:
            t = abrir(p)
        except Exception:
            continue
        g = lambda k: (t.get(k) or [""])[0]
        lib_sid.add(g("spotify_id"))
        for a in {g("artist"), g("albumartist")}:
            if a: lib_key.add((clave_artista(a), clave_titulo(g("title"))))
def la_tenemos(sids, artista, titulo):
    return bool(set(sids) & lib_sid) or (clave_artista(artista), clave_titulo(titulo)) in lib_key

# ---------- historial ----------
ev = [e for p in HIST for e in json.load(open(p, encoding="utf-8")) if e.get("spotify_track_uri") and e.get("master_metadata_track_name")]
ev.sort(key=lambda e: e["ts"])
fin = datetime.datetime.fromisoformat(ev[-1]["ts"].replace("Z", "+00:00"))
S = {}
for e in ev:
    k = (clave_artista(e["master_metadata_album_artist_name"]), clave_titulo(e["master_metadata_track_name"]))
    s = S.setdefault(k, {"artista": e["master_metadata_album_artist_name"], "titulo": e["master_metadata_track_name"],
                         "album": e["master_metadata_album_album_name"], "sids": set(), "por_sid": collections.Counter(), "esc": 0, "dias": set(),
                         "delib_dias": set(), "starts": 0, "done": 0, "first": None, "last": None})
    s["sids"].add(tid(e["spotify_track_uri"])); s["starts"] += 1
    s["done"] += e.get("reason_end") == "trackdone"
    if e.get("reason_start") in DELIB: s["delib_dias"].add(e["ts"][:10])
    if (e.get("ms_played") or 0) >= 30000:
        s["esc"] += 1; s["dias"].add(e["ts"][:10]); s["por_sid"][tid(e["spotify_track_uri"])] += 1
        s["first"] = s["first"] or e["ts"]; s["last"] = e["ts"]
def mejor_sid(s):   # de los enlaces de Spotify de una canción, el que la persona más escuchó
    return s["por_sid"].most_common(1)[0][0] if s["por_sid"] else sorted(s["sids"])[0]
art_canc = collections.Counter(k[0] for k, s in S.items() if s["esc"] >= 2)
sid2k = {sid: k for k, s in S.items() for sid in s["sids"]}
faltan = {k: s for k, s in S.items() if not la_tenemos(s["sids"], s["artista"], s["titulo"])}
print(f"Historial: {len(ev)} reproducciones, {ev[0]['ts'][:10]} → {ev[-1]['ts'][:10]} | {len(S)} canciones | "
      f"ya en la biblioteca: {len(S) - len(faltan)} | faltan: {len(faltan)}")

# ---------- criterio v4 ----------
anio_pasado = str(fin.year - 1)
REGLAS = {
    "1. >=10 escuchas": lambda s, k: s["esc"] >= 10,
    "2. >=3 escuchas en >=3 días": lambda s, k: s["esc"] >= 3 and len(s["dias"]) >= 3,
    "3. elegida en >=2 días": lambda s, k: len(s["delib_dias"]) >= 2,
    "4. artista suyo": lambda s, k: art_canc[k[0]] >= 4 and s["esc"] >= 2 and len(s["dias"]) >= 2
                                   and ((s["last"] or "") >= anio_pasado or s["esc"] >= 3),
    "5. descubierta <60 días, >=3": lambda s, k: s["first"] is not None and s["esc"] >= 3
                                   and (fin - datetime.datetime.fromisoformat(s["first"].replace("Z", "+00:00"))).days <= 60,
}
sel = {}   # sid → {artista, titulo, motivo, orden}
cuenta = collections.Counter()
for k, s in faltan.items():
    hits = [n for n, fn in REGLAS.items() if fn(s, k)]
    for n in hits: cuenta[n] += 1
    if not hits:
        continue
    if s["starts"] and s["done"] / s["starts"] < 0.25 and not s["delib_dias"]:
        cuenta["(excluidas: termina <25% y nunca la eligió)"] += 1
        continue
    sid = mejor_sid(s)
    sel[sid] = dict(artista=s["artista"], titulo=s["titulo"], motivo="historial: " + ", ".join(h[:2].strip(".") for h in hits),
                    orden=(0, -len(s["dias"]), -s["esc"]))
print("\nCriterio v4 sobre las que faltan:")
for n in list(REGLAS) + ["(excluidas: termina <25% y nunca la eligió)"]:
    print(f"  {n:45s} {cuenta[n]:5d}")
print(f"  → {len(sel)} canciones")
borde = [v for v in sel.values() if "," not in v["motivo"]]
print(f"  borde (entran por UNA sola regla): {len(borde)}, p. ej.: " + "; ".join(f"{v['artista']} – {v['titulo']}" for v in borde[:6]))

# ---------- playlists (embed público: hasta 100 canciones, sin API) ----------
def ids_de(v):
    if not v: return []
    txt = open(v, encoding="utf-8").read() if os.path.exists(v) else v.replace(",", "\n")
    return [tid(l) for l in txt.splitlines() if l.strip() and not l.startswith("#")]
EMB = cache_path("embed-playlists.json")
emb = json.load(open(EMB)) if os.path.exists(EMB) else {}
def playlist(pid):
    if pid not in emb:
        h = pagina(f"https://open.spotify.com/embed/playlist/{pid}")   # red.py: 1 cada 1,5 s
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
        try:
            e = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
        except Exception:   # sin red o sin respuesta: NO se guarda (antes quedaba como playlist vacía para siempre)
            return {"nombre": f"(no se pudo leer {pid})", "canciones": []}
        emb[pid] = {"nombre": e["name"], "canciones": [(t["uri"].split(":")[-1], t["title"], t["subtitle"]) for t in e["trackList"]]}
        json.dump(emb, open(EMB, "w"), ensure_ascii=False)
    return emb[pid]
for pid in ids_de(opt("--propias")):
    pl = playlist(pid); n0 = len(sel)
    for sid, tit, art in pl["canciones"]:
        if sid not in sel and not la_tenemos([sid], art, tit):
            sel[sid] = dict(artista=art, titulo=tit, motivo=f"playlist propia «{pl['nombre']}»", orden=(1, 0, 0))
    print(f"\nPlaylist propia «{pl['nombre']}»: {len(pl['canciones'])} canciones (el embed da hasta 100), +{len(sel) - n0} nuevas")
if opt("--playlists"):
    print("\nPlaylists que sigue (cuentan si las usa: >=20 escuchas de sus canciones):")
    for pid in ids_de(opt("--playlists")):
        pl = playlist(pid)
        ks = [sid2k[sid] for sid, _, _ in pl["canciones"] if sid in sid2k]
        uso = sum(S[k]["esc"] for k in set(ks))
        if uso < 20:
            continue
        n0 = len(sel)
        for k in set(ks):
            s = S[k]
            if k in faltan and s["esc"] >= 2 and s["done"] >= 1:
                sid = mejor_sid(s)
                if sid not in sel:
                    sel[sid] = dict(artista=s["artista"], titulo=s["titulo"], motivo=f"playlist «{pl['nombre']}» (la oyó {s['esc']}, la terminó)",
                                    orden=(2, -len(s["dias"]), -s["esc"]))
        print(f"  {uso:4d} escuchas  «{pl['nombre'][:50]}»  +{len(sel) - n0}")

# ---------- discos a completar (Deezer para el tamaño del disco; la página pública del disco en Spotify para los enlaces) ----------
if "--albumes" in args:
    from comun import spotify_cancion, spotify_disco
    dz = Cache("deezer-cache.json")   # red.py
    def dz_get(url):
        return pedir_json(url, dz) or {}
    oido = collections.defaultdict(lambda: {"titulos": set(), "dias": set(), "sid": None})
    for e in ev:
        if (e.get("ms_played") or 0) >= 30000:
            o = oido[(e["master_metadata_album_artist_name"], e["master_metadata_album_album_name"])]
            o["titulos"].add(clave_titulo(e["master_metadata_track_name"])); o["dias"].add(e["ts"][:10]); o["sid"] = tid(e["spotify_track_uri"])
    print("\nDiscos que escucha como disco (>=70% del disco, >=3 días, >=4 canciones):")
    n_disc = 0
    for (art, alb), o in oido.items():
        if len(o["titulos"]) < 4 or len(o["dias"]) < 3:
            continue
        res = dz_get("https://api.deezer.com/search/album?q=" + urllib.parse.quote(f'artist:"{art}" album:"{alb}"')).get("data", [])
        m = next((a for a in res if clave_titulo(a.get("title")) == clave_titulo(alb)), None)
        if not m:
            continue
        pistas = [clave_titulo(t.get("title")) for t in dz_get(f"https://api.deezer.com/album/{m['id']}/tracks?limit=200").get("data", [])]
        if not pistas or sum(p in o["titulos"] for p in pistas) / len(pistas) < 0.70:
            continue
        c = spotify_cancion(o["sid"])
        disco = spotify_disco(c["disco_id"]) if c else None
        if not disco:
            print(f"  {art} — {alb}: no pude leer su página pública de Spotify → se salta"); continue
        n0 = len(sel)
        for t in disco["canciones"]:
            if t["id"] not in sel and not la_tenemos([t["id"]], t["artista"], t["titulo"]):
                sel[t["id"]] = dict(artista=t["artista"], titulo=t["titulo"], motivo=f"completar disco «{alb}»", orden=(3, 0, t["pista"]))
        n_disc += 1
        if len(sel) > n0:
            print(f"  {art} — {alb}: +{len(sel) - n0}")
    dz.guardar()
    print(f"  ({n_disc} discos cumplen el criterio)")

# ---------- salida ----------
orden = sorted(sel.items(), key=lambda kv: kv[1]["orden"])
dest = os.path.join(LISTAS, nombre)
os.makedirs(dest, exist_ok=True)
out = os.path.join(dest, f"{nombre.upper()}-{len(orden)}.txt")
open(out, "w").write("".join(f"https://open.spotify.com/track/{sid}\n" for sid, _ in orden))
json.dump([{"spotify_id": sid, **{k: v for k, v in x.items() if k != "orden"}} for sid, x in orden],
          open(os.path.join(SP, "seleccion.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
por_motivo = collections.Counter(x["motivo"].split(":")[0].split("«")[0].strip() for _, x in orden)
print(f"\nTOTAL: {len(orden)} canciones (~{len(orden) * 0.037:.0f} GB, ~{len(orden) / 90:.1f} h de Antra) → {out}")
print("  " + " | ".join(f"{k}: {v}" for k, v in por_motivo.items()))
print("Siguiente: pegar los enlaces en una playlist nueva de Spotify (cliente de escritorio) → Antra (strict) → procesar_descarga.py")
