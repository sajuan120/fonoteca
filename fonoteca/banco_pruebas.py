#!/usr/bin/env python3
"""Banco de pruebas: corre procesar_descarga.py COMPLETO sobre una biblioteca de mentira y comprueba el resultado.
Correrlo después de cambiar cualquier script. No toca la biblioteca real, ni sus listas/logs, ni Navidrome.

Uso: banco_pruebas.py            (tarda 1-3 min; deja todo en rutas.banco de config.toml para mirarlo, se rehace cada vez)

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
"""
import glob, hashlib, json, os, shutil, subprocess, sys
from mutagen.flac import FLAC
from audio import abrir, es_audio

from comun import ruta, BANCO, DOC, DOC_FLAC, DOC_AUDITORIA
REAL = ruta("biblioteca", "~/Music")   # la biblioteca de verdad (de ahí salen las canciones de prueba; no se toca)
HERE = os.path.dirname(os.path.abspath(__file__))
T = BANCO                             # config.toml: rutas.banco (se rehace en cada corrida)
M, D = os.path.join(T, "Music"), os.path.join(T, "datos")
DESC = "Prueba Descarga"
def real(carpeta, titulo):
    """Ruta (relativa a REAL) de UNA canción real, por su título con cualquier número adelante: los números cambian al
    renumerar (27 sep: «15 - Funk Ad» pasó a «16 - Funk Ad» y el banco se caía al armar)."""
    ms = glob.glob(os.path.join(glob.escape(os.path.join(REAL, carpeta)), "*" + glob.escape(f" - {titulo}.flac")))
    assert len(ms) == 1, f"banco: no encuentro UNA canción real «{titulo}» en {carpeta}: {ms}"
    return os.path.relpath(ms[0], REAL)
SHREK, HUMANZ = "Soundtracks/2004 - Soundtrack Shrek 2", "Gorillaz/2017 - Humanz (Deluxe)"   # 28 sep: OST por franquicia
LIB = [real(SHREK, "Accidentally In Love - From _Shrek 2_ Soundtrack"), real(SHREK, "Holding Out For A Hero"),
       real(HUMANZ, "Interlude_ Elevator Going Up"), real(HUMANZ, "Interlude_ Penthouse"), real(HUMANZ, "Interlude_ The Elephant")]
NUEVAS = [(LIB[0], {"title": ["Accidentally In Love"], "album": ["Accidentally In Love"], "albumartist": ["Counting Crows"],
                    "spotify_id": ["4ccM2xBxicGigjLqt6A0YY"]}),   # el single: audio del soundtrack, tags del single
          real(HUMANZ, "Interlude_ Talk Radio"), real("Daft Punk/1997 - Homework", "WDPK 83.7 FM"),
          real("Rawayana/2026 - ¿Dónde Es El After_", "Si Te Pica Es Porque Eres Tú")]
FUNK_AD = real("Daft Punk/1997 - Homework", "Funk Ad")
NO_BAJO = "53QdfEoKCXlEfjgXPmvPjx"   # Shaky Shaky (Remix), Daddy Yankee
PROCESADO = ("musicbrainz_", "replaygain_", "genre_deezer", "originaldate")   # tags que pone el procesado: se quitan

def huella():
    """Estado de lo real que NO debe cambiar: canciones de la biblioteca y listas/planes reales."""
    n = sum(1 for d, _, fs in os.walk(REAL) for f in fs if es_audio(f) and os.path.relpath(d, REAL).count(os.sep) >= 1
            and os.path.relpath(d, REAL).split(os.sep)[0] != "_Prueba")   # _Prueba cambia sola (Octo-Fiesta)
    h = hashlib.sha1()
    for f in ["revisar_fallidas.tsv", "revisar_dudosas.tsv", "planes/plan-reparto.json", "planes/plan-generos.json",
              DOC, DOC_FLAC, DOC_AUDITORIA]:   # 1 oct: también los documentos reales (el banco pisaba el «conseguir en FLAC»)
        p = os.path.join(HERE, f)
        h.update(open(p, "rb").read() if os.path.exists(p) else b"-")
    return n, h.hexdigest()

# ---------- armar ----------
antes = huella()
shutil.rmtree(T, ignore_errors=True)
os.makedirs(os.path.join(M, "_Playlists")); os.makedirs(os.path.join(T, "listas", "Prueba")); os.makedirs(D)
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

env = dict(os.environ, MUSIC_ROOT=M, MUSIC_DATOS=D, MUSIC_DOC=os.path.join(T, "pendientes.md"),
           ANTRA_HISTORY=os.path.join(T, "history.json"), MUSIC_LISTAS=os.path.join(T, "listas"))
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
        check(bool(t.get("musicbrainz_trackid")) or "Rawayana" in p, f"{n}: ID de MusicBrainz")
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
REEA = os.path.join(REAL, real("Reea/2011 - Need Me Baby", "Need Me Baby - Radio Edit"))   # AcoustID no la conoce
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
if ok:   # 5a: el audio es OTRA canción (Daramola) con las etiquetas de la correcta (Reea): 7,5 s menos, AcoustID no la conoce
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
if ok:   # 5b: la canción CORRECTA pero 8 s más corta: es su audio (la vista previa coincide), ¿cortada u otra edición? → dudosa
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
if ok:
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
    grabs = json.load(open(os.path.join(HERE, "cache", "ids-mb-grabaciones.json")))
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
check(huella() == antes, "la biblioteca real y sus listas/planes NO se tocaron")
print("\nRESULTADO:", "✅ TODO BIEN" if ok else "❌ HAY PROBLEMAS", f"(salidas en {T}/salida-*.txt)")
sys.exit(0 if ok else 1)
