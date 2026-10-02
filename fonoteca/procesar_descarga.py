#!/usr/bin/env python3
"""Procesa una carpeta recién bajada por Antra, de punta a punta. Es el ÚNICO comando tras cada descarga.

Uso:
  procesar_descarga.py "<Carpeta>" [--historial <zip> --usuario <Nombre>] [--execute]

Sin --execute: SIMULACIÓN (no escribe nada; corre hasta el paso 5 y muestra qué haría).
Con --execute, en orden (se detiene si algo sale mal):
  0. Antra cerrado.
  1. Integridad (flac -t; los otros formatos: audio.verificar). Corruptas → se BORRAN, se anotan para re-bajar y el comando PARA (re-sincroniza en Antra).
  1b. No bajadas (Antra 'failed'): identifica la lista .txt usada (la que más IDs comparte con la carpeta) y anota en
      revisar_fallidas.tsv los enlaces que no están ni en la carpeta ni en la biblioteca (por ID, artista+título o ISRC).
  2. Respaldo de los tags de toda la biblioteca (respaldos/).
  3. enriquecer.py: duración vs ISRC, género de Deezer, ID de canción de MusicBrainz (por ISRC), YEAR.
  3b. Sospechosas (>3 s distinto a su ISRC, o sin dato) → AcoustID; las no confirmadas se comparan con la canción
      exacta de Spotify (vista previa de 30 s + duración): no es ese audio → se borra y se anota para re-bajar;
      dudosa (se parece solo en parte, o es la misma grabación pero dura distinto) → revisar_dudosas.tsv (a escuchar).
  3c. mb_disco.py: ID de DISCO de MusicBrainz (agrupa soundtracks/recopilatorios; lo que antes hacía Picard).
  4. Artista del álbum unificado por disco de MusicBrainz (artista_album.py): Navidrome no parte álbumes.
  5. Repartir la carpeta en Artista/Año - Álbum/NN - Título (repartir.py; borra el .m3u y la carpeta vacía).
  5c. Duplicados: una sola copia de cada grabación (duplicados.py; sobrantes a respaldos/duplicados-<fecha>/).
  6. Una fecha por disco (fechas.py) y géneros: lista de 20, hasta 2 por artista (generos.py).
  7. Números de pista (numeros_pista.py), carátulas (caratulas.py), letras (letras.py), ReplayGain (replaygain.py);
     7e. las que se borraron (corruptas/equivocadas) y ya se re-bajaron vuelven a sus playlists (devolver_playlists.py).
  8. Navidrome (nd_actualizar.py): playlist del historial si hay --historial/--usuario; escaneo; reproducciones de
     los archivos renumerados/duplicados pasan a su ruta nueva; sin canciones "faltantes".
  9. Documento de pendientes (revisar.py), chequeo de salud (musica-salud.py) y kit de recuperación (kit_recuperacion.py).
"""
import datetime, glob, json, os, subprocess, sys, time
from comun import ROOT, HERE, LOGS, RESPALDOS, PRUEBA, ANTRA_HISTORY, LISTAS, KIT, SCRIPTS, antra_abierto, anotar_fallida, anotar_dudosa
from comun import duracion_spotify, dura_distinto, parecido_spotify
from audio import audios, es_audio, verificar

args = sys.argv[1:]
if not args or args[0].startswith("--"):
    sys.exit(__doc__)
EXECUTE = "--execute" in args
# 2 oct: «Carpeta/» (la barra que pone el Tab) dejaba cada canción con dos nombres; una ruta absoluta o con «..» tampoco
folder = os.path.normpath(args[0])
if os.path.isabs(folder):
    folder = os.path.relpath(folder, ROOT)
if folder.startswith("..") or os.sep in folder or folder in (".", ""):
    sys.exit(f"La carpeta tiene que ser una descarga de la raíz de la biblioteca (sin «/»): {args[0]}")
def opt(k):
    if k not in args: return None
    i = args.index(k) + 1
    if i >= len(args) or args[i].startswith("--"): sys.exit(f"Falta el valor de {k}.")
    return args[i]
zipf, user = opt("--historial"), opt("--usuario")
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
X = ["--execute"] if EXECUTE else []

def run(title, cmd, check=True):
    print(f"\n=== {title}\n$ {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=HERE)
    if check and r.returncode != 0:
        sys.exit(f"Falló: {title}. Me detengo; nada de lo que sigue se ejecutó.")
    return r.returncode

def nombres_del_audio(paths):
    """Todos los nombres (hardlinks) en la biblioteca de los audios dados, relativos a ROOT."""
    inos = {os.stat(p).st_ino for p in paths}
    return sorted(os.path.relpath(os.path.join(d, f), ROOT) for d, _, fs in os.walk(ROOT) for f in fs
                  if es_audio(f) and os.stat(os.path.join(d, f)).st_ino in inos)

def tags(p):
    from audio import abrir
    t = abrir(p)
    return {k: (t.get(k) or [""])[0] for k in ("artist", "title", "album", "spotify_id")}

if antra_abierto():
    sys.exit("Antra está abierto: ciérralo primero.")
assert os.path.isdir(os.path.join(ROOT, folder)), f"No existe {ROOT}/{folder}"
if any(os.path.isdir(os.path.join(ROOT, folder, x)) for x in os.listdir(os.path.join(ROOT, folder)) if not x.startswith(".")):
    sys.exit(f"«{folder}» tiene subcarpetas: parece un artista, no una descarga. Mueve las canciones nuevas a otra carpeta.")
if zipf:
    assert user and os.path.isfile(zipf), "--historial necesita --usuario y un zip que exista"
print("MODO:", "EJECUCIÓN" if EXECUTE else "SIMULACIÓN (no se escribe nada)", "— PRUEBA en " + ROOT if PRUEBA else "")

# 1. integridad
files = sorted(audios(os.path.join(ROOT, folder)))
print(f"\n=== 1. integridad de {len(files)} archivos", flush=True)
def falla(fs):   # cualquier error (decodificación o MD5); flac solo imprime el nombre del archivo, no la ruta
    return subprocess.run(["flac", "-t", "-s", *fs], capture_output=True).returncode != 0
bad = []
flacs_d = [f for f in files if f.lower().endswith(".flac")]   # FLAC: en lotes de 20 con flac -t (como siempre)
for i in range(0, len(flacs_d), 20):
    lote = flacs_d[i:i + 20]
    if falla(lote):
        bad += [f for f in lote if falla([f])]
bad += [f for f in files if not f.lower().endswith(".flac") and not verificar(f)[0]]   # los demás: audio.verificar
if bad:
    lista = os.path.join(LOGS, f"corruptas-{folder}-{stamp}.txt")
    open(lista, "w").write("".join(n + "\n" for n in nombres_del_audio(bad)))
    print(f"{len(bad)} corruptas:")
    for b in bad:
        print("  ", os.path.relpath(b, ROOT))
    if not EXECUTE:
        sys.exit("(simulación) con --execute se BORRAN, se anotan para re-bajar y el comando PARA.")
    run("borrar corruptas y anotarlas", ["python3", "borrar_canciones.py", lista, "--motivo", "corrupta", "--execute"])
    sys.exit("PARA: re-sincroniza la playlist en Antra (bajará solo esas) y vuelve a correr este comando.")
print("0 corruptas")

# 1b. no bajadas. NO se usa la posición en la playlist (el orden de Spotify puede no ser el de la lista .txt: pasó
# el 24 sep). Se usan los IDs: cada archivo de Antra trae el spotify_id de su canción. Falta = enlace de la lista cuyo ID
# no está en la carpeta ni en la biblioteca, y que tampoco está con otro ID (mismo artista+título o mismo ISRC).
try:
    # .get: Antra guarda sin "title" los intentos que fallan (p. ej. "Spotify metadata unavailable", 26 sep) y se caía aquí
    hist = next(h for h in json.load(open(ANTRA_HISTORY)) if h.get("title") == folder)
except (OSError, StopIteration):
    hist = None
    print(f"\n(1b) No encontré «{folder}» en el historial de Antra: no puedo saber cuáles fallaron.")
if hist and hist["failed"]:
    print(f"\n=== 1b. {hist['failed']} no bajadas según Antra", flush=True)
    from audio import abrir, es_audio
    from comun import es_de_album, clave_titulo, clave_artista
    tid = lambda u: u.rsplit("/", 1)[-1].split("?")[0]
    en_carpeta = {tags(f)["spotify_id"] for f in files}
    cands = []   # listas .txt con la misma cantidad de canciones; gana la que más IDs comparte con la carpeta
    for t in glob.glob(os.path.join(LISTAS, "**", "*.txt"), recursive=True):
        ls = [tid(l.strip()) for l in open(t, encoding="utf-8", errors="ignore") if "open.spotify.com/track/" in l]
        if len(ls) == hist["total"]:
            cands.append((len(set(ls) & en_carpeta), t, ls))
    comun_, txt, urls = max(cands) if cands else (0, None, [])
    if not txt or comun_ < 0.8 * hist["downloaded"]:
        print(f"  No encontré la lista .txt de esta descarga (con {hist['total']} enlaces y sus canciones en la carpeta).")
        print("  Anota a mano las que falten.")
    else:
        print(f"  lista: {txt} ({comun_} de sus canciones están en la carpeta ✓)")
        lib_sid, lib_key = set(), set()
        for d, _, fs in os.walk(ROOT):
            for f in fs:
                p = os.path.join(d, f)
                if es_audio(f) and (es_de_album(p) or p in files):
                    try:
                        t = abrir(p)
                    except Exception:
                        continue
                    g = lambda k: (t.get(k) or [""])[0]
                    lib_sid.add(g("spotify_id"))
                    for a in {g("artist"), g("albumartist")}:
                        lib_key.add((clave_artista(a), clave_titulo(g("title"))))
        # nombre, artistas y disco: de la página pública de Spotify (30 sep: antes la Web API, que exige Premium)
        from comun import spotify_cancion
        for sid in [x for x in urls if x not in lib_sid]:
            t = spotify_cancion(sid)
            if not t:
                print(f"   {sid}: no pude leer su página pública de Spotify; anótala a mano"); continue
            art, tit, alb = (t["artistas"] or [""])[0], t["titulo"], t["disco"]
            if any((clave_artista(a), clave_titulo(tit)) in lib_key for a in t["artistas"] or [art]):
                continue   # ya estaba con otro ID (Antra la saltó por existente)
            print(f"   falta: {art} — {tit} ({alb})")
            if EXECUTE:
                anotar_fallida(f"Antra no la bajó ({folder})", art, tit, alb, "spotify:track:" + sid)

# 2-5
if EXECUTE:
    run("2. respaldo de tags", ["python3", "tags_backup.py", "dump", os.path.join(RESPALDOS, f"tags-antes-{folder}-{stamp}.json")])
t3 = time.time()
run("3. enriquecer (duración, género, MusicBrainz por ISRC, YEAR)", ["python3", "enriquecer.py", folder, *X])

# 3b. audio equivocado. enriquecer marca las que duran >3 s distinto a su ISRC en Deezer (o sin dato). Si AcoustID no
# confirma la grabación, se compara con la canción EXACTA de Spotify (embed público, sin cuota): su vista previa de 30 s
# (comun.parecido_spotify) y su duración (comun.duracion_spotify). Caso CANDY Remix (25 sep 2026): 8 s menos y AcoustID
# no la conocía; con el umbral viejo de 10 s se coló.
#   - no contiene el audio de la vista previa (parecido < 0,75) → EQUIVOCADA: se borra y se anota para re-bajar;
#   - lo contiene (>= 0,85) y dura lo mismo → bien (AcoustID no la conocía o la tenía con otro nombre);
#   - lo demás (lo contiene pero dura distinto, se parece solo en parte, sin vista previa y dura distinto…) → dudosa;
#   - sin ningún dato de Spotify: como antes (equivocada solo si AcoustID dice otra canción y difiere >10 s de su ISRC).
elog = max((f for f in glob.glob(os.path.join(LOGS, "enriquecer-*.json")) if os.path.getmtime(f) >= t3),
           key=os.path.getmtime, default=None)
sosp = json.load(open(elog))["sospechosas"] if elog else []
if sosp:
    lst = os.path.join(LOGS, f"sospechosas-{folder}-{stamp}.txt")
    open(lst, "w").write("".join(x["archivo"] + "\n" for x in sosp))
    t3b = time.time()
    run("3b. AcoustID a las sospechosas por duración", ["python3", "acoustid_check.py", lst])
    ares = max((f for f in glob.glob(os.path.join(LOGS, "acoustid-resultado-*.json")) if os.path.getmtime(f) >= t3b),
               key=os.path.getmtime, default=None)
    res = json.load(open(ares)) if ares else {}
    dif_isrc = {x["archivo"]: x["dif"] for x in sosp}
    equiv = []
    print("\n=== 3b. las no confirmadas, contra la canción exacta de Spotify (vista previa y duración)", flush=True)
    from audio import abrir
    for k, v in res.items():
        ver, quien = v.get("veredicto"), v.get("audio_es") or ""
        if ver == "OK":
            continue
        p = os.path.join(ROOT, k); g = tags(p); largo = abrir(p).info.length
        sp, sim = duracion_spotify(g["spotify_id"]), parecido_spotify(g["spotify_id"], p)
        distinta = sp is not None and dura_distinto(largo, sp)
        dur = f"dura {largo - sp:+.0f} s distinto a Spotify" if distinta else "dura lo mismo que en Spotify" if sp else "sin duración de Spotify"
        acou = f"AcoustID: {ver}{' ' + quien if quien else ''}"
        if sim is not None and sim < 0.75:
            equiv.append(k)
            print(f"  ❌ EQUIVOCADA: {k} → no es el audio de Spotify (parecido {sim}; {dur}; {acou})")
        elif sim is None and sp is None and ver == "EQUIVOCADA" and (dif_isrc.get(k) or 0) > 10:
            equiv.append(k)
            print(f"  ❌ EQUIVOCADA: {k} → el audio es {quien} (sin datos de Spotify; {dif_isrc[k]} s distinto a su ISRC)")
        elif not distinta and (sim or 0) >= 0.85:   # 2 oct: sin vista previa ya no basta la duración → dudosa
            print(f"  ✓ es la de Spotify ({'parecido ' + str(sim) if sim else 'sin vista previa'}; {dur}): {k}")
        else:
            motivo = (f"misma grabación que la de Spotify pero dura {largo - sp:+.0f} s distinto (¿otra edición o cortada?)"
                      if (sim or 0) >= 0.85 and distinta
                      else f"se parece solo en parte a la de Spotify (parecido {sim}; ¿remix u otra mezcla?)" if sim
                      else f"Spotify no tiene vista previa; {dur}; {acou}")
            print(f"  ❓ {motivo}: {k}")
            if EXECUTE:
                anotar_dudosa(motivo, g["spotify_id"], g["artist"], g["title"], acou)
    if equiv:
        le = os.path.join(LOGS, f"equivocadas-{folder}-{stamp}.txt")
        open(le, "w").write("".join(n + "\n" for n in nombres_del_audio([os.path.join(ROOT, k) for k in equiv])))
        if EXECUTE:
            run("3b. borrar equivocadas y anotarlas", ["python3", "borrar_canciones.py", le, "--motivo", "equivocada", "--execute"])
        else:
            print(f"  (simulación) con --execute se borrarían y anotarían: {le}")
run("3c. ID de DISCO de MusicBrainz", ["python3", "mb_disco.py", folder, *X])
run("4. artista del álbum unificado", ["python3", "artista_album.py", *X])
reorg_log = os.path.join(LOGS, f"reorg-{folder}-{stamp}.json")
run("5. repartir la carpeta en Artista/Año - Álbum", ["python3", "repartir.py", folder, "--log", reorg_log, *X])
if not EXECUTE:
    print("\n(Simulación: los pasos 5c-9 dependen de que el 5 se haya ejecutado; se omiten.)")
    sys.exit()
t5 = time.time()
run("5c. duplicados: una sola copia de cada grabación", ["python3", "duplicados.py", "--execute"])
duplog = max((f for f in glob.glob(os.path.join(LOGS, "duplicados-*.json")) if os.path.getmtime(f) >= t5),
             key=os.path.getmtime, default=None)

# 6-7
run("6a. una fecha por disco", ["python3", "fechas.py", "--execute"])
run("6b. géneros (lista de 20, hasta 2 por artista)", ["python3", "generos.py", "--execute", "--sin-respaldo"])
t7 = time.time()
run("7a. números de pista", ["python3", "numeros_pista.py", "--execute"])
tnlog = max((f for f in glob.glob(os.path.join(LOGS, "tracknums-log-*.json")) if os.path.getmtime(f) >= t7),
            key=os.path.getmtime, default=None)
run("7b. carátulas faltantes", ["python3", "caratulas.py", "--execute"])
run("7c. letras (sincronizadas en LYRICS, LRCLIB, instrumentales)", ["python3", "letras.py", "--execute"])
run("7d. volumen parejo (ReplayGain) de los discos nuevos", ["python3", "replaygain.py", "--execute"])
run("7e. devolver a sus playlists las canciones re-bajadas", ["python3", "devolver_playlists.py", "--execute"])

# 8. Navidrome
if PRUEBA:
    print("\n(modo prueba: sin Navidrome ni chequeo de salud)")
else:
    if zipf:
        run("8a. playlist del historial", ["python3", "playlist_historial.py", zipf, user, "--min-plays", "1", "--execute"])
    # el reparto (carpeta de la descarga → su disco) también va a Navidrome, PRIMERO: si Navidrome ya vio las canciones
    # en la carpeta de la descarga (escaneo, o re-bajadas que reconoce solo con sus escuchas viejas), sus escuchas están
    # en esa ruta y se perdían al repartir (27 sep: 106 escuchas de las 9 re-bajadas)
    reorg_nd = None
    if os.path.exists(reorg_log):
        cambios = [{"old_path": os.path.join(ROOT, a), "new_path": os.path.join(ROOT, b)}
                   for a, b in json.load(open(reorg_log, encoding="utf-8")).get("links", [])]
        if cambios:
            reorg_nd = os.path.join(LOGS, f"nd-reorg-{folder}-{stamp}.json")
            json.dump({"cambios": cambios}, open(reorg_nd, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    run("8b. Navidrome al día (escaneo, IDs migrados, sin faltantes)",
        ["python3", "nd_actualizar.py", *[l for l in (reorg_nd, duplog, tnlog) if l], *(["--usuario", user] if user else [])])

# 9
run("9a. documento de pendientes", ["python3", "revisar.py"])
if not PRUEBA:
    run("9b. chequeo de salud", ["python3", os.path.join(SCRIPTS, "musica-salud.py")], check=False)
    run(f"9c. kit de recuperación actualizado ({KIT}: súbelo a la nube)", ["python3", "kit_recuperacion.py"], check=False)
quedan = sorted(audios(os.path.join(ROOT, folder))) if os.path.isdir(os.path.join(ROOT, folder)) else []
if quedan:   # 2 oct: una colisión en el reparto dejaba la canción fuera de todo y aun así decía «LISTO»
    print(f"\n⚠️ NO TERMINÓ: {len(quedan)} canción(es) siguen en «{folder}» porque chocaron con un archivo que ya existe "
          "(¿la misma canción con otro spotify_id?). Míralas y usa quitar_copia.py; el plan está en planes/plan-reparto.txt:")
    for q in quedan[:10]:
        print("   ", os.path.relpath(q, ROOT))
    sys.exit(1)
print(f"\nLISTO: {folder} procesada.")
