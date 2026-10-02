#!/usr/bin/env python3
"""CARÁTULAS, todo en un comando (30 sep 2026: antes caratulas.py, caratulas_mejorar.py, caratulas_ia.py y un puntual).

  caratulas.py [faltantes] [--execute] | --revert <log>
      Las que NO tienen imagen (ni embebida ni cover.jpg/folder.jpg): 1) Deezer por ISRC (cover_xl, 1000 px) si el disco
      se llama igual; 2) iTunes (1200 px). Es el paso 7b del procesado.
  caratulas.py mezcladas [--execute] | mezcladas --revert <log>
      Discos con imágenes DISTINTAS entre sus canciones (auditoría: caratula_mezclada): 1) si todas son la misma imagen
      (huella dHash 16x16 a ≤ 20 bits) → la más grande; 2) si no, la de Deezer del disco con el MISMO nombre y artista
      (no por código de barras: a veces apunta a otro disco); 3) si no, la de la mayoría de sus canciones.
  caratulas.py mejorar [--execute] [--umbral N] | mejorar --revert <log>
      Chicas (<500 px) o no cuadradas (auditoría: caratula_chica / caratula_rara) → la MISMA imagen en grande (Deezer,
      iTunes, Cover Art Archive): solo si su huella coincide (≤ UMBRAL bits) y es cuadrada de ≥ 1000 px (o más grande que
      la actual si nada llega a 1000), así no cambia la edición. Las de otra imagen quedan en el log para decidir a mano.
      Excepciones revisadas a ojo: decisiones/caratulas-no-tocar.txt (nunca) y caratulas-elegidas.tsv (disco → url).
  caratulas.py ia preparar | ia aplicar NN=2 NN=3 … [--execute]
      Las que no tienen versión grande en internet → agrandadas con IA (Real-ESRGAN, el motor de Upscayl), elegidas a ojo
      disco por disco: «preparar» arma la comparación (1 original · 2 IA foto · 3 IA dibujo) en rutas.portadas_ia, con
      «ver todas.html»; «aplicar» pone la elegida en todas las canciones del disco. Lección (27 sep, 6 portadas): texto y
      anime mejoran mucho, las caras de foto quedan «plásticas» y la letra muy chica se inventa → por eso se elige a ojo.
Sin --execute: simulación. Respaldo de cada imagen cambiada en respaldos/caratulas-*-<fecha>/ y log para --revert.
"""
import datetime, hashlib, html, io, json, os, re, shutil, subprocess, sys, tempfile, urllib.parse
from mutagen.flac import Picture
from PIL import Image, ImageDraw, ImageFont
from audio import abrir, audios, es_audio
from comun import (ROOT, RESPALDOS, PORTADAS_IA, antra_abierto, cache_path, decision, es_de_album, log_path, plan_path,
                   plano, sin_parentesis, leer_json, guardar_json, cerrojo)
from red import Cache, pedir_bytes, pedir_json

dz = Cache("deezer-cache.json")   # red.py: la caché de Deezer que comparten varios scripts
fetch = pedir_bytes


def jget(url):
    """JSON (Deezer, iTunes) con la caché de Deezer; {} si no existe o no hubo respuesta (la falla de red NO se guarda)."""
    return pedir_json(url, dz) or {}


def dhash(img):
    """Huella visual de 256 bits (16x16): la misma portada reescalada o recomprimida queda a 0-8 bits; otra, a más de 60."""
    g = img.convert("L").resize((17, 16), Image.LANCZOS)
    px = list(g.get_flattened_data() if hasattr(g, "get_flattened_data") else g.getdata())   # getdata se va en Pillow 14
    return [px[r * 17 + c] > px[r * 17 + c + 1] for r in range(16) for c in range(16)]


def dist(a, b):
    return sum(x != y for x, y in zip(a, b))


def canciones(d):
    return sorted(os.path.join(d, f) for f in os.listdir(d) if es_audio(f))


def poner(f, data, mime=None, tam=None):
    """Deja `data` como ÚNICA carátula (portada) de la canción."""
    pic = Picture(); pic.type = 3; pic.data = data
    pic.mime = mime or ("image/png" if data[:4] == b"\x89PNG" else "image/jpeg")
    if tam is None:
        try: tam = Image.open(io.BytesIO(data)).size
        except Exception: tam = None
    if tam: pic.width, pic.height = tam; pic.depth = 24
    t = abrir(f); t.clear_pictures(); t.add_picture(pic); t.save()


def de_la_auditoria(tsv):
    """Primera columna de planes/auditoria-<tsv> (correr antes auditoria.py)."""
    p = plan_path(tsv)
    return [l.split("\t")[0] for l in open(p, encoding="utf-8").read().splitlines()[1:] if l.strip()] if os.path.exists(p) else []


# ---------------------------------------------------------------- faltantes (paso 7b del procesado)
def faltantes(execute):
    def find(t):
        g = lambda k: (t.get(k) or [""])[0]
        if g("isrc"):
            alb = jget(f"https://api.deezer.com/track/isrc:{g('isrc')}").get("album", {})
            if alb.get("cover_xl") and sin_parentesis(alb.get("title")) == sin_parentesis(g("album")): return alb["cover_xl"], "deezer"
        q = urllib.parse.urlencode({"term": f"{g('albumartist') or g('artist')} {g('album')}", "entity": "album", "limit": 10})
        for r in jget(f"https://itunes.apple.com/search?{q}").get("results", []):
            if sin_parentesis(r.get("collectionName")) == sin_parentesis(g("album")) and r.get("artworkUrl100"):
                return r["artworkUrl100"].replace("100x100bb", "1200x1200bb"), "itunes"
        return None, None

    seen, todo = set(), []
    for f in sorted(audios(ROOT)):
        if not es_de_album(f) or os.stat(f).st_ino in seen: continue   # solo Artista/Álbum (nunca una descarga en curso)
        seen.add(os.stat(f).st_ino)
        d = os.path.dirname(f)
        if any(os.path.exists(os.path.join(d, c)) for c in ("cover.jpg", "folder.jpg", "cover.png", "folder.png")): continue
        if not abrir(f).pictures: todo.append(f)
    agregadas, fallo, cache_img = [], [], {}
    for f in todo:
        t = abrir(f); url, src = find(t)
        img = cache_img.get(url) or (fetch(url) if url else None)
        if not img or len(img) < 5000: fallo.append(os.path.relpath(f, ROOT)); continue
        cache_img[url] = img
        print(f"  {src:6} {len(img)//1024:5} KB  {os.path.relpath(f, ROOT)}")
        if execute:
            p = Picture(); p.type = 3; p.mime = "image/png" if img[:4] == b"\x89PNG" else "image/jpeg"; p.data = img
            t.add_picture(p); t.save()
        agregadas.append(f)
    dz.guardar()
    out = log_path(f"caratulas-{'log' if execute else 'simulacion'}")
    json.dump(dict(agregadas=agregadas, fallo=fallo), open(out, "w"), ensure_ascii=False, indent=1)
    print(f"sin carátula: {len(todo)} | encontradas: {len(agregadas)} | sin fuente: {len(fallo)}")
    for x in fallo: print("   ✗", x)
    print(("ESCRITO. " if execute else "SIMULACIÓN, no se escribió nada. ") + f"Log: {out}")


def faltantes_revert(lg):
    log = json.load(open(lg))
    for p in log["agregadas"]:
        t = abrir(p); t.clear_pictures(); t.save()
    print(f"quitadas {len(log['agregadas'])}")


# ---------------------------------------------------------------- mezcladas (antes un puntual, 28 sep)
def mezcladas(execute):
    def deezer(aa, album):
        q = urllib.parse.quote(f'artist:"{aa}" album:"{album}"')
        for a in jget(f"https://api.deezer.com/search/album?limit=25&q={q}").get("data", []):
            if plano(a["title"]) == plano(album) and plano(a["artist"]["name"]) == plano(aa) and a.get("cover_xl"):
                return fetch(a["cover_xl"]), a["id"]
        return None, None
    discos = de_la_auditoria("auditoria-caratula_mezclada.tsv")
    if execute and antra_abierto(): sys.exit("Antra está abierto: ciérralo y reintenta.")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S"); resp = os.path.join(RESPALDOS, f"caratulas-mezcladas-{stamp}")
    log = []
    for d in discos:
        if not os.path.isdir(os.path.join(ROOT, d)): continue
        fs = canciones(os.path.join(ROOT, d))
        imgs = {}   # md5 → {data, mime, px, fs}
        for f in fs:
            pics = [p for p in abrir(f).pictures if p.type == 3] or abrir(f).pictures
            if not pics: continue
            p = pics[0]; h = hashlib.md5(p.data).hexdigest()
            imgs.setdefault(h, {"data": p.data, "mime": p.mime, "px": Image.open(io.BytesIO(p.data)).size, "fs": []})["fs"].append(f)
        if len(imgs) < 2: continue
        hs = {h: dhash(Image.open(io.BytesIO(v["data"]))) for h, v in imgs.items()}
        t0 = abrir(fs[0]); aa, album = (t0.get("albumartist") or t0.get("artist"))[0], t0["album"][0]
        if all(dist(hs[a], hs[b]) <= 20 for a in hs for b in hs):
            h = max(imgs, key=lambda h: imgs[h]["px"][0] * imgs[h]["px"][1]); nueva, mime, por = imgs[h]["data"], imgs[h]["mime"], "misma imagen → la más grande"
        else:
            data, did = deezer(aa, album)
            if data:
                nueva, mime, por = data, "image/jpeg", f"Deezer {did} (mismo nombre)"
            else:
                h = max(imgs, key=lambda h: (len(imgs[h]["fs"]), imgs[h]["px"][0] * imgs[h]["px"][1]))
                nueva, mime, por = imgs[h]["data"], imgs[h]["mime"], "la de la mayoría"
        px = Image.open(io.BytesIO(nueva)).size
        cambian = [f for f in fs if not any(f in v["fs"] and v["data"] == nueva for v in imgs.values())]
        print(f"   {d[:95]}\n      {len(imgs)} imágenes → {por} ({px[0]}x{px[1]}); cambian {len(cambian)} de {len(fs)}")
        if execute:
            os.makedirs(resp, exist_ok=True)
            for f in cambian:
                t = abrir(f); old = ([p for p in t.pictures if p.type == 3] or t.pictures or [None])[0]
                r = os.path.join(resp, hashlib.md5(f.encode()).hexdigest() + ".img")
                if old: open(r, "wb").write(old.data)
                log.append({"path": os.path.relpath(f, ROOT), "respaldo": r, "mime": old.mime if old else "image/jpeg"})
                poner(f, nueva, mime, px)
    dz.guardar()
    if not execute: sys.exit(f"\nSimulación: {len(discos)} discos. Usa --execute.")
    lp = log_path("caratulas-mezcladas"); json.dump(log, open(lp, "w"), ensure_ascii=False, indent=1)
    print(f"HECHO: {len(log)} canciones. Log (mezcladas --revert): {lp}")


def mezcladas_revert(lg):
    log = json.load(open(lg))
    for x in log:
        poner(os.path.join(ROOT, x["path"]), open(x["respaldo"], "rb").read(), x["mime"])
    print(f"revertidas {len(log)}")


# ---------------------------------------------------------------- mejorar (chicas o raras → la misma en grande)
def mejorar(execute, umbral):
    hcp = cache_path("caratulas-huellas.json")
    huellas = leer_json(hcp, {})

    def candidatos(fs):
        t = abrir(fs[0]); g = lambda k: (t.get(k) or [""])[0]
        album, artista = g("album"), g("albumartist") or g("artist")
        urls = []
        for f in fs[:3]:   # Deezer por ISRC: el disco donde está la canción (con 3 basta para hallar el disco)
            isrc = (abrir(f).get("isrc") or [""])[0]
            if not isrc: continue
            a = jget(f"https://api.deezer.com/track/isrc:{isrc}").get("album", {})
            if a.get("cover_xl") and sin_parentesis(a.get("title")) == sin_parentesis(album): urls.append(("deezer", a["cover_xl"]))
        q = urllib.parse.quote(f'artist:"{artista}" album:"{album}"')
        for a in (jget(f"https://api.deezer.com/search/album?q={q}").get("data") or [])[:10]:
            if a.get("cover_xl") and sin_parentesis(a.get("title")) == sin_parentesis(album): urls.append(("deezer", a["cover_xl"]))
        q = urllib.parse.urlencode({"term": f"{artista} {album}", "entity": "album", "limit": 10})
        for r in jget(f"https://itunes.apple.com/search?{q}").get("results", []):
            if sin_parentesis(r.get("collectionName")) == sin_parentesis(album) and r.get("artworkUrl100"):
                urls.append(("itunes", r["artworkUrl100"].replace("100x100bb", "1200x1200bb")))
        if g("musicbrainz_albumid"):
            urls.append(("caa", f"https://coverartarchive.org/release/{g('musicbrainz_albumid')}/front-1200"))
        vistos, out = set(), []
        for u in urls:
            if u[1] not in vistos: vistos.add(u[1]); out.append(u)
        return out

    discos = []
    for d in de_la_auditoria("auditoria-caratula_chica.tsv") + [os.path.dirname(c) for c in de_la_auditoria("auditoria-caratula_rara.tsv")]:
        if d and d not in discos and os.path.isdir(os.path.join(ROOT, d)): discos.append(d)
    _nt = decision("caratulas-no-tocar.txt")   # revisados a ojo: la «misma» imagen era de otra edición (27 sep)
    no_tocar = {l.strip() for l in open(_nt, encoding="utf-8") if l.strip() and not l.startswith("#")} if os.path.exists(_nt) else set()
    discos = [d for d in discos if d not in no_tocar]
    _el = decision("caratulas-elegidas.tsv")   # elegidas a ojo: misma portada con otro color/recorte (27 sep)
    elegidas = dict(l.rstrip("\n").split("\t")[:2] for l in open(_el, encoding="utf-8") if l.strip() and not l.startswith("#")) \
        if os.path.exists(_el) else {}
    print(f"{len(discos)} discos a revisar ({len(no_tocar)} en caratulas-no-tocar.txt)", flush=True)
    if execute and antra_abierto(): sys.exit("Antra está abierto: ciérralo y reintenta.")

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    resp = os.path.join(RESPALDOS, f"caratulas-antes-{stamp}")
    cambiadas, otra, nada = [], [], []
    for i, d in enumerate(discos, 1):
        fs = canciones(os.path.join(ROOT, d))
        pics = abrir(fs[0]).pictures
        if not pics: nada.append({"disco": d, "motivo": "sin imagen"}); continue
        vieja = pics[0]
        try: iv = Image.open(io.BytesIO(vieja.data)); hv = dhash(iv); tam_v = iv.size
        except Exception: nada.append({"disco": d, "motivo": "imagen actual ilegible"}); continue
        mejor, alternativas = None, []
        if d in elegidas:
            url = elegidas[d]
            if url not in huellas:
                b = fetch(url)
                if b: im = Image.open(io.BytesIO(b)); im.load(); huellas[url] = [*im.size, "".join("1" if x else "0" for x in dhash(im))]
            if huellas.get(url):
                w, h, hh = huellas[url]
                mejor = {"fuente": "elegida", "url": url, "tam": f"{w}x{h}", "dist": dist(hv, [c == "1" for c in hh]), "_w": min(w, h), "_sq": w == h}
        for src, url in ([] if mejor else candidatos(fs)):
            if url not in huellas:   # huella de cada imagen en caché: la corrida de verdad no las vuelve a bajar
                b = fetch(url)
                if b is None: continue   # falla de red o 404: no se guarda
                try: im = Image.open(io.BytesIO(b)); im.load(); huellas[url] = [*im.size, "".join("1" if x else "0" for x in dhash(im))]
                except Exception: huellas[url] = None
                if len(b) < 5000: huellas[url] = None
            if not huellas[url]: continue
            w, h, hh = huellas[url]; dd = dist(hv, [c == "1" for c in hh])
            cand = {"fuente": src, "url": url, "tam": f"{w}x{h}", "dist": dd, "_w": min(w, h), "_sq": w == h}
            if dd <= umbral and cand["_sq"] and cand["_w"] > max(tam_v):
                if not mejor or cand["_w"] >= 1000 > mejor["_w"] or (cand["_w"] >= 1000) == (mejor["_w"] >= 1000) and dd < mejor["dist"]:
                    mejor = cand
            else: alternativas.append(cand)
            if mejor and mejor["_w"] >= 1000 and mejor["dist"] <= 8: break   # ya está: no bajar más imágenes
        limpio = lambda c: {k: v for k, v in c.items() if not k.startswith("_")}
        if mejor:
            cambiadas.append({"disco": d, "viejo": f"{tam_v[0]}x{tam_v[1]}", **limpio(mejor), "canciones": len(fs),
                              "mime_viejo": vieja.mime, "respaldo": os.path.join(resp, f"{i:04d}.img")})
            print(f"  ✅ {mejor['fuente']:6} {tam_v[0]}x{tam_v[1]} → {mejor['tam']} (dist {mejor['dist']})  {d}", flush=True)
            img = fetch(mejor["url"]) if execute else None
            if execute and img:
                os.makedirs(resp, exist_ok=True); open(cambiadas[-1]["respaldo"], "wb").write(vieja.data)
                for f in fs:
                    poner(f, img)
            elif execute:
                cambiadas.pop(); nada.append({"disco": d, "motivo": "no se pudo bajar la imagen (red): reintentar"})
        elif alternativas:
            otra.append({"disco": d, "viejo": f"{tam_v[0]}x{tam_v[1]}", "opciones": [limpio(c) for c in alternativas]})
            print(f"  ~  otra imagen (mín. dist {min(c['dist'] for c in alternativas)})  {d}", flush=True)
        else:
            nada.append({"disco": d, "motivo": "ninguna fuente la tiene"}); print(f"  ✗  sin fuente  {d}", flush=True)
        if i % 25 == 0: dz.guardar(); guardar_json(hcp, huellas)
    dz.guardar(); guardar_json(hcp, huellas)
    out = log_path(f"caratulas-mejorar-{'log' if execute else 'simulacion'}")
    json.dump(dict(cambiadas=cambiadas, otra_imagen=otra, sin_fuente=nada), open(out, "w"), ensure_ascii=False, indent=1)
    print(f"\ndiscos {len(discos)} | misma imagen en grande: {len(cambiadas)} ({sum(x['canciones'] for x in cambiadas)} canciones)"
          f" | solo otra imagen: {len(otra)} | sin fuente: {len(nada)}")
    print(("ESCRITO. Respaldo: " + resp + ". " if execute else "SIMULACIÓN, no se escribió nada. ") + f"Log: {out}")


def mejorar_revert(lg):
    log = json.load(open(lg))
    for x in log["cambiadas"]:
        for f in canciones(os.path.join(ROOT, x["disco"])):
            poner(f, open(x["respaldo"], "rb").read(), x["mime_viejo"])
    print(f"devueltas {len(log['cambiadas'])}")


# ---------------------------------------------------------------- ia (agrandar con Real-ESRGAN, elegidas a ojo)
SALIDA = PORTADAS_IA   # config.toml: rutas.portadas_ia
MOTOR = "/usr/share/upscayl/bin/upscayl-bin"
MODELOS = "/usr/share/upscayl/models"
VERSIONES = {2: ("upscayl-standard-4x", "IA foto"), 3: ("digital-art-4x", "IA dibujo")}
LADO = 1200      # tamaño final de la carátula (Deezer da 1000, iTunes 1200)
PANEL = 800      # tamaño de cada panel en la imagen de comparación
FUENTE = "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"


def ia_discos():
    lineas = open(plan_path("auditoria-caratula_chica.tsv"), encoding="utf-8").read().splitlines()[1:]
    return [l.split("\t")[0] for l in lineas if l.strip()]


def ia_portada(carpeta):
    for f in audios(os.path.join(ROOT, carpeta), recursivo=False):
        pics = abrir(f).pictures
        if pics:
            return max(pics, key=lambda p: (p.type == 3, len(p.data)))
    return None


def ia_preparar():
    lista = ia_discos()
    if os.path.exists(SALIDA):   # 2 oct: se borra entera, así que solo si es una comparación anterior
        if os.listdir(SALIDA) and not os.path.exists(os.path.join(SALIDA, "ver todas.html")):
            sys.exit(f"{SALIDA} tiene otras cosas (no es una comparación de carátulas): no la toco. Revisa rutas.portadas_ia.")
        shutil.rmtree(SALIDA)
    os.makedirs(os.path.join(SALIDA, "_versiones"))
    fuente = ImageFont.truetype(FUENTE, 34) if os.path.exists(FUENTE) else ImageFont.load_default()
    filas = []
    with tempfile.TemporaryDirectory() as tmp:
        ent = os.path.join(tmp, "ent"); os.makedirs(ent)
        nombres = {}
        for i, d in enumerate(lista, 1):
            p = ia_portada(d)
            if not p:
                print("sin carátula:", d); continue
            o = os.path.join(ent, f"{i:02d}.png")
            Image.open(__import__("io").BytesIO(p.data)).convert("RGB").save(o)
            nombres[i] = d
        for v, (modelo, _) in VERSIONES.items():   # una pasada por modelo con la carpeta entera (la GPU va más rápido)
            sal = os.path.join(tmp, f"v{v}"); os.makedirs(sal)
            r = subprocess.run([MOTOR, "-i", ent, "-o", sal, "-m", MODELOS, "-n", modelo, "-s", "4", "-f", "png"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"falló el motor con {modelo}:\n{r.stderr[-800:]}")
        for i, d in nombres.items():
            orig = Image.open(os.path.join(ent, f"{i:02d}.png"))
            vers = {1: orig.resize((LADO, round(LADO * orig.height / orig.width)), Image.LANCZOS)}
            for v in VERSIONES:
                im = Image.open(os.path.join(tmp, f"v{v}", f"{i:02d}.png")).convert("RGB")
                vers[v] = im.resize((LADO, round(LADO * im.height / im.width)), Image.LANCZOS)
            for v, im in vers.items():
                im.save(os.path.join(SALIDA, "_versiones", f"{i:02d}-{v}.jpg"), quality=92)
            alto = round(PANEL * orig.height / orig.width)
            hoja = Image.new("RGB", (PANEL * 3 + 40, alto + 70), "white")
            dib = ImageDraw.Draw(hoja)
            for k, (v, nombre) in enumerate([(1, f"1 Original ({orig.width} px)")] + [(v, f"{v} {n}") for v, (_, n) in VERSIONES.items()]):
                hoja.paste(vers[v].resize((PANEL, alto), Image.LANCZOS), (k * (PANEL + 20), 70))
                dib.text((k * (PANEL + 20) + 8, 12), nombre, fill="black", font=fuente)
            artista, disco = d.split("/", 1)
            limpio = re.sub(r'[/\\:*?"<>|]', "_", f"{i:02d} - {artista} - {disco}")[:150]
            hoja.save(os.path.join(SALIDA, limpio + ".jpg"), quality=88)
            filas.append((i, d, limpio + ".jpg"))
    with open(os.path.join(SALIDA, "ver todas.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta charset=utf-8><title>Portadas con IA</title><style>body{font-family:sans-serif;"
                "background:#f4f4f4;margin:16px}h2{font-size:18px;margin:28px 0 6px}img{max-width:100%;height:auto;"
                "background:#fff}p{color:#555}</style><h1>Portadas chicas: 1 Original · 2 IA foto · 3 IA dibujo</h1>"
                "<p>Dime por número cuál quieres en cada disco (p. ej. «5 = 3, 12 = 2»; lo que no digas queda 1, la original)."
                " Las versiones completas están en <code>_versiones/</code> (NN-1, NN-2, NN-3).</p>")
        for i, d, img in filas:
            f.write(f"<h2>{i:02d}. {html.escape(d)}</h2><a href=\"{html.escape(img)}\"><img loading=lazy src=\"{html.escape(img)}\"></a>")
    json.dump({f"{i:02d}": d for i, d, _ in filas}, open(os.path.join(SALIDA, "_versiones", "discos.json"), "w",
                                                          encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(filas)} discos → {SALIDA} (abrir «ver todas.html»)")


def ia_aplicar(elecciones, execute):
    mapa = json.load(open(os.path.join(SALIDA, "_versiones", "discos.json"), encoding="utf-8"))
    plan = []
    for e in elecciones:
        n, v = e.split("=")
        n, v = f"{int(n):02d}", int(v)
        if v == 1: continue
        assert n in mapa and v in VERSIONES, e
        plan.append((n, mapa[n], v))
    for n, d, v in plan:
        print(f"  {n}. {d} → {VERSIONES[v][1]}")
    if not execute:
        sys.exit("Simulación: no se tocó nada. Usa --execute.")
    if antra_abierto():
        sys.exit("Antra está abierto: ciérralo y reintenta.")
    resp = os.path.join(RESPALDOS, f"caratulas-antes-ia-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    hechas = 0
    for n, d, v in plan:
        data = open(os.path.join(SALIDA, "_versiones", f"{n}-{v}.jpg"), "rb").read()
        im = Image.open(os.path.join(SALIDA, "_versiones", f"{n}-{v}.jpg"))
        for f in audios(os.path.join(ROOT, d), recursivo=False):
            t = abrir(f)
            if t.pictures:
                dst = os.path.join(resp, os.path.relpath(f, ROOT) + ".jpg")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                open(dst, "wb").write(t.pictures[0].data)
            pic = Picture(); pic.type = 3; pic.mime = "image/jpeg"; pic.data = data
            pic.width, pic.height, pic.depth = im.width, im.height, 24
            t.clear_pictures(); t.add_picture(pic); t.save(); hechas += 1
    print(f"HECHO: {hechas} canciones en {len(plan)} discos. Respaldo: {resp}")



if __name__ == "__main__":
    a = sys.argv[1:]
    modo = a[0] if a and not a[0].startswith("-") else "faltantes"
    execute = "--execute" in a
    if execute: cerrojo("caratulas.py " + modo)
    revert = a[a.index("--revert") + 1] if "--revert" in a else None
    if modo == "faltantes":
        faltantes_revert(revert) if revert else faltantes(execute)
    elif modo == "mezcladas":
        mezcladas_revert(revert) if revert else mezcladas(execute)
    elif modo == "mejorar":
        mejorar_revert(revert) if revert else mejorar(execute, int(a[a.index("--umbral") + 1]) if "--umbral" in a else 20)
    elif modo == "ia" and a[1:2] == ["preparar"]:
        ia_preparar()
    elif modo == "ia" and a[1:2] == ["aplicar"]:
        ia_aplicar([x for x in a[2:] if "=" in x], execute)
    else:
        sys.exit(__doc__)
