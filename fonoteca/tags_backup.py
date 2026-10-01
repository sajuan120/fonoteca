#!/usr/bin/env python3
"""Respaldo/restauración de tags de texto (FLAC y los demás formatos de audio.py; sin carátulas).

  tags_backup.py dump    <salida.json>   # guarda tags de cada audio único (por inodo)
  tags_backup.py restore <entrada.json>  # deja los tags EXACTAMENTE como en el respaldo
  tags_backup.py diff    <entrada.json>  # muestra qué claves cambiaron (no escribe)
  tags_backup.py desde-kit <etiquetas.json.gz> [--execute]
                                         # tras re-bajar la biblioteca con Antra (kit de recuperación): devuelve a cada
                                         # canción, por su spotify_id, EXACTAMENTE las etiquetas que tenía (sin --execute
                                         # solo cuenta). 30 sep: antes era restaurar_etiquetas.py

Las carátulas (bloques PICTURE) no se tocan en restore.
"""
import json, os, sys
from collections import Counter
from audio import abrir, es_audio

ROOT, SKIP = __import__('comun').ROOT, __import__('comun').SKIP


def unique_files():
    seen = set()
    for r, d, fs in os.walk(ROOT):
        d[:] = sorted(x for x in d if not (r == ROOT and x in SKIP))   # _Prueba (Octo-Fiesta) no es la biblioteca
        for f in sorted(fs):
            if not es_audio(f):
                continue
            p = os.path.join(r, f)
            st = os.stat(p)
            if st.st_ino in seen:
                continue
            seen.add(st.st_ino)
            yield p, st.st_ino


def read_tags(p):
    t = abrir(p).tags
    return [[k, v] for k, v in t] if t is not None else []


def dump(out):
    data, saltados = {}, []
    for p, ino in unique_files():
        try:
            data[str(ino)] = {'path': p, 'tags': read_tags(p)}
        except Exception:   # archivo a medio escribir (Antra bajando) o dañado: no se respalda, se avisa
            saltados.append(p)
    with open(out, 'w') as fh:
        json.dump(data, fh, ensure_ascii=False)
    print(f'{len(data)} audios respaldados en {out}' + (f' ({len(saltados)} ilegibles saltados, p. ej. {saltados[0]})' if saltados else ''))


def load(inp):
    with open(inp) as fh:
        return json.load(fh)


def current_by_inode():
    return {str(ino): p for p, ino in unique_files()}


def diff(inp):
    data, cur = load(inp), current_by_inode()
    changed, keys, missing = 0, Counter(), 0
    for ino, e in data.items():
        p = cur.get(ino)
        if p is None:
            missing += 1
            continue
        old = {}
        for k, v in e['tags']:
            old.setdefault(k.lower(), []).append(v)
        new = {}
        for k, v in read_tags(p):
            new.setdefault(k.lower(), []).append(v)
        ks = {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}
        if ks:
            changed += 1
            for k in ks:
                keys['+' + k if k not in old else '-' + k if k not in new else '~' + k] += 1
    print(f'{changed} audios con cambios, {missing} inodos ya no existen')
    for k, n in keys.most_common():
        print(f'  {n:5d}  {k}')
    print('(+ agregada, - quitada, ~ modificada)')


def restore(inp):
    data, cur = load(inp), current_by_inode()
    n = 0
    for ino, e in data.items():
        p = cur.get(ino)
        if p is None:
            continue
        f = abrir(p)
        if [[k, v] for k, v in (f.tags or [])] == e['tags']:
            continue
        if f.tags is None:
            f.add_tags()
        f.tags.clear()
        for k, v in e['tags']:
            f.tags.append((k, v))
        f.save()
        n += 1
    print(f'{n} audios restaurados')


def desde_kit(inp, execute):
    import gzip
    from comun import es_de_album
    datos = json.load(gzip.open(inp, "rt", encoding="utf-8"))
    iguales = cambian = 0
    encontradas = set()
    for d, _, fs in os.walk(ROOT):
        for f in fs:
            p = os.path.join(d, f)
            if not es_audio(f) or not es_de_album(p):
                continue
            try:
                t = abrir(p)
            except Exception:
                continue
            sid = (t.get("spotify_id") or [""])[0]
            if sid not in datos:
                continue
            encontradas.add(sid)
            guardadas = datos[sid]["tags"]
            if sorted(map(tuple, guardadas)) == sorted((k, v) for k, v in (t.tags or [])):
                iguales += 1
                continue
            cambian += 1
            if execute:
                t.delete()   # solo borra las etiquetas de texto; las carátulas quedan (en FLAC son otro bloque)
                t = abrir(p)
                if t.tags is None:
                    t.add_tags()
                for k, v in guardadas:
                    t.tags.append((k, v))
                t.save()
    print(f"en el kit: {len(datos)} | en la biblioteca: {len(encontradas)} (ya iguales {iguales}, "
          f"{'restauradas' if execute else 'a restaurar'} {cambian}) | del kit que no están: {len(datos) - len(encontradas)}")
    if not execute and cambian:
        print("SIMULACIÓN: usa --execute para escribirlas.")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, arg = sys.argv[1], sys.argv[2]
    if cmd == 'desde-kit':
        desde_kit(arg, '--execute' in sys.argv)
    else:
        {'dump': dump, 'restore': restore, 'diff': diff}[cmd](arg)
