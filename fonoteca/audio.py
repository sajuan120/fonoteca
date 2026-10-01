#!/usr/bin/env python3
"""Etiquetas, carátulas y letras de CUALQUIER formato con la MISMA interfaz que los scripts ya usaban con mutagen FLAC.
28 sep 2026 — el sistema pasó a aceptar otros formatos además de FLAC (Octo-Fiesta trae MP3; descargas a mano AAC/Opus).

Formatos: FLAC, MP3 (ID3v2.4), M4A/MP4 (AAC y ALAC), Ogg Vorbis, Opus.
  · FLAC: abrir() devuelve el objeto mutagen FLAC DE SIEMPRE (nada cambia para los 5.847 FLAC de la biblioteca).
  · Los demás: una capa con la misma forma de uso — t.get(k) / t[k] / t[k] = [...] / del t[k] / t.pop(k, None) /
    k in t / t.keys() / t.update({...}) / t.tags (pares clave-valor) / t.pictures / t.clear_pictures() /
    t.add_picture(Picture) / t.info.length / t.save() / t.delete() (quita el texto, deja las carátulas, como FLAC).
    t.tags también escribe como en FLAC (t.tags.clear() + t.tags.append((k, v)) = restaurar un respaldo).
Nombres de etiqueta: los de Vorbis en minúscula (title, artist, albumartist, musicbrainz_albumid, replaygain_track_gain,
spotify_id, …). «year» es una etiqueta PROPIA en todos (TXXX:YEAR, ----:YEAR): sin ella Navidrome toma en MP3 la
fecha ORIGINAL como fecha del disco y el disco se parte (probado 28 sep). En MP3 y M4A se traducen a los marcos que lee Navidrome (los mismos que usa Picard); lo que no tiene
marco estándar va como TXXX:<NOMBRE> (MP3) o ----:com.apple.iTunes:<NOMBRE> (M4A). Ogg/Opus son Vorbis como FLAC.
Carátulas: siempre objetos mutagen.flac.Picture (data, mime, width, height, type), en cualquier formato.
Otras utilidades: EXT_AUDIO, RE_EXT, es_audio(nombre), audios(carpeta), con_perdida(ruta), verificar(ruta) (la prueba de integridad: flac -t en
FLAC; decodificar entero con ffmpeg en los demás).
Pruebas: puntuales/2026-09-28-probar-audio.py (ida y vuelta de cada etiqueta en cada formato + lo que lee Navidrome).
"""
import base64, io, os, subprocess
from mutagen.flac import FLAC, Picture

EXT_AUDIO = (".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".oga", ".opus")
CON_PERDIDA = (".mp3", ".ogg", ".oga", ".opus")   # + .m4a/.mp4 si el códec es AAC (ALAC es sin pérdida)


RE_EXT = r"\.(?:flac|mp3|m4a|mp4|ogg|oga|opus)"   # para patrones de nombre: r"^\d+ - .+" + RE_EXT + "$"


def es_audio(nombre):
    return nombre.lower().endswith(EXT_AUDIO) and not os.path.basename(nombre).startswith(".")


def audios(carpeta, recursivo=True):
    """Audios bajo carpeta, ordenados — reemplaza glob(«**/*.flac», recursive=True): como glob, salta los nombres y
    carpetas que empiezan con «.» (p. ej. los temporales .tn-tmp-N de numeros_pista.py)."""
    out = []
    for d, dirs, fs in os.walk(carpeta):
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        out += [os.path.join(d, f) for f in fs if es_audio(f)]
        if not recursivo:
            break
    return sorted(out)


def con_perdida(ruta):
    ext = os.path.splitext(ruta)[1].lower()
    if ext in CON_PERDIDA:
        return True
    if ext in (".m4a", ".mp4"):
        try:
            from mutagen.mp4 import MP4
            return "alac" not in (getattr(MP4(ruta).info, "codec", "") or "").lower()
        except Exception:
            return True
    return False


def verificar(ruta):
    """(ok, detalle): el audio se decodifica ENTERO sin errores. FLAC: flac -t (tiene firma MD5). Los demás: ffmpeg
    decodifica todo y además se compara la duración decodificada con la que declara la cabecera — un MP3 cortado se
    decodifica «bien» hasta donde llega (28 sep: el MP3 cortado a la mitad declaraba 190,7 s y daba 86 s)."""
    if ruta.lower().endswith(".flac"):
        r = subprocess.run(["flac", "-t", "-s", ruta], capture_output=True, text=True)
        return r.returncode == 0, (r.stderr or "").strip()
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", ruta, "-f", "null", "-"],
                       capture_output=True, text=True)
    err = (r.stderr or "").strip()
    if r.returncode != 0 or err:
        return False, err or f"ffmpeg salió con {r.returncode}"
    us = [int(l.split("=", 1)[1]) for l in r.stdout.splitlines() if l.startswith("out_time_us=") and l.split("=", 1)[1].isdigit()]
    decodificado = (us[-1] / 1e6) if us else 0
    try:
        declarado = abrir(ruta).info.length
    except Exception:
        declarado = 0
    if declarado and decodificado < declarado - max(2, declarado * 0.03):
        return False, f"se decodifican {decodificado:.1f} s de {declarado:.1f} s (archivo cortado)"
    if ruta.lower().endswith((".ogg", ".oga", ".opus")):
        # Ogg no declara la duración total (sale de la última página que haya): un corte no cambia la cuenta. Pero la
        # última página de un stream completo lleva la marca de FIN (EOS); en uno cortado falta.
        from mutagen.ogg import OggPage
        ultima = None
        with open(ruta, "rb") as fo:
            while True:
                try:
                    ultima = OggPage(fo)
                except Exception:
                    break
        if ultima is None or not ultima.last:
            return False, "el stream Ogg no tiene su página final (archivo cortado)"
    return True, ""


def abrir(ruta):
    ext = os.path.splitext(ruta)[1].lower()
    if ext == ".flac":
        return FLAC(ruta)
    if ext == ".mp3":
        return _MP3(ruta)
    if ext in (".m4a", ".mp4"):
        return _MP4(ruta)
    if ext in (".ogg", ".oga", ".opus"):
        return _Ogg(ruta)
    raise ValueError(f"formato no soportado: {ruta}")


# ---------------------------------------------------------------- comunes
def _lista(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [str(v)]


def _pic_desde_bytes(data, mime=None, tipo=3, desc=""):
    p = Picture()
    p.type, p.desc, p.data = tipo, desc, data
    p.mime = mime or ("image/png" if data[:4] == b"\x89PNG" else "image/jpeg")
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        p.width, p.height = im.size
        p.depth = {"RGB": 24, "RGBA": 32, "L": 8}.get(im.mode, 24)
    except Exception:
        pass
    return p


class _Info:
    """Lo que los scripts leen de t.info (en FLAC es el de mutagen; aquí se completa lo que no traen otros formatos)."""
    def __init__(self, i):
        self.length = getattr(i, "length", 0) or 0
        self.sample_rate = getattr(i, "sample_rate", 0) or 0
        self.channels = getattr(i, "channels", 0) or 0
        self.bitrate = getattr(i, "bitrate", 0) or 0
        self.bits_per_sample = getattr(i, "bits_per_sample", 0) or 0
        self.total_samples = int(round(self.length * self.sample_rate))
        self.md5_signature = 0            # solo FLAC tiene firma MD5 del audio
        self.codec = getattr(i, "codec", "") or type(i).__name__


class _Base:
    """Interfaz tipo diccionario sobre _leer/_escribir/_borrar/_claves de cada formato."""
    def get(self, k, default=None):
        v = self._leer(k.lower())
        return v if v else default

    def __getitem__(self, k):
        v = self._leer(k.lower())
        if not v:
            raise KeyError(k)
        return v

    def __setitem__(self, k, v):
        self._escribir(k.lower(), _lista(v))

    def __delitem__(self, k):
        if not self._leer(k.lower()):
            raise KeyError(k)
        self._borrar(k.lower())

    def __contains__(self, k):
        return bool(self._leer(k.lower()))

    def pop(self, k, *default):
        v = self._leer(k.lower())
        if v:
            self._borrar(k.lower())
            return v
        if default:
            return default[0]
        raise KeyError(k)

    def keys(self):
        return self._claves()

    def items(self):
        return [(k, self._leer(k)) for k in self._claves()]

    def update(self, d):
        for k, v in dict(d).items():
            self[k] = v

    def delete(self):
        """Como FLAC.delete(): quita del ARCHIVO, ya (sin save()), todas las etiquetas de texto; las carátulas quedan
        (en FLAC son otro bloque: tags_backup.py desde-kit hace delete() y vuelve a abrir el archivo contando con eso).
        Para quitar también las carátulas: clear_pictures() + save()."""
        self._quitar_texto()
        self.save()

    def _pares(self):
        return [(k, v) for k in self._claves() for v in self._leer(k)]

    def _propios(self, k):   # los valores guardados bajo esa clave (M4A: sin la fecha que se lee de ©day)
        return self._leer(k.lower())

    @property
    def tags(self):
        """Pares (clave, valor) como la VCommentDict de FLAC: [("title", "X"), ("artist", "A"), ("artist", "B"), …]."""
        return _Etiquetas(self)


class _Etiquetas(list):
    """t.tags en MP3/M4A/Ogg, como la VCommentDict de FLAC: lista de pares (clave, valor) que también se usa como
    diccionario (t.tags.get(k), t.tags[k], k in t.tags, t.tags.keys()) y que ESCRIBE en el archivo: t.tags[k] = [...],
    del t.tags[k], t.tags.clear() (el texto, no las carátulas) y t.tags.append((k, v)) — así restauran etiquetas
    tags_backup.py (restore y desde-kit). Se guarda con t.save() del archivo, como en FLAC."""
    def __init__(self, archivo):
        list.__init__(self, archivo._pares())
        self._a = archivo

    def _releer(self):
        list.clear(self)
        list.extend(self, self._a._pares())

    def __getitem__(self, k):
        return list.__getitem__(self, k) if isinstance(k, (int, slice)) else self._a[k]

    def __setitem__(self, k, v):
        self._a[k] = v
        self._releer()

    def __delitem__(self, k):
        del self._a[k]
        self._releer()

    def __contains__(self, k):
        return k in self._a if isinstance(k, str) else list.__contains__(self, k)

    def get(self, k, default=None):
        return self._a.get(k, default)

    def keys(self):
        return self._a.keys()

    def as_dict(self):
        return dict(self._a.items())

    def update(self, d):
        self._a.update(d)
        self._releer()

    def clear(self):   # como en FLAC: solo en memoria, se escribe con save()
        self._a._quitar_texto()
        self._releer()

    def append(self, par):
        k, v = par
        self._a[k] = self._a._propios(k) + [v]
        self._releer()


# ---------------------------------------------------------------- MP3 (ID3v2.4)
_ID3_TEXTO = {"title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2", "date": "TDRC",
              "originaldate": "TDOR", "genre": "TCON", "isrc": "TSRC", "organization": "TPUB", "media": "TMED",
              "copyright": "TCOP", "composer": "TCOM", "bpm": "TBPM", "encodedby": "TENC", "language": "TLAN",
              "albumsort": "TSOA", "artistsort": "TSOP", "titlesort": "TSOT", "albumartistsort": "TSO2",
              "discsubtitle": "TSST", "lyricist": "TEXT", "grouping": "TIT1", "conductor": "TPE3", "remixer": "TPE4",
              "releasedate": "TDRL", "subtitle": "TIT3", "mood": "TMOO", "key": "TKEY"}
_ID3_TXXX = {"musicbrainz_albumid": "MusicBrainz Album Id", "musicbrainz_artistid": "MusicBrainz Artist Id",
             "musicbrainz_albumartistid": "MusicBrainz Album Artist Id",
             "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
             "musicbrainz_releasetrackid": "MusicBrainz Release Track Id",
             "musicbrainz_workid": "MusicBrainz Work Id", "releasestatus": "MusicBrainz Album Status",
             "releasetype": "MusicBrainz Album Type", "releasecountry": "MusicBrainz Album Release Country",
             "acoustid_id": "Acoustid Id", "acoustid_fingerprint": "Acoustid Fingerprint"}
_ID3_TXXX_INV = {v.lower(): k for k, v in _ID3_TXXX.items()}
_POS = {"tracknumber": ("TRCK", 0), "totaltracks": ("TRCK", 1), "tracktotal": ("TRCK", 1),
        "discnumber": ("TPOS", 0), "totaldiscs": ("TPOS", 1), "disctotal": ("TPOS", 1)}


class _MP3(_Base):
    def __init__(self, ruta):
        from mutagen.mp3 import MP3
        self.filename = ruta
        self._m = MP3(ruta)
        if self._m.tags is None:
            self._m.add_tags()
        self.info = _Info(self._m.info)

    @property
    def _t(self):
        return self._m.tags

    def _txxx_desc(self, k):
        return _ID3_TXXX.get(k, k.upper())

    def _leer(self, k):
        t = self._t
        if k in _ID3_TEXTO:
            f = t.get(_ID3_TEXTO[k])
            return [str(x) for x in f.text] if f else []
        if k in _POS:
            fid, i = _POS[k]
            f = t.get(fid)
            if not f or not f.text:
                return []
            partes = str(f.text[0]).split("/")
            return [partes[i]] if len(partes) > i and partes[i] else []
        if k == "lyrics":
            return [f.text for f in t.getall("USLT") if f.text]
        if k == "musicbrainz_trackid":
            for f in t.getall("UFID"):
                if f.owner == "http://musicbrainz.org":
                    return [f.data.decode("utf-8", "replace")]
            return []
        for f in t.getall("TXXX"):
            if f.desc.lower() == self._txxx_desc(k).lower():
                return [str(x) for x in f.text]
        return []

    def _escribir(self, k, vals):
        from mutagen.id3 import TXXX, UFID, USLT, Frames
        t = self._t
        if not vals:
            return self._borrar(k)
        if k in _ID3_TEXTO:
            t.setall(_ID3_TEXTO[k], [Frames[_ID3_TEXTO[k]](encoding=3, text=vals)])
        elif k in _POS:
            fid, i = _POS[k]
            f = t.get(fid)
            partes = (str(f.text[0]).split("/") if f and f.text else []) + ["", ""]
            partes[i] = vals[0]
            txt = partes[0] + (f"/{partes[1]}" if partes[1] else "")
            t.setall(fid, [Frames[fid](encoding=3, text=[txt])])
        elif k == "lyrics":
            t.delall("USLT")
            t.add(USLT(encoding=3, lang="XXX", desc="", text=vals[0]))
        elif k == "musicbrainz_trackid":
            t.delall("UFID:http://musicbrainz.org")
            t.add(UFID(owner="http://musicbrainz.org", data=vals[0].encode()))
        else:
            desc = self._txxx_desc(k)
            for f in list(t.getall("TXXX")):
                if f.desc.lower() == desc.lower():
                    t.delall(f.HashKey)
            t.add(TXXX(encoding=3, desc=desc, text=vals))

    def _borrar(self, k):
        t = self._t
        if k in _ID3_TEXTO:
            t.delall(_ID3_TEXTO[k])
        elif k in _POS:
            fid, i = _POS[k]
            f = t.get(fid)
            if f and f.text:
                partes = str(f.text[0]).split("/")
                if i == 0:
                    t.delall(fid)
                elif partes[0]:
                    from mutagen.id3 import Frames
                    t.setall(fid, [Frames[fid](encoding=3, text=[partes[0]])])
        elif k == "lyrics":
            t.delall("USLT")
        elif k == "musicbrainz_trackid":
            t.delall("UFID:http://musicbrainz.org")
        else:
            desc = self._txxx_desc(k)
            for f in list(t.getall("TXXX")):
                if f.desc.lower() == desc.lower():
                    t.delall(f.HashKey)

    def _claves(self):
        t, ks = self._t, []
        inv = {v: k for k, v in _ID3_TEXTO.items()}
        for f in t.values():
            fid = f.FrameID
            if fid in inv:
                ks.append(inv[fid])
            elif fid in ("TRCK", "TPOS"):
                n = "tracknumber" if fid == "TRCK" else "discnumber"
                tot = "totaltracks" if fid == "TRCK" else "totaldiscs"
                ks.append(n)
                if "/" in str(f.text[0]):
                    ks.append(tot)
            elif fid == "USLT":
                ks.append("lyrics")
            elif fid == "UFID" and f.owner == "http://musicbrainz.org":
                ks.append("musicbrainz_trackid")
            elif fid == "TXXX":
                ks.append(_ID3_TXXX_INV.get(f.desc.lower(), f.desc.lower()))
        return list(dict.fromkeys(ks))

    @property
    def pictures(self):
        return [_pic_desde_bytes(f.data, f.mime, int(f.type), f.desc) for f in self._t.getall("APIC")]

    def clear_pictures(self):
        self._t.delall("APIC")

    def add_picture(self, pic):
        from mutagen.id3 import APIC
        self._t.add(APIC(encoding=3, mime=pic.mime, type=pic.type, desc=pic.desc or "", data=pic.data))

    def save(self):
        self._m.save(v2_version=4)

    def _quitar_texto(self):
        for clave in list(self._t.keys()):
            if not clave.startswith("APIC"):
                del self._t[clave]


# ---------------------------------------------------------------- M4A / MP4
# Fechas en M4A (mappings.yaml de Navidrome 0.64): ©day es la fecha de PUBLICACIÓN (la que agrupa discos, como YEAR en
# FLAC) → ahí va «year»; la fecha completa («date») va en ----:DATE (si no está, se lee ©day). Probado 28 sep.
_MP4_ATOM = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "albumartist": "aART", "year": "\xa9day",
             "genre": "\xa9gen", "composer": "\xa9wrt", "comment": "\xa9cmt", "lyrics": "\xa9lyr", "copyright": "cprt",
             "grouping": "\xa9grp", "albumsort": "soal", "artistsort": "soar", "titlesort": "sonm",
             "albumartistsort": "soaa", "encodedby": "\xa9too"}
_MP4_FREE = {"musicbrainz_trackid": "MusicBrainz Track Id", "musicbrainz_albumid": "MusicBrainz Album Id",
             "musicbrainz_artistid": "MusicBrainz Artist Id", "musicbrainz_albumartistid": "MusicBrainz Album Artist Id",
             "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
             "musicbrainz_releasetrackid": "MusicBrainz Release Track Id", "musicbrainz_workid": "MusicBrainz Work Id",
             "releasestatus": "MusicBrainz Album Status", "releasetype": "MusicBrainz Album Type",
             "releasecountry": "MusicBrainz Album Release Country", "acoustid_id": "Acoustid Id",
             "isrc": "ISRC", "organization": "LABEL", "barcode": "BARCODE", "catalognumber": "CATALOGNUMBER",
             "asin": "ASIN", "media": "MEDIA", "script": "SCRIPT", "originaldate": "ORIGINALDATE",
             "replaygain_track_gain": "replaygain_track_gain", "replaygain_track_peak": "replaygain_track_peak",
             "replaygain_album_gain": "replaygain_album_gain", "replaygain_album_peak": "replaygain_album_peak",
             "replaygain_reference_loudness": "replaygain_reference_loudness"}
_MP4_FREE_INV = {v.lower(): k for k, v in _MP4_FREE.items()}
_MP4_POS = {"tracknumber": ("trkn", 0), "totaltracks": ("trkn", 1), "tracktotal": ("trkn", 1),
            "discnumber": ("disk", 0), "totaldiscs": ("disk", 1), "disctotal": ("disk", 1)}
_FF = "----:com.apple.iTunes:"


class _MP4(_Base):
    def __init__(self, ruta):
        from mutagen.mp4 import MP4
        self.filename = ruta
        self._m = MP4(ruta)
        if self._m.tags is None:
            self._m.add_tags()
        self.info = _Info(self._m.info)

    @property
    def _t(self):
        return self._m.tags

    def _free(self, k):
        return _FF + _MP4_FREE.get(k, k.upper())

    def _leer(self, k, alias=True):
        t = self._t
        if k in _MP4_ATOM:
            return [str(x) for x in t.get(_MP4_ATOM[k], [])]
        if k in _MP4_POS:
            atom, i = _MP4_POS[k]
            v = t.get(atom)
            return [str(v[0][i])] if v and v[0][i] else []
        for atom in (self._free(k),):
            for key in list(t.keys()):
                if key.lower() == atom.lower():
                    return [bytes(x).decode("utf-8", "replace") for x in t[key]]
        if alias and k == "date" and t.get("\xa9day"):   # M4A de otra fuente: la fecha completa suele estar en ©day
            return [str(t["\xa9day"][0])]
        return []

    def _propios(self, k):
        return self._leer(k.lower(), alias=False)

    def _escribir(self, k, vals):
        from mutagen.mp4 import MP4FreeForm
        t = self._t
        if not vals:
            return self._borrar(k)
        if k in _MP4_ATOM:
            t[_MP4_ATOM[k]] = vals
        elif k in _MP4_POS:
            atom, i = _MP4_POS[k]
            v = list(t.get(atom, [(0, 0)])[0])
            try:
                v[i] = int(str(vals[0]).split("/")[0])
            except ValueError:
                return
            t[atom] = [tuple(v)]
        else:
            atom = self._free(k)
            for key in [x for x in t.keys() if x.lower() == atom.lower()]:
                del t[key]
            t[atom] = [MP4FreeForm(v.encode("utf-8")) for v in vals]

    def _borrar(self, k):
        t = self._t
        if k in _MP4_ATOM:
            t.pop(_MP4_ATOM[k], None)
        elif k in _MP4_POS:
            atom, i = _MP4_POS[k]
            v = t.get(atom)
            if v:
                if i == 0:
                    del t[atom]
                else:
                    t[atom] = [(v[0][0], 0)]
        else:
            atom = self._free(k)
            for key in [x for x in t.keys() if x.lower() == atom.lower()]:
                del t[key]

    def _claves(self):
        t, ks = self._t, []
        inv = {v: k for k, v in _MP4_ATOM.items()}
        for key in t.keys():
            if key in inv:
                ks.append(inv[key])
            elif key in ("trkn", "disk"):
                n, tot = ("tracknumber", "totaltracks") if key == "trkn" else ("discnumber", "totaldiscs")
                if t[key][0][0]: ks.append(n)
                if t[key][0][1]: ks.append(tot)
            elif key.startswith(_FF):
                nombre = key[len(_FF):]
                ks.append(_MP4_FREE_INV.get(nombre.lower(), nombre.lower()))
        return list(dict.fromkeys(ks))

    @property
    def pictures(self):
        from mutagen.mp4 import MP4Cover
        return [_pic_desde_bytes(bytes(c), "image/png" if c.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg")
                for c in self._t.get("covr", [])]

    def clear_pictures(self):
        self._t.pop("covr", None)

    def add_picture(self, pic):
        from mutagen.mp4 import MP4Cover
        fmt = MP4Cover.FORMAT_PNG if pic.mime == "image/png" else MP4Cover.FORMAT_JPEG
        self._t["covr"] = list(self._t.get("covr", [])) + [MP4Cover(pic.data, imageformat=fmt)]

    def save(self):
        if "\xa9day" not in self._t:   # sin año propio: el de la fecha, para que Navidrome agrupe el disco. Al guardar y no
            fecha = [x for x in self._leer("date") if x[:4].isdigit()]   # al escribir «date»: si no, restaurar un respaldo
            if fecha:                                                    # (date antes que year) duplicaba el año
                self._t["\xa9day"] = [fecha[0][:4]]
        self._m.save()

    def _quitar_texto(self):   # las carátulas (covr) quedan
        for clave in list(self._t.keys()):
            if clave != "covr":
                del self._t[clave]


# ---------------------------------------------------------------- Ogg Vorbis / Opus (comentarios Vorbis, como FLAC)
class _Ogg(_Base):
    def __init__(self, ruta):
        import mutagen
        self.filename = ruta
        self._m = mutagen.File(ruta)
        if self._m is None:
            raise ValueError(f"no es Ogg/Opus: {ruta}")
        if self._m.tags is None:
            self._m.add_tags()
        self.info = _Info(self._m.info)

    def _leer(self, k):
        if k == "metadata_block_picture":
            return []
        return list(self._m.tags.get(k, []))

    def _escribir(self, k, vals):
        self._m.tags[k] = vals

    def _borrar(self, k):
        if k in self._m.tags:
            del self._m.tags[k]

    def _claves(self):
        return [k.lower() for k in dict.fromkeys(k for k, _ in self._m.tags) if k.lower() != "metadata_block_picture"]

    @property
    def pictures(self):
        out = []
        for b64 in self._m.tags.get("metadata_block_picture", []):
            try:
                out.append(Picture(base64.b64decode(b64)))
            except Exception:
                pass
        return out

    def clear_pictures(self):
        if "metadata_block_picture" in self._m.tags:
            del self._m.tags["metadata_block_picture"]

    def add_picture(self, pic):
        viejas = list(self._m.tags.get("metadata_block_picture", []))
        self._m.tags["metadata_block_picture"] = viejas + [base64.b64encode(pic.write()).decode("ascii")]

    def save(self):
        self._m.save()

    def _quitar_texto(self):   # las carátulas (metadata_block_picture) quedan
        pics = list(self._m.tags.get("metadata_block_picture", []))
        self._m.tags.clear()
        if pics:
            self._m.tags["metadata_block_picture"] = pics
