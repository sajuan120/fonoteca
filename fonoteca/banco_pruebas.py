#!/usr/bin/env python3
"""Banco de pruebas: corre procesar_descarga.py COMPLETO sobre una biblioteca de mentira y comprueba el resultado.
Correrlo después de cambiar cualquier script. No toca la biblioteca real, ni sus listas/logs, ni Navidrome.

Uso: banco_pruebas.py [--sintetico]   (tarda 1-3 min; deja todo en rutas.banco de config.toml para mirarlo, se rehace cada vez)

Con la biblioteca real a mano usa COPIAS de sus canciones (la lista está abajo: adáptala a tus discos). Sin ella (otra
máquina, o con --sintetico) las FABRICA (2 oct): tonos de ffmpeg de 30 s con las etiquetas y la carátula que tendría cada
una, y lo que Deezer diría de ellas (duración, género, lista del disco) sembrado en una caché propia del banco, así corre
sin red; lo que exige red o la grabación real (AcoustID, la vista previa de Spotify, los IDs de MusicBrainz: escenarios
5 y 7) se salta y se dice «⏭». En los dos modos el banco usa su propia caché (copia de la real) y su propio config.toml.

Arma (con COPIAS de canciones reales, sin tags de procesado, como si recién las bajara Antra):
  - biblioteca: el soundtrack de Shrek 2 (2 canciones) y 3 interludios de Gorillaz "Humanz";
  - descarga «Prueba Descarga» con 4 canciones: el single de "Accidentally In Love" (DUPLICADO de la del soundtrack; se
    fabrica con el audio del soundtrack y los tags del single, porque el single real se apartó como duplicado),
    otro interludio de Humanz (se une a su disco), Daft Punk y Rawayana (nuevos);
  - su lista .txt con 5 enlaces (uno, Shaky Shaky, "no bajó") y su entrada en un history.json de Antra falso.
Comprueba: carpeta repartida y borrada, duplicado apartado, no bajada anotada, género/ReplayGain/IDs puestos,
state de Antra sin rutas rotas, documento de pendientes generado y NADA real tocado.
Escenario 2: una descarga con un archivo CORRUPTO → se borra, se anota, sale del state y el procesado se detiene.
Escenario 3: dos copias sobrantes dentro del MISMO disco chico, que es el mismo disco de MusicBrainz que el grande (lo que
  tumbó un procesado real el 25 sep con Tchaikovsky) → duplicados.py no se cae, no repite canciones al unir y el
  state y las playlists apuntan a la copia que queda.
Escenario 4: una canción SUELTA bajada desde su enlace (Antra la deja en "<artistas>/<año> - <álbum>/<artistas> - <título>",
  caso CANDY Remix del 25 sep) → juntar_descarga.py la reúne en su carpeta sin tocar lo que no es de Antra, procesar_descarga
  la deja en su disco con su número, y si no aparece nada queda anotada en pendientes.
Escenario 5: a) OTRO audio con las etiquetas de la canción correcta, que AcoustID no conoce (el CANDY Remix equivocado)
  → el paso 3b ve que no es el audio de la vista previa de Spotify, lo borra y lo anota para re-bajar, y el procesado no
  se cae aunque la descarga quede vacía; b) la canción correcta pero cortada 8 s → NO se borra (es el audio de Spotify):
  va a dudosas para escucharla.
Escenario 6 (27 sep): números de pista. a) Dark Side of the Moon con 2 canciones de 2 ediciones de MusicBrainz (empate
  1-1: el numeros_pista viejo elegía la del primer archivo en orden alfabético y renombraba lo mismo en cada corrida);
  b) Torches con dos descargas mezcladas («01 01 02»: orden de descarga, no del disco). → Con la edición de Deezer que
  las contiene todas quedan bien, y la 2ª corrida NO cambia nada.
Escenario 7 (27 sep): IDs de MusicBrainz. a) Thriller con el error de Picard (Baby Be Mine y Beat It con el ID de
  «Thriller») → ids_mb.py les pone su grabación verdadera y no toca la de Thriller; b) un sencillo con el ID de OTRA canción
  que MusicBrainz no tiene (Yosuf «Tren» con el de «Tren 200mg») → se le quitan los IDs; c) la 2ª corrida no cambia nada.
Escenario 8 (28 sep): otros formatos. a) una descarga con un MP3, un M4A (AAC) y un Opus (canciones reales convertidas,
  con sus etiquetas y carátula) → cada una termina procesada en su disco (junto a FLAC), con su extensión, ReplayGain,
  género y carátula, y el state de Antra apunta ahí; b) un MP3 cortado a la mitad → se borra, se anota y el procesado para.
Escenario 9 (2 oct): dos descargas seguidas traen el audio de una canción que YA está en su disco, con otro spotify_id
  → el procesado avisa del choque y la deja en su carpeta sin tocar la original; quitar_copia.py la aparta, el state de
  Antra apunta a la original y su spotify_id queda en equivalencias.tsv; al final hay UNA copia en la biblioteca.
Escenario 10 (2 oct): unir_discos.py con dos ediciones del MISMO disco (una canción repetida, una nueva): el destino como
  «otra» se rechaza; la repetida va a respaldos, la nueva entra provisional (9NN) con el nombre y el año del destino, el
  state, la playlist y el log pendiente apuntan al destino, y la 2ª corrida no toca nada.
Escenario 11 (2 oct): numeros_pista.py cortado entre sus dos pasos de renombrado (quedan .tn-tmp-N y
  tracknums-en-curso.json) → la siguiente corrida lo termina y el state queda sano.
Escenario 12 (2 oct): el embudo (prueba.py revisar) reemplaza un MP3 de _Prueba por su FLAC por ISRC solo si dura lo
  mismo: el que dura 10 s menos (otra edición) se queda, y el reemplazado va a respaldos con su log pendiente.
"""
import glob, hashlib, io, json, os, re, shutil, subprocess, sys, time
from mutagen.flac import FLAC, Picture
from audio import abrir, es_audio

from comun import ruta, BANCO, DOC, DOC_FLAC, DOC_AUDITORIA, CONF, CACHE as CACHE_REAL
REAL_BIB = ruta("biblioteca", "~/Music")   # la biblioteca de verdad (de ahí salen las canciones de prueba; no se toca)
HERE = os.path.dirname(os.path.abspath(__file__))
T = BANCO                             # config.toml: rutas.banco (se rehace en cada corrida)
M, D = os.path.join(T, "Music"), os.path.join(T, "datos")
DESC = "Prueba Descarga"
SHREK, HUMANZ = "Soundtracks/2004 - Soundtrack Shrek 2", "Gorillaz/2017 - Humanz (Deluxe)"   # 28 sep: OST por franquicia
# 2 oct: MODO SINTÉTICO. Sin la biblioteca real (otra máquina, o --sintetico) las canciones se fabrican: un tono de
# ffmpeg de 30 s con las etiquetas y la carátula que tendría la real, y las respuestas de Deezer que harían falta
# (duración, género, lista del disco) sembradas en una caché propia. Lo que exige red o la grabación real (AcoustID,
# la vista previa de Spotify, los IDs de MusicBrainz) se salta y se dice.
SINTETICO = "--sintetico" in sys.argv or not os.path.isdir(os.path.join(REAL_BIB, SHREK))
REAL = os.path.join(T, "real") if SINTETICO else REAL_BIB
CACHE = os.path.join(T, "cache")      # caché propia: copia de la real (si hay) + lo sembrado; el banco no ensucia la real
print(f"banco de pruebas: {'SINTÉTICO (canciones fabricadas, sin red)' if SINTETICO else 'con canciones reales de ' + REAL_BIB} → {T}")

def real(carpeta, titulo):
    """Ruta (relativa a REAL) de UNA canción real, por su título con cualquier número adelante: los números cambian al
    renumerar (27 sep: «15 - Funk Ad» pasó a «16 - Funk Ad» y el banco se caía al armar). En modo sintético la fabrica."""
    if SINTETICO:
        return fabricar(carpeta, titulo)
    ms = glob.glob(os.path.join(glob.escape(os.path.join(REAL, carpeta)), "*" + glob.escape(f" - {titulo}.flac")))
    assert len(ms) == 1, f"banco: no encuentro UNA canción real «{titulo}» en {carpeta}: {ms}"
    return os.path.relpath(ms[0], REAL)

# ---------- modo sintético: fabricar canciones y sembrar Deezer ----------
POSICIONES = {   # discos cuyos números importan en los escenarios (el resto: por orden de fabricación)
    "Daft Punk/1997 - Homework": ["Daftendirekt", "WDPK 83.7 FM", "Revolution 909", "Da Funk", "Phoenix", "Fresh", "Around the World",
                                  "Rollin' & Scratchin'", "Teachers", "High Fidelity", "Rock'n Roll", "Oh Yeah", "Burnin'", "Indo Silver Club", "Alive", "Funk Ad"],
    "Pink Floyd/1973 - The Dark Side of the Moon": ["Speak to Me", "Breathe (In the Air)", "On the Run", "Time", "The Great Gig in the Sky", "Money"],
    "Foster The People/2011 - Torches": ["Helena Beat", "Pumped Up Kicks", "Call It What You Want"]}
ARTISTA_SINT = {"Soundtracks": {"Accidentally In Love - From _Shrek 2_ Soundtrack": "Counting Crows", "Holding Out For A Hero": "Bonnie Tyler"}}
GENERO_SINT = {"Daft Punk": "Dance", "Gorillaz": "Rap/Hip Hop", "Rawayana": "Latin Music", "Pink Floyd": "Rock", "Foster The People": "Rock"}
_fabricadas = {}   # carpeta → [títulos] en orden de fabricación

def _h(s, n=8):
    return int(hashlib.sha1(s.encode()).hexdigest()[:n], 16)

def sembrar(nombre, entradas):
    """Agrega entradas a una caché de red.py en CACHE (se mezcla con lo que haya: los scripts también escriben ahí)."""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, nombre)
    d = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    d.update(entradas)
    json.dump(d, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False); os.replace(p + ".tmp", p)

def fabricar(carpeta, titulo):
    """Fabrica (si no está) la canción «carpeta/NN - titulo.flac» bajo REAL y siembra lo que Deezer diría de ella y de su
    disco. Devuelve la ruta relativa a REAL."""
    artista, disco = carpeta.split("/", 1)
    anio, album = disco.split(" - ", 1)
    lista = POSICIONES.get(carpeta)
    if lista:
        assert titulo in lista, f"banco sintético: «{titulo}» no está en POSICIONES de {carpeta}"
    fab = _fabricadas.setdefault(carpeta, [])
    if titulo not in fab:
        fab.append(titulo)
    pos = lista.index(titulo) + 1 if lista else fab.index(titulo) + 1
    rel = os.path.join(carpeta, f"{pos:02d} - {titulo}.flac")
    p = os.path.join(REAL, rel)
    if os.path.exists(p):
        return rel
    os.makedirs(os.path.dirname(p), exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={200 + _h(rel) % 600}:duration=30",
                    "-ar", "44100", "-ac", "2", "-sample_fmt", "s16", p], check=True)
    art = ARTISTA_SINT.get(artista, {}).get(titulo, artista)
    aa = "Various Artists" if artista == "Soundtracks" else artista
    genero = GENERO_SINT.get(artista, "Pop")
    isrc = f"ZZBAN{_h(rel) % 10**7:07d}"
    t = FLAC(p)
    t.update(title=[titulo], artist=[art], albumartist=[aa], album=[album], date=[f"{anio}-01-01"], year=[anio], tracknumber=[str(pos)],
             discnumber=["1"], isrc=[isrc], spotify_id=[hashlib.sha1(rel.encode()).hexdigest()[:22]], genre=[genero], genre_deezer=[genero], antra_downloaded=["1"],
             replaygain_track_gain=["-3.00 dB"], replaygain_track_peak=["0.5"], replaygain_album_gain=["-3.00 dB"], replaygain_album_peak=["0.5"])
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (64, 64), (_h(rel) % 256, 90, 140)).save(buf, "PNG")
    pic = Picture(); pic.type, pic.mime, pic.data, pic.width, pic.height, pic.depth = 3, "image/png", buf.getvalue(), 64, 64, 24
    t.add_picture(pic); t.save()
    # lo que Deezer diría: la canción por ISRC, su disco (género) y la lista del disco con lo fabricado hasta ahora
    aid = 990000000 + _h(carpeta) % 10**6
    import urllib.parse
    pistas = []
    for tit in fab:
        q = lista.index(tit) + 1 if lista else fab.index(tit) + 1
        f = FLAC(os.path.join(REAL, carpeta, f"{q:02d} - {tit}.flac"))
        pistas.append({"id": _h(tit) % 10**8, "track_position": q, "disk_number": 1, "isrc": f["isrc"][0], "title": tit, "duration": round(f.info.length)})
    disco_dz = {"id": aid, "title": album, "release_date": f"{anio}-01-01", "nb_tracks": len(pistas), "artist": {"name": aa},
                "genres": {"data": [{"name": genero}]}}
    sembrar("deezer-cache.json", {f"https://api.deezer.com/track/isrc:{isrc}": {"id": _h(titulo) % 10**8, "title": titulo, "isrc": isrc, "duration": 30,
                                  "track_position": pos, "disk_number": 1, "artist": {"name": art}, "album": {"id": aid, "title": album}},
                                  f"https://api.deezer.com/album/{aid}": disco_dz})
    sembrar("deezer-numeros.json", {f"https://api.deezer.com/album/{aid}": disco_dz,
                                    f"https://api.deezer.com/album/{aid}/tracks?limit=300": {"data": pistas},
                                    "https://api.deezer.com/search/album?limit=50&q=" + urllib.parse.quote(f'artist:"{aa}" album:"{album}"'): {"data": [{"id": aid, "title": album}]}})
    return rel

def huella():
    """Estado de lo real que NO debe cambiar: canciones de la biblioteca y listas/planes reales."""
    n = 0 if SINTETICO else sum(1 for d, _, fs in os.walk(REAL) for f in fs if es_audio(f) and os.path.relpath(d, REAL).count(os.sep) >= 1
                                and os.path.relpath(d, REAL).split(os.sep)[0] != "_Prueba")   # _Prueba cambia sola (Octo-Fiesta)
    h = hashlib.sha1()
    for f in ["revisar_fallidas.tsv", "revisar_dudosas.tsv", "planes/plan-reparto.json", "planes/plan-generos.json",
              DOC, DOC_FLAC, DOC_AUDITORIA]:   # 1 oct: también los documentos reales (el banco pisaba el «conseguir en FLAC»)
        p = os.path.join(HERE, f)
        h.update(open(p, "rb").read() if os.path.exists(p) else b"-")
    return n, h.hexdigest()

# ---------- armar ----------
antes = huella()
# 2 oct: se borra entera: solo si está vacía o es un banco anterior (tiene Music/ y datos/)
if os.path.isdir(T) and os.listdir(T) and not (os.path.isdir(M) and os.path.isdir(D)):
    sys.exit(f"{T} tiene otras cosas (no es un banco anterior): no la toco. Revisa rutas.banco en config.toml.")
shutil.rmtree(T, ignore_errors=True)
os.makedirs(os.path.join(M, "_Playlists")); os.makedirs(os.path.join(T, "listas", "Prueba")); os.makedirs(D); os.makedirs(CACHE)
if os.path.isdir(CACHE_REAL):   # la caché real se copia: con red se aprovecha, y lo que el banco pida no la ensucia
    for f in glob.glob(os.path.join(CACHE_REAL, "*.json")):
        shutil.copy(f, CACHE)
if SINTETICO:   # sin red los reintentos de red.py no duermen; y la «página pública de Spotify» de la que no bajó
    os.makedirs(os.path.join(T, "site")); open(os.path.join(T, "site", "sitecustomize.py"), "w").write("import time\ntime.sleep = lambda s: None\n")
    sembrar("spotify-publico.json", {"track:53QdfEoKCXlEfjgXPmvPjx": {"titulo": "Shaky Shaky (Remix)", "artistas": ["Daddy Yankee"], "disco": "Shaky Shaky",
                                                                    "disco_id": "banco", "anio": "2016", "duracion": 220}})
def _toml(v):
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, (int, float)): return str(v)
    if isinstance(v, list): return "[" + ", ".join(_toml(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
def _tabla(nombre, d, out):
    out.append(f"[{nombre}]" if nombre else "")
    for k, v in d.items():
        if not isinstance(v, dict): out.append(f"{k} = {_toml(v)}")
    for k, v in d.items():
        if isinstance(v, dict): _tabla(f"{nombre}.{k}" if nombre else k, v, out)
conf = json.loads(json.dumps(CONF))   # copia; las rutas del banco apuntan al banco (Navidrome de mentira, listas, kit, Antra)
conf.setdefault("rutas", {}).update(navidrome=os.path.join(T, "navidrome"), kit=os.path.join(T, "kit"), antra=os.path.join(T, "antra"),
                                    listas=os.path.join(T, "listas"), banco=T)
lineas = []; _tabla("", conf, lineas); open(os.path.join(T, "config.toml"), "w", encoding="utf-8").write("\n".join(lineas) + "\n")
# ---------- las canciones ----------
LIB = [real(SHREK, "Accidentally In Love - From _Shrek 2_ Soundtrack"), real(SHREK, "Holding Out For A Hero"),
       real(HUMANZ, "Interlude_ Elevator Going Up"), real(HUMANZ, "Interlude_ Penthouse"), real(HUMANZ, "Interlude_ The Elephant")]
NUEVAS = [(LIB[0], {"title": ["Accidentally In Love"], "album": ["Accidentally In Love"], "albumartist": ["Counting Crows"],
                    "spotify_id": ["4ccM2xBxicGigjLqt6A0YY"]}),   # el single: audio del soundtrack, tags del single
          real(HUMANZ, "Interlude_ Talk Radio"), real("Daft Punk/1997 - Homework", "WDPK 83.7 FM"),
          real("Rawayana/2026 - ¿Dónde Es El After_", "Si Te Pica Es Porque Eres Tú")]
FUNK_AD = real("Daft Punk/1997 - Homework", "Funk Ad")
NO_BAJO = "53QdfEoKCXlEfjgXPmvPjx"   # Shaky Shaky (Remix), Daddy Yankee
PROCESADO = ("musicbrainz_", "replaygain_", "genre_deezer", "originaldate")   # tags que pone el procesado: se quitan

state = {}
for rel in LIB:
    dst = os.path.join(M, rel); os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(os.path.join(REAL, rel), dst)
    state[f"TRACK:spotify:{FLAC(dst)['spotify_id'][0]}"] = dst
sids = []
for i, rel in enumerate(NUEVAS, 1):
    rel, cambiar = rel if isinstance(rel, tuple) else (rel, {})
    t = FLAC(os.path.join(REAL, rel))
    dst = os.path.join(M, DESC, f"{i:02d} - {cambiar.get('title', t['title'])[0].replace('/', '_')}.flac")
    os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(os.path.join(REAL, rel), dst)
    t = FLAC(dst)
    for k in [k for k in list(t.keys()) if k.lower().startswith(PROCESADO)]:
        del t[k]
    t.update(cambiar)
    t["genre"] = ["Rap/Hip Hop"] if "Gorillaz" in rel else ["Latin Music"] if "Rawayana" in rel else ["Dance"] if "Daft" in rel else ["Pop"]
    t.save()
    sids.append(t["spotify_id"][0]); state[f"TRACK:spotify:{sids[-1]}"] = dst
open(os.path.join(M, ".antra_state.json"), "w").write(json.dumps(state, indent=2, ensure_ascii=True))
open(os.path.join(M, "_Playlists", "Prueba.m3u"), "w").write("#EXTM3U\n../" + LIB[1] + "\n")
open(os.path.join(T, "listas", "Prueba", "PRUEBA-5.txt"), "w").write(
    "".join(f"https://open.spotify.com/track/{s}\n" for s in sids + [NO_BAJO]))
json.dump([{"date": "2026-09-24T00:00:00", "title": DESC, "total": 5, "downloaded": 4, "failed": 1, "skipped": 0}],
          open(os.path.join(T, "history.json"), "w"))

env = dict(os.environ, MUSIC_ROOT=M, MUSIC_DATOS=D, MUSIC_DOC=os.path.join(T, "pendientes.md"), MUSIC_CACHE=CACHE,
           MUSIC_CONFIG=os.path.join(T, "config.toml"), ANTRA_HISTORY=os.path.join(T, "history.json"), MUSIC_LISTAS=os.path.join(T, "listas"))
env.pop("FONOTECA_CERROJO", None)
if SINTETICO:
    env["PYTHONPATH"] = os.path.join(T, "site") + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
def salta(texto):
    print("⏭  " + texto + " (solo con la biblioteca real y red)")
# ---------- correr: simulación y ejecución ----------
ok = True
for modo in ([], ["--execute"]):
    r = subprocess.run(["python3", os.path.join(HERE, "procesar_descarga.py"), DESC, *modo], env=env, cwd=HERE,
                       capture_output=True, text=True)
    open(os.path.join(T, f"salida{'-execute' if modo else '-simulacion'}.txt"), "w").write(r.stdout + r.stderr)
    if r.returncode != 0:
        print(f"❌ procesar_descarga {'--execute' if modo else '(simulación)'} terminó con error {r.returncode}:")
        print((r.stdout + r.stderr)[-1500:]); ok = False; break

# ---------- comprobar ----------
def check(cond, texto):
    global ok
    print(("✅ " if cond else "❌ ") + texto); ok = ok and cond
if ok:
    album = lambda: [p for p in glob.glob(os.path.join(M, "**", "*.flac"), recursive=True) if os.path.relpath(p, M).count(os.sep) >= 2]
    check(not os.path.exists(os.path.join(M, DESC)), "la carpeta de la descarga se repartió y se borró")
    check(not os.path.exists(os.path.join(M, DESC + ".m3u")), "no queda .m3u de Antra en la raíz")
    check(glob.glob(os.path.join(M, "Gorillaz", "*Humanz*", "*Talk Radio*")) != [], "el interludio nuevo entró a su disco de Humanz")
    check(glob.glob(os.path.join(M, "Daft Punk", "*", "*WDPK*")) != [] and glob.glob(os.path.join(M, "Rawayana", "*", "*.flac")) != [],
          "Daft Punk y Rawayana quedaron en Artista/Año - Álbum")
    check(glob.glob(os.path.join(D, "respaldos", "duplicados-*", "**", "*Accidentally*"), recursive=True) != []
          and os.path.exists(os.path.join(M, LIB[0])), "duplicado: se apartó el single y quedó la del soundtrack")
    fall = open(os.path.join(D, "revisar_fallidas.tsv"), encoding="utf-8").read() if os.path.exists(os.path.join(D, "revisar_fallidas.tsv")) else ""
    check(NO_BAJO in fall, "la canción que no bajó quedó anotada en la lista a conseguir")
    nuevas = [p for p in album() if FLAC(p).get("spotify_id", [""])[0] in sids]
    check(len(nuevas) == 3, f"3 canciones nuevas en la biblioteca (hay {len(nuevas)})")
    for p in nuevas:
        t = FLAC(p); n = os.path.basename(p)[:35]
        check(bool(t.get("genre")) and len(t["genre"]) <= 2 and bool(t.get("genre_deezer")), f"{n}: género {t.get('genre')} y original guardado")
        check(bool(t.get("replaygain_track_gain")), f"{n}: ReplayGain {t.get('replaygain_track_gain')}")
        if SINTETICO: salta(f"{n}: ID de MusicBrainz")
        else: check(bool(t.get("musicbrainz_trackid")) or "Rawayana" in p, f"{n}: ID de MusicBrainz")
    st = json.load(open(os.path.join(M, ".antra_state.json")))
    check(all(os.path.exists(v) for v in st.values()), "state de Antra: ninguna ruta rota")
    check(os.path.exists(os.path.join(T, "pendientes.md")), "documento de pendientes generado")
# ---------- escenario 2: una descarga con un archivo CORRUPTO ----------
if ok:
    CORR = "Prueba Corrupta"
    src = os.path.join(REAL, FUNK_AD)
    dst = os.path.join(M, CORR, "01 - Funk Ad.flac"); os.makedirs(os.path.dirname(dst)); shutil.copy2(src, dst)
    with open(dst, "r+b") as fh:   # romperlo: se corta a la mitad
        fh.truncate(os.path.getsize(dst) // 2)
    st = json.load(open(os.path.join(M, ".antra_state.json"))); st["TRACK:spotify:corrupta"] = dst
    open(os.path.join(M, ".antra_state.json"), "w").write(json.dumps(st, indent=2, ensure_ascii=True))
    with open(os.path.join(M, "_Playlists", "Prueba.m3u"), "a") as fh:   # estaba en una playlist, entre dos canciones
        fh.write(f"../{CORR}/01 - Funk Ad.flac\n../{LIB[4]}\n")
    r = subprocess.run(["python3", os.path.join(HERE, "procesar_descarga.py"), CORR, "--execute"], env=env, cwd=HERE,
                       capture_output=True, text=True)
    open(os.path.join(T, "salida-corrupta.txt"), "w").write(r.stdout + r.stderr)
    check(r.returncode != 0 and "PARA" in (r.stdout + r.stderr), "corrupta: el procesado se detiene y pide re-sincronizar")
    check(not os.path.exists(dst), "corrupta: el archivo se borró")
    fall = open(os.path.join(D, "revisar_fallidas.tsv"), encoding="utf-8").read()
    check("corrupta" in fall and "Funk Ad" in fall, "corrupta: quedó anotada para re-bajar")
    st = json.load(open(os.path.join(M, ".antra_state.json")))
    check("TRACK:spotify:corrupta" not in st, "corrupta: se sacó del state de Antra (así Antra la vuelve a bajar)")
# ---------- escenario 3: dos copias sobrantes dentro del MISMO disco chico (caso Tchaikovsky, 25 sep) ----------
if ok:
    rutas = {}
    for disco, n in (("Disco Grande", 3), ("Disco Chico", 2)):   # el chico = mismo disco de MusicBrainz, con 2 de las 3
        for i in range(1, n + 1):
            p = os.path.join(M, "Banco Duplicados", f"2020 - {disco}", f"0{i} - Pista {i}.flac")
            os.makedirs(os.path.dirname(p), exist_ok=True); shutil.copy2(os.path.join(REAL, LIB[1 + i]), p)
            t = FLAC(p); t.clear()
            t.update(title=[f"Pista {i}"], artist=["Banco Duplicados"], albumartist=["Banco Duplicados"], album=[disco],
                     date=["2020"], tracknumber=[str(i)], isrc=[f"BANCO000000{i}"], musicbrainz_releasegroupid=["banco-rg"])
            t.save(); rutas[(disco, i)] = p
    st = json.load(open(os.path.join(M, ".antra_state.json"))); st["TRACK:spotify:banco-chica-1"] = rutas[("Disco Chico", 1)]
    open(os.path.join(M, ".antra_state.json"), "w").write(json.dumps(st, indent=2, ensure_ascii=True))
    open(os.path.join(M, "_Playlists", "Banco.m3u"), "w").write("#EXTM3U\n../" + os.path.relpath(rutas[("Disco Chico", 2)], M) + "\n")
    r = subprocess.run(["python3", os.path.join(HERE, "duplicados.py"), "--execute"], env=env, cwd=HERE,
                       capture_output=True, text=True)
    open(os.path.join(T, "salida-duplicados.txt"), "w").write(r.stdout + r.stderr)
    grande = os.path.dirname(rutas[("Disco Grande", 1)])
    check(r.returncode == 0, "duplicados: no se cae con dos copias sobrantes en el mismo disco chico")
    check(not os.path.exists(os.path.dirname(rutas[("Disco Chico", 1)]))
          and sorted(os.listdir(grande)) == [f"0{i} - Pista {i}.flac" for i in (1, 2, 3)],
          "duplicados: el disco chico se vació y el grande quedó con sus 3 canciones, sin copias '(2)'")
    st = json.load(open(os.path.join(M, ".antra_state.json")))
    check(st.get("TRACK:spotify:banco-chica-1") == rutas[("Disco Grande", 1)]
          and "../" + os.path.relpath(rutas[("Disco Grande", 2)], M) in open(os.path.join(M, "_Playlists", "Banco.m3u")).read(),
          "duplicados: el state de Antra y la playlist apuntan a la copia que queda")
# ---------- escenario 4: canción SUELTA bajada desde su enlace (caso CANDY Remix, 25 sep) ----------
if ok:
    SUEL = "Homework"   # con un enlace de canción, Antra anota el nombre del DISCO como título en su historial
    suelta = os.path.join(M, "Daft Punk, Otro", "1997 - Homework", "Daft Punk, Otro - Funk Ad.flac")   # como la deja Antra
    os.makedirs(os.path.dirname(suelta)); shutil.copy2(os.path.join(REAL, FUNK_AD), suelta)
    t = FLAC(suelta)
    for k in [k for k in list(t.keys()) if k.lower().startswith(PROCESADO)]:
        del t[k]
    t["tracknumber"] = ["1"]; t.save()   # bajada sola: Antra la numera 1
    sid = t["spotify_id"][0]; url = f"https://open.spotify.com/track/{sid}"
    st = json.load(open(os.path.join(M, ".antra_state.json"))); st[f"TRACK:spotify:{sid}"] = suelta
    open(os.path.join(M, ".antra_state.json"), "w").write(json.dumps(st, indent=2, ensure_ascii=True))
    h = json.load(open(os.path.join(T, "history.json")))
    h.insert(0, {"date": "2026-09-25T09:35:56", "url": url, "title": SUEL, "total": 1, "downloaded": 1, "failed": 0, "skipped": 0})
    json.dump(h, open(os.path.join(T, "history.json"), "w"))
    r = subprocess.run(["python3", os.path.join(HERE, "juntar_descarga.py"), SUEL, "--url", url, "--execute"], env=env, cwd=HERE,
                       capture_output=True, text=True)
    r2 = subprocess.run(["python3", os.path.join(HERE, "procesar_descarga.py"), SUEL, "--execute"], env=env, cwd=HERE,
                        capture_output=True, text=True)
    r3 = subprocess.run(["python3", os.path.join(HERE, "juntar_descarga.py"), "Nada Que Juntar", "--url",
                         "https://open.spotify.com/track/bancoNoEncontrada", "--execute"], env=env, cwd=HERE, capture_output=True, text=True)
    open(os.path.join(T, "salida-suelta.txt"), "w").write("\n\n".join(x.stdout + x.stderr for x in (r, r2, r3)))
    check(r.returncode == 0 and not os.path.exists(os.path.join(M, "Daft Punk, Otro")),
          "suelta: se juntó en su carpeta de descarga y se borraron las carpetas que Antra le creó")
    check(sorted(os.listdir(grande)) == [f"0{i} - Pista {i}.flac" for i in (1, 2, 3)] and "no bajó Antra" in r.stdout,
          "suelta: lo sin procesar que no bajó Antra (el disco del escenario 3) no se tocó y se avisó")
    final = (glob.glob(os.path.join(M, "Daft Punk", "1997 - Homework", "[0-9][0-9] - Funk Ad.flac")) + [""])[0]
    check(r2.returncode == 0 and os.path.exists(final) and not final.endswith("/01 - Funk Ad.flac")
          and not os.path.exists(os.path.join(M, SUEL)),
          f"suelta: procesada, en su disco y renumerada (Antra la deja en 1): {os.path.basename(final)}")
    check(os.path.exists(final) and bool(FLAC(final).get("replaygain_track_gain")), "suelta: tiene ReplayGain (quedó procesada)")
    st = json.load(open(os.path.join(M, ".antra_state.json")))
    check(st.get(f"TRACK:spotify:{sid}") == final, "suelta: el state de Antra apunta a su lugar final")
    fall = open(os.path.join(D, "revisar_fallidas.tsv"), encoding="utf-8").read()
    check(r3.returncode == 2 and "spotify:track:bancoNoEncontrada" in fall and not os.path.exists(os.path.join(M, "Nada Que Juntar")),
          "suelta que no aparece: queda anotada en pendientes y no se crea carpeta")
    doc = open(os.path.join(T, "pendientes.md"), encoding="utf-8").read()
    check("Funk Ad" not in doc.split("## 1.")[1].split("## 2.")[0],
          "la corrupta del escenario 2, ya re-bajada, salió sola de la lista a conseguir")
    pl = open(os.path.join(M, "_Playlists", "Prueba.m3u"), encoding="utf-8").read().splitlines()
    fa = [i for i, x in enumerate(pl) if "Funk Ad" in x]
    check(len(fa) == 1 and pl[fa[0]] == "../" + os.path.relpath(final, M) and fa[0] + 1 < len(pl)
          and "Interlude_ The Elephant" in pl[fa[0] + 1],
          "la corrupta re-bajada volvió a su playlist, en su mismo lugar (antes de su vecina de siempre)")
# ---------- escenario 5: audio equivocado que AcoustID no conoce (el CANDY Remix del 25 sep) ----------
REEA = os.path.join(REAL, real("Reea/2011 - Need Me Baby", "Need Me Baby - Radio Edit")) if not SINTETICO else None   # AcoustID no la conoce
def descarga_suelta(nombre, archivo, fabricar):
    """Arma una descarga de Antra de una canción: carpeta, state e historial; fabricar(destino) crea el audio."""
    os.makedirs(os.path.join(M, nombre)); fabricar(archivo)
    t = FLAC(archivo)
    for k in [k for k in list(t.keys()) if k.lower().startswith(PROCESADO)]:
        del t[k]
    t.save()
    sid = t["spotify_id"][0]
    st = json.load(open(os.path.join(M, ".antra_state.json"))); st[f"TRACK:spotify:{sid}"] = archivo
    open(os.path.join(M, ".antra_state.json"), "w").write(json.dumps(st, indent=2, ensure_ascii=True))
    h = json.load(open(os.path.join(T, "history.json")))
    h.insert(0, {"date": f"2026-09-25T10:0{len(h)}:00", "url": f"https://open.spotify.com/track/{sid}", "title": nombre,
                 "total": 1, "downloaded": 1, "failed": 0, "skipped": 0})
    json.dump(h, open(os.path.join(T, "history.json"), "w"))
    r = subprocess.run(["python3", os.path.join(HERE, "procesar_descarga.py"), nombre, "--execute"], env=env, cwd=HERE,
                       capture_output=True, text=True)
    open(os.path.join(T, f"salida-{nombre.lower().replace(' ', '-')}.txt"), "w").write(r.stdout + r.stderr)
    return r, sid
if ok and SINTETICO:
    salta("escenario 5 (audio equivocado / cortado: AcoustID y la vista previa de Spotify)")
if ok and not SINTETICO:   # 5a: el audio es OTRA canción (Daramola) con las etiquetas de la correcta (Reea): 7,5 s menos, AcoustID no la conoce
    def otro_audio(dst):
        shutil.copy2(os.path.join(REAL, real("Daramola/2026 - Gidi 2 Caracas (La Música)", "Gidi 2 Caracas - La Música")), dst)
        t = FLAC(dst); t.clear(); t.update({k: v for k, v in FLAC(REEA).tags}); t.save()
    mala = os.path.join(M, "Prueba Otro Audio", "01 - Need Me Baby - Radio Edit.flac")
    r, sid = descarga_suelta("Prueba Otro Audio", mala, otro_audio)
    check(not os.path.exists(mala) and not glob.glob(os.path.join(M, "Reea", "**", "*.flac"), recursive=True),
          "otro audio con las etiquetas correctas (AcoustID no lo conoce): se borró por no ser el audio de Spotify")
    check(r.returncode == 0, "otro audio: el procesado sigue hasta el final aunque la descarga quede vacía")
    fall = open(os.path.join(D, "revisar_fallidas.tsv"), encoding="utf-8").read()
    st = json.load(open(os.path.join(M, ".antra_state.json")))
    check(sid in fall and f"TRACK:spotify:{sid}" not in st, "otro audio: anotado para re-bajar y fuera del state de Antra")
if ok and not SINTETICO:   # 5b: la canción CORRECTA pero 8 s más corta: es su audio (la vista previa coincide), ¿cortada u otra edición? → dudosa
    cortada = os.path.join(M, "Prueba Cortada", "01 - Need Me Baby - Radio Edit.flac")
    r, sid = descarga_suelta("Prueba Cortada", cortada, lambda dst: subprocess.run(
        ["ffmpeg", "-v", "error", "-i", REEA, "-t", f"{FLAC(REEA).info.length - 8:.2f}", "-map_metadata", "0", "-c:a", "flac", dst],
        check=True))
    dud = open(os.path.join(D, "revisar_dudosas.tsv"), encoding="utf-8").read() if os.path.exists(os.path.join(D, "revisar_dudosas.tsv")) else ""
    check(r.returncode == 0 and glob.glob(os.path.join(M, "Reea", "**", "*Need Me Baby*.flac"), recursive=True) != [],
          "cortada: NO se borró (es el audio de Spotify) y quedó procesada en la biblioteca")
    check(any(sid in l and "misma grabación" in l for l in dud.splitlines()), "cortada: quedó en dudosas (a escuchar), con el motivo")
# ---------- escenario 6: números de pista (27 sep) ----------
if ok:
    # se FABRICA el estado malo sobre copias (la biblioteca real ya está arreglada): (título, número del nombre, disco)
    casos = {"Pink Floyd/1973 - The Dark Side of the Moon": [("Breathe (In the Air)", "02", 2), ("Money", "06", 1)],
             "Foster The People/2011 - Torches": [("Helena Beat", "01", 1), ("Pumped Up Kicks", "01", 1), ("Call It What You Want", "02", 1)]}
    for d, fs in casos.items():
        os.makedirs(os.path.join(M, d), exist_ok=True)
        for tit, n, dn in fs:
            dst = os.path.join(M, d, f"{n} - {tit}.flac"); shutil.copy2(os.path.join(REAL, real(d, tit)), dst)
            t = FLAC(dst); t["tracknumber"] = [str(int(n))]; t["discnumber"] = [str(dn)]; t.save()
    def corrida(n):
        r = subprocess.run(["python3", os.path.join(HERE, "numeros_pista.py"), "--execute"], env=env, cwd=HERE,
                           capture_output=True, text=True)
        open(os.path.join(T, f"salida-numeros-{n}.txt"), "w").write(r.stdout + r.stderr)
        return r
    r1 = corrida(1)
    dsotm = os.path.join(M, "Pink Floyd/1973 - The Dark Side of the Moon")
    check(r1.returncode == 0 and sorted(os.listdir(dsotm)) == ["02 - Breathe (In the Air).flac", "06 - Money.flac"]
          and FLAC(os.path.join(dsotm, "02 - Breathe (In the Air).flac"))["discnumber"] == ["1"],
          "números: Dark Side (2 canciones de 2 ediciones, empate 1-1) → 02 y 06, las dos del disco 1")
    torches = sorted(os.listdir(os.path.join(M, "Foster The People/2011 - Torches")))
    check(torches == ["01 - Helena Beat.flac", "02 - Pumped Up Kicks.flac", "03 - Call It What You Want.flac"],
          f"números: Torches (dos descargas mezcladas, «01 01 02») → 01 02 03 como el disco ({', '.join(torches)})")
    r2 = corrida(2)
    check(r2.returncode == 0 and "cambios: 0 canciones" in r2.stdout, "números: la 2ª corrida no cambia nada (ya no oscila)")
# ---------- escenario 7: IDs de MusicBrainz equivocados (Picard por posición, 27 sep) ----------
if ok and SINTETICO:
    salta("escenario 7 (IDs de MusicBrainz equivocados)")
if ok and not SINTETICO:
    from comun import nivel_titulo
    thr = "Michael Jackson/2008 - Thriller"
    os.makedirs(os.path.join(M, thr), exist_ok=True)
    rutas = {tit: os.path.join(M, real(thr, tit)) for tit in ("Baby Be Mine", "Thriller", "Beat It")}
    for tit, dst in rutas.items(): shutil.copy2(os.path.join(REAL, real(thr, tit)), dst)
    buena = {k: list(FLAC(rutas["Thriller"])[k]) for k in ("musicbrainz_trackid", "musicbrainz_releasetrackid", "musicbrainz_albumid")}
    for tit in ("Baby Be Mine", "Beat It"):                   # se FABRICA el error: el ID de «Thriller» en las otras dos
        t = FLAC(rutas[tit]); t.update(buena); t.save()
    tren = os.path.join(M, real("Yosuf/2021 - Tren", "Tren")); os.makedirs(os.path.dirname(tren), exist_ok=True)
    shutil.copy2(os.path.join(REAL, real("Yosuf/2021 - Tren", "Tren")), tren)
    t = FLAC(tren); t["musicbrainz_trackid"] = ["422fcdbe-ce5a-4fd6-a081-9fe73281b457"]; t.save()   # el de «Tren 200mg»
    def ids(n):
        r = subprocess.run(["python3", os.path.join(HERE, "ids_mb.py"), thr, "Yosuf/2021 - Tren", "--execute"], env=env, cwd=HERE,
                           capture_output=True, text=True)
        open(os.path.join(T, f"salida-ids-mb-{n}.txt"), "w").write(r.stdout + r.stderr)
        return r
    r1 = ids(1)
    grabs = json.load(open(os.path.join(CACHE, "ids-mb-grabaciones.json")))
    def bien(tit):
        rid = (FLAC(rutas[tit]).get("musicbrainz_trackid") or [""])[0]
        return rid and rid != buena["musicbrainz_trackid"][0] and (nivel_titulo(tit, (grabs.get(rid) or {}).get("title") or "") or 0) >= 2
    check(r1.returncode == 0 and bien("Baby Be Mine") and bien("Beat It"),
          "IDs: Baby Be Mine y Beat It (con el ID de «Thriller», como dejó Picard) quedan con su propia grabación")
    check(FLAC(rutas["Thriller"])["musicbrainz_trackid"] == buena["musicbrainz_trackid"], "IDs: la de Thriller, que estaba bien, no se toca")
    check(not FLAC(tren).get("musicbrainz_trackid") and not FLAC(tren).get("musicbrainz_albumid"),
          "IDs: el sencillo con el ID de otra canción que MusicBrainz no tiene queda sin IDs (mejor que uno ajeno)")
    r2 = ids(2)
    check(r2.returncode == 0 and "ESCRITO: 0 canciones" in r2.stdout, "IDs: la 2ª corrida no cambia nada")
# ---------- escenario 8: otros formatos (28 sep): MP3, M4A (AAC) y Opus por el procesado completo ----------
FORMATOS = {".mp3": ("Daft Punk/1997 - Homework", "Revolution 909", ["-c:a", "libmp3lame", "-b:a", "192k"]),
            ".m4a": ("Rawayana/2026 - ¿Dónde Es El After_", "Se Presta", ["-c:a", "aac", "-b:a", "256k"]),
            ".opus": ("Gorillaz/2017 - Humanz (Deluxe)", "Interlude_ New World", ["-c:a", "libopus", "-b:a", "128k"])}
def a_formato(src, dst, args):
    """Como llegaría de otra fuente: el audio en otro formato, con las etiquetas y la carátula del FLAC (sin las del procesado)."""
    subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-map", "0:a", "-map_metadata", "-1", *args, dst], check=True)
    f, t = FLAC(src), abrir(dst)
    for k in f.keys():
        if not k.lower().startswith(PROCESADO):
            t[k] = f[k]
    for pic in f.pictures:
        t.add_picture(pic)
    t.save()
if ok:   # 8a
    FORM = "Prueba Formatos"
    os.makedirs(os.path.join(M, FORM))
    st, sids8 = json.load(open(os.path.join(M, ".antra_state.json"))), {}
    for i, (ext, (disco, tit, args)) in enumerate(FORMATOS.items(), 1):
        dst = os.path.join(M, FORM, f"{i:02d} - {tit}{ext}")
        a_formato(os.path.join(REAL, real(disco, tit)), dst, args)
        sids8[ext] = abrir(dst)["spotify_id"][0]; st[f"TRACK:spotify:{sids8[ext]}"] = dst
    open(os.path.join(M, ".antra_state.json"), "w").write(json.dumps(st, indent=2, ensure_ascii=True))
    h = json.load(open(os.path.join(T, "history.json")))
    h.insert(0, {"date": "2026-09-28T23:00:00", "title": FORM, "total": 3, "downloaded": 3, "failed": 0, "skipped": 0})
    json.dump(h, open(os.path.join(T, "history.json"), "w"))
    r = subprocess.run(["python3", os.path.join(HERE, "procesar_descarga.py"), FORM, "--execute"], env=env, cwd=HERE,
                       capture_output=True, text=True)
    open(os.path.join(T, "salida-formatos.txt"), "w").write(r.stdout + r.stderr)
    check(r.returncode == 0 and not os.path.exists(os.path.join(M, FORM)), "formatos: la descarga MP3 + M4A + Opus se procesó y su carpeta se borró")
    st = json.load(open(os.path.join(M, ".antra_state.json")))
    for ext, (disco, tit, _) in FORMATOS.items():
        final, n = st.get(f"TRACK:spotify:{sids8[ext]}") or "", f"{ext[1:].upper()} «{tit}»"
        check(final.endswith(ext) and os.path.exists(final) and os.path.dirname(os.path.relpath(final, M)) == disco,
              f"formatos: {n} en su disco, con su extensión, y el state apunta ahí ({os.path.basename(final) or '—'})")
        t = abrir(final) if os.path.exists(final) else {}
        check(bool(t) and bool(t.get("replaygain_track_gain")) and bool(t.get("genre")) and bool(t.get("genre_deezer")) and len(t.pictures) >= 1,
              f"formatos: {n} con ReplayGain {t.get('replaygain_track_gain') if t else ''}, género {t.get('genre') if t else ''} y carátula")
    hw = sorted(os.listdir(os.path.join(M, FORMATOS[".mp3"][0])))
    nums = [x.split(" - ")[0] for x in hw]
    check(any(x.endswith(".mp3") for x in hw) and any(x.endswith(".flac") for x in hw) and len(nums) == len(set(nums)),
          f"formatos: FLAC y MP3 en el mismo disco, cada uno con su número ({', '.join(hw)})")
if ok:   # 8b: MP3 cortado a la mitad (como el FLAC del escenario 2)
    CORR8 = "Prueba MP3 Cortado"
    dst = os.path.join(M, CORR8, "01 - Da Funk.mp3"); os.makedirs(os.path.dirname(dst))
    a_formato(os.path.join(REAL, real(FORMATOS[".mp3"][0], "Da Funk")), dst, FORMATOS[".mp3"][2])
    with open(dst, "r+b") as fh:
        fh.truncate(os.path.getsize(dst) // 2)
    st = json.load(open(os.path.join(M, ".antra_state.json"))); st["TRACK:spotify:mp3-cortado"] = dst
    open(os.path.join(M, ".antra_state.json"), "w").write(json.dumps(st, indent=2, ensure_ascii=True))
    r = subprocess.run(["python3", os.path.join(HERE, "procesar_descarga.py"), CORR8, "--execute"], env=env, cwd=HERE,
                       capture_output=True, text=True)
    open(os.path.join(T, "salida-mp3-cortado.txt"), "w").write(r.stdout + r.stderr)
    fall = open(os.path.join(D, "revisar_fallidas.tsv"), encoding="utf-8").read()
    st = json.load(open(os.path.join(M, ".antra_state.json")))
    check(r.returncode != 0 and "PARA" in (r.stdout + r.stderr) and not os.path.exists(dst) and "Da Funk" in fall
          and "TRACK:spotify:mp3-cortado" not in st, "MP3 cortado: se borra, se anota para re-bajar, sale del state y el procesado para")
# ---------- escenario 9 (2 oct): dos descargas que traen el audio de una canción que YA está, con otro spotify_id ----------
def descarga_de_copia(carp, origen, sid, nombre):
    """Una descarga de Antra con una COPIA de `origen` (etiquetas de la biblioteca sin las del procesado, otro spotify_id)."""
    dst = os.path.join(M, carp, nombre); os.makedirs(os.path.dirname(dst)); shutil.copy2(origen, dst)
    t = FLAC(dst)
    for k in [k for k in list(t.keys()) if k.lower().startswith(PROCESADO)]:
        del t[k]
    t["spotify_id"] = [sid]; t.save()
    st = json.load(open(os.path.join(M, ".antra_state.json"))); st[f"TRACK:spotify:{sid}"] = dst
    open(os.path.join(M, ".antra_state.json"), "w").write(json.dumps(st, indent=2, ensure_ascii=True))
    h = json.load(open(os.path.join(T, "history.json")))
    h.insert(0, {"date": f"2026-10-02T10:{len(h):02d}:00", "title": carp, "total": 1, "downloaded": 1, "failed": 0, "skipped": 0})
    json.dump(h, open(os.path.join(T, "history.json"), "w"))
    return dst
if ok:
    orig = os.path.join(M, LIB[2])   # un interludio de Humanz, en su disco con su número
    sids9 = [hashlib.sha1(f"doble{i}".encode()).hexdigest()[:22] for i in (1, 2)]
    for i, sid in enumerate(sids9, 1):
        carp = f"Prueba Doble {i}"
        dst = descarga_de_copia(carp, orig, sid, os.path.basename(orig))
        r = subprocess.run(["python3", os.path.join(HERE, "procesar_descarga.py"), carp, "--execute"], env=env, cwd=HERE,
                           capture_output=True, text=True)
        open(os.path.join(T, f"salida-doble-{i}.txt"), "w").write(r.stdout + r.stderr)
        check(r.returncode != 0 and "NO TERMINÓ" in r.stdout and os.path.exists(dst) and os.path.exists(orig),
              f"doble {i}: el procesado avisa del choque con la que ya está, la deja en su carpeta y no toca la original")
        r = subprocess.run(["python3", os.path.join(HERE, "quitar_copia.py"), os.path.relpath(dst, M), LIB[2], "--execute"], env=env,
                           cwd=HERE, capture_output=True, text=True)
        open(os.path.join(T, f"salida-doble-{i}-quitar.txt"), "w").write(r.stdout + r.stderr)
        st = json.load(open(os.path.join(M, ".antra_state.json")))
        check(r.returncode == 0 and not os.path.exists(dst) and st.get(f"TRACK:spotify:{sid}") == orig,
              f"doble {i}: quitar_copia la aparta y el state de Antra apunta a la original")
    nombre = os.path.basename(orig)
    copias = [p for p in glob.glob(os.path.join(M, "**", glob.escape(nombre)), recursive=True)]
    eqp = os.path.join(D, "decisiones", "equivalencias.tsv")
    eq = open(eqp, encoding="utf-8").read() if os.path.exists(eqp) else ""
    apartadas = glob.glob(os.path.join(D, "respaldos", "quitadas-*", "**", glob.escape(nombre)), recursive=True)
    check(copias == [orig] and all(s in eq for s in sids9) and len(apartadas) == 2,
          "doble: una sola copia en la biblioteca, las dos apartadas en respaldos y sus spotify_id en equivalencias.tsv")
# ---------- escenario 10 (2 oct): unir dos ediciones del MISMO disco (una canción repetida, una nueva) ----------
if ok:
    UN = "Banco Unir"
    def pista(disco, nombre, n, origen, isrc, sid):
        p = os.path.join(M, UN, disco, nombre); os.makedirs(os.path.dirname(p), exist_ok=True); shutil.copy2(os.path.join(REAL, origen), p)
        t = FLAC(p); t.clear()
        t.update(title=[nombre.split(" - ", 1)[1][:-5]], artist=[UN], albumartist=[UN], album=[disco.split(" - ", 1)[1]], date=[disco[:4]], tracknumber=[str(n)],
                 isrc=[isrc], spotify_id=[sid]); t.save()
        return p
    dest, delx = f"{UN}/2020 - Edicion", f"{UN}/2021 - Edicion (Deluxe)"
    for n in (1, 2, 3):
        pista("2020 - Edicion", f"0{n} - Pista {n}.flac", n, LIB[1 + n], f"BANCOUNIR00{n}", f"unir-edicion-{n}")
    d2 = pista("2021 - Edicion (Deluxe)", "01 - Pista 2.flac", 1, LIB[3], "BANCOUNIR002", "unir-deluxe-2")   # la misma grabación
    d4 = pista("2021 - Edicion (Deluxe)", "02 - Pista 4.flac", 2, LIB[0], "BANCOUNIR004", "unir-deluxe-4")   # nueva
    st = json.load(open(os.path.join(M, ".antra_state.json")))
    st.update({"TRACK:spotify:unir-deluxe-2": d2, "TRACK:spotify:unir-deluxe-4": d4})
    open(os.path.join(M, ".antra_state.json"), "w").write(json.dumps(st, indent=2, ensure_ascii=True))
    open(os.path.join(M, "_Playlists", "Unir.m3u"), "w").write(f"#EXTM3U\n../{os.path.relpath(d2, M)}\n../{os.path.relpath(d4, M)}\n")
    pend_antes = len(glob.glob(os.path.join(D, "logs", "nd-pendientes", "*.json")))
    def unir(n, *args):
        r = subprocess.run(["python3", os.path.join(HERE, "unir_discos.py"), *args, "--execute"], env=env, cwd=HERE, capture_output=True, text=True)
        open(os.path.join(T, f"salida-unir-{n}.txt"), "w").write(r.stdout + r.stderr)
        return r
    r0 = unir(0, dest, dest)
    check(r0.returncode != 0 and os.path.isdir(os.path.join(M, dest)) and len(os.listdir(os.path.join(M, dest))) == 3,
          "unir: el destino como «otra» se rechaza sin tocar nada")
    r1 = unir(1, dest, delx)
    quedan = sorted(os.listdir(os.path.join(M, dest))) if os.path.isdir(os.path.join(M, dest)) else []
    nueva = [f for f in quedan if re.match(r"^9\d\d - Pista 4\.flac$", f)]
    check(r1.returncode == 0 and not os.path.exists(os.path.join(M, delx)) and quedan[:3] == ["01 - Pista 1.flac", "02 - Pista 2.flac", "03 - Pista 3.flac"]
          and len(quedan) == 4 and nueva, f"unir: la Deluxe desapareció; el destino tiene sus 3 y la nueva provisional ({', '.join(quedan)})")
    check(glob.glob(os.path.join(D, "respaldos", "**", "01 - Pista 2.flac"), recursive=True) != [], "unir: la repetida (misma grabación) fue a respaldos")
    st = json.load(open(os.path.join(M, ".antra_state.json")))
    f4 = os.path.join(M, dest, nueva[0]) if nueva else ""
    pl = open(os.path.join(M, "_Playlists", "Unir.m3u"), encoding="utf-8").read().splitlines()
    check(st.get("TRACK:spotify:unir-deluxe-2") == os.path.join(M, dest, "02 - Pista 2.flac") and st.get("TRACK:spotify:unir-deluxe-4") == f4
          and pl[1:] == [f"../{dest}/02 - Pista 2.flac", f"../{os.path.relpath(f4, M)}"] and len(glob.glob(os.path.join(D, "logs", "nd-pendientes", "*.json"))) > pend_antes,
          "unir: state de Antra, playlist y log pendiente para Navidrome apuntan al destino")
    check(bool(f4) and FLAC(f4)["album"] == ["Edicion"] and FLAC(f4)["date"] == ["2020"], "unir: la nueva toma el nombre del disco y el año del destino")
    r2 = unir(2, dest, delx)
    check(r2.returncode != 0 and sorted(os.listdir(os.path.join(M, dest))) == quedan, "unir: la 2ª corrida (la Deluxe ya no existe) no toca nada")
# ---------- escenario 11 (2 oct): un corte a mitad de numeros_pista: la siguiente corrida termina lo que quedó ----------
if ok:
    CO = "Banco Corte/2020 - Corte"
    carp = os.path.join(M, CO); os.makedirs(carp)
    rutas11 = {}
    for n, nombre, origen in ((1, "02 - Pista 1.flac", LIB[2]), (2, "01 - Pista 2.flac", LIB[3])):   # al revés
        p = os.path.join(carp, nombre); shutil.copy2(os.path.join(REAL, origen), p)
        t = FLAC(p); t.clear()
        t.update(title=[f"Pista {n}"], artist=["Banco Corte"], albumartist=["Banco Corte"], album=["Corte"], date=["2020"],
                 tracknumber=[nombre[:2].lstrip("0")], isrc=[f"BANCOCORTE0{n}"], spotify_id=[f"corte-{n}"]); t.save()
        rutas11[n] = p
    st = json.load(open(os.path.join(M, ".antra_state.json")))
    st.update({f"TRACK:spotify:corte-{n}": p for n, p in rutas11.items()})
    open(os.path.join(M, ".antra_state.json"), "w").write(json.dumps(st, indent=2, ensure_ascii=True))
    AID = 990000001   # un disco de Deezer de mentira, solo en la caché del banco
    sembrar("deezer-numeros.json", {f"https://api.deezer.com/album/{AID}": {"id": AID, "title": "Corte", "release_date": "2020-01-01", "nb_tracks": 2},
            f"https://api.deezer.com/album/{AID}/tracks?limit=300": {"data": [
                {"track_position": n, "disk_number": 1, "isrc": f"BANCOCORTE0{n}", "title": f"Pista {n}", "duration": round(abrir(p).info.length)}
                for n, p in rutas11.items()]}})
    corte = f"""import os, runpy, sys
n = [0]; rr = os.rename
def r3(a, b):
    n[0] += 1
    if n[0] == 3: raise KeyboardInterrupt   # entre «viejo → temporal» y «temporal → final»
    rr(a, b)
os.rename = r3
sys.argv = ["numeros_pista.py", "--a-mano", {CO!r}, "--deezer", "{AID}", "--execute"]
runpy.run_path(os.path.join({HERE!r}, "numeros_pista.py"), run_name="__main__")
"""
    r1 = subprocess.run(["python3", "-c", corte], env=env, cwd=HERE, capture_output=True, text=True)
    open(os.path.join(T, "salida-corte-1.txt"), "w").write(r1.stdout + r1.stderr)
    en_curso = os.path.join(D, "logs", "tracknums-en-curso.json")
    check(r1.returncode != 0 and any(f.startswith(".tn-tmp") for f in os.listdir(carp)) and os.path.exists(en_curso),
          "corte: numeros_pista se cortó entre los dos pasos: quedan .tn-tmp-N y tracknums-en-curso.json")
    r2 = subprocess.run(["python3", os.path.join(HERE, "numeros_pista.py"), "--a-mano", CO, "--deezer", str(AID), "--execute"], env=env, cwd=HERE,
                        capture_output=True, text=True)
    open(os.path.join(T, "salida-corte-2.txt"), "w").write(r2.stdout + r2.stderr)
    st = json.load(open(os.path.join(M, ".antra_state.json")))
    check(r2.returncode == 0 and sorted(os.listdir(carp)) == ["01 - Pista 1.flac", "02 - Pista 2.flac"] and not os.path.exists(en_curso)
          and st.get("TRACK:spotify:corte-1") == os.path.join(carp, "01 - Pista 1.flac") and all(os.path.exists(v) for v in st.values()),
          "corte: la siguiente corrida termina el renombrado y el state de Antra queda sano")
# ---------- escenario 12 (2 oct): el embudo reemplaza un MP3 por su FLAC por ISRC solo si dura lo mismo ----------
if ok:
    import sqlite3
    PR, ND = os.path.join(M, "_Prueba"), os.path.join(T, "navidrome", "data"); os.makedirs(ND)
    hum = os.path.join(PR, HUMANZ); os.makedirs(hum)
    igual = os.path.join(hum, "03 - Interlude_ Penthouse.mp3")     # mismo ISRC y misma duración que su FLAC → se reemplaza
    corta = os.path.join(hum, "04 - Interlude_ The Elephant.mp3")  # mismo ISRC pero 10 s menos (otra edición) → NO
    a_formato(os.path.join(M, LIB[3]), igual, ["-c:a", "libmp3lame", "-b:a", "128k"])
    a_formato(os.path.join(M, LIB[4]), corta, ["-t", f"{abrir(os.path.join(M, LIB[4])).info.length - 10:.2f}", "-c:a", "libmp3lame", "-b:a", "128k"])
    hace3 = time.strftime("%Y-%m-%dT%H:%M:%S.0000000Z", time.gmtime(time.time() - 3 * 86400))
    json.dump({f"deezer:{i}": {"LocalPath": p.replace(PR, "/app/downloads", 1), "ExternalId": str(i), "ExternalProvider": "deezer", "DownloadedAt": hace3}
               for i, p in enumerate((igual, corta), 1)}, open(os.path.join(PR, ".mappings.json"), "w"), indent=1)
    con = sqlite3.connect(os.path.join(ND, "navidrome.db"))
    con.executescript("""create table media_file(id text primary key, path text, missing int default 0, created_at text, artist text, tags text, album_id text);
        create table scrobbles(media_file_id text, submission_time real);
        create table annotation(item_type text, item_id text, user_id text, play_count int, play_date text, starred int, starred_at text, rating int);""")
    for i, p in enumerate((igual, corta), 1):
        con.execute("insert into media_file values (?,?,0,?,?,?,?)", (f"mp3-{i}", os.path.relpath(p, M), hace3[:19], "Gorillaz", json.dumps({"genre": [{"value": "Prueba"}]}), "alb"))
    con.commit(); con.close()
    r = subprocess.run(["python3", os.path.join(HERE, "prueba.py"), "revisar", "--execute"], env=env, cwd=HERE, capture_output=True, text=True)
    open(os.path.join(T, "salida-embudo.txt"), "w").write(r.stdout + r.stderr)
    resp = glob.glob(os.path.join(D, "respaldos", "prueba-*", "**", "03 - Interlude_ Penthouse.mp3"), recursive=True)
    check(r.returncode == 0 and not os.path.exists(igual) and resp, "embudo: el MP3 con el ISRC y la duración de su FLAC se reemplaza (va a respaldos, no se borra)")
    check(os.path.exists(corta) and "mismo ISRC pero otra duración" in r.stdout, "embudo: el MP3 con el mismo ISRC pero otra duración NO se reemplaza, y se dice")
    logs12 = [json.load(open(f)) for f in glob.glob(os.path.join(D, "logs", "nd-pendientes", "*-prueba.json"))]
    check(any(c["old_path"] == igual and c["new_path"] == os.path.join(M, LIB[3]) for lg in logs12 for c in lg["cambios"]),
          "embudo: el log pendiente pasa las escuchas del MP3 a su FLAC")
check(huella() == antes, "la biblioteca real y sus listas/planes NO se tocaron")
print("\nRESULTADO:", "✅ TODO BIEN" if ok else "❌ HAY PROBLEMAS", f"(salidas en {T}/salida-*.txt)")
sys.exit(0 if ok else 1)
