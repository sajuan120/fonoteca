#!/usr/bin/env python3
"""Pedidos a internet en UN solo lugar (30 sep 2026). Antes cada script traía su propia versión (get, api, jget, fetch,
dz_get, http, get_json…) con las mismas reglas escritas otra vez, y algunas copias se habían quedado atrás (caratulas.py
guardaba las fallas de red como «no existe»; descubrir.py se caía sin red). Las reglas:

  · CACHÉ en disco (cache/<nombre>.json: url → respuesta). Al guardar se MEZCLA con lo que haya en el archivo: si dos
    scripts usan la misma caché a la vez (deezer-cache.json la usan cuatro), ninguno borra lo que agregó el otro.
  · Una FALLA DE RED nunca se guarda (si no, la canción quedaría como «no existe» para siempre: pasó con letras.py y
    enriquecer.py el 24 sep). Un 404 sí se guarda, como {}: es un «no existe» de verdad.
  · Cada servicio a su RITMO: Deezer 50 cada 5 s, MusicBrainz 1 por segundo (lo exige), LRCLIB, AcoustID 3 por
    segundo, iTunes ~20 por minuto, Tidal, Qobuz, ListenBrainz y las páginas públicas de Spotify (1 cada 1,5 s).
  · Deezer contesta a veces «demasiadas consultas» (error 4, con código HTTP 200) y MusicBrainz 503 (ocupado): se espera
    y se reintenta.
  · User-Agent con un contacto (MusicBrainz lo pide): comun.UA.

Uso:   from red import Cache, pedir_json, pedir_bytes, pagina
       dz = Cache("deezer-cache.json")
       d = pedir_json("https://api.deezer.com/track/isrc:USUM71703089", dz)   # JSON · {} = no existe · None = sin respuesta
"""
import atexit, json, os, subprocess, time, urllib.error, urllib.parse, urllib.request
from comun import UA, cache_path, leer_json

RITMO = {"api.deezer.com": 0.12, "musicbrainz.org": 1.1, "lrclib.net": 0.2, "api.acoustid.org": 0.34,
         "itunes.apple.com": 3.2,   # iTunes Search admite ~20 consultas por minuto
         "api.tidal.com": 0.5, "www.qobuz.com": 0.5, "api.listenbrainz.org": 0.2, "open.spotify.com": 1.5}   # segundos entre consultas
_ultima = {}


def _esperar(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    pausa = next((v for k, v in RITMO.items() if host == k or host.endswith("." + k)), 0)
    if pausa:
        time.sleep(max(0, _ultima.get(host, 0) + pausa - time.time()))
        _ultima[host] = time.time()


class Cache(dict):
    """Caché de respuestas en cache/<nombre>.json. Se guarda sola cada `cada` respuestas nuevas y al terminar el script.
    Las entradas nuevas se agregan con poner() (no con c[k] = v, que no se guardaría) y se borran con quitar()."""
    def __init__(self, nombre, cada=50, solo_leer=False):
        self.ruta, self.cada, self.solo_leer = cache_path(nombre), cada, solo_leer
        self._nuevas, self._quitadas = {}, set()
        try:
            super().__init__(leer_json(self.ruta, {}) or {})   # 2 oct: una caché rota se aparta y avisa (no se pisa en silencio)
        except OSError:
            super().__init__()
        if not solo_leer:
            atexit.register(self.guardar)

    def poner(self, k, v):
        self[k] = v
        self._nuevas[k] = v
        self._quitadas.discard(k)
        if len(self._nuevas) >= self.cada:
            self.guardar()

    def quitar(self, k):
        self.pop(k, None)
        self._nuevas.pop(k, None)
        self._quitadas.add(k)

    def guardar(self):
        if self.solo_leer or not (self._nuevas or self._quitadas):
            return
        try:
            disco = json.load(open(self.ruta, encoding="utf-8"))
        except (OSError, ValueError):
            disco = {}
        for k in self._quitadas:
            disco.pop(k, None)
        disco.update(self._nuevas)
        tmp = self.ruta + ".tmp"
        json.dump(disco, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, self.ruta)
        self._nuevas, self._quitadas = {}, set()


def _abrir(url, datos=None, cabeceras=None, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, data=datos, headers={**UA, **(cabeceras or {})}), timeout=timeout)


def pedir_json(url, cache=None, datos=None, cabeceras=None, intentos=4, timeout=30):
    """El JSON de `url` (GET; POST si hay `datos`, en bytes). Devuelve:
       el JSON · {} si no existe (404/410: se guarda en la caché) · None si no hubo respuesta (sin red, el servicio
       siguió ocupado, o lo rechazó con 400/401/403…): NO se guarda, la próxima vez se vuelve a pedir."""
    if cache is not None and url in cache:
        return cache[url]
    for intento in range(intentos):
        _esperar(url)
        try:
            d = json.load(_abrir(url, datos, cabeceras, timeout))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:   # demasiadas consultas / servicio ocupado: esperar y reintentar
                time.sleep(3 + 3 * intento); continue
            if e.code not in (404, 410):         # 2 oct: 400/401/403/408 (clave vencida, bloqueo…) NO es «no existe»
                print(f"  ⚠️ {urllib.parse.urlsplit(url).hostname} respondió {e.code}: no se guarda", flush=True)
                return None
            d = {}                                 # 404/410: no existe de verdad (se guarda)
        except (OSError, ValueError):              # sin red, tiempo agotado, o una respuesta que no es JSON
            time.sleep(3 + 3 * intento); continue
        if "api.deezer.com" in url and isinstance(d, dict) and (d.get("error") or {}).get("code") in (4, 700):
            time.sleep(5 * (intento + 1)); continue   # Deezer: 4 «Quota limit exceeded», 700 «Service busy»
        if cache is not None:
            cache.poner(url, d)
        return d
    return None


def pedir_bytes(url, intentos=3, timeout=30):
    """El contenido de `url` (p. ej. una carátula). None si no existe o no hubo respuesta."""
    for intento in range(intentos):
        _esperar(url)
        try:
            return _abrir(url, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                return None
        except OSError:
            pass
        time.sleep(2 * (intento + 1))
    return None


def pagina(url):
    """HTML de una página pública (open.spotify.com: sin la Web API, sin Premium ni cuota). Con curl como un navegador:
    así Spotify entrega la página completa con sus datos. "" si no hubo respuesta."""
    _esperar(url)
    return subprocess.run(["curl", "-s", "--max-time", "20", "-A", "Mozilla/5.0", url], capture_output=True, text=True).stdout
