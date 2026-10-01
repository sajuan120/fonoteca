#!/usr/bin/env python3
"""Busca en OTRAS tiendas las canciones que Antra no consiguió (30 sep 2026: reemplaza a los puntuales buscar-en-deezer,
-tidal, -apple, -qobuz, lista-faltan y spotify-id-descarga-suelta). Antra acepta enlaces de Deezer, Tidal, Apple Music y
Qobuz además de Spotify.

Uso: buscar_fuentes.py [--en deezer,tidal,apple,qobuz]
         Las canciones «a conseguir» (revisar_fallidas.tsv que todavía no están en la biblioteca), buscadas en orden en
         cada tienda hasta encontrarla. Solo lee. Salida en la carpeta de listas: FUENTES-<n>.txt (los enlaces, para
         pegarlos en Antra) y «FUENTES-<n> (con nombres).tsv» (qué se encontró, dónde y con qué duración).
     buscar_fuentes.py --poner-spotify-id "<carpeta>" [--execute]
         DESPUÉS de bajar esos enlaces con Antra y ANTES de procesar: lo bajado desde Deezer/Tidal/Apple/Qobuz llega sin
         spotify_id, y sin él el procesado no puede compararlo con la canción exacta de Spotify (paso 3b) ni devolverlo
         a sus playlists (7e). Se lo pone emparejando con los FUENTES-*.tsv: por ISRC o por título.

La regla (la misma en las cuatro tiendas, 28-29 sep): MISMO artista + MISMA canción (comun.clave_titulo: ignora
remaster, radio edit o feat., pero NO remix, en vivo ni versiones) + duración a ±max(3 s, 1 %) de la canción de Spotify
(su página pública). Sin duración de Spotify → «revisar». Segunda pasada en Apple y Qobuz (el título se escribe distinto,
«Enemy feat. J.I.D. (from…)» contra «Enemy (from…) [feat. JID]»): mismo artista + mismo comienzo del título + duración
a ±1 s → «revisar». Qobuz: solo pistas con derechos (streamable; si no, Antra da «not found»).
Cuentas: Deezer, Tidal (token público de su web) y Apple (iTunes Search, tiendas US y JP) no piden nada. Qobuz pide una
sesión: el token va en .qobuz_token junto a los scripts (privado; se saca en play.qobuz.com → consola del navegador:
JSON.parse(localStorage.getItem("localuser")).token). Sin ese archivo, Qobuz se salta.
"""
import csv, glob, os, re, sys, urllib.parse
from audio import abrir, es_audio
from comun import CONF, HERE, LISTAS, ROOT, a_conseguir, clave_artista, clave_titulo, duracion_spotify
from red import Cache, pedir_json

args = sys.argv[1:]
if any(a in ("-h", "--help") for a in args):
    sys.exit(__doc__)
TIDAL_TOKEN = CONF.get("tiendas", {}).get("tidal_token", "CzET4vdadNUFQ5JU")   # el de la web de Tidal (público)
QOBUZ_APP = CONF.get("tiendas", {}).get("qobuz_app_id", "798273057")           # el de play.qobuz.com (público)
_qt = os.path.join(HERE, ".qobuz_token")
QOBUZ_TOKEN = open(_qt).read().strip().strip('"') if os.path.exists(_qt) else None
dz = Cache("deezer-cache.json")


def artistas(art):
    return {clave_artista(a) for a in re.split(r",\s*|\s+&\s+|\s+feat\.?\s+|\s+x\s+", art or "") if a.strip()}


def base_titulo(t):
    return re.sub(r"\W", "", re.split(r"\s+(?:feat\.?|ft\.?|with)\s+|\s*[\(\[]|\s+-\s+", t or "", flags=re.I)[0].lower())


# ---------- cada tienda: candidatos [(enlace, artistas, título completo, disco, duración s, isrc)] ----------
def en_deezer(principal, titulo_q):
    out = []
    for q in (f'artist:"{principal}" track:"{titulo_q}"', f"{principal} {titulo_q}"):   # la estricta a veces no ve nada
        for d in (pedir_json("https://api.deezer.com/search?limit=25&q=" + urllib.parse.quote(q), dz) or {}).get("data", []):
            out.append((d["link"], {d["artist"]["name"]}, d["title"], d.get("album", {}).get("title", ""), d.get("duration"), ""))
    return out


def en_tidal(principal, titulo_q):
    url = "https://api.tidal.com/v1/search/tracks?limit=25&countryCode=US&query=" + urllib.parse.quote(f"{principal} {titulo_q}")
    out = []
    for d in (pedir_json(url, cabeceras={"x-tidal-token": TIDAL_TOKEN}) or {}).get("items", []):
        completo = d["title"] + (f" ({d['version']})" if d.get("version") else "")   # «Lacrimosa (Drill Version)» ≠ el Réquiem
        nombres = {a["name"] for a in d.get("artists", [])} | {d["artist"]["name"]}
        out.append((f"https://tidal.com/track/{d['id']}", nombres, completo, d.get("album", {}).get("title", ""),
                    d.get("duration"), d.get("isrc", "")))
    return out


def en_apple(principal, titulo_q, japones, limite=50, solo_artista=False):
    out = []
    for pais in (["JP", "US"] if japones else ["US", "JP"]):
        for q in ([principal] if solo_artista else [f"{principal} {titulo_q}", titulo_q]):
            url = f"https://itunes.apple.com/search?entity=song&limit={limite}&country={pais}&term=" + urllib.parse.quote(q)
            for d in (pedir_json(url) or {}).get("results", []):
                nombres = set(re.split(r",\s*|\s+&\s+", d.get("artistName", ""))) | {d.get("artistName", "")}
                out.append((d["trackViewUrl"].split("&uo=")[0], nombres, d.get("trackName", ""), d.get("collectionName", ""),
                            (d.get("trackTimeMillis") or 0) / 1000, ""))
        if out:
            break
    return out


_qobuz_avisado = [False]
def en_qobuz(principal, titulo_q, limite=50, solo_artista=False):
    if not QOBUZ_TOKEN:
        return []
    out = []
    for q in ([principal] if solo_artista else [f"{principal} {titulo_q}", titulo_q]):
        url = f"https://www.qobuz.com/api.json/0.2/track/search?limit={limite}&query=" + urllib.parse.quote(q)
        r = pedir_json(url, cabeceras={"X-App-Id": QOBUZ_APP, "X-User-Auth-Token": QOBUZ_TOKEN})
        if r == {} and not _qobuz_avisado[0]:
            print("  ⚠ Qobuz no contesta a la búsqueda (¿token vencido? ver la ayuda)"); _qobuz_avisado[0] = True
        for d in (r or {}).get("tracks", {}).get("items", []):
            if d.get("streamable") is not True:
                continue   # sin derechos: Antra da «not found» (Mohamed Jamal, Bakugo x Royalty, 28 sep)
            principal_q = d.get("performer", {}).get("name", "")
            nombres = {principal_q, d.get("album", {}).get("artist", {}).get("name", "")}
            for p in d.get("performers", "").split(" - "):   # «Nombre, MainArtist - Nombre, Composer…»: el nombre y sus roles
                nombre, _, roles = p.partition(", ")
                if "Artist" in roles: nombres.add(nombre)
            completo = d["title"] + (f" ({d['version']})" if d.get("version") else "")
            out.append((f"https://open.qobuz.com/track/{d['id']}", nombres - {""}, completo, d.get("album", {}).get("title", ""),
                        d.get("duration"), d.get("isrc", "")))
        if out:
            break
    return out


TIENDAS = {"deezer": en_deezer, "tidal": en_tidal, "apple": en_apple, "qobuz": en_qobuz}


def elegir(cands, art, tit, seg, tolerancia=None, por_comienzo=False):
    """El mejor candidato que cumple la regla, o None. (diferencia de duración, candidato)."""
    arts, kt, principal = artistas(art), clave_titulo(tit), re.split(r",\s*", art)[0]
    base = base_titulo(tit)
    buenos = []
    for c in cands:
        _, nombres, titulo, _, dura, _ = c
        ns = {clave_artista(n) for n in nombres}
        if not (ns & arts or any(clave_artista(principal) in n for n in ns if n)):
            continue
        if por_comienzo:
            if not base or re.sub(r"\W", "", titulo.lower())[:len(base)] != base: continue
        elif kt != clave_titulo(titulo):
            continue
        dif = abs((dura or 0) - seg) if seg else None
        if seg and dif > (tolerancia if tolerancia is not None else max(3, seg * 0.01)):
            continue
        buenos.append((dif if dif is not None else 0, c))
    return min(buenos, key=lambda x: x[0]) if buenos else None


def buscar_todo(orden):
    filas = a_conseguir()
    print(f"{len(filas)} canciones a conseguir; se buscan en: {', '.join(orden)}" + ("" if QOBUZ_TOKEN or "qobuz" not in orden else " (Qobuz sin token: se salta)"))
    res = []
    for i, (origen, art, tit, alb, sid) in enumerate(filas, 1):
        seg = duracion_spotify(sid) if sid else None
        principal = re.split(r",\s*", art)[0]
        titulo_q = re.sub(r"\s*[\(\[].*?[\)\]]", "", tit).split(" - ")[0]
        japones = bool(re.search(r"[぀-ヿ一-鿿]", art + tit + alb))
        hallado, tienda, estado = None, "", "no está"
        for t in orden:
            cands = TIENDAS[t](principal, titulo_q, japones) if t == "apple" else TIENDAS[t](principal, titulo_q)
            e = elegir(cands, art, tit, seg)
            if e and seg:
                hallado, tienda, estado = e, t, "ok"
                break
            if e and not hallado:   # sin duración de Spotify: la de la PRIMERA tienda que la tiene, a revisar
                hallado, tienda, estado = e, t, "revisar (sin duración de Spotify)"
                continue
            elif seg and t in ("apple", "qobuz"):   # 2ª pasada: título escrito distinto, misma duración ±1 s
                extra = (en_apple(principal, titulo_q, japones, 200, solo_artista=True) if t == "apple"
                         else en_qobuz(principal, titulo_q, 200, solo_artista=True))
                e = elegir(cands + extra, art, tit, seg, tolerancia=1, por_comienzo=True)
                if e and not hallado:
                    hallado, tienda, estado = e, t, f"revisar (título distinto en {t}; misma duración)"
        if hallado:
            dif, (enlace, nombres, titulo, disco, dura, isrc) = hallado
            res.append((estado, tienda, origen, art, tit, alb, sid, enlace, ", ".join(sorted(n for n in nombres if n)), titulo, disco, dura, seg, isrc))
        else:
            res.append(("no está", "", origen, art, tit, alb, sid, "", "", "", "", "", seg, ""))
        print(f"  {i}/{len(filas)} {res[-1][0][:8]:8} {res[-1][1]:7} {art[:25]} — {tit[:40]}", flush=True)
    dz.guardar()
    ok = [r for r in res if r[0] == "ok"]; rev = [r for r in res if r[0].startswith("revisar")]; no = [r for r in res if r[0] == "no está"]
    os.makedirs(LISTAS, exist_ok=True)
    base = os.path.join(LISTAS, f"FUENTES-{len(ok) + len(rev)}")
    open(base + ".txt", "w").write("".join(r[7] + "\n" for r in ok + rev))
    with open(base + " (con nombres).tsv", "w", encoding="utf-8") as fh:
        fh.write("estado\ttienda\torigen\tartista\ttítulo\tálbum\tspotify_id\tenlace\tartista tienda\ttítulo tienda\tálbum tienda\t"
                 "dura tienda\tdura Spotify\tisrc\n")
        for r in ok + rev + no: fh.write("\t".join(str(x if x is not None else "") for x in r) + "\n")
    print(f"\n{len(res)} canciones: {len(ok)} encontradas (misma duración), {len(rev)} a revisar, {len(no)} no están en ninguna")
    print(f"→ {base}.txt  (pegar los enlaces en Antra)\n→ {base} (con nombres).tsv")


def poner_spotify_id(carpeta, execute):
    d = carpeta if os.path.isabs(carpeta) else os.path.join(ROOT, carpeta)
    por_isrc, por_titulo = {}, {}
    for p in sorted(glob.glob(os.path.join(glob.escape(LISTAS), "FUENTES-* (con nombres).tsv"))):
        for r in csv.DictReader(open(p, encoding="utf-8"), delimiter="\t"):
            if not (r.get("spotify_id") and r.get("enlace")): continue
            isrc = (r.get("isrc") or "").upper()
            if not isrc and "deezer.com" in r["enlace"]:   # Deezer no da el ISRC en la búsqueda: se pide la canción
                isrc = ((pedir_json("https://api.deezer.com/track/" + r["enlace"].rsplit("/", 1)[-1], dz) or {}).get("isrc") or "").upper()
            if isrc: por_isrc[isrc] = (r["spotify_id"], r["artista"], r["título"])
            if r.get("título tienda"): por_titulo[clave_titulo(r["título tienda"])] = (r["spotify_id"], r["artista"], r["título"])
    hechos, sin = 0, []
    for dd, _, fs in os.walk(d):
        for f in sorted(fs):
            if not es_audio(f): continue
            a = abrir(os.path.join(dd, f))
            if (a.get("spotify_id") or [""])[0]: continue
            m = por_isrc.get((a.get("isrc") or [""])[0].upper()) or por_titulo.get(clave_titulo((a.get("title") or [""])[0]))
            if not m: sin.append(f); continue
            print(f"  {m[0]}  {f[:70]}  ←  {m[1]} — {m[2]}")
            if execute:
                a["spotify_id"] = [m[0]]; a.save()
            hechos += 1
    dz.guardar()
    print(f"\n{hechos} con spotify_id{'' if execute else ' (SIMULACIÓN, usa --execute)'} | sin pareja: {len(sin)}")
    for f in sin: print("   sin pareja:", f)


if __name__ == "__main__":
    if "--poner-spotify-id" in args:
        poner_spotify_id(args[args.index("--poner-spotify-id") + 1], "--execute" in args)
    else:
        orden = args[args.index("--en") + 1].split(",") if "--en" in args else list(TIENDAS)
        malas = [t for t in orden if t not in TIENDAS]
        if malas: sys.exit(f"tiendas desconocidas: {malas} (son: {', '.join(TIENDAS)})")
        buscar_todo(orden)
