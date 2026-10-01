#!/usr/bin/env python3
"""ReplayGain 2.0 (volumen parejo entre canciones, como "normalizar volumen" de Spotify). Solo AGREGA tags; no toca el audio.

Uso: replaygain.py [<carpeta de álbum> ...] [--execute] [--forzar]
  Sin carpetas: todos los álbumes (Artista/Álbum) donde a alguna canción le falte ReplayGain (incremental).
  --forzar: recalcula aunque ya tengan. Sin --execute solo mide y muestra.
Cómo: ffmpeg (filtro ebur128, EBU R128) mide la sonoridad integrada (LUFS) y el pico real de cada canción.
  Ganancia de pista = -18 LUFS (referencia de ReplayGain 2.0) - sonoridad.
  Álbum = sonoridad energética ponderada por duración de sus pistas; pico = el mayor.
Tags: REPLAYGAIN_TRACK_GAIN/PEAK, REPLAYGAIN_ALBUM_GAIN/PEAK, REPLAYGAIN_REFERENCE_LOUDNESS.
Navidrome los manda a las apps (web, Amperfy, Symfonium...), que ajustan el volumen si se activa ReplayGain.
"""
import collections, json, math, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from audio import abrir, es_audio
from comun import ROOT, es_de_album, log_path

REF = -18.0
args = sys.argv[1:]
if any(a in ("-h", "--help") for a in args) or any(a.startswith("--") and a not in ("--execute", "--forzar") for a in args):
    sys.exit(__doc__)
EXECUTE, FORZAR = "--execute" in args, "--forzar" in args
carpetas = [os.path.join(ROOT, a) for a in args if not a.startswith("--")]

def medir(p):
    """(sonoridad integrada LUFS, pico real dBFS, duración s) o None."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", p, "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    pk = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", r.stderr)
    if not i or not pk:
        return None
    try:
        dur = abrir(p).info.length
    except Exception:
        return None
    return float(i[-1]), (float(pk[-1]) if pk[-1] != "-inf" else -99.0), dur

# álbumes a procesar
albums = collections.defaultdict(list)
for base in carpetas or [ROOT]:
    for d, _, fs in os.walk(base):
        for f in fs:
            p = os.path.join(d, f)
            if es_audio(f) and es_de_album(p):
                albums[d].append(p)
todo = {}
for d, ps in albums.items():
    tags = [abrir(p) for p in ps]
    falta = any(not t.get("replaygain_track_gain") or not t.get("replaygain_album_gain") for t in tags)
    if FORZAR or falta:
        todo[d] = sorted(ps)
n = sum(len(v) for v in todo.values())
print(f"{len(todo)} álbumes / {n} canciones a medir", flush=True)

res = {}
with ThreadPoolExecutor(8) as ex:
    for k, (p, m) in enumerate(zip([p for ps in todo.values() for p in ps],
                                   ex.map(medir, [p for ps in todo.values() for p in ps])), 1):
        res[p] = m
        if k % 250 == 0:
            print(f"  {k}/{n}", flush=True)

escritos, sin_medida, log = 0, [], {}
for d, ps in todo.items():
    med = [(p, res[p]) for p in ps if res.get(p) and res[p][0] > -70]
    sin_medida += [p for p in ps if not res.get(p) or res[p][0] <= -70]
    if not med:
        continue
    energia = sum(dur * 10 ** (lufs / 10) for _, (lufs, _, dur) in med) / sum(dur for _, (_, _, dur) in med)
    alb_lufs = 10 * math.log10(energia)
    alb_peak = max(10 ** (pk / 20) for _, (_, pk, _) in med)
    for p, (lufs, pk, _) in med:
        nuevos = {"replaygain_track_gain": [f"{REF - lufs:+.2f} dB"], "replaygain_track_peak": [f"{10 ** (pk / 20):.6f}"],
                  "replaygain_album_gain": [f"{REF - alb_lufs:+.2f} dB"], "replaygain_album_peak": [f"{alb_peak:.6f}"],
                  "replaygain_reference_loudness": [f"{REF:.2f} LUFS"]}
        log[p] = {k: v[0] for k, v in nuevos.items()}
        if EXECUTE:
            t = abrir(p); t.update(nuevos); t.save(); escritos += 1

ej = list(log.items())[:3]
for p, v in ej:
    print(f"  {os.path.relpath(p, ROOT)[:70]:70s} pista {v['replaygain_track_gain']:>9s}  álbum {v['replaygain_album_gain']:>9s}")
if sin_medida:
    print(f"  sin medida (silencio o error de ffmpeg): {len(sin_medida)}")
if EXECUTE:
    out = log_path("replaygain-log")
    json.dump({"escritos": log, "sin_medida": sin_medida}, open(out, "w"), ensure_ascii=False, indent=0)
    print(f"ESCRITO ReplayGain en {escritos} canciones. Log: {out}")
else:
    print(f"SIMULACIÓN: {len(log)} canciones tendrían ReplayGain. Usa --execute.")
