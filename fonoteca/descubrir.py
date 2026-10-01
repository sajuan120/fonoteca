#!/usr/bin/env python3
"""«Descubrir» semanal — 28 sep 2026 (el filtro lo hace ListenBrainz). Música NUEVA de verdad, como playlist.

Por usuario (USUARIOS, abajo):
 1. Recomendaciones de ListenBrainz (API cf/recommendation, 1000; se recalculan los lunes).
 2. Nombres, ISRC y duración (API metadata/recording, lotes de 100).
 3. Solo lo NUEVO DE VERDAD — fuera: lo que está en la biblioteca (Navidrome, incluida _Prueba), lo que escuchó alguna
    vez en Spotify (su historial) y lo ya sugerido antes (descubrir-historial.json: NUNCA se repite, aunque se haya
    borrado por no escucharse). ListenBrainz marca «no escuchada» por ID exacto de grabación, por eso filtramos por
    artista + título (28 sep: de 1000, 569 ya estaban, 334 escuchadas en Spotify, 97 nuevas).
 4. Las N de más puntaje → Deezer por ISRC (exacto; si no, artista + título + duración ±3 s; solo si es «readable»).
 5. Octo-Fiesta las baja (usuario «robot» de Navidrome, contraseña en ~/navidrome/.robot) a _Prueba/ en MP3 128 →
    género «Prueba» → el embudo de siempre (prueba.py: 3+ escuchas en 4 semanas → FLAC; 6 sin escucharse → se borra).
 6. Playlist «Descubrir» (_Playlists/Descubrir.m3u) = las de ESTA semana, a nombre del usuario y privada. La 1ª vez
    se para Navidrome unos segundos para asignarla; después se mantiene sola.
Aviso en el escritorio; log en logs/descubrir-*.json. Sin --execute solo muestra.  Uso: descubrir.py [--execute] [--n 20] [--usuario <Navidrome>]
Timer: musica-descubrir (lunes 10:00).
"""
import datetime, glob, hashlib, json, os, secrets, sqlite3, subprocess, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comun import ROOT, HERE, LOGS, clave_artista, clave_titulo, CONF, NAVIDROME, NAVIDROME_DB
from red import pedir_json

# usuario de Navidrome → su cuenta de ListenBrainz, su carpeta de historial (usuarios/<…>), el archivo .m3u y el nombre
# visible: [[descubrir]] en config.toml (privado)
USUARIOS = {u["navidrome"]: {"lb": u["listenbrainz"], "historial": u["historial"], "archivo": u["archivo"],
                             "playlist": u.get("playlist", "Descubrir")} for u in CONF.get("descubrir", [])}
N_DEFECTO = 20
DB = NAVIDROME_DB
COMPOSE = os.path.join(NAVIDROME, "docker-compose.yml")
OCTO = CONF.get("octo_fiesta", {}).get("url", "http://127.0.0.1:5274")
ROBOT = CONF.get("octo_fiesta", {}).get("usuario_robot", "robot")   # usuario de Navidrome (no admin) que pide a Octo-Fiesta
PRUEBA = os.path.join(ROOT, "_Prueba")
MAPPINGS = os.path.join(PRUEBA, ".mappings.json")
HISTORIAL = os.path.join(HERE, "descubrir-historial.json")


def get_json(url, data=None, timeout=60):
    """GET/POST JSON. Deezer limita ~50 consultas / 5 s y responde {"error": {"code": 4}} («Quota limit exceeded»):
    se espera y se reintenta (antes eso contaba como «no está en Deezer»: XXX. de Kendrick, 28 sep)."""
    # red.py: el ritmo de cada servicio y los reintentos; None si no hubo respuesta (antes una falla de red tumbaba el
    # «Descubrir» semanal entero)
    return pedir_json(url, datos=json.dumps(data).encode() if data is not None else None,
                      cabeceras={"Content-Type": "application/json"} if data is not None else None, timeout=timeout)


def partir(art):
    """Artistas de un crédito. Navidrome junta varios con « • » («Kavinsky • Lovefoxxx»): sin partir por eso, una
    canción que YA estaba con invitado pasaba por nueva (28 sep, Nightcall)."""
    for sep in (" • ", " · ", "; ", " feat. ", " featuring ", " ft. ", " ft ", " & ", " x ", " with "):
        art = art.replace(sep, ",")
    return [a.strip() for a in art.split(",") if a.strip()]


def claves(art, tit):
    arts = partir(art)
    return {(clave_artista(a), clave_titulo(tit)) for a in arts} | {(clave_artista(art), clave_titulo(tit))}


def conocidas(carpeta_hist):
    """Claves (artista, título) de la biblioteca (Navidrome, incluida _Prueba) + el historial de Spotify del usuario."""
    k = set()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    for t, a in con.execute("select title, artist from media_file where missing=0"):
        k |= claves(a or "", t or "")
    for f in glob.glob(os.path.join(HERE, "usuarios", carpeta_hist, "Spotify Extended Streaming History", "*.json")):
        for e in json.load(open(f, encoding="utf-8")):
            if e.get("master_metadata_track_name"):
                k |= claves(e.get("master_metadata_album_artist_name") or "", e["master_metadata_track_name"])
    return k


def ids_biblioteca():
    """ISRC y MBID de grabación de la biblioteca (Navidrome, incluida _Prueba). 30 sep: por nombre se colaban las que ya
    teníamos con otro título («XXX.» = «XXX. FEAT. U2.», «LOYALTY.»); el ISRC/MBID de LB las atrapa."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    isrcs = {(v or "").upper() for (v,) in con.execute(
        "select j.value ->> 'value' from media_file, json_each(json_extract(tags, '$.isrc')) j where missing=0")}
    mbids = {m for (m,) in con.execute("select mbz_recording_id from media_file where missing=0 and mbz_recording_id!=''")}
    return isrcs - {""}, mbids


def artistas_clave(art):
    return {clave_artista(a) for a in partir(art)} | {clave_artista(art)}


def deezer_de(rec):
    """ID de Deezer de la grabación: por ISRC (exacto); si no hay ISRC (28 sep: varias de Milo j, Rodrigo Amarante),
    por nombre — primero la búsqueda avanzada y si no la simple «artista título» (la avanzada se confunde con la «ñ»:
    «Milo j – Niño» devolvía «DJ Kay Slay»). Por nombre exige: mismo artista, título igual o que empieza igual (Deezer
    agrega «(Narcos Theme)») y duración a ±3 s de la de MusicBrainz. None si no está."""
    dur = (rec.get("length") or 0) / 1000
    for isrc in rec.get("isrcs") or []:
        try:
            d = get_json(f"https://api.deezer.com/track/isrc:{isrc}", timeout=20) or {}
        except Exception:
            continue
        if d.get("id") and d.get("readable", True) and (not dur or abs(d.get("duration", 0) - dur) <= 3):
            return str(d["id"])
    arts, tit = artistas_clave(rec["artista"]), clave_titulo(rec["titulo"])
    for q in (f'artist:"{rec["artista"]}" track:"{rec["titulo"]}"', f'{rec["artista"]} {rec["titulo"]}'):
        try:
            r = get_json("https://api.deezer.com/search?limit=15&q=" + urllib.parse.quote(q), timeout=20) or {}
        except Exception:
            continue
        buenos = [x for x in r.get("data") or []
                  if x.get("readable", True) and clave_artista(x["artist"]["name"]) in arts
                  and (clave_titulo(x["title"]) == tit or clave_titulo(x["title"]).startswith(tit))
                  and (not dur or abs(x.get("duration", 0) - dur) <= 3)]
        if buenos:
            return str(min(buenos, key=lambda x: abs(x.get("duration", 0) - dur))["id"])
    return None


def pedir_a_octo(dz, pw):
    """Octo-Fiesta la baja (y la sirve): se lee el stream entero. Devuelve la ruta en el disco o None."""
    s = secrets.token_hex(6)
    q = urllib.parse.urlencode(dict(id=f"ext-deezer-song-{dz}", u=ROBOT, t=hashlib.md5((pw + s).encode()).hexdigest(),
                                    s=s, v="1.16.1", c="descubrir"))
    try:
        with urllib.request.urlopen(f"{OCTO}/rest/stream?{q}", timeout=180) as r:
            if "json" in (r.headers.get("Content-Type") or "") or "xml" in (r.headers.get("Content-Type") or ""):
                return None   # respuesta de error de Subsonic en vez de audio
            while r.read(1 << 16):
                pass
    except Exception:
        return None
    for _ in range(20):   # Octo-Fiesta anota la descarga en .mappings.json
        try:
            m = json.load(open(MAPPINGS, encoding="utf-8")).get(f"deezer:{dz}")
        except Exception:
            m = None
        if m and m.get("LocalPath"):
            p = m["LocalPath"].replace("/app/downloads", PRUEBA, 1)
            if os.path.exists(p):
                return p
        time.sleep(1)
    return None


def asignar_playlist(nombre_m3u, usuario):
    """La playlist importada del .m3u queda a nombre del usuario y privada (parando Navidrome unos segundos)."""
    ruta = f"/music/_Playlists/{nombre_m3u}"
    for _ in range(30):   # esperar a que Navidrome la importe (vigilante de archivos)
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        fila = con.execute("select p.id, u.user_name, p.public from playlist p join user u on u.id=p.owner_id where p.path=?", (ruta,)).fetchone()
        con.close()
        if fila:
            break
        time.sleep(2)
    else:
        return "Navidrome todavía no la importó (se asigna en la próxima corrida)"
    if fila[1] == usuario and not fila[2]:
        return f"ya es de {usuario} y privada"
    subprocess.run(["docker", "compose", "-f", COMPOSE, "stop"], check=True, capture_output=True)
    try:
        w = sqlite3.connect(DB)
        with w:
            w.execute("update playlist set owner_id=(select id from user where user_name=?), public=0 where path=?", (usuario, ruta))
    finally:
        subprocess.run(["docker", "compose", "-f", COMPOSE, "up", "-d"], check=True, capture_output=True)
    return f"asignada a {usuario} y privada (era de {fila[1]})"


def main():
    args = sys.argv[1:]
    execute = "--execute" in args
    n = int(args[args.index("--n") + 1]) if "--n" in args else N_DEFECTO
    hist = json.load(open(HISTORIAL, encoding="utf-8")) if os.path.exists(HISTORIAL) else {}
    pw = open(os.path.join(NAVIDROME, ".robot")).read().strip()
    log = {"fecha": datetime.date.today().isoformat(), "usuarios": {}}
    solo = args[args.index("--usuario") + 1] if "--usuario" in args else None   # uno solo (p. ej. alguien nuevo)
    for usuario, cfg in USUARIOS.items():
        if solo and usuario != solo:
            continue
        h = hist.setdefault(usuario, {})
        ya = {tuple(k) for x in h.values() for k in x.get("claves", [])}
        d = get_json(f"https://api.listenbrainz.org/1/cf/recommendation/user/{cfg['lb']}/recording?count=1000")
        if not d or not d.get("payload"):
            print(f"{usuario}: ListenBrainz no respondió o todavía no tiene recomendaciones; queda para la próxima semana.")
            continue
        d = d["payload"]
        recs = d["mbids"]
        meta, ids = {}, [r["recording_mbid"] for r in recs]
        for i in range(0, len(ids), 100):
            meta.update(get_json("https://api.listenbrainz.org/1/metadata/recording/", {"recording_mbids": ids[i:i + 100], "inc": "artist"}) or {})
        conoc = conocidas(cfg["historial"])
        isrcs_bib, mbids_bib = ids_biblioteca()
        nuevas = []
        for r in recs:
            x = meta.get(r["recording_mbid"], {})
            rec = dict(x.get("recording") or {}, mbid=r["recording_mbid"], score=r["score"],
                       artista=(x.get("artist") or {}).get("name", ""), titulo=(x.get("recording") or {}).get("name", ""))
            if not rec["titulo"] or r["recording_mbid"] in h:
                continue
            k = claves(rec["artista"], rec["titulo"])
            if k & conoc or k & ya:
                continue
            if r["recording_mbid"] in mbids_bib or {i.upper() for i in rec.get("isrcs") or []} & isrcs_bib:
                continue
            nuevas.append(rec)
        print(f"{usuario}: {len(recs)} recomendaciones (del {datetime.datetime.fromtimestamp(d['last_updated']):%Y-%m-%d}) "
              f"→ {len(nuevas)} nuevas de verdad; se piden {min(n, len(nuevas))}")
        elegidas, sin_deezer = [], []
        for rec in nuevas:
            if len(elegidas) >= n:
                break
            dz = deezer_de(rec)
            (elegidas if dz else sin_deezer).append(dict(rec, deezer=dz))
            time.sleep(0.2)
        for e in elegidas:
            print(f"  {e['score']:.2f}  {e['artista'][:30]:30} – {e['titulo'][:40]:40}  deezer {e['deezer']}")
        for e in sin_deezer:
            print(f"  (no está en Deezer) {e['artista']} – {e['titulo']}")
        if not execute:
            continue
        hoy = datetime.date.today().isoformat()
        bajadas = []
        for e in elegidas:
            p = pedir_a_octo(e["deezer"], pw)
            h[e["mbid"]] = {"fecha": hoy, "artista": e["artista"], "titulo": e["titulo"], "deezer": e["deezer"],
                            "claves": [list(k) for k in claves(e["artista"], e["titulo"])],
                            "ruta": os.path.relpath(p, ROOT) if p else None}
            if p:
                bajadas.append(p)
            print(f"  {'✓ bajada' if p else '✗ NO se pudo bajar'}: {e['artista']} – {e['titulo']}")
        for e in sin_deezer:   # tampoco se vuelven a intentar
            h[e["mbid"]] = {"fecha": hoy, "artista": e["artista"], "titulo": e["titulo"], "deezer": None,
                            "claves": [list(k) for k in claves(e["artista"], e["titulo"])], "ruta": None}
        json.dump(hist, open(HISTORIAL, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        asignacion = "sin cambios (nada bajado)"
        if bajadas:
            m3u = os.path.join(ROOT, "_Playlists", f"{cfg['archivo']}.m3u")
            lineas = ["#EXTM3U", f"#PLAYLIST:{cfg['playlist']}"] + [os.path.relpath(p, os.path.dirname(m3u)) for p in bajadas]
            open(m3u, "w", encoding="utf-8").write("\n".join(lineas) + "\n")
            time.sleep(65)   # el género «Prueba» (prueba.py marcar) solo toca archivos con más de 60 s
            subprocess.run([sys.executable, os.path.join(HERE, "prueba.py"), "marcar"], check=False)
            asignacion = asignar_playlist(f"{cfg['archivo']}.m3u", usuario)
            print("  playlist:", asignacion)
            subprocess.run(["notify-send", "-a", "Música", "-i", "folder-music", "-t", "0",
                            f"🎧 {cfg['playlist']} de {usuario}: {len(bajadas)} canciones nuevas",
                            "Recomendadas por ListenBrainz, que nunca escuchaste.\nEstán en la playlist «"
                            f"{cfg['playlist']}» (género Prueba). Lo que escuches 3+ veces pasa a FLAC."], check=False)
        log["usuarios"][usuario] = {"nuevas": len(nuevas), "pedidas": len(elegidas), "bajadas": len(bajadas),
                                    "sin_deezer": len(sin_deezer), "playlist": asignacion}
    if execute:
        lp = os.path.join(LOGS, f"descubrir-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
        json.dump(log, open(lp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("HECHO. Log:", lp)
    else:
        print("SIMULACIÓN: no se bajó nada. Usa --execute.")


if __name__ == "__main__":
    main()
