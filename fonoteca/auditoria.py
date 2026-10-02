#!/usr/bin/env python3
"""Auditoría de toda la biblioteca, versión 2. SOLO LEE: no toca música, etiquetas, Navidrome ni listas (26 sep 2026).

Uso: auditoria.py [--sin-audio] [--sin-red]
  Escribe ~/Documents/Música - auditoría.md y planes/auditoria-<sección>.tsv (listas completas).
  Cada sección es una de tres:
    🔴 ARREGLAR  = está mal y tiene arreglo claro (con las reglas ya decididas).
    🟡 DECIDIR   = puede estar bien o mal; se decide a mano.
    ⚪ INFO      = está bien así o no hace falta hacer nada; solo para saber.
  1. Audio: flac -t (integridad), sin firma MD5, duración rara.
  2. Etiquetas: faltantes, varios valores, texto roto, fechas, género, ruta vs etiquetas (con la MISMA regla de
     numeros_pista.py para el prefijo de disco: "D-NN" si la carpeta tiene canciones de un disco 2 o más, o si todos sus
     archivos ya lo usan).
  3. Letras y carátulas.
  4. Discos y artistas: pistas repetidas, discos partidos o mezclados, el mismo disco en dos carpetas (nombre mal
     escrito ≠ otra edición ≠ un remix del sencillo), el mismo artista con dos nombres.
  5. Canciones: copias repetidas (mismo audio y mismo título), IDs equivocados (misma grabación/ISRC pero otro
     audio; y desde el 27 sep CADA ID de grabación contra su grabación de MusicBrainz, con la caché de ids_mb.py y sus
     aceptados), y MISMO AUDIO con otro título → se confirma cuál está mal con la vista previa de su canción EXACTA de
     Spotify (correctas 0,89-0,99; equivocadas 0,50-0,75; calibrado 25 sep).
  6. Navidrome: discos partidos o unidos, diferencias con el disco.
  Lo lento (flac -t, huellas, vistas previas) queda en caché por archivo (cache/auditoria-*.json).
  --sin-audio: no corre flac -t ni huellas nuevas (usa la caché).   --sin-red: no consulta Spotify (usa la caché).
"""
import base64, collections, concurrent.futures as cf, datetime, difflib, hashlib, json, os, re, sqlite3, subprocess, sys
import numpy as np
from red import Cache, pedir_json
from audio import abrir, es_audio, RE_EXT, verificar, con_perdida
from comun import base_disco, nivel_titulo, decision, DOC_AUDITORIA, NAVIDROME_DB, plano, ROOT, plan_path, cache_path, clave_titulo, clave_artista, _plano, parecido_spotify, grabacion_corresponde, leer_json, guardar_json

SIN_AUDIO, SIN_RED = "--sin-audio" in sys.argv, "--sin-red" in sys.argv
DOC, NDDB = DOC_AUDITORIA, NAVIDROME_DB   # config.toml
HILOS = 12
MISMO_AUDIO, OTRO_AUDIO = 0.9, 0.75          # parecido entre dos archivos
SPOT_BIEN, SPOT_MAL = 0.85, 0.8              # parecido de un archivo con la vista previa de su canción de Spotify
BAD = str.maketrans({c: "_" for c in '/\\:*?"<>|'})          # misma regla que repartir.py
def clean_file(s): return s.translate(BAD).strip() or "_"
def clean_dir(s): return s.translate(BAD).strip().rstrip(". ") or "_"
from generos_reglas import MAPA
GENEROS = set(MAPA)
HOY = datetime.date.today()
def log(*a): print(*a, flush=True)
def tamano(pc):
    """Ancho y alto de la carátula; si el bloque no lo guarda (0x0), se lee de la imagen."""
    if pc.width and pc.height: return pc.width, pc.height
    try:
        from PIL import Image; import io
        return Image.open(io.BytesIO(pc.data)).size
    except Exception:
        return 0, 0

# ---------------------------------------------------------------- 0. leer la biblioteca
log("leyendo la biblioteca...")
flacs, otros, vacias = [], [], []
for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if not d.startswith(".") and not (dp == ROOT and d == "_Prueba")]   # _Prueba: MP3 de Octo-Fiesta
    rel_d = os.path.relpath(dp, ROOT)
    if not dns and not fns and rel_d != ".": vacias.append(rel_d)
    for fn in fns:
        rel = os.path.normpath(os.path.join(rel_d, fn))
        if es_audio(fn): flacs.append(rel)
        elif not (rel.startswith("_Playlists" + os.sep) and fn.endswith(".m3u")) and fn not in (".antra_state.json", "LEER CLAUDE.txt", ".ndignore"):
            otros.append(rel)
flacs.sort()
R = {}   # rel → registro
for i, rel in enumerate(flacs):
    if i % 1000 == 0: log(f"  {i}/{len(flacs)}")
    p = os.path.join(ROOT, rel); st = os.stat(p)
    x = {"rel": rel, "size": st.st_size, "mtime": st.st_mtime_ns, "ino": st.st_ino, "nlink": st.st_nlink, "parts": rel.split(os.sep)}
    try:
        f = abrir(p)
    except Exception as e:
        x["error"] = str(e)[:200]; R[rel] = x; continue
    x["tags"] = {k.lower(): list(f[k]) for k in f.keys()}   # 28 sep: f.keys() vale para todos los formatos
    x["len"], x["sr"], x["bits"], x["ch"] = f.info.length, f.info.sample_rate, f.info.bits_per_sample, f.info.channels
    x["md5"] = f.info.md5_signature if rel.lower().endswith(".flac") else 1   # la firma MD5 solo existe en FLAC
    x["con_perdida"] = con_perdida(p) and f"{os.path.splitext(rel)[1][1:].upper()} {round(f.info.bitrate / 1000)} kbps"
    x["pics"] = [(pc.type, *(tamano(pc)), len(pc.data), hashlib.sha1(pc.data).hexdigest()[:12]) for pc in f.pictures]
    R[rel] = x
def g(x, k): return (x.get("tags", {}).get(k) or [""])[0].strip()
def gl(x, k): return [v for v in x.get("tags", {}).get(k, []) if v.strip()]
album_rels = [r for r in flacs if len(R[r]["parts"]) == 3 and "error" not in R[r]]
carpetas = collections.defaultdict(list)
for r in album_rels: carpetas[os.path.dirname(r)].append(r)
por_art = collections.defaultdict(list)
for d in carpetas: por_art[d.split(os.sep)[0]].append(d)

# ---------------------------------------------------------------- 1. integridad (flac -t) y huellas, con caché
def cacheado(nombre):
    p = cache_path(nombre)
    return leer_json(p, {}), p   # 2 oct: una caché truncada se aparta en vez de tumbar la auditoría
def vigente(c, x): return c and c[0] == x["size"] and c[1] == x["mtime"]
ft, ftp = cacheado("auditoria-flac-t.json")
pend = [r for r in flacs if not vigente(ft.get(r), R[r])]
if pend and not SIN_AUDIO:
    log(f"integridad de {len(pend)} archivos...")
    def probar(rel):   # 28 sep: audio.verificar (flac -t en FLAC; los demás, decodificar entero + duración)
        ok, msg = verificar(os.path.join(ROOT, rel))
        msg = " ".join(l for l in (msg or "").splitlines() if "MD5 signature since it was unset" not in l)   # eso va en "sin firma MD5"
        return rel, 0 if ok else 1, msg.strip()[:300]
    with cf.ThreadPoolExecutor(HILOS) as ex:
        for n, (rel, rc, msg) in enumerate(ex.map(probar, pend)):
            ft[rel] = [R[rel]["size"], R[rel]["mtime"], rc, msg]
            if n % 500 == 0: log(f"  {n}/{len(pend)}")
    guardar_json(ftp, ft)
hu, hup = cacheado("auditoria-huellas.json")
pend = [r for r in album_rels if not vigente(hu.get(r), R[r])]
if pend and not SIN_AUDIO:
    log(f"huellas de audio de {len(pend)} archivos...")
    def huella(rel):
        r = subprocess.run(["fpcalc", "-raw", "-json", "-length", "120", os.path.join(ROOT, rel)], capture_output=True, text=True)
        try:
            fp = json.loads(r.stdout)["fingerprint"]
            return rel, base64.b64encode(np.array(fp, dtype=np.uint32).tobytes()).decode()
        except (ValueError, KeyError):
            return rel, ""
    with cf.ThreadPoolExecutor(HILOS) as ex:
        for n, (rel, b) in enumerate(ex.map(huella, pend)):
            hu[rel] = [R[rel]["size"], R[rel]["mtime"], b]
            if n % 500 == 0: log(f"  {n}/{len(pend)}")
    guardar_json(hup, hu)
FP = {r: np.frombuffer(base64.b64decode(hu[r][2]), dtype=np.uint32) for r in album_rels if vigente(hu.get(r), R[r]) and hu[r][2]}
_POP = np.array([bin(i).count("1") for i in range(65536)], dtype=np.uint8)
def parecido(a, b, offsets=None):
    """Mejor parecido (0-1) entre dos huellas, deslizando una sobre otra (mismo cálculo que comun.parecido_spotify)."""
    if len(a) < 20 or len(b) < 20: return None
    if offsets is None:
        lim = int(max(len(a), len(b)) * 0.3)
        offsets = range(-lim, lim + 1, 2)
    mejor = 0.0
    for off in offsets:
        sa, sb = (a[off:], b) if off >= 0 else (a, b[-off:])
        n = min(len(sa), len(sb))
        if n < 0.5 * min(len(a), len(b)): continue
        x = np.bitwise_xor(sa[:n], sb[:n])
        bits = int(_POP[x & 0xFFFF].sum()) + int(_POP[x >> 16].sum())
        mejor = max(mejor, 1 - bits / (32 * n))
    return round(mejor, 3)
def offsets_probables(a, b, k=3):
    """Desplazamientos donde más valores coinciden exacto (para no probar todos)."""
    pos = collections.defaultdict(list)
    for i, v in enumerate(a.tolist()): pos[v].append(i)
    c = collections.Counter()
    for j, v in enumerate(b.tolist()):
        for i in pos.get(v, ())[:5]: c[i - j] += 1
    offs = set()
    for o, _ in c.most_common(k):
        offs.update(range(o - 2, o + 3))
    return sorted(offs) or None
def par_audio(a, b):
    """Parecido de dos archivos: primero en los desplazamientos probables; si no da mismo audio, búsqueda completa."""
    if a not in FP or b not in FP: return None
    s = parecido(FP[a], FP[b], offsets_probables(FP[a], FP[b])) or 0
    return s if s >= MISMO_AUDIO else max(s, parecido(FP[a], FP[b]) or 0)
sp, spp = cacheado("auditoria-spotify.json")
def contra_spotify(rel):
    """Parecido del archivo con la vista previa de SU canción de Spotify (None = sin spotify_id, sin vista previa o sin red)."""
    x = R[rel]; sid = g(x, "spotify_id")
    c = sp.get(rel)
    if vigente(c, x) and c[2] == sid: return c[3]
    if SIN_RED or not sid: return None
    s = parecido_spotify(sid, os.path.join(ROOT, rel))
    if s is not None:
        sp[rel] = [x["size"], x["mtime"], sid, s]; guardar_json(spp, sp)
    return s

# ---------------------------------------------------------------- informe
SECS = []   # (tipo, clave, titulo, filas, cols, nota, arreglo, max_filas, unidad)
TIPOS = {"arreglar": "🔴 Hay que arreglar", "decidir": "🟡 Te toca decidir", "info": "⚪ Está bien o solo para saber"}
def seccion(tipo, clave, titulo, filas, cols, nota="", arreglo="", max_filas=40, unidad="casos"):
    SECS.append((tipo, clave, titulo, filas, cols, nota, arreglo, max_filas, unidad))
def dur(r): return f"{R[r]['len']:.0f}s"

# ---------------------------------------------------------------- 1. audio
malos = sorted((r, v[2], v[3]) for r, v in ft.items() if r in R and vigente(v, R[r]) and (v[2] != 0 or v[3]))
sin_probar = [r for r in flacs if not vigente(ft.get(r), R[r])]
seccion("arreglar", "corruptos", "Archivos dañados (la prueba de integridad da error)", malos, ["archivo", "código", "mensaje"],
        f"Probados {len(flacs) - len(sin_probar)} de {len(flacs)}." + (f" Sin probar: {len(sin_probar)}." if sin_probar else ""),
        "Borrar con borrar_canciones.py y re-bajar.", unidad="canciones")
seccion("arreglar", "ilegibles", "Archivos que no se pueden leer", [(r, R[r]["error"]) for r in flacs if "error" in R[r]], ["archivo", "error"],
        arreglo="Borrar y re-bajar.", unidad="canciones")
seccion("info", "sin_md5", "Sin firma MD5", [(r,) for r in album_rels if not R[r]["md5"]], ["archivo"],
        "Así los entrega Antra; el audio se decodificó entero sin errores, solo que flac -t no puede compararlo con una firma.",
        max_filas=5, unidad="canciones")
raros = [(r, f"{R[r]['len']:.0f} s") for r in album_rels if R[r]["len"] < 20] + [(r, f"{R[r]['len']/60:.1f} min") for r in album_rels if R[r]["len"] > 20 * 60]
seccion("info", "duracion_rara", "Duración rara (menos de 20 s o más de 20 min)", sorted(raros), ["archivo", "duración"],
        "Intros, interludios y mezclas largas; todas pasaron la prueba de integridad.", unidad="canciones")
seccion("info", "con_perdida", "Canciones con pérdida (MP3, AAC, Opus…)", [(r, R[r]["con_perdida"]) for r in album_rels if R[r]["con_perdida"]],
        ["archivo", "formato"], "La biblioteca es FLAC; estas llegaron en otro formato (descarga a mano o prueba adoptada).",
        unidad="canciones")

# ---------------------------------------------------------------- 1b. archivos y carpetas
PAT_DIR, PAT_FN = re.compile(r"^\d{4} - .+"), re.compile(r"^(\d+-)?\d{2,3} - .+" + RE_EXT + "$")
fuera = []
for r in flacs:
    p = R[r]["parts"]
    if len(p) != 3: fuera.append((r, f"profundidad {len(p)} (debe ser Artista/Álbum/archivo)"))
    elif not PAT_FN.match(p[2]): fuera.append((r, "nombre no es NN - Título"))
seccion("arreglar", "fuera_patron", "Archivos fuera del patrón Artista/AAAA - Álbum/NN - Título", fuera, ["archivo", "problema"],
        arreglo="repartir.py / numeros_pista.py.", unidad="canciones")
seccion("arreglar", "sin_anio", "Carpetas de disco sin año",
        sorted({(os.sep.join(R[r]["parts"][:2]), g(R[r], "date") or "(sin fecha)") for r in album_rels if not PAT_DIR.match(R[r]["parts"][1])}),
        ["carpeta", "fecha en las etiquetas"], arreglo="Renombrar a «AAAA - Álbum» con la fecha de las etiquetas (y buscar la fecha si falta).",
        unidad="discos")
seccion("arreglar", "vacias", "Carpetas vacías", [(r,) for r in sorted(vacias)], ["carpeta"],
        arreglo="Borrarlas (quedaron de canciones movidas o borradas).", unidad="carpetas")
seccion("arreglar", "otros", "Archivos que no son música dentro de la biblioteca", [(r,) for r in sorted(otros)], ["archivo"], unidad="archivos")
por_ino = collections.defaultdict(list)
for r in flacs: por_ino[R[r]["ino"]].append(r)
seccion("info", "hardlinks", "El mismo archivo en dos lugares (hardlink)", [(" ⟷ ".join(v),) for v in por_ino.values() if len(v) > 1] +
        [(r + f" (tiene {R[r]['nlink']} enlaces, el otro fuera de la biblioteca)",) for r in flacs if R[r]["nlink"] > 1 and len(por_ino[R[r]["ino"]]) == 1],
        ["archivos"], "No ocupa espacio doble; el otro enlace suele ser un respaldo en ~/music-tools/respaldos.", unidad="archivos")

# ---------------------------------------------------------------- 2. etiquetas
BASICAS = ["title", "artist", "albumartist", "album", "date", "tracknumber"]
seccion("arreglar", "faltan_basicas", "Faltan etiquetas básicas (título, artista, disco, fecha, número)",
        [(r, ", ".join(k for k in BASICAS if not gl(R[r], k))) for r in album_rels if any(not gl(R[r], k) for k in BASICAS)],
        ["archivo", "faltan"], unidad="canciones")
UNO = ["title", "album", "albumartist", "date", "tracknumber", "discnumber", "spotify_id"]
seccion("arreglar", "varios_valores", "Varios valores donde va uno (Navidrome puede partir el disco)",
        [(r, k, " ; ".join(gl(R[r], k))) for r in album_rels for k in UNO if len(gl(R[r], k)) > 1], ["archivo", "etiqueta", "valores"],
        arreglo="Dejar un solo valor.", unidad="canciones")
seccion("info", "varios_isrc", "Canciones con varios ISRC", [(r, " ; ".join(gl(R[r], "isrc"))) for r in album_rels if len(gl(R[r], "isrc")) > 1],
        ["archivo", "ISRC"], "La misma grabación publicada en varios lanzamientos tiene varios ISRC; guardarlos todos ayuda a encontrarla.",
        max_filas=5, unidad="canciones")
MOJI = re.compile(r"Ã[\x80-\xbf]|Â[\x80-\xbf ]|â€|�|[\x00-\x08\x0b-\x1f]")
HTML_ENT = re.compile(r"&(apos|amp|quot|lt|gt|#\d+);")
rar = []
for r in album_rels:
    for k in ["title", "artist", "albumartist", "album"]:
        for v in R[r]["tags"].get(k, []):
            if MOJI.search(v): rar.append((r, k, v, "caracteres rotos"))
            elif v != v.strip(): rar.append((r, k, repr(v), "espacios al borde"))
            elif "  " in v: rar.append((r, k, v, "doble espacio"))
            elif HTML_ENT.search(v): rar.append((r, k, v, "entidad HTML (&apos; en vez de ')"))   # 30 sep: Salgo Pa&apos; la Calle
seccion("arreglar", "texto_raro", "Texto roto en etiquetas", rar, ["archivo", "etiqueta", "valor", "problema"],
        arreglo="Corregir a mano (caracteres rotos: copiar el texto de Spotify).", unidad="valores")
# 30 sep: 4 M4A tenían el ISRC como «B'QZMEP2276434'» (texto de Python de unos bytes) y no servía para emparejar
PAT_ISRC = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
seccion("arreglar", "isrc_raro", "ISRC mal escrito (no sirve para emparejar)",
        [(r, v) for r in album_rels for v in gl(R[r], "isrc") if not PAT_ISRC.match(v)], ["archivo", "ISRC"],
        arreglo="Escribirlo limpio (12 caracteres: país, registrante, año y número), p. ej. con el de Deezer.", unidad="canciones")
PAT_FECHA = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
fechas = []
for r in album_rels:
    d = g(R[r], "date")
    if d and not PAT_FECHA.match(d): fechas.append((r, d, "formato raro"))
    elif d and (int(d[:4]) < 1900 or int(d[:4]) > HOY.year): fechas.append((r, d, "año fuera de rango"))
seccion("arreglar", "fechas", "Fechas raras", fechas, ["archivo", "fecha", "problema"], unidad="canciones")
seccion("arreglar", "genero_fuera", "Género vacío o fuera de la lista de 20",
        [(r, " ; ".join(gl(R[r], "genre")) or "(vacío)") for r in album_rels if not gl(R[r], "genre") or any(v not in GENEROS for v in gl(R[r], "genre"))],
        ["archivo", "género"], arreglo="generos.py (si Deezer no tiene el artista: ponerlo a mano en su mapa).", unidad="canciones")
gen_art = collections.defaultdict(set)
for r in album_rels:
    aa = g(R[r], "albumartist")
    if aa == "Soundtracks":   # 30 sep: cada OST lleva los géneros de SU artista (hasta 2) + «Soundtrack» (generos.py)
        gen_art[f"Soundtracks: {g(R[r], 'artist')}"].update(set(gl(R[r], "genre")) - {"Soundtrack"})
    elif plano(aa) not in ("variousartists", "variosartistas"): gen_art[aa].update(gl(R[r], "genre"))
seccion("arreglar", "artista_mas_2", "Artistas con más de 2 géneros (la regla es hasta 2)",
        sorted((a, " ; ".join(sorted(s))) for a, s in gen_art.items() if len(s) > 2), ["artista", "géneros"], unidad="artistas")

# ruta vs etiquetas — prefijo de disco con la misma regla que numeros_pista.py (27 sep): «D-NN» si la edición tiene más
# de un disco. Desde aquí no se sabe la edición, así que se pide coherencia: prefijo si alguna canción de la carpeta es
# de un disco 2 o más, o si todos sus archivos ya lo usan (disco doble del que solo tenemos canciones del disco 1).
def disco(r):
    m_ = re.match(r"\d+", g(R[r], "discnumber"))
    return int(m_.group()) if m_ else 1
pref_mal, art_carpeta, anio_mal, alb_mal = [], collections.defaultdict(collections.Counter), [], []
for d, rs in sorted(carpetas.items()):
    pref = any(disco(r) > 1 for r in rs) or all(re.match(r"^\d+-\d+ - ", R[r]["parts"][2]) for r in rs)
    art, alb = d.split(os.sep)
    m = re.match(r"(\d{4}) - (.+)$", alb)
    for r in rs:
        x = R[r]; aa, al = g(x, "albumartist") or g(x, "artist"), g(x, "album")
        if aa and clean_dir(aa).lower() != art.lower(): art_carpeta[d][aa] += 1
        if m and g(x, "date")[:4] and m.group(1) != g(x, "date")[:4]: anio_mal.append((r, m.group(1), g(x, "date")))
        if m and al and m.group(2).lower() != clean_dir(al).lower(): alb_mal.append((r, m.group(2), al))
        tn = re.match(r"\d+", g(x, "tracknumber"))
        if not tn or len(rs) < 2: continue        # numeros_pista.py solo numera carpetas de 2 o más canciones
        esperado = (f"{disco(r)}-" if pref else "") + f"{int(tn.group()):02d} - "
        if not x["parts"][2].startswith(esperado):
            pref_mal.append((r, x["parts"][2].split(" - ")[0], esperado.rstrip(" -")))
seccion("arreglar", "numero_archivo", "El número del nombre del archivo no coincide con sus etiquetas", pref_mal,
        ["archivo", "en el nombre", "según etiquetas"],
        "Regla (la de numeros_pista.py): «D-NN» si alguna canción de la carpeta es de un disco 2 o más, o si todos sus archivos "
        "ya lo usan; si no, «NN». El número tiene que ser el de las etiquetas.",
        "numeros_pista.py (paso 7) las renumbera solo si encuentra una edición de Deezer (o MusicBrainz) con todas las canciones "
        "de la carpeta; las que no, salen en «a mano» del documento de pendientes.", unidad="canciones")
seccion("arreglar", "anio_carpeta", "El año de la carpeta no coincide con la fecha", anio_mal, ["archivo", "carpeta", "fecha"], unidad="canciones")
seccion("arreglar", "album_carpeta", "El nombre de la carpeta no coincide con el disco", alb_mal, ["archivo", "carpeta", "etiqueta album"], unidad="canciones")
filas_ac, filas_ac_info = [], []
for d, c in sorted(art_carpeta.items()):
    art = d.split(os.sep)[0]
    artistas = {plano(clean_dir(a)) for r in carpetas[d] for v in gl(R[r], "artist") for a in re.split(r"\s*(?:,|&|;| feat\.? | x )\s*", v)}
    fila = (d, " / ".join(f"{a}×{n}" for a, n in c.most_common()), f"{sum(c.values())} de {len(carpetas[d])}")
    (filas_ac_info if plano(art) in artistas else filas_ac).append(fila)
seccion("decidir", "carpeta_artista", "Discos guardados en la carpeta de otro artista", filas_ac, ["carpeta", "artista del disco (etiqueta)", "canciones"],
        "Navidrome se guía por las etiquetas: esto solo afecta el orden de las carpetas. Casi todos son soundtracks o recopilatorios.",
        "¿Mover cada disco a la carpeta de su artista del disco (Various Artists, compositor…)?", unidad="discos")
seccion("info", "carpeta_artista_ok", "Discos en la carpeta de un artista que sí canta en ellos", filas_ac_info,
        ["carpeta", "artista del disco (etiqueta)", "canciones"], "Ej.: un disco de Bad Bunny guardado en Yandel porque Yandel está en la canción.",
        max_filas=10, unidad="discos")

# ---------------------------------------------------------------- 3. letras y carátulas
TS = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
let_falta, let_plana, let_larga, let_larga_poco, let_contra = [], [], [], [], []
for r in album_rels:
    x = R[r]; ly = g(x, "lyrics") or g(x, "unsyncedlyrics"); instr = g(x, "lrclib_instrumental") == "1"
    if instr and ly: let_contra.append((r, "marcada instrumental pero tiene letra"))
    if not ly and not instr: let_falta.append((r,)); continue
    if ly and not TS.search(ly): let_plana.append((r,))
    marcas = [int(m) * 60 + float(s) for m, s in TS.findall(ly or "")]
    if marcas and max(marcas) > x["len"] + 5:
        (let_larga if max(marcas) > x["len"] + 12 else let_larga_poco).append((r, f"{max(marcas):.0f} s", f"{x['len']:.0f} s"))
seccion("arreglar", "letra_larga", "Letra sincronizada de otra versión (sigue mucho después del final)", let_larga,
        ["archivo", "última línea", "dura"], arreglo="Borrar esa letra y buscar la de esta versión (letras.py con la duración correcta).",
        unidad="canciones")
seccion("arreglar", "letra_contra", "Marcada instrumental pero con letra", let_contra, ["archivo", "problema"], unidad="canciones")
seccion("info", "letra_larga_poco", "Letra que termina unos segundos después del final", let_larga_poco, ["archivo", "última línea", "dura"],
        "5-12 s de diferencia: suele ser la misma canción con otro corte del final; se lee bien.", unidad="canciones")
seccion("info", "letra_falta", "Sin letra", let_falta, ["archivo"],
        "LRCLIB no las tiene (o son instrumentales sin marcar). letras.py las reintenta solo cada 30 días.", max_filas=10, unidad="canciones")
seccion("info", "letra_plana", "Letra sin sincronizar", let_plana, ["archivo"], "Se muestra entera, sin avanzar con la canción.",
        max_filas=5, unidad="canciones")
car_mal, car_chica, car_rara = [], collections.defaultdict(set), []
for d, rs in sorted(carpetas.items()):
    for r in rs:
        pics = R[r]["pics"]; fr = [p for p in pics if p[0] == 3]
        if not pics: car_mal.append((r, "sin carátula")); continue
        p = (fr or pics)[0]
        if not p[1] or not p[2]: car_rara.append((r, "la imagen no se puede leer"))
        elif min(p[1], p[2]) < 290: car_mal.append((r, f"muy chica: {p[1]}x{p[2]}"))
        elif min(p[1], p[2]) < 500: car_chica[d].add(f"{p[1]}x{p[2]}")
        if p[1] and abs(p[1] - p[2]) / max(p[1], p[2]) > 0.05: car_rara.append((r, f"no cuadrada: {p[1]}x{p[2]}"))
        if not fr: car_rara.append((r, f"sin portada tipo 3 (tiene tipo {pics[0][0]})"))
        if len(pics) > 1: car_rara.append((r, f"{len(pics)} imágenes"))
seccion("arreglar", "caratula_falta", "Sin carátula o muy chica (menos de 290 px)", car_mal, ["archivo", "problema"],
        arreglo="caratulas.py.", unidad="canciones")
seccion("decidir", "caratula_chica", "Carátula de 300-499 px", [(d, ", ".join(sorted(s))) for d, s in sorted(car_chica.items())],
        ["disco", "tamaño"], "Se ve bien en el celular; en una pantalla grande se nota borrosa.",
        "¿Buscar versiones de 1000 px (Deezer/iTunes/Cover Art Archive) y reemplazarlas?", max_filas=15, unidad="discos")
seccion("decidir", "caratula_rara", "Carátulas no cuadradas, sin tipo portada, varias imágenes o ilegibles", car_rara, ["archivo", "problema"],
        unidad="canciones")
cov = collections.defaultdict(collections.Counter)
for r in album_rels:
    pics = R[r]["pics"]
    if pics: cov[os.path.dirname(r)][([p for p in pics if p[0] == 3] or pics)[0][4]] += 1
seccion("arreglar", "caratula_mezclada", "Discos con carátulas distintas entre sus canciones",
        sorted((d, len(c), " / ".join(f"{h}×{n}" for h, n in c.most_common())) for d, c in cov.items() if len(c) > 1),
        ["disco", "carátulas", "cuáles (imagen×canciones)"], "Navidrome muestra una sola para el disco; al abrir cada canción cambia.",
        "Poner a todas la carátula del disco (la de la mayoría; en empate, la más grande).", unidad="discos")

# ---------------------------------------------------------------- 4. discos y artistas
rep, mezcla, mezcla_mb = [], [], collections.Counter()
for d, rs in sorted(carpetas.items()):
    pos = collections.Counter(((re.match(r"\d+", g(R[r], "discnumber")) or re.match(r"", "1")).group() or "1", g(R[r], "tracknumber").split("/")[0])
                              for r in rs)
    for (dn, tn), n in pos.items():
        if n > 1 and tn: rep.append((d, f"disco {dn} pista {tn}", n))
    for k in ["album", "albumartist", "date"]:
        vs = collections.Counter(g(R[r], k) for r in rs)
        if len(vs) > 1: mezcla.append((d, k, " / ".join(f"{v or '(vacío)'}×{n}" for v, n in vs.most_common())))
    for k in ["musicbrainz_albumid", "musicbrainz_releasegroupid"]:
        if len({g(R[r], k) for r in rs}) > 1: mezcla_mb[k] += 1
seccion("arreglar", "pista_repetida", "Dos canciones con el mismo número dentro de un disco", rep, ["disco", "posición", "canciones"],
        "Suele ser una canción de otra edición del disco metida en la carpeta.",
        "numeros_pista.py (paso 7). Si no encuentra una edición con todas las canciones, casi siempre es porque una es otra "
        "versión (otra duración): escucharla y, si está mal, borrar_canciones.py; si no, numerarla a mano.", unidad="posiciones")
seccion("arreglar", "disco_mezclado", "Disco con nombre, artista o fecha distintos entre sus canciones", mezcla,
        ["carpeta", "etiqueta", "valores×canciones"], "Navidrome parte el disco en dos (o lo ordena raro).",
        "Unificar al valor de la mayoría.", unidad="casos")
w_mb = f"Además, {mezcla_mb['musicbrainz_albumid']} discos mezclan IDs de lanzamiento de MusicBrainz y {mezcla_mb['musicbrainz_releasegroupid']} de grupo: " \
       "está bien, son canciones bajadas de ediciones distintas del mismo disco."
EDIC = re.compile(r"\b(deluxe|edition|edición|edicion|remaster(ed)?|remasterizado|expanded|anniversary|version|versión|standard|"
                  r"explicit|clean|bonus|special|super|legacy|collector'?s|reissue|mono|stereo|complete works|int'?l|international|\d{4})\b")
def nucleo(s):
    """Nombre del disco sin palabras de edición (Deluxe, Remastered 2020…) pero CON lo demás de los paréntesis (Remix, Slowed…)."""
    s = EDIC.sub(" ", _plano(s))
    return re.sub(r"[^\w]", "", s)
def titulos(d): return {clave_titulo(g(R[r], "title")) for r in carpetas[d]}
def rgid(d): return {g(R[r], "musicbrainz_releasegroupid") for r in carpetas[d]} - {""}
# pares de carpetas revisados a mano que NO son el mismo disco: decisiones/discos-distintos.tsv (carpeta 1<TAB>carpeta 2)
NO_SON_EL_MISMO = {tuple(l.rstrip("\n").split("\t")[:2]) for l in open(decision("discos-distintos.tsv"), encoding="utf-8")
                   if l.strip() and not l.startswith("#")} if os.path.exists(decision("discos-distintos.tsv")) else set()
typo, ediciones, solo_mb = [], [], []
for art, ds in sorted(por_art.items()):
    for i in range(len(ds)):
        for j in range(i + 1, len(ds)):
            a, b = ds[i], ds[j]
            ra, rb = a.split(os.sep)[1], b.split(os.sep)[1]
            ya, yb = ra[:4], rb[:4]
            na, nb = nucleo(re.sub(r"^\d{4} - ", "", ra)), nucleo(re.sub(r"^\d{4} - ", "", rb))
            if not na or not nb: continue
            comun_ = len(titulos(a) & titulos(b)); info = f"{comun_} en común de {len(carpetas[a])}+{len(carpetas[b])}"
            if (a, b) in NO_SON_EL_MISMO or (b, a) in NO_SON_EL_MISMO: continue
            if na == nb:
                if re.sub(r"[\s_()\[\]\-.,:;'’!?¿¡]", "", _plano(ra)) == re.sub(r"[\s_()\[\]\-.,:;'’!?¿¡]", "", _plano(rb)):
                    typo.append((a, b, "el mismo nombre escrito distinto", info))
                else:
                    ediciones.append((a, b, info))
            elif re.sub(r"\d", "", na) != re.sub(r"\d", "", nb) and min(len(na), len(nb)) >= 6 and ya == yb \
                    and difflib.SequenceMatcher(None, na, nb).ratio() >= 0.9:
                typo.append((a, b, f"nombre {difflib.SequenceMatcher(None, na, nb).ratio():.0%} igual, mismo año", info))
            elif rgid(a) & rgid(b):
                solo_mb.append((a, b, info))
seccion("arreglar", "disco_mal_escrito", "El mismo disco en dos carpetas con el nombre mal escrito", typo, ["carpeta 1", "carpeta 2", "por qué", "canciones"],
        "Como Molotov «Donde Jugaran» / «Donde Jurgaran Las Niñas_».",
        "Unir en una carpeta con el nombre correcto (el de MusicBrainz/Spotify) y el mismo nombre de disco en las etiquetas.", unidad="pares")
seccion("decidir", "disco_ediciones", "Dos ediciones del mismo disco en carpetas separadas", ediciones, ["carpeta 1", "carpeta 2", "canciones"],
        "Ej.: «FutureSex_LoveSounds» y «… Deluxe Edition». En Navidrome se ven como dos discos.",
        "¿Unir cada par en una sola carpeta (la edición más completa), sin repetir canciones?", unidad="pares")
seccion("info", "disco_solo_mb", "Discos con nombre distinto que MusicBrainz agrupa juntos", solo_mb, ["carpeta 1", "carpeta 2", "canciones"],
        "Casi siempre sencillos distintos a los que se les asignó el mismo grupo de MusicBrainz; no se ve en Navidrome.", unidad="pares")
# disco de MusicBrainz AJENO (30 sep; antes check_mb_match.py, aparte): el ID de grupo de disco de la canción es de OTRO
# lanzamiento que también la tiene (un recopilatorio, un sencillo): restos de Picard. Mismo nombre con otra escritura
# (otro alfabeto, «III» = «3», una parte del nombre) no cuenta. Caché: cache/mb-rg-cache.json (sin red: solo lo guardado).
_rg = Cache("mb-rg-cache.json")
def _disco_rg(i):
    if i not in _rg and not SIN_RED:
        d = pedir_json(f"https://musicbrainz.org/ws/2/release-group/{i}?inc=artist-credits&fmt=json")
        if d:
            _rg.poner(i, {"title": d.get("title", ""), "artist": " ".join(c.get("name", "") + c.get("joinphrase", "")
                                                                         for c in d.get("artist-credit", []))})
    return _rg.get(i)
def _mismo_disco(alb, otro):
    a, b = base_disco(alb), base_disco(otro)
    if not a or not b or a == b or a in b or b in a: return True
    n = nivel_titulo(alb, otro)
    return n is None or n >= 1
mb_ajeno = []
for r in album_rels:
    i = g(R[r], "musicbrainz_releasegroupid")
    d = _disco_rg(i) if i else None
    if d and d.get("title") and not _mismo_disco(g(R[r], "album"), d["title"]):
        mb_ajeno.append((r, g(R[r], "album"), d["title"]))
_rg.guardar()
seccion("decidir", "disco_mb_ajeno", "Canciones con el ID de disco de MusicBrainz de OTRO lanzamiento", mb_ajeno,
        ["archivo", "su disco", "el disco de MusicBrainz"],
        "Restos de Picard: la grabación está bien, pero el disco apunta a un recopilatorio o sencillo que también la tiene. "
        "En Navidrome no se nota; ListenBrainz atribuye la escucha a ese otro disco.",
        "Regla «mejor sin ID que con uno ajeno»: quitar los IDs de disco (o poner el del disco con su nombre). OJO: cambia el "
        "ID con que Navidrome agrupa el disco → hacerlo verificando que no se pierdan escuchas.", unidad="canciones")
arts = sorted(por_art)
def nart(s): return re.sub(r"^the", "", plano(s))
simart = []
# pares revisados a mano: artistas DISTINTOS de verdad (27 sep: Buckethead/The Bucketheads, Creed/Creeds, Jack Back/Jack Black)
_distintos = {frozenset(x) for x in json.load(open(decision("artistas-distintos.json"), encoding="utf-8"))} \
    if os.path.exists(decision("artistas-distintos.json")) else set()
for i in range(len(arts)):
    for j in range(i + 1, len(arts)):
        a, b = nart(arts[i]), nart(arts[j])
        if a and b and (a == b or (min(len(a), len(b)) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.9)):
            if frozenset((arts[i], arts[j])) not in _distintos: simart.append((arts[i], arts[j], "nombre casi igual"))
# (el ID de artista de MusicBrainz NO sirve para esto: hay IDs mal puestos que juntan a Taylor Swift con ZAYN)
seccion("decidir", "mismo_artista", "El mismo artista con dos nombres de carpeta", simart, ["carpeta", "otra", "por qué"],
        "Solo por nombre casi igual: muchos son artistas distintos de verdad.", "¿Unir en un solo nombre (el de Spotify)?", unidad="pares")

# ---------------------------------------------------------------- 5. canciones repetidas y audio equivocado
log("comparando canciones...")
pares = {}   # (a, b) ordenado → set(motivos)
def agrega(rs, motivo):
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            pares.setdefault(tuple(sorted((rs[i], rs[j]))), set()).add(motivo)
def grupos(clave):
    gr = collections.defaultdict(list)
    for r in album_rels:
        for v in gl(R[r], clave): gr[v].append(r)
    return [v for v in gr.values() if 1 < len(v) <= 6]
for rs in grupos("spotify_id"): agrega(rs, "mismo spotify_id")
for rs in grupos("musicbrainz_trackid"): agrega(rs, "misma grabación MB")
for rs in grupos("isrc"): agrega(rs, "mismo ISRC")
por_clave = collections.defaultdict(list)
for r in album_rels: por_clave[(clave_artista(g(R[r], "artist") or g(R[r], "albumartist")), clave_titulo(g(R[r], "title")))].append(r)
for rs in por_clave.values():
    if 1 < len(rs) <= 6: agrega(rs, "mismo artista y título")
por_art_t = collections.defaultdict(list)
for (a, t), rs in por_clave.items(): por_art_t[a].append((t, rs))
for a, ts in por_art_t.items():
    for i in range(len(ts)):
        for j in range(i + 1, len(ts)):
            (ta, ra), (tb, rb) = ts[i], ts[j]
            ba, bb = ta.split("|")[0], tb.split("|")[0]
            if len(ba) >= 4 and len(bb) >= 4 and ba != bb and difflib.SequenceMatcher(None, ba, bb).ratio() >= 0.9 \
                    and abs(R[ra[0]]["len"] - R[rb[0]]["len"]) <= 5:
                agrega([ra[0], rb[0]], "título casi igual")
log("buscando audio igual en toda la biblioteca...")
idx = collections.defaultdict(list)
for r, fp in FP.items():
    for v in set(fp[len(fp) // 8: len(fp) * 7 // 8].tolist()): idx[v].append(r)
cand = collections.Counter()
for v, rs in idx.items():
    if 1 < len(rs) <= 20:
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)): cand[tuple(sorted((rs[i], rs[j])))] += 1
for (a, b), n in cand.items():
    if n >= 0.1 * min(len(FP[a]), len(FP[b])): pares.setdefault((a, b), set()).add("audio parecido")
def misma_dur(a, b): return abs(R[a]["len"] - R[b]["len"]) <= max(3, 0.02 * max(R[a]["len"], R[b]["len"]))
copias, ids_mal, versiones, igual_otro = [], [], [], []
for (a, b), motivos in sorted(pares.items()):
    s = par_audio(a, b)
    if s is None: continue
    mismo_t = clave_titulo(g(R[a], "title")) == clave_titulo(g(R[b], "title")) and \
        clave_artista(g(R[a], "artist")) == clave_artista(g(R[b], "artist")) and misma_dur(a, b)
    mot = ", ".join(sorted(motivos - {"audio parecido"})) or "solo el audio"
    fila = (f"{a} ({dur(a)})", f"{b} ({dur(b)})", s, mot)
    if s >= MISMO_AUDIO:
        (copias if mismo_t else igual_otro).append(fila)
    elif motivos & {"misma grabación MB", "mismo ISRC", "mismo spotify_id"} and s < OTRO_AUDIO and not mismo_t:
        ids_mal.append(fila)
    elif motivos - {"audio parecido"}:
        versiones.append(fila)
SEC_COPIAS = len(SECS)
log(f"confirmando {len(igual_otro)} pares con la vista previa de Spotify...")
audio_mal, igual_ok, igual_dup, igual_sin = [], [], [], []
for a_, b_, s, mot in igual_otro:
    a, b = a_.rsplit(" (", 1)[0], b_.rsplit(" (", 1)[0]
    sa, sb = contra_spotify(a), contra_spotify(b)
    malos_ = [f"{x} (Spotify {v})" for x, v in ((a, sa), (b, sb)) if v is not None and v < SPOT_MAL]
    fila = (a_, b_, s, f"{sa if sa is not None else '—'} / {sb if sb is not None else '—'}")
    if malos_: audio_mal.append((" ; ".join(malos_), (b_ if sa is not None and sa < SPOT_MAL else a_), s))
    elif sa is None or sb is None or sa < SPOT_BIEN or sb < SPOT_BIEN: igual_sin.append(fila)
    elif s >= 0.98 and misma_dur(a, b):
        mismo = clave_titulo(g(R[a], "title")) == clave_titulo(g(R[b], "title"))
        (copias if mismo else igual_dup).append(fila[:3] + (("confirmadas con Spotify, " if mismo else "") + mot,))
    else: igual_ok.append(fila)
SECS.insert(SEC_COPIAS, ("arreglar", "copias", "Copias repetidas: mismo audio, mismo título, misma duración", copias,
        ["archivo 1", "archivo 2", "parecido", "coinciden en"], "Suele ser la canción en su disco y en un recopilatorio, o en dos ediciones.",
        "Regla ya decidida: UNA copia por grabación (duplicados.py: queda la del disco con más canciones; empate → la más escuchada).",
        40, "pares"))
seccion("arreglar", "audio_equivocado", "AUDIO EQUIVOCADO: suena como otra canción de la biblioteca y no como la suya de Spotify", audio_mal,
        ["archivo con el audio equivocado", "suena igual que", "parecido"],
        "Confirmado dos veces: su audio es igual al de otra canción, y NO contiene la vista previa de su propia canción de Spotify.",
        "borrar_canciones.py --motivo equivocada y re-bajar con el enlace de la canción.", unidad="canciones")
seccion("decidir", "audio_igual_dup", "Mismo audio y duración con dos nombres, y Spotify confirma los dos", igual_dup,
        ["archivo 1", "archivo 2", "parecido", "Spotify 1 / 2"],
        "Spotify publica la misma grabación con dos títulos (p. ej. «Radio Version» y la normal).",
        "¿Quedarse con una sola (como las copias repetidas)?", unidad="pares")
seccion("decidir", "audio_igual_sin", "Mismo audio, sin poder confirmar con Spotify cuál es cuál", igual_sin,
        ["archivo 1", "archivo 2", "parecido", "Spotify 1 / 2"],
        "Falta la vista previa (o dio un valor intermedio): escuchar las dos.", unidad="pares")
seccion("info", "audio_igual_ok", "Versiones que comparten audio (Spotify confirma cada una)", igual_ok,
        ["archivo 1", "archivo 2", "parecido", "Spotify 1 / 2"], "Partes 1 y 2, versión extendida y radio edit, un medley…", unidad="pares")
seccion("arreglar", "id_equivocado", "Mismo ID de grabación/ISRC pero audio distinto (ID equivocado)", ids_mal,
        ["archivo 1", "archivo 2", "parecido", "coinciden en"],
        "Dos canciones distintas quedaron con el mismo ID (casi siempre de MusicBrainz, dentro del mismo disco). Afecta a ListenBrainz y a duplicados.py.",
        "ids_mb.py (simulación) → ids_mb.py --execute → nd_actualizar.py.", unidad="pares")
# cada ID de grabación contra su grabación (título, duración, ISRC: comun.grabacion_corresponde). Los datos de MusicBrainz y
# los que se dejan a propósito (el audio confirma el ID) los guarda ids_mb.py; esta auditoría no consulta MusicBrainz.
_gp, _ap = cache_path("ids-mb-grabaciones.json"), decision("ids-mb-aceptados.json")
GRABS = leer_json(_gp, {})
ACEPT = leer_json(_ap, {})
id_ajeno, id_sin_datos = [], 0
for r in album_rels:
    rid = g(R[r], "musicbrainz_trackid")
    if not rid or (ACEPT.get(r) or {}).get("rid") == rid: continue
    rec = GRABS.get(rid)
    if not rec: id_sin_datos += 1; continue
    ok, nt, mot = (False, None, "no existe en MusicBrainz") if rec.get("no_existe") else grabacion_corresponde(
        g(R[r], "title"), g(R[r], "artist"), R[r]["len"], gl(R[r], "isrc"), rec.get("title"), (rec.get("length") or 0) / 1000 or None,
        rec.get("isrcs"), [a.get("name") for a in rec.get("ac") or []])
    if not ok: id_ajeno.append((f"{r} ({dur(r)})", rec.get("title") or "", mot))
seccion("arreglar", "id_ajeno", "El ID de grabación de MusicBrainz es de OTRA canción (título, duración o ISRC no cuadran)", id_ajeno,
        ["archivo", "grabación de su ID", "por qué"],
        "Casi siempre Picard (21-23 sep), que emparejó por posición." + (f" {id_sin_datos} IDs sin datos todavía: correr ids_mb.py." if id_sin_datos else ""),
        "ids_mb.py (simulación) → ids_mb.py --execute → nd_actualizar.py.", unidad="canciones")
seccion("info", "versiones", "Misma canción en otra versión (edit, remaster distinto, en vivo)", versiones,
        ["archivo 1", "archivo 2", "parecido", "coinciden en"], "El audio difiere lo suficiente para ser otra grabación: se quedan las dos.",
        max_filas=15, unidad="pares")

# ---------------------------------------------------------------- 6. Navidrome
nd_msg = ""
try:
    con = sqlite3.connect(f"file:{NDDB}?mode=ro", uri=True)
    mf = con.execute("select path, album_id, missing from media_file where path not like '_Prueba/%'").fetchall()   # _Prueba: Octo-Fiesta
    presentes = [p for p, a, m in mf if not m]
    nd_msg = f"Navidrome: {len(presentes)} canciones (disco: {len(album_rels)}); faltantes guardadas a propósito (esperan re-descarga): {sum(1 for _, _, m in mf if m)}."
    alb_dir = collections.defaultdict(set); dir_alb = collections.defaultdict(set)
    for p, a, m in mf:
        if not m: alb_dir[os.path.dirname(p)].add(a); dir_alb[a].add(os.path.dirname(p))
    nom = dict(con.execute("select id, name from album").fetchall())
    seccion("arreglar", "nd_partido", "Una carpeta que Navidrome muestra como varios discos",
            [(d, len(a), " / ".join(nom.get(x, x) for x in a)) for d, a in sorted(alb_dir.items()) if len(a) > 1], ["carpeta", "discos", "nombres"],
            arreglo="Unificar nombre/artista/fecha del disco en sus canciones.", unidad="discos")
    unido_mal, unido_ok = [], []
    for a, ds in dir_alb.items():
        if len(ds) > 1:
            (unido_mal if len({d.split(os.sep)[0] for d in ds}) < len(ds) else unido_ok).append((nom.get(a, a), " ⟷ ".join(sorted(ds))))
    seccion("arreglar", "nd_unido", "Dos carpetas del MISMO artista que Navidrome junta en un disco", sorted(unido_mal), ["disco", "carpetas"],
            arreglo="Unir las carpetas en una.", unidad="discos")
    seccion("info", "nd_unido_ok", "Discos de varios artistas repartidos en carpetas (Navidrome los junta bien)", sorted(unido_ok), ["disco", "carpetas"],
            "Soundtracks: en Navidrome se ven como un solo disco. Ver también «Discos guardados en la carpeta de otro artista».", unidad="discos")
    en_nd = set(presentes)
    seccion("arreglar", "nd_distinto", "Diferencias entre Navidrome y el disco",
            [(r, "no está en Navidrome") for r in album_rels if r not in en_nd] + [(p, "en Navidrome pero no en el disco") for p in sorted(en_nd - set(album_rels))],
            ["archivo", "problema"], arreglo="nd_actualizar.py (reescaneo).", unidad="canciones")
    con.close()
except Exception as e:
    nd_msg = f"⚠️ No pude leer Navidrome: {e}"

# ---------------------------------------------------------------- escribir
for tipo, clave, titulo, filas, cols, *_ in SECS:
    with open(plan_path(f"auditoria-{clave}").replace(".json", "") + ".tsv", "w", encoding="utf-8") as o:
        o.write("\t".join(cols) + "\n" + "".join("\t".join(str(v) for v in f) + "\n" for f in filas))
for viejo in os.listdir(os.path.dirname(plan_path("x"))):          # listas de la versión 1 que ya no existen
    if viejo.startswith("auditoria-") and viejo.endswith(".tsv") and viejo[10:-4] not in {s[1] for s in SECS}:
        os.remove(os.path.join(os.path.dirname(plan_path("x")), viejo))
fmt = collections.Counter(R[r]["con_perdida"].split()[0] + " (con pérdida)" if R[r]["con_perdida"] else
                          f"{R[r]['sr']/1000:g} kHz / {R[r]['bits']} bits" for r in album_rels)
faltan = collections.Counter(k for r in album_rels for k in ["isrc", "spotify_id", "musicbrainz_trackid", "replaygain_track_gain"] if not gl(R[r], k))
def ancla(t): return re.sub(r"[^\w\- ]", "", t.lower()).strip().replace(" ", "-")
L = ["# Música — auditoría completa\n",
     f"Generada por `~/music-tools/auditoria.py` (versión 2) el {datetime.datetime.now():%d %b %Y %H:%M}. **Solo lee: no cambió nada.**  ",
     f"Biblioteca: {len(flacs)} canciones en {len(carpetas)} discos de {len(por_art)} artistas · {' · '.join(f'{k}: {v}' for k, v in fmt.most_common())}  ",
     nd_msg + "\n",
     "Cada lista completa está en `~/music-tools/planes/auditoria-<nombre>.tsv`.\n"]
for tipo, nombre in TIPOS.items():
    ss = [s for s in SECS if s[0] == tipo]
    L += [f"## {nombre}\n", "| Qué | Cuántos | Lista |", "|---|---|---|"]
    L += [f"| {'**' if s[3] and tipo == 'arreglar' else ''}[{s[2]}](#{ancla(s[2])}){'**' if s[3] and tipo == 'arreglar' else ''} | {len(s[3])} {s[8]} | `{s[1]}` |"
          for s in ss if s[3]]
    vacias_ = [s[2] for s in ss if not s[3]]
    if vacias_: L.append(f"\n✅ Sin ningún caso: {' · '.join(vacias_)}.")
    L.append("")
L.append("Etiquetas que faltan (info): " + " · ".join(f"{k} {n}" for k, n in faltan.most_common()) + ". " + w_mb + "\n")
L.append("---\n")
for tipo, nombre in TIPOS.items():
    L.append(f"# {nombre}\n")
    for _, clave, titulo, filas, cols, nota, arreglo, max_filas, unidad in [s for s in SECS if s[0] == tipo]:
        if not filas: continue
        L.append(f"### {titulo}\n")
        L.append(f"**{len(filas)} {unidad}** · `planes/auditoria-{clave}.tsv`" + (" · ✅ nada que hacer" if not filas else "") + "\n")
        if not filas: continue
        if nota: L.append(nota + "\n")
        if arreglo: L.append(f"**{'Cómo se arregla' if tipo == 'arreglar' else 'A decidir'}:** {arreglo}\n")
        L += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        L += ["| " + " | ".join(str(v).replace("|", "¦").replace("\n", " ")[:110] for v in f) + " |" for f in filas[:max_filas]]
        if len(filas) > max_filas: L.append(f"\n… y {len(filas) - max_filas} más en la lista.")
        L.append("")
open(DOC, "w", encoding="utf-8").write("\n".join(L) + "\n")
log("escrito:", DOC)
for tipo in TIPOS:
    log(f"[{tipo}] " + " · ".join(f"{s[1]} {len(s[3])}" for s in SECS if s[0] == tipo))
