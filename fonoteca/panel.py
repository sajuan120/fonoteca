#!/usr/bin/env python3
"""PANEL de fonoteca: todas las herramientas con botones, en una ventana del navegador (1 oct 2026).

Uso: panel.py              abre el panel (y arranca su servidor si no está corriendo)
     panel.py --servir     solo el servidor (queda de fondo y se apaga solo tras 20 min sin uso)
     panel.py --instalar   agrega «Fonoteca» al menú de aplicaciones, con su ícono

Las mismas reglas que en la terminal, con botones:
  · Primero la simulación: EJECUTAR se enciende solo después de SIMULAR esa acción con esos mismos datos, y el servidor
    lo exige igual. Después de cualquier ejecución hay que volver a simular (la biblioteca ya cambió). Lo que no tiene
    simulación (NAVIDROME AL DÍA, RESTAURAR ETIQUETAS, REINICIAR) pide un segundo clic.
  · Una acción a la vez. La salida se ve en vivo y queda guardada en logs/panel/.
  · Lo que mueve o renombra canciones (duplicados, números de pista, quitar una copia, numerar a mano) pasa al terminar
    sus escuchas, estrellas y playlists en Navidrome (nd_actualizar.py con el log que dejó), como hace el procesado.
    Si termina con error y dejó un log de cambios, el panel lo avisa en vez de pasarlo.
Seguridad: escucha solo en 127.0.0.1. Cada pedido lleva un token que solo conoce la página (otra página abierta en el
navegador no puede lanzar nada), se rechaza un Host que no sea el local y la página no se deja incrustar.
Sin dependencias: solo la biblioteca estándar. Puerto: [panel] puerto en config.toml (4747 por defecto).
"""
import codecs, datetime, glob, json, os, re, secrets, shutil, signal, sqlite3, subprocess, sys, threading, time
import unicodedata, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from comun import (CONF, HERE, ROOT, LOGS, RESPALDOS, LISTAS, KIT, PORTADAS_IA, NAVIDROME, NAVIDROME_DB, OCTO, SCRIPTS,
                   DOC, DOC_FLAC, DOC_AUDITORIA, DUDOSAS, SKIP, PRUEBA, antra_abierto, sin_procesar, a_conseguir,
                   esperando_rebajar, rutas_por_sid)
from audio import es_audio, con_perdida

PUERTO = int(os.environ.get("FONOTECA_PANEL_PUERTO") or CONF.get("panel", {}).get("puerto", 4747))   # env: pruebas
ND_URL = CONF.get("navidrome", {}).get("url", "http://localhost:4533")   # para el enlace a la web de Navidrome
REPO = CONF.get("rutas", {}).get("repositorio")                          # la carpeta pública (publicar.py)
REPO = os.path.expanduser(REPO) if REPO else None
REGISTRO = os.path.join(LOGS, "panel")         # la salida de cada acción corrida desde el panel
TOKEN_ARCHIVO = os.path.join(REGISTRO, ".token")
INACTIVO = 20 * 60                             # se apaga solo tras 20 min sin pedidos (y sin nada corriendo)
VIGENCIA = 60 * 60                             # una simulación vale para EJECUTAR durante 1 h
PY = sys.executable
YO = os.path.abspath(__file__)
VERSION = str(os.path.getmtime(YO))            # el lanzador reinicia un servidor de una versión anterior
HOSTS = {f"127.0.0.1:{PUERTO}", f"localhost:{PUERTO}"}
ORIGENES = {f"http://{h}" for h in HOSTS}


def _compose(carpeta):
    p = os.path.join(carpeta, "docker-compose.yml")
    return p if os.path.isfile(p) else None
ND_COMPOSE, OCTO_COMPOSE = _compose(NAVIDROME), _compose(OCTO)

def _contenedor(compose, defecto):
    try:
        m = re.search(r"^\s*container_name:\s*[\"']?([\w.-]+)", open(compose, encoding="utf-8").read(), re.M)
        return m.group(1) if m else defecto
    except (OSError, TypeError):
        return defecto
ND_CONTENEDOR, OCTO_CONTENEDOR = _contenedor(ND_COMPOSE, "navidrome"), _contenedor(OCTO_COMPOSE, "octo-fiesta")


# ═══════════════════════════════════ catálogo: cada botón y qué comando arma ═══════════════════════════════════
# Campo: tipo = texto | numero | opcion | casilla | marcas (varias casillas) | descarga (carpeta de Antra sin procesar) |
#   carpeta / cancion (de la biblioteca) | archivo / directorio (fuera de ella: ext y donde) | persona (usuarios/) |
#   usuario (de Navidrome) | lista (varios textos) | carpetas / rutas (varios discos, o discos y canciones) | logs.
# Acción: tipo = sim (SIMULAR → EJECUTAR, agrega --execute) | lee (un botón; no toca la biblioteca) | directo (actúa
#   sin simulación: segundo clic). antra = "siempre" (no corre con Antra abierto) o "ejecutar" (solo simula).
#   navidrome = True: al ejecutar, pasa a Navidrome las escuchas de lo que movió (los logs de cambios que dejó).
MULTI = {"lista", "carpetas", "rutas", "logs"}
ACCIONES, POR_ID = [], {}
GRUPOS = [
    {"id": "descargas", "nombre": "DESCARGAS", "texto": "Lo que bajó Antra, y lo que falta conseguir."},
    {"id": "revision", "nombre": "REVISIÓN", "texto": "Documentos, auditoría, salud y banco de pruebas: solo leen la biblioteca."},
    {"id": "biblioteca", "nombre": "BIBLIOTECA", "texto": "Sobre toda la biblioteca. Son los pasos del procesado, por si hace falta uno suelto."},
    {"id": "mano", "nombre": "A MANO", "texto": "Arreglos puntuales, con rutas de la biblioteca (Artista/Año - Álbum)."},
    {"id": "embudo", "nombre": "EMBUDO", "texto": "Música nueva a prueba (Octo-Fiesta) y la playlist «Descubrir»."},
    {"id": "personas", "nombre": "PERSONAS", "texto": "El historial y las playlists de Spotify de cada persona."},
    {"id": "caratulas", "nombre": "CARÁTULAS IA", "texto": "Agrandar con IA las carátulas chicas que no están en grande en ningún lado. Se eligen a ojo."},
    {"id": "respaldo", "nombre": "RESPALDO", "texto": "Kit de recuperación y respaldos de etiquetas."},
    {"id": "sistema", "nombre": "SISTEMA", "texto": "Servicios y publicación."},
    {"id": "registro", "nombre": "REGISTRO", "texto": "Lo que se corrió desde el panel (logs/panel/). Clic para verlo en la consola."},
]

def C(clave, etiqueta, tipo="texto", **kw):
    return {"clave": clave, "etiqueta": etiqueta, "tipo": tipo, **kw}

def A(grupo, id_, nombre, texto, cmd, tipo="sim", campos=(), args=None, si=True, **kw):
    if not si or (PRUEBA and kw.get("real")):   # real: toca Navidrome, Docker o internet de verdad aunque sea modo prueba
        return
    a = {"grupo": grupo, "id": id_, "nombre": nombre, "texto": texto, "cmd": cmd, "tipo": tipo, "campos": list(campos),
         "args": args or (lambda v: []), **kw}
    ACCIONES.append(a); POR_ID[id_] = a

def _opt(bandera, valor):
    return [bandera, valor] if valor else []

# 01 DESCARGAS
A("descargas", "procesar", "PROCESAR DESCARGA",
  "El único comando después de cada descarga de Antra: integridad, ¿es la canción?, etiquetas, orden, duplicados, "
  "géneros, números, carátulas, letras, volumen, Navidrome, documento de pendientes y kit.",
  ["procesar_descarga.py"], antra="siempre", sim_estricta=True, largo=True,
  campos=[C("carpeta", "CARPETA", "descarga", obligatorio=True, ayuda="la carpeta que creó Antra"),
          C("historial", "HISTORIAL", "archivo", ext=[".zip"], donde=["descargas", "usuarios"],
            ayuda="opcional: zip del historial de Spotify (arma su playlist)"),
          C("usuario", "USUARIO", "usuario", ayuda="con el historial: dueño de esa playlist")],
  args=lambda v: [v["carpeta"], *_opt("--historial", v["historial"]), *_opt("--usuario", v["usuario"])],
  validar=lambda v: "El historial y el usuario van juntos." if bool(v["historial"]) != bool(v["usuario"]) else None)
A("descargas", "juntar", "JUNTAR CANCIONES SUELTAS",
  "Bajado desde el enlace de una canción o de un disco, Antra lo guarda como «Artista/Año - Álbum/Artista - Título»: "
  "esto lo junta en UNA carpeta, para procesarla como cualquier descarga.",
  ["juntar_descarga.py"], antra="siempre",
  campos=[C("carpeta", "CARPETA NUEVA", obligatorio=True, ayuda="nombre sin «/», p. ej. el título"),
          C("url", "ENLACE", ayuda="opcional: el enlace que se bajó (si no bajó nada, queda anotado)")],
  args=lambda v: [v["carpeta"], *_opt("--url", v["url"])],
  validar=lambda v: "La carpeta va sin «/»." if "/" in v["carpeta"] else None)
A("descargas", "fuentes", "BUSCAR EN OTRAS TIENDAS",
  "Las canciones que Antra no consiguió, buscadas en Deezer, Tidal, Apple Music y Qobuz: mismo artista, misma "
  "canción y misma duración. Los enlaces quedan en la carpeta de listas, para pegarlos en Antra.",
  ["buscar_fuentes.py"], tipo="lee", boton="BUSCAR", abrir=["listas"],
  campos=[C("en", "TIENDAS", "marcas", opciones=[["deezer", "Deezer"], ["tidal", "Tidal"], ["apple", "Apple"],
                                                  ["qobuz", "Qobuz"]], defecto=["deezer", "tidal", "apple", "qobuz"])],
  args=lambda v: ["--en", ",".join(v["en"])] if v["en"] else [],
  validar=lambda v: None if v["en"] else "Elige al menos una tienda.")
A("descargas", "spotify_id", "PONER SPOTIFY_ID",
  "Después de bajar con Antra esos enlaces de otras tiendas, y ANTES de procesar: les pone su spotify_id, para que el "
  "procesado pueda compararlas con la canción exacta y devolverlas a sus playlists.",
  ["buscar_fuentes.py"], campos=[C("carpeta", "CARPETA", "descarga", obligatorio=True)],
  args=lambda v: ["--poner-spotify-id", v["carpeta"]])
A("descargas", "importar", "IMPORTAR BAJADAS A MANO",
  "Canciones conseguidas fuera de Antra, en cualquier formato: entran a la biblioteca como una descarga. Después, "
  "PROCESAR DESCARGA con la carpeta que indique.",
  ["importar_manual.py"], antra="ejecutar",
  campos=[C("carpeta", "CARPETA", "directorio", obligatorio=True, donde=["descargas"], ayuda="la carpeta con los archivos")],
  args=lambda v: [v["carpeta"]])
A("descargas", "borrar", "BORRAR CANCIONES MALAS",
  "Borra las corruptas o las que tienen el audio equivocado (una ruta por línea en la lista) y las deja anotadas para "
  "volver a conseguirlas.",
  ["borrar_canciones.py"], antra="siempre",
  campos=[C("lista", "LISTA", "archivo", ext=[".txt", ".tsv"], donde=["listas", "descargas", "planes"], obligatorio=True,
            ayuda="archivo con una ruta por línea"),
          C("motivo", "MOTIVO", "opcion", opciones=[["corrupta", "corrupta"], ["equivocada", "audio equivocado"]],
            defecto="corrupta")],
  args=lambda v: [v["lista"], "--motivo", v["motivo"]])

# 02 REVISIÓN
A("revision", "revisar", "DOCUMENTO DE PENDIENTES",
  "Rehace «cosas por revisar» y «conseguir en FLAC» con el estado de ahora. Lo que ya se resolvió desaparece solo.",
  ["revisar.py"], tipo="lee", boton="GENERAR", abrir=["pendientes", "flac"])
A("revision", "auditoria", "AUDITORÍA",
  "Revisa TODA la biblioteca y deja cada hallazgo como ARREGLAR, DECIDIR o INFO. La rápida usa lo guardado de la "
  "última; la completa vuelve a probar el audio y a consultar Spotify (tarda).",
  ["auditoria.py"], tipo="lee", boton="AUDITAR", largo=True, abrir=["auditoria"],
  campos=[C("modo", "MODO", "opcion", opciones=[["rapida", "rápida (con lo guardado)"], ["completa", "completa"]],
            defecto="rapida")],
  args=lambda v: ["--sin-audio", "--sin-red"] if v["modo"] == "rapida" else [])
A("revision", "salud", "CHEQUEO DE SALUD",
  "Navidrome igual al disco, descargas sin procesar, playlists sanas y espacio libre. Es el mismo de cada domingo.",
  [os.path.join(SCRIPTS, "musica-salud.py")], tipo="lee", boton="CHEQUEAR",
  si=os.path.isfile(os.path.join(SCRIPTS, "musica-salud.py")))
A("revision", "banco", "BANCO DE PRUEBAS",
  "Corre el procesado completo sobre una biblioteca de mentira y comprueba cada paso (unos minutos). Después de cambiar "
  "cualquier script.",
  ["banco_pruebas.py"], tipo="lee", boton="PROBAR", largo=True)

# 03 BIBLIOTECA
A("biblioteca", "duplicados", "DUPLICADOS",
  "Una sola copia de cada grabación: sin pérdida antes que con pérdida; si no, la del disco con más canciones, o la "
  "más escuchada. La que sobra va a respaldos/.",
  ["duplicados.py"], antra="ejecutar", navidrome=True,
  campos=[C("isrc", "ISRC EXTRA", "lista", ayuda="opcional: ISRC que también son duplicados")],
  args=lambda v: ["--tambien", *v["isrc"]] if v["isrc"] else [])
A("biblioteca", "fechas", "UNA FECHA POR DISCO",
  "Si las canciones de un disco tienen años distintos, Navidrome lo parte en varios.", ["fechas.py"], antra="ejecutar")
A("biblioteca", "generos", "GÉNEROS",
  "La lista corta de 20 géneros, hasta 2 por artista. Las bandas sonoras: los de su artista y «Soundtrack».",
  ["generos.py"])
A("biblioteca", "artista_album", "ARTISTA DEL DISCO",
  "Un solo artista del disco en cada disco, para que Navidrome no lo parta.", ["artista_album.py"])
A("biblioteca", "numeros", "NÚMEROS DE PISTA",
  "Números de pista y de disco según UNA edición de Deezer que tenga todas sus canciones, y archivos «NN - Título».",
  ["numeros_pista.py"], antra="ejecutar", navidrome=True)
A("biblioteca", "caratulas", "CARÁTULAS",
  "Las que faltan (Deezer o iTunes), las mezcladas dentro de un disco, o las chicas → la MISMA imagen en grande.",
  ["caratulas.py"], antra="ejecutar",
  campos=[C("modo", "QUÉ", "opcion", opciones=[["faltantes", "las que faltan"], ["mezcladas", "mezcladas"],
                                               ["mejorar", "chicas → grandes"]], defecto="faltantes")],
  args=lambda v: [v["modo"]])
A("biblioteca", "letras", "LETRAS",
  "Letras sincronizadas de LRCLIB, dentro de cada canción; marca las instrumentales.", ["letras.py"])
A("biblioteca", "replaygain", "VOLUMEN PAREJO",
  "ReplayGain 2.0 a lo que no lo tenga, o a los discos que digas (con «recalcular»).", ["replaygain.py"],
  campos=[C("carpetas", "DISCOS", "carpetas", ayuda="opcional: vacío = toda la biblioteca"),
          C("forzar", "recalcular aunque ya tengan", "casilla")],
  args=lambda v: [*v["carpetas"], *(["--forzar"] if v["forzar"] else [])])
A("biblioteca", "ids_mb", "IDS DE MUSICBRAINZ",
  "Comprueba que el ID de grabación de cada canción sea de SU grabación y corrige los ajenos.",
  ["ids_mb.py"], antra="ejecutar", largo=True,
  campos=[C("carpetas", "DISCOS", "carpetas", ayuda="opcional: vacío = toda la biblioteca"),
          C("sin_red", "sin consultar MusicBrainz (solo lo guardado)", "casilla")],
  args=lambda v: [*v["carpetas"], *(["--sin-red"] if v["sin_red"] else [])])
A("biblioteca", "mb_disco", "ID DE DISCO",
  "Completa el ID de disco de MusicBrainz donde falta.", ["mb_disco.py"],
  campos=[C("carpetas", "DISCOS", "carpetas", ayuda="opcional: vacío = toda la biblioteca")],
  args=lambda v: v["carpetas"])
A("biblioteca", "ost", "BANDAS SONORAS",
  "Un disco «Soundtrack <Obra>» por franquicia, con al menos 3 canciones (las de menos vuelven a su disco). Sigue solo "
  "con ReplayGain, géneros y Navidrome.",
  ["ost.py", "--seguir"], antra="ejecutar")
A("biblioteca", "devolver", "DEVOLVER A SUS PLAYLISTS",
  "Las canciones borradas (corruptas o equivocadas) que ya se volvieron a bajar vuelven a su lugar en sus playlists.",
  ["devolver_playlists.py"])
A("biblioteca", "nd", "NAVIDROME AL DÍA",
  "Escaneo, escuchas y estrellas de las rutas viejas a las nuevas (con los logs, en orden) y sin faltantes. El panel "
  "lo corre solo después de lo que mueve canciones; esto es por si quedó un log sin pasar.",
  ["nd_actualizar.py"], tipo="directo", boton="PONER AL DÍA",
  campos=[C("logs", "LOGS", "logs", ayuda="opcional: logs con cambios de ruta, el más viejo primero"),
          C("usuario", "DUEÑO DE PLAYLIST", "usuario", ayuda="opcional: _Playlists/<Nombre>.m3u queda a su nombre")],
  args=lambda v: [*v["logs"], *_opt("--usuario", v["usuario"])])

# 04 A MANO
A("mano", "quitar", "QUITAR UNA COPIA",
  "Quita una canción sin perder nada: sus escuchas, estrellas y playlists pasan a la que queda. Sin «queda», se quita "
  "sin reemplazo. Varias a la vez: una lista con «sobra<TAB>queda» por línea.",
  ["quitar_copia.py"], antra="ejecutar", navidrome=True,
  campos=[C("sobra", "SOBRA", "cancion", ayuda="la canción que se quita"),
          C("queda", "QUEDA", "cancion", ayuda="opcional: la que se queda con todo lo suyo"),
          C("lista", "O UNA LISTA", "archivo", ext=[".tsv", ".txt"], donde=["listas", "descargas", "planes"],
            ayuda="opcional: pares sobra<TAB>queda")],
  args=lambda v: ["--lista", v["lista"]] if v["lista"] else (
      [v["sobra"], v["queda"]] if v["queda"] else ["--sin-reemplazo", v["sobra"]]),
  validar=lambda v: None if bool(v["lista"]) != bool(v["sobra"]) else (
      "La canción que sobra, o una lista: no las dos." if v["lista"] else "falta SOBRA (o una lista)"))
A("mano", "unir", "UNIR DISCOS",
  "Une ediciones del mismo disco, o devuelve un sencillo a su disco: todo pasa al destino (nombre, artista, año, "
  "carátula) y sigue solo con números, ID de disco, ReplayGain y Navidrome.",
  ["unir_discos.py"], antra="ejecutar",
  campos=[C("destino", "DESTINO", "carpeta", obligatorio=True, ayuda="el disco que queda"),
          C("otras", "OTRAS", "rutas", obligatorio=True, ayuda="discos o canciones que pasan al destino")],
  args=lambda v: [v["destino"], *v["otras"], "--seguir"],
  validar=lambda v: "El destino no puede estar también en OTRAS." if v["destino"].rstrip("/") in
  [x.rstrip("/") for x in v["otras"]] else None)
A("mano", "numerar", "NUMERAR A MANO",
  "Numera un disco según un disco de Deezer elegido a mano (su ID está en el enlace: deezer.com/album/<ID>). Las que no "
  "estén en ese disco: «Título=N» o «Título=D-N».",
  ["numeros_pista.py"], antra="ejecutar", navidrome=True,
  campos=[C("carpeta", "DISCO", "carpeta", obligatorio=True, ayuda="Artista/Año - Álbum"),
          C("deezer", "ID DE DEEZER", obligatorio=True, ayuda="solo números"),
          C("fijas", "A MANO", "lista", ayuda="opcional: Título=N")],
  args=lambda v: ["--a-mano", v["carpeta"], "--deezer", v["deezer"], *v["fijas"]],
  validar=lambda v: None if v["deezer"].isdigit() else "El ID de Deezer son solo números.")

# 05 EMBUDO (Octo-Fiesta)
_embudo = os.path.isdir(os.path.join(ROOT, "_Prueba")) or bool(OCTO_COMPOSE)
A("embudo", "marcar", "MARCAR LAS DE PRUEBA",
  "Pone a las canciones de prueba sus géneros reales y «Prueba». Ya lo hace solo cada 5 minutos.",
  ["prueba.py", "marcar"], tipo="lee", boton="MARCAR", si=_embudo,
  campos=[C("todo", "recalcular también las que ya tienen géneros", "casilla")],
  args=lambda v: ["--todo"] if v["todo"] else [])
A("embudo", "embudo", "EMBUDO",
  "Lo de cada día: 3+ escuchas en 4 semanas → gana su FLAC; si ya está en la biblioteca → se reemplaza; 6 semanas sin "
  "escucharse → aviso y se borra; ganó el FLAC hace 14 días y no llegó → entra en MP3.",
  ["prueba.py", "revisar"], antra="ejecutar", si=_embudo)
A("embudo", "descubrir", "DESCUBRIR",
  "La playlist semanal con recomendaciones de ListenBrainz que nunca escuchaste.", ["descubrir.py"],
  si=bool(CONF.get("descubrir")), real=True,
  campos=[C("usuario", "PARA", "opcion", opciones=[["", "todos"]] + [[d["navidrome"], d["navidrome"]]
                                                                    for d in CONF.get("descubrir", [])], defecto=""),
          C("n", "CANCIONES", "numero", defecto="20", min=5, max=60)],
  args=lambda v: [*_opt("--usuario", v["usuario"]), *_opt("--n", v["n"])])

# 06 PERSONAS
A("personas", "seleccion", "QUÉ BAJARLE A ALGUIEN",
  "Con su historial de Spotify elige lo que de verdad escucha (en días distintos, elegido a propósito, escuchado hasta "
  "el final) y, si quieres, los discos que escucha como disco. Deja listas de enlaces para Antra.",
  ["seleccion_usuario.py"], tipo="lee", boton="ELEGIR", abrir=["listas"],
  campos=[C("nombre", "PERSONA", "persona", obligatorio=True, ayuda="su carpeta en usuarios/"),
          C("zip", "HISTORIAL", "archivo", ext=[".zip"], donde=["descargas", "usuarios"],
            ayuda="la primera vez: el zip de su historial extendido"),
          C("propias", "SUS PLAYLISTS", ayuda="opcional: archivo, o enlaces separados por comas"),
          C("playlists", "LAS QUE SIGUE", ayuda="opcional: archivo, o enlaces separados por comas"),
          C("albumes", "completar los discos que escucha como disco", "casilla")],
  args=lambda v: [v["nombre"], *_opt("--zip", v["zip"]), *_opt("--propias", v["propias"]),
                  *_opt("--playlists", v["playlists"]), *(["--albumes"] if v["albumes"] else [])])
A("personas", "playlist_historial", "PLAYLIST DE SU HISTORIAL",
  "Una playlist con las canciones de su historial que están en la biblioteca, las más escuchadas primero.",
  ["playlist_historial.py"],
  campos=[C("zip", "HISTORIAL", "archivo", ext=[".zip"], donde=["descargas", "usuarios"], obligatorio=True),
          C("nombre", "ARCHIVO", obligatorio=True, ayuda="nombre del .m3u"),
          C("min", "MÍNIMO DE ESCUCHAS", "numero", min=0, max=10000),
          C("dias", "SIN ESCUCHAR HACE (DÍAS)", "numero", min=1, max=100000),
          C("titulo", "TÍTULO", ayuda="opcional: el nombre que se ve")],
  args=lambda v: [v["zip"], v["nombre"], *_opt("--min-plays", v["min"]), *_opt("--sin-escuchar", v["dias"]),
                  *_opt("--titulo", v["titulo"])])
A("personas", "escuchas", "SUS ESCUCHAS A NAVIDROME",
  "Carga las escuchas de su historial de Spotify en sus reproducciones de Navidrome (lo detiene un momento y respalda "
  "la base antes).",
  ["nd_escuchas_spotify.py"], real=True,
  campos=[C("zip", "HISTORIAL", "archivo", ext=[".zip"], donde=["descargas", "usuarios"], obligatorio=True),
          C("usuario", "USUARIO", "usuario", obligatorio=True)],
  args=lambda v: [v["zip"], v["usuario"]])
A("personas", "playlists_cuenta", "SUS PLAYLISTS A NAVIDROME",
  "Pasa a Navidrome sus playlists propias, desde sus «datos de la cuenta» de Spotify.", ["playlists_cuenta.py"],
  campos=[C("zip", "DATOS", "archivo", ext=[".zip", ".json"], donde=["descargas", "usuarios"], obligatorio=True,
            ayuda="zip de datos de la cuenta, o PlaylistN.json"),
          C("usuario", "USUARIO", "usuario", obligatorio=True),
          C("solo", "SOLO ESTAS", ayuda="opcional: «Nombre 1,Nombre 2»")],
  args=lambda v: [v["zip"], v["usuario"], *_opt("--solo", v["solo"])])

# 07 CARÁTULAS IA
A("caratulas", "ia_preparar", "PREPARAR LA COMPARACIÓN",
  "Las carátulas chicas sin versión grande en internet, agrandadas con IA (Real-ESRGAN, el motor de Upscayl): "
  "1 original · 2 IA foto · 3 IA dibujo, todas en una página para elegir.",
  ["caratulas.py", "ia", "preparar"], tipo="lee", boton="PREPARAR", largo=True, abrir=["portadas"])
A("caratulas", "ia_aplicar", "APLICAR LAS ELEGIDAS",
  "Pone la elegida en todas las canciones de cada disco: NN=2 (IA foto), NN=3 (IA dibujo); NN=1 deja la original. "
  "NN es el número del disco en la comparación.",
  ["caratulas.py", "ia", "aplicar"], antra="ejecutar",
  campos=[C("elegidas", "ELEGIDAS", "lista", obligatorio=True, ayuda="p. ej. 07=2 (Enter para agregar)")],
  args=lambda v: v["elegidas"],
  validar=lambda v: None if all(re.fullmatch(r"\d{1,3}=[123]", x) for x in v["elegidas"]) else "Cada una como NN=1, NN=2 o NN=3.")

# 08 RESPALDO
A("respaldo", "kit", "KIT DE RECUPERACIÓN",
  "Rehace el kit: el enlace de cada canción, todas las etiquetas, las playlists y Navidrome, sin claves. Para subirlo a "
  "la nube.",
  ["kit_recuperacion.py"], tipo="lee", boton="REHACER", abrir=["kit"])
A("respaldo", "tags_dump", "RESPALDAR ETIQUETAS",
  "Guarda las etiquetas de texto de todas las canciones en respaldos/, para comparar o restaurar después.",
  ["tags_backup.py", "dump"], tipo="lee", boton="RESPALDAR",
  args=lambda v: [os.path.join(RESPALDOS, f"tags-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")])
A("respaldo", "tags_diff", "COMPARAR CON UN RESPALDO", "Qué etiquetas cambiaron desde un respaldo. No escribe nada.",
  ["tags_backup.py", "diff"], tipo="lee", boton="COMPARAR",
  campos=[C("archivo", "RESPALDO", "archivo", ext=[".json"], donde=["respaldos"], obligatorio=True)],
  args=lambda v: [v["archivo"]])
A("respaldo", "tags_restore", "RESTAURAR ETIQUETAS",
  "Deja las etiquetas EXACTAMENTE como en el respaldo (las carátulas no se tocan). Compara antes.",
  ["tags_backup.py", "restore"], tipo="directo", boton="RESTAURAR",
  campos=[C("archivo", "RESPALDO", "archivo", ext=[".json"], donde=["respaldos"], obligatorio=True)],
  args=lambda v: [v["archivo"]])
A("respaldo", "desde_kit", "ETIQUETAS DESDE EL KIT",
  "Tras volver a bajar la biblioteca con el kit: devuelve a cada canción, por su spotify_id, las etiquetas que tenía.",
  ["tags_backup.py", "desde-kit"],
  campos=[C("archivo", "ETIQUETAS", "archivo", ext=[".gz"], donde=["kit", "descargas"], obligatorio=True,
            ayuda="etiquetas.json.gz del kit")],
  args=lambda v: [v["archivo"]])

# 09 SISTEMA
for _comp, _nom, _id in ((ND_COMPOSE, "NAVIDROME", "nd_"), (OCTO_COMPOSE, "OCTO-FIESTA", "octo_")):
    A("sistema", _id + "arrancar", f"{_nom} · ARRANCAR", "Si está apagado.",
      ["docker", "compose", "-f", _comp or "", "up", "-d"], tipo="directo", boton="ARRANCAR", si=bool(_comp), real=True)
    A("sistema", _id + "reiniciar", f"{_nom} · REINICIAR", "Corta unos segundos lo que se esté escuchando.",
      ["docker", "compose", "-f", _comp or "", "restart"], tipo="directo", boton="REINICIAR", si=bool(_comp), real=True)
A("sistema", "publicar", "PUBLICAR EN EL REPOSITORIO",
  "Copia al repositorio público solo lo publicable, y se niega si encuentra un dato personal. No sube nada a internet: "
  "eso es aparte, con git.",
  ["publicar.py", REPO or ""], si=bool(REPO), real=True)

DONDE = {"descargas": ["~/Downloads", "~/Descargas", "~/Desktop", "~/Escritorio"], "listas": [LISTAS],
         "usuarios": [os.path.join(HERE, "usuarios")], "kit": [KIT], "respaldos": [RESPALDOS], "logs": [LOGS],
         "planes": [os.path.join(HERE, "planes")]}
ABRIR = {"pendientes": (DOC, "ABRIR PENDIENTES"), "flac": (DOC_FLAC, "ABRIR «CONSEGUIR EN FLAC»"),
         "auditoria": (DOC_AUDITORIA, "ABRIR AUDITORÍA"), "listas": (LISTAS, "ABRIR LISTAS"),
         "kit": (KIT, "ABRIR KIT"), "portadas": (os.path.join(PORTADAS_IA, "ver todas.html"), "ABRIR COMPARACIÓN"),
         "registro": (REGISTRO, "ABRIR CARPETA")}


# ═══════════════════════════════════ datos del formulario → comando ═══════════════════════════════════
def _plano(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).casefold()

def _casa(p):
    h = os.path.expanduser("~")
    return "~" + p[len(h):] if p == h or p.startswith(h + os.sep) else p

def _en_biblioteca(v):
    return os.path.join(ROOT, v)   # una ruta absoluta queda igual

def preparar(a, crudos):
    """(canon, valores para armar el comando, error, falta). canon = los valores tal como se escribieron, en texto
    (para comparar con la simulación); en los valores para el comando las rutas de archivo van expandidas."""
    canon, vx = {}, {}
    if not isinstance(crudos, dict):
        crudos = {}
    for c in a["campos"]:
        k, t, x, et = c["clave"], c["tipo"], crudos.get(c["clave"], c.get("defecto")), c["etiqueta"]
        if t == "casilla":
            canon[k] = vx[k] = bool(c.get("defecto")) if x is None else bool(x)
            continue
        if t in MULTI or t == "marcas":
            xs = x if isinstance(x, list) else ([] if x in (None, "") else str(x).splitlines())
            v = [str(s).strip() for s in xs if str(s).strip()]
            if t == "marcas":
                v = [o[0] for o in c["opciones"] if o[0] in v]
        else:
            v = "" if x is None else str(x).strip()
            if t == "opcion" and v not in {o[0] for o in c["opciones"]}:
                return None, None, f"{et}: elige una opción de la lista.", False
            if t == "numero" and v and not (v.isdigit() and c.get("min", 0) <= int(v) <= c.get("max", 10 ** 9)):
                return None, None, f"{et}: un número entre {c.get('min', 0)} y {c.get('max', 10 ** 9)}.", False
        for s in v if isinstance(v, list) else [v]:
            if s.startswith("-"):
                return None, None, f"{et}: no puede empezar con «-».", False
            if "\x00" in s or "\n" in s or len(s) > 2000:
                return None, None, f"{et}: texto inválido.", False
        if c.get("obligatorio") and not v:
            return None, None, f"falta {et}", True
        canon[k] = v
        if t in ("archivo", "directorio", "logs"):
            exp = [os.path.abspath(os.path.expanduser(s)) for s in (v if isinstance(v, list) else [v]) if s]
            for p in exp:
                if t == "directorio" and not os.path.isdir(p):
                    return None, None, f"{et}: no existe la carpeta {_casa(p)}", True
                if t != "directorio" and not os.path.isfile(p):
                    return None, None, f"{et}: no existe el archivo {_casa(p)}", True
            vx[k] = exp if isinstance(v, list) else (exp[0] if exp else "")
        elif t in ("carpeta", "carpetas", "descarga", "cancion", "rutas"):
            for s in v if isinstance(v, list) else ([v] if v else []):
                p = _en_biblioteca(s)
                ok = os.path.isfile(p) if t == "cancion" else (os.path.exists(p) if t == "rutas" else os.path.isdir(p))
                if not ok:
                    return None, None, f"{et}: no está en la biblioteca: {s}", True
            vx[k] = v
        else:
            vx[k] = [os.path.expanduser(s) if s.startswith("~/") else s for s in v] if isinstance(v, list) else (
                os.path.expanduser(v) if v.startswith("~/") else v)
    if a.get("validar"):
        e = a["validar"](vx)
        if e:
            return None, None, e, e.startswith("falta ")
    return json.dumps(canon, sort_keys=True, ensure_ascii=False), vx, None, False

def comando(a, vx, modo):
    c = a["cmd"]
    argv = [PY, "-u", c[0] if os.path.isabs(c[0]) else os.path.join(HERE, c[0]), *c[1:]] if c[0].endswith(".py") else list(c)
    return argv + a["args"](vx) + (["--execute"] if modo == "ejecutar" else [])

def mostrar(argv):
    """El comando como se escribiría en la terminal, corto: duplicados.py --execute."""
    if argv[:2] == [PY, "-u"]:
        argv = [os.path.basename(argv[2]), *argv[3:]]
    return " ".join(s if re.fullmatch(r"[\w@%+=:,./~-]+", s) else "'" + s.replace("'", "'\\''") + "'"
                    for s in map(_casa, argv))


# ═══════════════════════════════════ trabajos (una acción a la vez) ═══════════════════════════════════
CERROJO = threading.Lock()
TRABAJO = None        # el último (corriendo o terminado)
SIMULADAS = {}        # acción → {"canon", "ok", "fin"}: la última simulación de cada una
ULTIMO = [time.time()]
ENV = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")

class Trabajo:
    def __init__(self, a, modo, canon, vx):
        self.id, self.a, self.modo, self.canon, self.vx = secrets.token_hex(6), a, modo, canon, vx
        self.argv = comando(a, vx, modo)
        self.lineas, self.parcial, self._cr = [], "", False
        self.inicio, self.fin, self.rc, self.estado = time.time(), None, None, "corriendo"
        self.proc, self.detener_pedido, self.cerrojo = None, False, threading.Lock()

    def escribir(self, texto):
        with self.cerrojo:
            for parte in re.split(r"(\r\n|\n|\r)", texto):
                if parte in ("\n", "\r\n"):
                    self.lineas.append(self.parcial[:10000]); self.parcial, self._cr = "", False
                elif parte == "\r":
                    self._cr = True    # barra de progreso: lo que sigue reemplaza la línea
                elif parte:
                    if self._cr:
                        self.parcial, self._cr = "", False
                    self.parcial += parte

    def sistema(self, texto):
        """Una línea del panel (no del script): empieza con ∅."""
        self.escribir(("\n" if self.parcial else "") + "∅ " + texto + "\n")

    def _uno(self, argv):
        self.escribir(("\n" if self.parcial or self.lineas else "") + "$ " + mostrar(argv) + "\n")
        try:
            p = subprocess.Popen(argv, cwd=HERE, env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            self.sistema(f"No se pudo lanzar: {e}")
            return 127
        self.proc = p
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            b = p.stdout.read1(65536)
            if not b:
                break
            self.escribir(dec.decode(b))
        self.escribir(dec.decode(b"", final=True))
        return p.wait()

    def correr(self):
        rc = -1
        try:
            rc = self._uno(self.argv)
            mueve = self.modo == "ejecutar" and self.a.get("navidrome")
            if mueve and PRUEBA:
                self.sistema("(modo prueba: Navidrome no se toca)")
            elif mueve and not self.detener_pedido:
                logs = logs_de_cambios(self.inicio)
                if rc == 0 and logs:
                    self.sistema("NAVIDROME: las escuchas, estrellas y playlists pasan a las rutas nuevas")
                    rc = self._uno([PY, "-u", os.path.join(HERE, "nd_actualizar.py"), *logs])
                elif rc == 0:
                    self.sistema("Nada que pasar a Navidrome: ninguna canción cambió de ruta.")
                elif logs:
                    self.sistema("ATENCIÓN: terminó con error y dejó cambios de ruta SIN pasar a Navidrome. Revisa la "
                                 "salida y usa NAVIDROME AL DÍA con: " + " ".join(_casa(p) for p in logs))
        except Exception as e:   # un error del panel, no del script
            self.sistema(f"ERROR DEL PANEL: {e!r}")
        finally:
            self.rc, self.fin = rc, time.time()
            if self.detener_pedido:
                self.estado = "detenido"
            elif self.modo == "simular":
                self.estado = "ok" if self.simulacion_ok() else "fallo"
            else:
                self.estado = "ok" if rc == 0 else "fallo"
            with CERROJO:
                if self.modo == "simular":
                    SIMULADAS[self.a["id"]] = {"canon": self.canon, "ok": self.estado == "ok", "fin": self.fin}
                elif self.modo == "ejecutar" or self.a["tipo"] == "directo":
                    SIMULADAS.clear()   # la biblioteca cambió: lo simulado antes ya no vale
            try:
                self.guardar()
            except OSError:
                pass
            pedir_pesado()

    def simulacion_ok(self):
        """Muchos scripts terminan la simulación con sys.exit("Simulación: … Usa --execute.") (código 1): eso es una
        simulación normal. Un error de verdad trae un Traceback o no dice «simulación» al final. El procesado es
        estricto, como en la Konsole: cualquier código distinto de 0 pide «ejecutar igual»."""
        if self.rc == 0:
            return True
        if self.rc != 1 or self.a.get("sim_estricta"):
            return False
        todo = "\n".join(self.lineas + [self.parcial]).casefold()
        return "traceback" not in todo and "simulaci" in "\n".join(self.lineas[-8:] + [self.parcial]).casefold()

    def detener(self):
        self.detener_pedido = True
        p = self.proc
        if not p or p.poll() is not None:
            return
        self.sistema("DETENIDO a pedido (Ctrl+C al script; si no responde, se termina).")
        def escalar():
            for sig, espera in ((signal.SIGINT, 0), (signal.SIGTERM, 8), (signal.SIGKILL, 8)):
                time.sleep(espera)
                if p.poll() is not None:
                    return
                try:
                    os.killpg(p.pid, sig)
                except ProcessLookupError:
                    return
        threading.Thread(target=escalar, daemon=True).start()

    def resumen(self, desde=None):
        d = {"id": self.id, "accion": self.a["id"], "nombre": self.a["nombre"], "modo": self.modo,
             "estado": self.estado, "rc": self.rc, "inicio": self.inicio, "fin": self.fin, "canon": self.canon,
             "comando": mostrar(self.argv)}
        if desde is not None:
            with self.cerrojo:
                d.update(lineas=self.lineas[max(desde, 0):], desde=len(self.lineas), parcial=self.parcial)
        return d

    def guardar(self):
        os.makedirs(REGISTRO, exist_ok=True)
        f = lambda t, fmt: time.strftime(fmt, time.localtime(t))
        nombre = f"{f(self.inicio, '%Y%m%d-%H%M%S')}-{self.a['id']}-{self.modo}-{self.estado}.txt"
        cab = [f"# {self.a['nombre']} · {self.modo} · {self.estado} (código {self.rc})",
               f"# {f(self.inicio, '%Y-%m-%d %H:%M:%S')} → {f(self.fin, '%H:%M:%S')}", ""]
        with open(os.path.join(REGISTRO, nombre), "w", encoding="utf-8") as fh:
            fh.write("\n".join(cab + self.lineas + ([self.parcial] if self.parcial else [])) + "\n")

def logs_de_cambios(desde):
    """Los logs de cambios de ruta (old_path → new_path) escritos desde `desde`, del más viejo al más nuevo: lo que
    nd_actualizar.py necesita para pasar las escuchas. Los suyos (nd-*) no: esos ya los escribe él."""
    res = []
    for p in glob.glob(os.path.join(LOGS, "*.json")):
        try:
            if os.path.getmtime(p) < desde - 1 or os.path.basename(p).startswith("nd-"):
                continue
            d = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        c = d.get("cambios") if isinstance(d, dict) else None
        if isinstance(c, list) and any(isinstance(x, dict) and x.get("old_path") and x.get("new_path")
                                       and x["old_path"] != x["new_path"] for x in c):
            res.append(p)
    return sorted(res, key=os.path.getmtime)

def ocupado():
    return TRABAJO is not None and TRABAJO.estado == "corriendo"

def api_comando(d):
    a = POR_ID.get(d.get("accion"))
    if not a:
        return 404, {"error": "acción desconocida"}
    canon, vx, err, falta = preparar(a, d.get("valores"))
    if err:
        return 200, {"error": err, "falta": falta}
    return 200, {"cmd": mostrar(comando(a, vx, "simular" if a["tipo"] == "sim" else "correr")), "canon": canon}

def api_correr(d):
    global TRABAJO
    a = POR_ID.get(d.get("accion"))
    if not a:
        return 404, {"error": "acción desconocida"}
    modo = d.get("modo")
    if modo not in (("simular", "ejecutar") if a["tipo"] == "sim" else ("correr",)):
        return 400, {"error": "modo inválido"}
    canon, vx, err, _ = preparar(a, d.get("valores"))
    if err:
        return 400, {"error": err}
    with CERROJO:
        if ocupado():
            return 409, {"error": f"Ya está corriendo {TRABAJO.a['nombre']}: espera a que termine."}
        if modo == "ejecutar":
            s = SIMULADAS.get(a["id"])
            if not s or s["canon"] != canon or time.time() - s["fin"] > VIGENCIA:
                return 409, {"error": "Primero SIMULAR con estos mismos datos."}
            if not s["ok"] and not d.get("forzar"):
                return 409, {"error": "La simulación terminó con error: léela antes de ejecutar igual."}
        if a["tipo"] == "directo" and not d.get("confirmar"):
            return 409, {"error": "Falta confirmar (segundo clic)."}
        if a.get("antra") and (modo != "simular" or a["antra"] == "siempre") and antra_abierto():
            return 409, {"error": "Antra está abierto: ciérralo primero."}
        TRABAJO = Trabajo(a, modo, canon, vx)
        threading.Thread(target=TRABAJO.correr, daemon=True).start()
        return 200, {"trabajo": TRABAJO.resumen()}

def api_detener(d):
    t = TRABAJO
    if not t or t.id != d.get("id") or t.estado != "corriendo":
        return 409, {"error": "No hay nada corriendo con ese id."}
    t.detener()
    return 200, {"ok": True}

def abrir_externo(ruta):
    """Abre con la aplicación del escritorio, en su propio scope de systemd: si no, se cerraría al apagarse el panel."""
    cmd = ["xdg-open", ruta]
    if shutil.which("systemd-run"):
        cmd = ["systemd-run", "--user", "--scope", "--collect", "--quiet", *cmd]
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)

def api_abrir(d):
    x = ABRIR.get(d.get("cual"))
    if not x:
        return 404, {"error": "no sé abrir eso"}
    if not os.path.exists(x[0]):
        return 404, {"error": f"Todavía no existe: {_casa(x[0])}"}
    abrir_externo(x[0])
    return 200, {"ok": True}

def api_apagar(d):
    if ocupado():
        return 409, {"error": "Hay algo corriendo."}
    threading.Thread(target=SERVIDOR[0].shutdown, daemon=True).start()
    return 200, {"ok": True}


# ═══════════════════════════════════ estado (la telemetría de arriba) ═══════════════════════════════════
PESADO = {}                       # lo que lee toda la biblioteca: se calcula de fondo
_PEDIDO, _CALCULANDO = threading.Event(), threading.Event()
_LIGERO, _MEMO = {"t": 0, "d": {}}, {}

def pedir_pesado():
    _PEDIDO.set()

def _calcular():
    canciones = perdida = prueba = 0
    for d, dirs, fs in os.walk(ROOT):
        rel = os.path.relpath(d, ROOT)
        partes = [] if rel == "." else rel.split(os.sep)
        dirs[:] = [x for x in dirs if not x.startswith(".") and not (not partes and x in SKIP and x != "_Prueba")]
        audios = [f for f in fs if es_audio(f)]
        if partes[:1] == ["_Prueba"]:
            prueba += len(audios)
            continue
        canciones += len(audios)
        perdida += sum(1 for f in audios if len(partes) == 2 and con_perdida(os.path.join(d, f)))
    sp = sin_procesar()
    dud = set()
    if os.path.isfile(DUDOSAS):
        dud = {l.split("\t")[2] for l in open(DUDOSAS, encoding="utf-8") if not l.startswith("#") and l.count("\t") >= 2}
    return {"canciones": canciones, "perdida": perdida, "prueba": prueba,
            "descargas": sorted({p.split(os.sep)[0] for p in sp if p.count(os.sep) == 1}),
            "sueltas": sum(1 for p in sp if p.count(os.sep) != 1), "conseguir": len(a_conseguir()),
            "dudosas": len(rutas_por_sid(dud)), "rebajar": len(esperando_rebajar())}

def _refrescador():
    global PESADO
    while True:
        _PEDIDO.wait(); _PEDIDO.clear()
        _CALCULANDO.set()
        try:
            nuevo = _calcular()
        except Exception as e:
            nuevo = {"error_pesado": repr(e)}
        nuevo["calculado"] = time.time()
        PESADO = nuevo
        _CALCULANDO.clear()

def _memo(clave, archivo, leer):
    """Lee un archivo solo si cambió (por su fecha)."""
    try:
        m = os.path.getmtime(archivo)
    except OSError:
        return None
    if _MEMO.get(clave, (None,))[0] != m:
        try:
            _MEMO[clave] = (m, leer(m))
        except (OSError, ValueError):
            return None
    return _MEMO[clave][1]

def _docker_vivo(nombre):
    try:
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", nombre], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "true"
    except (OSError, subprocess.TimeoutExpired):
        return None

def _nd_canciones():
    try:
        con = sqlite3.connect(f"file:{NAVIDROME_DB}?mode=ro", uri=True, timeout=2)
        n = con.execute("select count(*) from media_file where missing=0 and substr(path, 1, 8) != '_Prueba/'").fetchone()[0]
        con.close()
        return n
    except sqlite3.Error:
        return None

def _salud(m):
    ult = (open(os.path.join(LOGS, "salud.log"), encoding="utf-8").read().strip().splitlines() or [""])[-1]
    x = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d)\s+(.+?)\s+\|", ult)
    return {"fecha": x.group(1), "estado": x.group(2)} if x else None

def _auditoria(m):
    rojo = amarillo = 0; sec = None
    for l in open(DOC_AUDITORIA, encoding="utf-8"):
        if l.startswith("## "):
            sec = "r" if "🔴" in l else ("a" if "🟡" in l else None)
        elif sec and l.startswith("| ["):
            rojo, amarillo = rojo + (sec == "r"), amarillo + (sec == "a")
    return {"fecha": m, "rojo": rojo, "amarillo": amarillo}

def _promovidas(m):
    return sum(1 for e in json.load(open(os.path.join(HERE, "prueba-estado.json"), encoding="utf-8")).values()
               if isinstance(e, dict) and e.get("promovida"))

UNIDADES = [("musica-salud", "timer", "SALUD"), ("musica-prueba-embudo", "timer", "EMBUDO"),
            ("musica-prueba-marcar", "timer", "MARCAR"), ("musica-descubrir", "timer", "DESCUBRIR"),
            ("musica-descarga-lista", "path", "AVISO")]

def _daemons():
    nombres = [f"{u}.{t}" for u, t, _ in UNIDADES] + [f"{u}.service" for u, _, _ in UNIDADES]
    try:
        r = subprocess.run(["systemctl", "--user", "show", "--timestamp=unix", "-p",
                            "Id,LoadState,ActiveState,NextElapseUSecRealtime,LastTriggerUSec,Result", *nombres],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    bloques = {}
    for b in r.stdout.strip().split("\n\n"):
        kv = dict(l.split("=", 1) for l in b.splitlines() if "=" in l)
        bloques[kv.get("Id")] = kv
    unix = lambda s: float(s[1:]) if s and s.startswith("@") else None
    out = []
    for u, t, nombre in UNIDADES:
        x, s = bloques.get(f"{u}.{t}", {}), bloques.get(f"{u}.service", {})
        if x.get("LoadState") != "loaded":
            out.append({"nombre": nombre, "estado": "ausente"})
            continue
        out.append({"nombre": nombre, "tipo": t, "estado": x.get("ActiveState"), "resultado": s.get("Result"),
                    "proximo": unix(x.get("NextElapseUSecRealtime")), "ultimo": unix(x.get("LastTriggerUSec"))})
    return out

def ligero():
    if time.time() - _LIGERO["t"] < 8:
        return _LIGERO["d"]
    try:
        libres = round(shutil.disk_usage(ROOT).free / 1e9)
    except OSError:
        libres = None
    d = {"navidrome": {"vivo": _docker_vivo(ND_CONTENEDOR) if ND_COMPOSE else None, "canciones": _nd_canciones()},
         "octo": {"vivo": _docker_vivo(OCTO_CONTENEDOR)} if OCTO_COMPOSE else None,
         "libres_gb": libres, "salud": _memo("salud", os.path.join(LOGS, "salud.log"), _salud),
         "auditoria": _memo("auditoria", DOC_AUDITORIA, _auditoria),
         "promovidas": _memo("promovidas", os.path.join(HERE, "prueba-estado.json"), _promovidas),
         "daemons": _daemons()}
    _LIGERO.update(t=time.time(), d=d)
    return d

def estado():
    if not PESADO.get("calculado") or time.time() - PESADO["calculado"] > 300:
        pedir_pesado()
    with CERROJO:
        t = TRABAJO.resumen() if TRABAJO else None
        sims = {k: {"canon": v["canon"], "ok": v["ok"]} for k, v in SIMULADAS.items() if time.time() - v["fin"] < VIGENCIA}
    return {**ligero(), **PESADO, "calculando": _CALCULANDO.is_set(), "antra": antra_abierto(), "trabajo": t,
            "simuladas": sims}


# ═══════════════════════════════════ sugerencias de los campos ═══════════════════════════════════
_INDICE = {"t": 0}

def indice():
    """Discos y canciones de la biblioteca (solo nombres: rápido)."""
    if time.time() - _INDICE["t"] > 60:
        carpetas, canciones = [], []
        for d, dirs, fs in os.walk(ROOT):
            rel = os.path.relpath(d, ROOT)
            prof = 0 if rel == "." else rel.count(os.sep) + 1
            dirs[:] = sorted(x for x in dirs if not x.startswith(".") and not (prof == 0 and x in SKIP))
            if prof == 2:
                carpetas.append(rel)
                canciones += [os.path.join(rel, f) for f in sorted(fs) if es_audio(f)]
        _INDICE.update(t=time.time(), carpetas=carpetas, canciones=canciones)
    return _INDICE

def _archivos(c):
    dirs = [os.path.expanduser(x) for k in c.get("donde", ["descargas"]) for x in DONDE.get(k, [])]
    ext, res, vistos = tuple(c.get("ext") or ()), [], set()
    for base in dirs:
        if not os.path.isdir(base):
            continue
        for d, subdirs, fs in os.walk(base):
            prof = d[len(base):].count(os.sep)
            subdirs[:] = [] if prof >= 2 else [s for s in subdirs if not s.startswith(".")]
            for f in (subdirs if c["tipo"] == "directorio" else fs):
                p = os.path.join(d, f)
                if (c["tipo"] == "directorio" or not ext or f.lower().endswith(ext)) and p not in vistos:
                    vistos.add(p); res.append(p)
    return sorted(res, key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)[:600]

def _logs_cambios():
    res = []
    for p in sorted(glob.glob(os.path.join(LOGS, "*.json")), key=os.path.getmtime, reverse=True):
        try:
            cab = open(p, encoding="utf-8").read(8192)
        except OSError:
            continue
        if '"cambios"' in cab and '"old_path"' in cab:
            res.append(p)
        if len(res) >= 80:
            break
    return res

def buscar(accion, campo, q):
    a = POR_ID.get(accion)
    c = next((x for x in a["campos"] if x["clave"] == campo), None) if a else None
    if not c:
        return []
    t, qs = c["tipo"], _plano(q).split()
    if t in ("carpeta", "carpetas"):
        xs = indice()["carpetas"]
    elif t == "cancion":
        xs = indice()["canciones"]
    elif t == "rutas":
        xs = indice()["carpetas"] + indice()["canciones"]
    elif t == "logs":
        xs = [_casa(p) for p in _logs_cambios()]
    elif t in ("archivo", "directorio"):
        xs = [_casa(p) for p in _archivos(c)]
    else:
        return []
    out = []
    for x in xs:
        if all(w in _plano(x) for w in qs):
            out.append(x)
            if len(out) >= 40:
                break
    return out

def registro(nombre=None):
    if nombre:
        if not re.fullmatch(r"[\w.-]+\.txt", nombre) or not os.path.isfile(os.path.join(REGISTRO, nombre)):
            return None
        return open(os.path.join(REGISTRO, nombre), encoding="utf-8", errors="replace").read(3_000_000)
    res = []
    for p in sorted(glob.glob(os.path.join(REGISTRO, "*.txt")), reverse=True)[:80]:
        n = os.path.basename(p)
        x = re.fullmatch(r"(\d{8})-(\d{6})-(\w+)-(simular|ejecutar|correr)-(\w+)\.txt", n)
        if x:
            a = POR_ID.get(x.group(3))
            res.append({"archivo": n, "fecha": f"{x.group(1)}{x.group(2)}", "accion": x.group(3),
                        "nombre": a["nombre"] if a else x.group(3).upper(), "modo": x.group(4), "estado": x.group(5)})
    return res

def contexto():
    usuarios = []
    try:
        con = sqlite3.connect(f"file:{NAVIDROME_DB}?mode=ro", uri=True, timeout=2)
        robot = CONF.get("octo_fiesta", {}).get("usuario_robot")
        usuarios = [r[0] for r in con.execute("select user_name from user order by user_name") if r[0] != robot]
        con.close()
    except sqlite3.Error:
        pass
    pu = os.path.join(HERE, "usuarios")
    personas = sorted(x for x in os.listdir(pu) if os.path.isdir(os.path.join(pu, x))) if os.path.isdir(pu) else []
    return {"usuarios": usuarios, "personas": personas, "navidrome_url": ND_URL, "puerto": PUERTO,
            "prueba": ROOT if PRUEBA else None}

def catalogo():
    cliente = []
    for a in ACCIONES:
        x = {k: a[k] for k in ("id", "grupo", "nombre", "texto", "tipo", "boton", "largo", "antra") if k in a}
        x["campos"] = [{k: v for k, v in c.items() if k != "donde"} for c in a["campos"]]
        x["abrir"] = [[k, ABRIR[k][1]] for k in a.get("abrir", []) if k in ABRIR]
        cliente.append(x)
    grupos = [g for g in GRUPOS if g["id"] == "registro" or any(a["grupo"] == g["id"] for a in ACCIONES)]
    return {"grupos": grupos, "acciones": cliente, "contexto": contexto()}


# ═══════════════════════════════════ servidor ═══════════════════════════════════
TOKEN, NONCE = secrets.token_urlsafe(24), secrets.token_urlsafe(16)
SERVIDOR = [None]

class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "fonoteca"
    sys_version = ""

    def log_message(self, *_):
        pass

    def _enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        datos = cuerpo.encode() if isinstance(cuerpo, str) else json.dumps(cuerpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        for k, v in (("Content-Type", tipo), ("Content-Length", str(len(datos))), ("Cache-Control", "no-store"),
                     ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"), ("Referrer-Policy", "no-referrer"),
                     ("Content-Security-Policy", f"default-src 'none'; script-src 'nonce-{NONCE}'; style-src 'unsafe-inline'; "
                      "img-src data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(datos)

    def _permitido(self, con_token=True):
        if (self.headers.get("Host") or "").lower() not in HOSTS:
            return False
        o = self.headers.get("Origin")
        if o and o.lower() not in ORIGENES:
            return False
        return not con_token or secrets.compare_digest(self.headers.get("X-Fonoteca", ""), TOKEN)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/vivo":
            return self._enviar(200, {"app": "fonoteca", "version": VERSION, "ocupado": ocupado()})
        if not self._permitido(con_token=u.path.startswith("/api/")):
            return self._enviar(403, {"error": "prohibido"})
        ULTIMO[0] = time.time()
        if u.path == "/":
            return self._enviar(200, pagina(), "text/html; charset=utf-8")
        if u.path == "/api/estado":
            return self._enviar(200, estado())
        if u.path == "/api/trabajo":
            t = TRABAJO
            if not t or t.id != q.get("id"):
                return self._enviar(404, {"error": "ese trabajo ya no está"})
            return self._enviar(200, t.resumen(int(q.get("desde") or 0)))
        if u.path == "/api/buscar":
            return self._enviar(200, {"opciones": buscar(q.get("accion", ""), q.get("campo", ""), q.get("q", ""))})
        if u.path == "/api/registro":
            r = registro(q.get("archivo"))
            return self._enviar(200 if r is not None else 404, {"registro": r} if r is not None else {"error": "no existe"})
        return self._enviar(404, {"error": "no existe"})

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        if not self._permitido() or not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._enviar(403, {"error": "prohibido"})
        ULTIMO[0] = time.time()
        n = int(self.headers.get("Content-Length") or 0)
        if n > 200_000:
            return self._enviar(413, {"error": "demasiado grande"})
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._enviar(400, {"error": "JSON inválido"})
        f = {"/api/comando": api_comando, "/api/correr": api_correr, "/api/detener": api_detener,
             "/api/abrir": api_abrir, "/api/apagar": api_apagar}.get(u.path)
        if not f or not isinstance(d, dict):
            return self._enviar(404, {"error": "no existe"})
        self._enviar(*f(d))

def _vigilar(srv):
    while True:
        time.sleep(20)
        if not ocupado() and time.time() - ULTIMO[0] > INACTIVO:
            srv.shutdown()
            return

def servir():
    os.makedirs(REGISTRO, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
    srv.daemon_threads = True
    SERVIDOR[0] = srv
    fd = os.open(TOKEN_ARCHIVO, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # para que el lanzador lo apague
    os.write(fd, TOKEN.encode()); os.close(fd)
    threading.Thread(target=_refrescador, daemon=True).start()
    threading.Thread(target=_vigilar, args=(srv,), daemon=True).start()
    pedir_pesado()
    print(f"fonoteca: panel en http://127.0.0.1:{PUERTO}/", flush=True)
    try:
        srv.serve_forever()
    finally:
        try:
            if open(TOKEN_ARCHIVO).read() == TOKEN:
                os.remove(TOKEN_ARCHIVO)
        except OSError:
            pass


# ═══════════════════════════════════ lanzador y menú ═══════════════════════════════════
def _vivo():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PUERTO}/vivo", timeout=1.5) as r:
            d = json.loads(r.read())
            return d if d.get("app") == "fonoteca" else None
    except (OSError, ValueError):
        return None

def abrir_panel():
    v = _vivo()
    if v and v["version"] != VERSION and not v["ocupado"]:   # panel.py cambió: se reinicia el servidor
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PUERTO}/api/apagar", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "X-Fonoteca": open(TOKEN_ARCHIVO).read().strip()})
            urllib.request.urlopen(req, timeout=3).read()
            for _ in range(50):
                if not _vivo():
                    break
                time.sleep(0.1)
        except OSError:
            pass
        v = _vivo()
    if not v:
        cmd = [PY, YO, "--servir"]
        lanzado = False
        if shutil.which("systemd-run"):   # en su propia unidad: sigue vivo aunque se cierre quien lo abrió
            lanzado = subprocess.run(["systemd-run", "--user", "--collect", "--quiet", f"--unit=fonoteca-panel-{PUERTO}",
                                      *cmd], capture_output=True).returncode == 0
        if not lanzado:
            os.makedirs(REGISTRO, exist_ok=True)
            subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=open(os.path.join(REGISTRO, "servidor.txt"), "a"), stderr=subprocess.STDOUT)
        for _ in range(80):
            if _vivo():
                break
            time.sleep(0.1)
        else:
            sys.exit(f"El panel no arrancó (¿el puerto {PUERTO} está ocupado? Cámbialo en config.toml: [panel] puerto).")
    url = f"http://127.0.0.1:{PUERTO}/"
    for nav in ("brave", "brave-browser", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
                "microsoft-edge"):
        if shutil.which(nav):   # ventana propia, sin pestañas ni barra: como una aplicación
            subprocess.Popen([nav, f"--app={url}"], start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return print(url)
    import webbrowser
    webbrowser.open(url)
    print(url)

def icono(tam=256):
    """El ícono: la matriz de puntos de NULL-00 con su ∅ carmesí."""
    paso, m = 30, 38
    puntos = "".join(f'<circle cx="{m + c * paso}" cy="{m + f * paso}" r="4.4" fill="#e8e3d8" opacity=".55"/>'
                     for f in range(7) for c in range(7) if (f, c) != (5, 5))
    x = y = m + 5 * paso
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{tam}" height="{tam}" viewBox="0 0 256 256">'
            f'<rect width="256" height="256" rx="40" fill="#0d0c0b"/>{puntos}'
            f'<circle cx="{x}" cy="{y}" r="15" fill="none" stroke="#b91c1c" stroke-width="5.5"/>'
            f'<path d="M{x - 20} {y + 20}L{x + 20} {y - 20}" stroke="#b91c1c" stroke-width="5.5"/></svg>')

FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#0d0c0b"/>'
           '<circle cx="16" cy="16" r="8" fill="none" stroke="#b91c1c" stroke-width="3"/>'
           '<path d="M6 26L26 6" stroke="#b91c1c" stroke-width="3"/></svg>')

def instalar():
    apps = os.path.expanduser("~/.local/share/applications")
    iconos = os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps")
    os.makedirs(apps, exist_ok=True); os.makedirs(iconos, exist_ok=True)
    open(os.path.join(iconos, "fonoteca.svg"), "w", encoding="utf-8").write(icono())
    q = lambda s: '"' + re.sub(r'(["`$\\])', r"\\\1", s) + '"' if re.search(r"[\s\"'\\`$]", s) else s
    p = os.path.join(apps, "fonoteca.desktop")
    open(p, "w", encoding="utf-8").write(
        "[Desktop Entry]\nType=Application\nName=Fonoteca\nGenericName=Biblioteca de música\n"
        "Comment=Todas las herramientas de la biblioteca, con botones\n"
        f"Exec={q(PY)} {q(YO)}\nIcon=fonoteca\nTerminal=false\nCategories=AudioVideo;Audio;Utility;\n"
        "Keywords=música;biblioteca;navidrome;antra;fonoteca;\n")
    for cmd in (["update-desktop-database", apps], ["kbuildsycoca6"], ["gtk-update-icon-cache", "-q", "-t",
                os.path.expanduser("~/.local/share/icons/hicolor")]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, capture_output=True)
    print(f"Listo: «Fonoteca» en el menú de aplicaciones ({_casa(p)}).")


# ═══════════════════════════════════ la página ═══════════════════════════════════
def pagina():
    cat = json.dumps(catalogo(), ensure_ascii=False).replace("<", "\\u003c")
    return (PAGINA.replace("__TOKEN__", TOKEN).replace("__NONCE__", NONCE).replace("__PUERTO__", str(PUERTO))
            .replace("__FAVICON__", "data:image/svg+xml," + urllib.parse.quote(FAVICON)).replace("__CATALOGO__", cat))

PAGINA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="fonoteca" content="__TOKEN__">
<title>Fonoteca</title>
<link rel="icon" href="__FAVICON__">
<style>
:root{
  --fondo:#0d0c0b; --hundido:#090807; --sobre:#141210; --linea:#211e1a; --linea2:#36312b;
  --hueso:#e8e3d8; --hueso2:#c3bdb1; --gris:#8b8579; --tenue:#4e4943;
  --carmesi:#b91c1c; --carmesi2:#cf2525; --sangre:#7a1212; --alerta:#e60012;
  --mono:"JetBrainsMono Nerd Font","JetBrainsMono NF","JetBrains Mono","Hack","DejaVu Sans Mono",ui-monospace,monospace;
  color-scheme:dark;
}
*{box-sizing:border-box}
html{background:var(--fondo)}
body{margin:0;background:var(--fondo);color:var(--hueso);font:13px/1.6 var(--mono);-webkit-font-smoothing:antialiased;
  font-variant-numeric:tabular-nums}
::selection{background:var(--carmesi);color:var(--hueso)}
button,input,select,textarea{font:inherit;color:inherit}
a{color:inherit}
.marco{max-width:1640px;margin:0 auto;padding:28px 28px 0}

/* filas de telemetría: CLAVE ............ VALOR */
.fila{display:flex;align-items:baseline;gap:1ch;white-space:nowrap;min-width:0}
.fila>span{flex:none}
.fila>i{flex:1 1 2ch;min-width:2ch;overflow:hidden;color:var(--tenue);font-style:normal;user-select:none}
.fila>i::before{content:"........................................................................................................................................................................................"}
.fila>b{flex:none;font-weight:500;overflow:hidden;text-overflow:ellipsis;max-width:70%}
.ok{color:var(--hueso)} .mal{color:var(--alerta)} .gris{color:var(--gris)} .acento{color:var(--carmesi2)}

/* cabecera */
.cab{display:grid;grid-template-columns:auto minmax(0,560px) 1fr;gap:20px 40px;align-items:center}
.logo{margin:0;font-size:12px;line-height:1.32;color:var(--hueso2);letter-spacing:0;user-select:none}
.logo .nulo{color:var(--carmesi2);font-weight:700}
.corriendo .logo .nulo{animation:parpadeo 1.1s steps(1) infinite}
.ident h1{margin:0 0 10px;font-size:26px;line-height:1;letter-spacing:.38em;font-weight:700}
.ident .fila{color:var(--hueso2)}
.sello{justify-self:end;align-self:start;color:var(--carmesi2);letter-spacing:.12em;white-space:nowrap}
.sello.dormido{color:var(--gris)}
.sello{grid-column:3;grid-row:1}
.donde{grid-column:3;grid-row:1;align-self:end;justify-self:end;color:var(--tenue);font-size:11px;letter-spacing:.16em}

/* telemetría */
.tele{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:0 52px;margin-top:26px;
  padding-top:18px;border-top:1px solid var(--linea)}
.tele h2{margin:0 0 6px;font-size:11px;font-weight:500;letter-spacing:.2em;color:var(--gris)}
.tele .col{min-width:0;padding-bottom:12px}
.tele .fila{padding:1px 0}
.tele .fila[data-ir]{cursor:pointer}
.tele .fila[data-ir]:hover>span{color:var(--carmesi2)}
.tele .fila a{color:var(--gris);text-decoration:none;margin-left:.6ch}
.tele .fila a:hover{color:var(--carmesi2)}
.arranque .tele .fila,.arranque .ident .fila,.arranque .sello{animation:aparece 1ms linear both;animation-delay:calc(var(--i,0) * 38ms)}
@keyframes aparece{from{opacity:0}to{opacity:1}}
@keyframes parpadeo{50%{opacity:0}}

/* advertencias */
.avisos{margin-top:6px}
.avisos div{color:var(--alerta);letter-spacing:.04em;padding:2px 0}

/* cuerpo: módulos | acciones | consola */
.cuerpo{display:grid;grid-template-columns:200px minmax(0,1fr) minmax(0,.92fr);grid-template-areas:"nav acc con";
  margin-top:18px;border-top:1px solid var(--linea)}
.mods{grid-area:nav;padding:14px 0;border-right:1px solid var(--linea);display:flex;flex-direction:column}
.mods button{display:flex;gap:1.2ch;align-items:baseline;width:100%;background:none;border:0;color:var(--gris);
  text-align:left;padding:7px 16px;cursor:pointer;letter-spacing:.1em}
.mods button:hover{color:var(--hueso)}
.mods button .n{color:var(--tenue)}
.mods button[aria-current="true"]{color:var(--hueso);box-shadow:inset 2px 0 var(--carmesi)}
.mods button[aria-current="true"] .n{color:var(--carmesi2)}
.mods .marca{margin-left:auto;color:var(--carmesi2);letter-spacing:0}
.acciones{grid-area:acc;padding:4px 30px 48px;min-width:0}
.gcab{padding:20px 0 14px}
.gcab .gnum{letter-spacing:.2em;font-size:12px;color:var(--gris)}
.gcab .gnum b{color:var(--hueso);font-weight:600}
.gcab p{margin:6px 0 0;color:var(--hueso2);max-width:70ch}
.gextra{margin-top:10px}
.gextra .fila{max-width:560px}

.acc{padding:18px 0 18px;border-top:1px solid var(--linea);position:relative}
.acc.activa::before{content:"";position:absolute;left:-30px;top:-1px;bottom:0;width:2px;background:var(--carmesi)}
.tit{display:flex;flex-wrap:wrap;align-items:center;gap:8px 1ch}
.tit h3{margin:0;font-size:13px;font-weight:600;letter-spacing:.12em}
.tit>i{flex:1 1 30px;min-width:30px;overflow:hidden;color:var(--tenue);font-style:normal;white-space:nowrap;user-select:none}
.tit>i::before{content:"........................................................................................................................................................................................"}
.etq{font-style:normal;font-size:10px;letter-spacing:.16em;color:var(--gris);border:1px solid var(--linea2);padding:0 5px;line-height:16px}
.botones{display:flex;flex-wrap:wrap;gap:8px}
.desc{margin:7px 0 0;color:var(--hueso2);max-width:74ch}
.campos{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,250px),1fr));gap:12px 18px;margin-top:14px}
.campo{min-width:0}
.campo.ancho{grid-column:1/-1}
.campo>label,.campo .rot{display:block;font-size:10.5px;letter-spacing:.18em;color:var(--gris);margin-bottom:5px}
.entrada{position:relative}
.campo input[type=text],.campo input[type=number],.campo select{width:100%;background:var(--hundido);
  border:1px solid var(--linea2);border-radius:0;padding:7px 9px;color:var(--hueso);outline:none}
.campo input::placeholder{color:var(--tenue)}
.campo input:focus,.campo select:focus{border-color:var(--carmesi)}
.campo.casilla{display:flex;align-items:center;gap:1ch;align-self:end;padding-bottom:7px}
.campo.casilla label{color:var(--hueso2)}
input[type=checkbox]{accent-color:var(--carmesi);width:14px;height:14px;margin:0}
.marcas{display:flex;flex-wrap:wrap;gap:6px 16px;padding-top:6px}
.marcas span{display:flex;align-items:center;gap:.8ch;color:var(--hueso2)}
.multi{display:flex;gap:8px}
.multi .entrada{flex:1;min-width:0}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}
.chips:empty{display:none}
.chip{display:inline-flex;align-items:center;gap:.6ch;border:1px solid var(--linea2);padding:1px 4px 1px 8px;
  color:var(--hueso2);max-width:100%;min-width:0}
.chip>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip button{background:none;border:0;color:var(--gris);cursor:pointer;padding:0 4px}
.chip button:hover{color:var(--alerta)}
.chip.pend{cursor:pointer;border-style:dashed}
.chip.pend:hover{border-color:var(--carmesi);color:var(--hueso)}
.sug{position:absolute;left:0;right:0;top:100%;z-index:30;background:var(--sobre);border:1px solid var(--linea2);
  border-top:0;max-height:300px;overflow:auto}
.sug div{padding:5px 9px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--hueso2)}
.sug div[aria-selected="true"],.sug div:hover{background:var(--sangre);color:var(--hueso)}
.cmd{margin-top:12px;color:var(--gris);font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}
.cmd::before{content:"$ ";color:var(--carmesi2)}
.cmd .ex{color:var(--tenue)}
.cmd.falta::before{content:"· ";color:var(--tenue)}
.cmd.falta{color:var(--tenue)}
.cmd.error{color:var(--alerta)}
.cmd.error::before{content:"! ";color:var(--alerta)}
.nota{color:var(--alerta);font-size:12px;margin-top:6px}
.nota:empty{display:none}

/* botones [ ASÍ ] */
.btn{font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;background:transparent;color:var(--hueso);
  border:1px solid var(--linea2);border-radius:0;padding:6px 10px;cursor:pointer;white-space:nowrap;line-height:1.3}
.btn::before{content:"[ ";color:var(--gris)} .btn::after{content:" ]";color:var(--gris)}
.btn:hover:not(:disabled){border-color:var(--hueso)}
.btn:focus-visible{outline:1px solid var(--carmesi2);outline-offset:2px}
.btn:disabled{color:var(--tenue);border-color:var(--linea);cursor:not-allowed}
.btn:disabled::before,.btn:disabled::after{color:var(--tenue)}
.btn.ej{color:var(--carmesi2);border-color:var(--sangre)}
.btn.ej:disabled{color:var(--tenue);border-color:var(--linea)}
.btn.ej.armado:not(:disabled){background:var(--carmesi);border-color:var(--carmesi);color:var(--hueso)}
.btn.ej.armado:not(:disabled)::before,.btn.ej.armado:not(:disabled)::after{color:var(--hueso)}
.btn.ej.armado:not(:disabled):hover{background:var(--carmesi2);border-color:var(--carmesi2)}
.btn.ej.igual:not(:disabled){border-color:var(--alerta);color:var(--alerta)}
.btn.dir{border-color:var(--sangre)}
.btn.sec{color:var(--hueso2)}
.btn.mas{padding:6px 9px}
.btn.confirmar,.btn.confirmar:hover{background:var(--alerta)!important;border-color:var(--alerta)!important;color:var(--fondo)!important}
.btn.confirmar::before,.btn.confirmar::after{color:var(--fondo)!important}

/* consola */
.consola{grid-area:con;border-left:1px solid var(--linea);background:var(--hundido);position:sticky;top:0;
  height:100vh;display:flex;flex-direction:column;min-width:0}
.ccab{padding:14px 18px 12px;border-bottom:1px solid var(--linea)}
.ccab .fila b{max-width:75%}
.c-cmd{color:var(--gris);font-size:12px;margin-top:4px;white-space:pre-wrap;overflow-wrap:anywhere}
.c-cmd:not(:empty)::before{content:"$ ";color:var(--carmesi2)}
.salida{flex:1;min-height:0;margin:0;padding:14px 18px;overflow:auto;white-space:pre-wrap;word-break:break-word;
  font-size:12.5px;line-height:1.55;color:var(--hueso2)}
.salida .err{color:var(--alerta)}
.salida .sim{color:var(--carmesi2)}
.salida .paso{color:var(--hueso);font-weight:600}
.salida .cmdl{color:var(--gris)}
.salida .bien{color:var(--hueso)}
.salida .sis{color:var(--carmesi2);font-weight:600}
.salida .guia{color:var(--gris)}
.salida .guia b{color:var(--hueso);font-weight:500}
.cursor{color:var(--hueso);animation:parpadeo 1s steps(1) infinite}
.cpie{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.cpie:empty{display:none}

/* registro */
.reg{display:flex;flex-direction:column}
.reg button{background:none;border:0;border-top:1px solid var(--linea);padding:9px 0;text-align:left;cursor:pointer;color:var(--hueso2)}
.reg button:hover{color:var(--hueso)}
.reg button .fila b{max-width:none}
.vacio{color:var(--gris);padding:14px 0}


@media (max-width:1240px){
  .cuerpo{grid-template-columns:minmax(0,1fr) minmax(0,1fr);grid-template-areas:"nav nav" "acc con"}
  .mods{flex-direction:row;flex-wrap:wrap;border-right:0;border-bottom:1px solid var(--linea);padding:6px 0}
  .mods button{width:auto;padding:8px 12px}
  .mods button[aria-current="true"]{box-shadow:inset 0 -2px var(--carmesi)}
  .acc.activa::before{left:-30px}
}
@media (max-width:900px){
  .marco{padding:20px 16px 32px}
  .cab{grid-template-columns:minmax(0,1fr)}
  .logo{display:none}
  .sello,.donde{grid-column:1;grid-row:auto;justify-self:start}
  .cuerpo{grid-template-columns:minmax(0,1fr);grid-template-areas:"nav" "acc" "con"}
  .acciones{padding:4px 0 32px}
  .acc.activa::before{left:-12px}
  .consola{position:static;height:72vh;border-left:0;border-top:1px solid var(--linea)}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
</style>
</head>
<body class="arranque">
<div class="marco">
  <header class="cab">
    <pre class="logo" id="logo" aria-hidden="true"></pre>
    <div class="ident">
      <h1>FONOTECA</h1>
      <div class="fila" style="--i:1"><span>DESIGNACION DE SISTEMA</span><i></i><b>NULL-00</b></div>
      <div class="fila" style="--i:2"><span>CLASIFICACION</span><i></i><b>BIBLIOTECA / FIELD UNIT</b></div>
      <div class="fila" style="--i:3"><span>CORE_LINK</span><i></i><b id="link" class="gris">ESTABLISHING</b></div>
    </div>
    <div class="sello" id="sello" style="--i:22">[ NULL-00 -- ACTIVE ]</div>
    <div class="donde">PANEL LOCAL · 127.0.0.1:__PUERTO__</div>
  </header>
  <section class="tele" id="tele" aria-label="Estado"></section>
  <div class="avisos" id="avisos" role="status"></div>
  <main class="cuerpo">
    <nav class="mods" id="mods" aria-label="Módulos"></nav>
    <section class="acciones" id="acciones"></section>
    <aside class="consola" id="consola" aria-label="Consola">
      <div class="ccab">
        <div class="fila"><span id="c-tit">PROC/--</span><i></i><b id="c-est" class="gris">IDLE</b></div>
        <div class="c-cmd" id="c-cmd"></div>
        <div class="cpie" id="cpie"></div>
      </div>
      <pre class="salida" id="salida" tabindex="0"></pre>
    </aside>
  </main>
</div>
<script type="application/json" id="catalogo">__CATALOGO__</script>
<script nonce="__NONCE__">
'use strict';
const TOKEN = document.querySelector('meta[name="fonoteca"]').content;
const CAT = JSON.parse(document.getElementById('catalogo').textContent);
const ACC = Object.fromEntries(CAT.acciones.map(a => [a.id, a]));
const MULTI = new Set(['lista', 'carpetas', 'rutas', 'logs']);
const BUSCA = new Set(['carpeta', 'carpetas', 'cancion', 'rutas', 'archivo', 'directorio', 'logs']);
const ANCHO = new Set(['lista', 'carpetas', 'rutas', 'logs', 'archivo', 'directorio', 'cancion', 'carpeta', 'descarga']);
const $ = (s, r = document) => r.querySelector(s);

function h(tag, at, ...hijos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(at || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of hijos.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
const leer = (k, d) => { try { const x = localStorage.getItem('fonoteca:' + k); return x == null ? d : JSON.parse(x); } catch (_) { return d; } };
const guardar = (k, v) => { try { localStorage.setItem('fonoteca:' + k, JSON.stringify(v)); } catch (_) {} };
const plano = s => String(s).normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase();
const num = n => n == null ? '···' : String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
const DIAS = ['DOM', 'LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB'];
const MESES = ['ENE', 'FEB', 'MAR', 'ABR', 'MAY', 'JUN', 'JUL', 'AGO', 'SEP', 'OCT', 'NOV', 'DIC'];
const dos = n => String(n).padStart(2, '0');
function cuando(ts) {
  if (!ts) return '--';
  const d = new Date(ts * 1000), hoy = new Date(), hm = `${dos(d.getHours())}:${dos(d.getMinutes())}`;
  const dia = x => Math.floor((new Date(x.getFullYear(), x.getMonth(), x.getDate())) / 864e5);
  const dd = dia(d) - dia(hoy);
  if (dd === 0) return 'HOY ' + hm;
  if (dd === 1) return 'MAÑANA ' + hm;
  if (dd === -1) return 'AYER ' + hm;
  return `${DIAS[d.getDay()]} ${dos(d.getDate())} ${MESES[d.getMonth()]} ${hm}`;
}
const dur = s => { s = Math.max(0, Math.round(s)); return `${dos(Math.floor(s / 60))}:${dos(s % 60)}`; };

class ErrorApi extends Error { constructor(m, codigo) { super(m); this.codigo = codigo; } }
async function api(ruta, datos) {
  const op = {headers: {'X-Fonoteca': TOKEN}, cache: 'no-store'};
  if (datos !== undefined) { op.method = 'POST'; op.headers['Content-Type'] = 'application/json'; op.body = JSON.stringify(datos); }
  let r;
  try { r = await fetch(ruta, op); } catch (_) { throw new ErrorApi('sin conexión con el panel', 0); }
  if (r.status === 403) {   // el servidor se reinició: otra sesión, otro token
    const ult = Number(sessionStorage.getItem('fonoteca:recarga') || 0);
    if (Date.now() - ult > 30000) { sessionStorage.setItem('fonoteca:recarga', Date.now()); location.reload(); }
    throw new ErrorApi('sesión vencida', 403);
  }
  let j = {};
  try { j = await r.json(); } catch (_) {}
  if (!r.ok) throw new ErrorApi(j.error || ('error ' + r.status), r.status);
  return j;
}

/* ─── estado global ─── */
let E = null, conectado = null, tCiclo = null;
let grupo = leer('grupo', CAT.grupos[0].id);
if (!CAT.grupos.some(g => g.id === grupo)) grupo = CAT.grupos[0].id;
const V = {}, PREV = {}, TPREV = {};
let T = {id: null, desde: 0, info: null, pegado: true, solo: false};

/* ─── logo, telemetría, módulos ─── */
function pintarLogo() {
  const pre = $('#logo');
  for (let f = 0; f < 9; f++) {
    for (let c = 0; c < 14; c++) {
      if (c) pre.append(' ');
      pre.append(f === 7 && c === 10 ? h('span', {class: 'nulo'}, '∅') : '·');
    }
    if (f < 8) pre.append('\n');
  }
}
const TELE = [
  ['SISTEMA', [['biblioteca', 'BIBLIOTECA'], ['disco', 'DISCO'], ['navidrome', 'NAVIDROME'], ['octo', 'OCTO-FIESTA'], ['antra', 'ANTRA']]],
  ['COLAS', [['sinproc', 'SIN PROCESAR', 'descargas'], ['conseguir', 'A CONSEGUIR', 'descargas'], ['perdida', 'CON PÉRDIDA', 'revision'],
             ['dudosas', 'DUDOSAS', 'revision'], ['rebajar', 'ESPERAN RE-DESCARGA', 'revision'], ['prueba', 'PRUEBA', 'embudo']]],
  ['INTEGRIDAD', [['salud', 'SALUD', 'revision'], ['auditoria', 'AUDITORÍA', 'revision']]],
];
function pintarTele() {
  const t = $('#tele'); let i = 4;
  for (const [tit, filas] of TELE) {
    const col = h('div', {class: 'col', id: 'col-' + tit}, h('h2', {text: tit}));
    for (const [k, et, ir] of filas) {
      const span = h('span', {text: et});
      if (k === 'navidrome' && CAT.contexto.navidrome_url) span.append(h('a', {href: CAT.contexto.navidrome_url, target: '_blank', rel: 'noopener', title: 'abrir Navidrome', onclick: e => e.stopPropagation()}, '↗'));
      col.append(h('div', {class: 'fila', id: 'r-' + k, style: `--i:${i++}`, 'data-ir': ir, onclick: ir ? () => irA(ir) : null}, span, h('i'), h('b', {id: 't-' + k, class: 'gris', text: '···'})));
    }
    t.append(col);
  }
}
function valor(k, texto, cls) { const b = $('#t-' + k); if (b) { b.textContent = texto; b.className = cls || ''; } }
function pintarNav() {
  const nav = $('#mods'); nav.replaceChildren();
  CAT.grupos.forEach((g, i) => nav.append(h('button', {type: 'button', 'aria-current': String(g.id === grupo), onclick: () => irA(g.id)},
    h('span', {class: 'n', text: dos(i + 1)}), h('span', {text: g.nombre}), h('span', {class: 'marca', id: 'm-' + g.id}))));
}
function irA(g) {
  if (g !== grupo) { grupo = g; guardar('grupo', g); pintarNav(); pintarGrupo(); marcas(); }
  const acc = $('#acciones');
  if (acc.getBoundingClientRect().top < 0) acc.scrollIntoView({block: 'start', behavior: 'smooth'});
}

/* ─── el módulo elegido: sus acciones ─── */
function pintarGrupo() {
  const g = CAT.grupos.find(x => x.id === grupo) || CAT.grupos[0], i = CAT.grupos.indexOf(g);
  const cont = $('#acciones'); cont.replaceChildren();
  cont.append(h('header', {class: 'gcab'}, h('div', {class: 'gnum'}, dos(i + 1) + ' / ', h('b', {text: g.nombre})),
    h('p', {text: g.texto}), h('div', {class: 'gextra', id: 'gextra'})));
  if (g.id === 'registro') return pintarRegistro(cont);
  const acciones = CAT.acciones.filter(a => a.grupo === g.id);
  for (const a of acciones) cont.append(filaAccion(a));
  for (const a of acciones) previsualizar(a, 0);
  extraGrupo();
  if (T.info) $('#acc-' + T.info.accion)?.classList.add('activa');
}
function inicial(a) {
  const v = {};
  for (const c of a.campos) v[c.clave] = c.defecto != null ? c.defecto : (c.tipo === 'casilla' ? false : (MULTI.has(c.tipo) || c.tipo === 'marcas' ? [] : ''));
  const g = leer('v:' + a.id, {});
  for (const c of a.campos) if (c.clave in g) v[c.clave] = g[c.clave];
  return v;
}
function filaAccion(a) {
  V[a.id] = inicial(a);
  const bot = h('div', {class: 'botones'});
  if (a.tipo === 'sim') bot.append(
    h('button', {type: 'button', class: 'btn', 'data-b': 'simular', onclick: () => lanzar(a, 'simular')}, 'SIMULAR'),
    h('button', {type: 'button', class: 'btn ej', 'data-b': 'ejecutar', onclick: e => clicEjecutar(a, e.currentTarget)}, 'EJECUTAR'));
  else bot.append(h('button', {type: 'button', class: 'btn' + (a.tipo === 'directo' ? ' dir' : ''), 'data-b': 'correr',
    onclick: e => a.tipo === 'directo' ? dosClics(e.currentTarget, () => lanzar(a, 'correr', {confirmar: true})) : lanzar(a, 'correr')}, a.boton || 'CORRER'));
  for (const [k, et] of a.abrir || []) bot.append(h('button', {type: 'button', class: 'btn sec', onclick: () => abrir(k, a)}, et));
  const art = h('article', {class: 'acc', id: 'acc-' + a.id},
    h('div', {class: 'tit'}, h('h3', {text: a.nombre}), a.largo ? h('em', {class: 'etq', text: 'TARDA'}) : null, h('i'), bot),
    h('p', {class: 'desc', text: a.texto}));
  if (a.campos.length) art.append(h('div', {class: 'campos'}, a.campos.map(c => campo(a, c))));
  art.append(h('div', {class: 'cmd', id: 'cmd-' + a.id}), h('div', {class: 'nota', id: 'nota-' + a.id}));
  return art;
}
function cambiar(a, k, x) { V[a.id][k] = x; guardar('v:' + a.id, V[a.id]); $('#nota-' + a.id).textContent = ''; previsualizar(a); }
function fuente(a, c) {
  if (c.tipo === 'persona') return async q => filtrar(CAT.contexto.personas, q);
  if (c.tipo === 'usuario') return async q => filtrar(CAT.contexto.usuarios, q);
  if (c.tipo === 'descarga') return async q => filtrar((E && E.descargas) || [], q);
  if (BUSCA.has(c.tipo)) return async q => (await api(`/api/buscar?accion=${encodeURIComponent(a.id)}&campo=${encodeURIComponent(c.clave)}&q=${encodeURIComponent(q)}`)).opciones;
  return null;
}
const filtrar = (xs, q) => { const w = plano(q).split(/\s+/).filter(Boolean); return xs.filter(x => w.every(p => plano(x).includes(p))); };
function campo(a, c) {
  const id = `f-${a.id}-${c.clave}`, v = V[a.id][c.clave];
  if (c.tipo === 'casilla')
    return h('div', {class: 'campo casilla'}, h('input', {type: 'checkbox', id, checked: !!v, onchange: e => cambiar(a, c.clave, e.target.checked)}), h('label', {for: id, text: c.etiqueta}));
  const cont = h('div', {class: 'campo' + (ANCHO.has(c.tipo) ? ' ancho' : '')});
  if (c.tipo === 'marcas') {
    const caja = h('div', {class: 'marcas', role: 'group', 'aria-label': c.etiqueta});
    const leerMarcas = () => c.opciones.map(o => o[0]).filter(x => document.getElementById(id + '-' + x).checked);
    for (const [val, t] of c.opciones) caja.append(h('span', {}, h('input', {type: 'checkbox', id: id + '-' + val, checked: (v || []).includes(val), onchange: () => cambiar(a, c.clave, leerMarcas())}), h('label', {for: id + '-' + val, text: t})));
    cont.append(h('div', {class: 'rot', text: c.etiqueta}), caja);
    return cont;
  }
  cont.append(h('label', {for: id, text: c.etiqueta}));
  if (c.tipo === 'opcion') {
    if (!c.opciones.some(o => o[0] === v)) V[a.id][c.clave] = c.opciones[0][0];
    cont.append(h('select', {id, onchange: e => cambiar(a, c.clave, e.target.value)}, c.opciones.map(([val, t]) => h('option', {value: val, selected: val === v}, t))));
    return cont;
  }
  const inp = h('input', {id, type: c.tipo === 'numero' ? 'number' : 'text', placeholder: c.ayuda || '', autocomplete: 'off', spellcheck: 'false', min: c.min, max: c.max});
  const ent = h('div', {class: 'entrada'}, inp);
  const f = fuente(a, c);
  if (MULTI.has(c.tipo)) {
    const chips = h('div', {class: 'chips'});
    const pintarChips = () => chips.replaceChildren(...(V[a.id][c.clave] || []).map((x, i) => h('span', {class: 'chip'}, h('span', {text: x, title: x}),
      h('button', {type: 'button', title: 'quitar', 'aria-label': 'quitar ' + x, onclick: () => { const l = [...V[a.id][c.clave]]; l.splice(i, 1); cambiar(a, c.clave, l); pintarChips(); }}, '×'))));
    const agregar = x => { x = (x ?? inp.value).trim(); if (!x) return; cambiar(a, c.clave, [...(V[a.id][c.clave] || []), x]); inp.value = ''; pintarChips(); };
    if (f) autocompletar(inp, f, x => agregar(x));
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); agregar(); } });
    cont.append(h('div', {class: 'multi'}, ent, h('button', {type: 'button', class: 'btn mas', title: 'agregar', onclick: () => agregar()}, '+')), chips);
    pintarChips();
    return cont;
  }
  inp.value = v ?? '';
  inp.addEventListener('input', () => cambiar(a, c.clave, inp.value));
  if (f) autocompletar(inp, f, x => { inp.value = x; cambiar(a, c.clave, x); });
  cont.append(ent);
  if (c.tipo === 'descarga') cont.append(h('div', {class: 'chips', 'data-pend': id}));
  return cont;
}
function autocompletar(inp, fuente, elegir) {
  const caja = h('div', {class: 'sug', role: 'listbox', hidden: true});
  inp.after(caja);
  inp.setAttribute('role', 'combobox'); inp.setAttribute('aria-autocomplete', 'list');
  let items = [], sel = -1, t = null, n = 0;
  const cerrar = () => { caja.hidden = true; sel = -1; };
  const pintar = () => {
    caja.replaceChildren(...items.map((x, i) => h('div', {role: 'option', 'aria-selected': String(i === sel), title: x,
      onmousedown: e => { e.preventDefault(); elegir(x); cerrar(); }}, x)));
    caja.hidden = !items.length;
    if (sel >= 0) caja.children[sel]?.scrollIntoView({block: 'nearest'});
  };
  const pedir = () => {
    clearTimeout(t);
    t = setTimeout(async () => {
      const yo = ++n; let xs = [];
      try { xs = await fuente(inp.value); } catch (_) {}
      if (yo !== n || document.activeElement !== inp) return;
      items = (xs || []).slice(0, 40); sel = -1; pintar();
    }, 140);
  };
  inp.addEventListener('input', pedir);
  inp.addEventListener('focus', pedir);
  inp.addEventListener('blur', () => setTimeout(cerrar, 120));
  inp.addEventListener('keydown', e => {
    if (caja.hidden) return;
    if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, items.length - 1); pintar(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); pintar(); e.preventDefault(); }
    else if (e.key === 'Enter' && sel >= 0) { e.preventDefault(); e.stopImmediatePropagation(); elegir(items[sel]); cerrar(); }
    else if (e.key === 'Escape') cerrar();
  });
}
function previsualizar(a, espera = 220) {
  clearTimeout(TPREV[a.id]);
  PREV[a.id] = Object.assign({}, PREV[a.id], {pend: true});
  botones(a);
  TPREV[a.id] = setTimeout(async () => {
    try { PREV[a.id] = await api('/api/comando', {accion: a.id, valores: V[a.id]}); }
    catch (e) { PREV[a.id] = {error: e.message}; }
    pintarCmd(a); botones(a);
  }, espera);
}
function pintarCmd(a) {
  const el = $('#cmd-' + a.id); if (!el) return;
  const p = PREV[a.id] || {};
  el.className = 'cmd' + (p.error ? (p.falta ? ' falta' : ' error') : '');
  el.textContent = p.error || p.cmd || '';
  if (!p.error && a.tipo === 'sim') el.append(h('span', {class: 'ex', text: '   [--execute al ejecutar]'}));
}
const corriendo = () => !!(E && E.trabajo && E.trabajo.estado === 'corriendo') || !!(T.info && T.info.estado === 'corriendo');
function botones(a) {
  const art = $('#acc-' + a.id); if (!art) return;
  const p = PREV[a.id] || {}, oc = corriendo(), invalido = !!p.error || !!p.pend;
  const antra = !!(E && E.antra && a.antra), s = E && E.simuladas && E.simuladas[a.id];
  const listo = !!(s && p.canon && s.canon === p.canon);
  for (const b of art.querySelectorAll('button[data-b]')) {
    if (b.dataset.armado) continue;
    const k = b.dataset.b;
    if (k === 'ejecutar') {
      b.disabled = oc || invalido || !listo || antra;
      b.classList.toggle('armado', listo && s.ok);
      b.classList.toggle('igual', listo && !s.ok);
      b.textContent = listo && !s.ok ? 'EJECUTAR IGUAL' : 'EJECUTAR';
      b.title = !listo ? 'Primero SIMULAR con estos datos' : (s.ok ? 'Hacer de verdad lo que mostró la simulación' : 'La simulación terminó con error: léela antes');
    } else b.disabled = oc || invalido || (antra && (a.antra === 'siempre' || k === 'correr'));
  }
  const nota = $('#nota-' + a.id);
  if (nota && antra && !nota.dataset.error) nota.textContent = a.antra === 'siempre' ? 'ANTRA ACTIVE: ciérralo para usar esto.' : 'ANTRA ACTIVE: ciérralo para ejecutar.';
  else if (nota && !antra && !nota.dataset.error) nota.textContent = '';
}
const todosLosBotones = () => CAT.acciones.forEach(botones);
function dosClics(b, accion, texto = '¿SEGURO? OTRA VEZ') {
  if (b.dataset.armado) { delete b.dataset.armado; b.classList.remove('confirmar'); b.textContent = b.dataset.orig; accion(); return; }
  b.dataset.orig = b.textContent; b.dataset.armado = '1'; b.classList.add('confirmar'); b.textContent = texto;
  setTimeout(() => { if (b.dataset.armado) { delete b.dataset.armado; b.classList.remove('confirmar'); b.textContent = b.dataset.orig; todosLosBotones(); pintarPie(); } }, 4000);
}
function clicEjecutar(a, b) {
  const s = E && E.simuladas && E.simuladas[a.id];
  if (s && !s.ok) return dosClics(b, () => lanzar(a, 'ejecutar', {forzar: true}));
  lanzar(a, 'ejecutar');
}
async function lanzar(a, modo, extra = {}, valores) {
  const nota = $('#nota-' + a.id);
  try {
    const r = await api('/api/correr', {accion: a.id, modo, valores: valores || V[a.id], ...extra});
    if (nota) { nota.textContent = ''; delete nota.dataset.error; }
    if (E) E.trabajo = r.trabajo;
    adjuntar(r.trabajo);
  } catch (e) {
    if (nota) { nota.textContent = e.message; nota.dataset.error = '1'; setTimeout(() => { delete nota.dataset.error; }, 8000); }
  }
}
async function abrir(k, a) {
  try { await api('/api/abrir', {cual: k}); }
  catch (e) { const n = $('#nota-' + a.id); if (n) { n.textContent = e.message; n.dataset.error = '1'; setTimeout(() => { delete n.dataset.error; botones(a); }, 6000); } }
}

/* ─── consola ─── */
const salida = $('#salida');
let parcialEl = null, cursorEl = null, tReloj = null;
salida.addEventListener('scroll', () => { T.pegado = salida.scrollTop + salida.clientHeight >= salida.scrollHeight - 30; });
function clase(l) {
  if (l.startsWith('∅ ')) return 'sis';
  if (l.startsWith('$ ')) return 'cmdl';
  if (/^={3,}/.test(l)) return 'paso';
  if (/Traceback|^\s+File "|\bError\b|❌|⛔|^Falló|FALLÓ|^ERROR/.test(l)) return 'err';
  if (/SIMULACI[ÓO]N|\bSimulaci[óo]n\b|\(simulaci[óo]n\)/.test(l)) return 'sim';
  if (/^(HECHO|LISTO|ESCRITO|ESCRITAS|RESULTADO: ✅)|^✅/.test(l)) return 'bien';
  return '';
}
function guia() {
  T = {id: null, desde: 0, info: null, pegado: true, solo: false};
  $('#c-tit').textContent = 'PROC/--'; const b = $('#c-est'); b.textContent = 'IDLE'; b.className = 'gris';
  $('#c-cmd').textContent = ''; $('#cpie').replaceChildren();
  salida.replaceChildren(h('span', {class: 'guia'},
    h('b', {text: 'SIMULAR'}), ' muestra lo que haría, sin tocar nada.\n',
    h('b', {text: 'EJECUTAR'}), ' se enciende después, solo para esa misma simulación.\n',
    'Lo que no tiene simulación pide un segundo clic.\n',
    'Una acción a la vez; la salida queda en REGISTRO.\n\n',
    'Lo que mueve canciones pasa sus escuchas a Navidrome al terminar.'));
}
function adjuntar(t, solo) {
  T = {id: t.id, desde: 0, info: t, pegado: true, solo: !!solo};
  salida.replaceChildren(); parcialEl = cursorEl = null;
  document.querySelectorAll('.acc.activa').forEach(x => x.classList.remove('activa'));
  $('#acc-' + t.accion)?.classList.add('activa');
  cabecera(); todosLosBotones();
  if (matchMedia('(max-width:900px)').matches) $('#consola').scrollIntoView({behavior: 'smooth'});
  clearInterval(tReloj); tReloj = setInterval(cabecera, 1000);
  seguir();
}
function agregar(lineas, parcial, vivo) {
  const frag = document.createDocumentFragment();
  for (const l of lineas) frag.append(h('span', {class: clase(l)}, l + '\n'));
  parcialEl?.remove(); cursorEl?.remove();
  salida.append(frag);
  parcialEl = h('span', {class: clase(parcial || '')}, parcial || '');
  salida.append(parcialEl);
  cursorEl = vivo ? h('span', {class: 'cursor', text: '█'}) : null;
  if (cursorEl) salida.append(cursorEl);
  if (T.pegado) salida.scrollTop = salida.scrollHeight;
}
async function seguir() {
  const id = T.id; if (!id) return;
  let r;
  try { r = await api(`/api/trabajo?id=${id}&desde=${T.desde}`); }
  catch (e) {
    if (T.id !== id) return;
    if (e.codigo === 404) { T.id = null; clearInterval(tReloj); cursorEl?.remove(); }   // ya empezó otro
    else setTimeout(seguir, 2000);
    return;
  }
  if (T.id !== id) return;
  T.desde = r.desde; T.info = r;
  agregar(r.lineas, r.parcial, r.estado === 'corriendo');
  cabecera();
  if (r.estado === 'corriendo') setTimeout(seguir, 450);
  else { clearInterval(tReloj); if (r.estado !== 'ok') glitch($('#c-est')); ahora(); }
}
function cabecera() {
  const t = T.info; if (!t) return;
  $('#c-tit').textContent = 'PROC/' + t.accion.toUpperCase();
  const modo = {simular: 'SIMULACIÓN', ejecutar: 'EJECUCIÓN'}[t.modo];
  const est = {corriendo: 'RUNNING', ok: 'PASS', fallo: 'FAIL', detenido: 'HALTED'}[t.estado] || t.estado;
  const b = $('#c-est');
  if (!b.dataset.glitch) b.textContent = [modo, `${est} ${dur((t.fin || Date.now() / 1000) - t.inicio)}`].filter(Boolean).join(' · ');
  b.className = {corriendo: 'acento', ok: 'ok', fallo: 'mal', detenido: 'mal'}[t.estado] || '';
  $('#c-cmd').textContent = t.comando;
  document.body.classList.toggle('corriendo', t.estado === 'corriendo');
  pintarPie();
}
let clavePie = '';
function pintarPie() {
  const pie = $('#cpie'), t = T.info;
  if ([...pie.querySelectorAll('button')].some(b => b.dataset.armado)) return;
  const a = t && ACC[t.accion], s = a && E && E.simuladas && E.simuladas[a.id];
  const clave = t ? [t.id, t.estado, T.solo, s && s.canon === t.canon, s && s.ok, corriendo(), E && E.antra].join('|') : '';
  if (clave === clavePie) return;
  clavePie = clave;
  pie.replaceChildren();
  if (!t) return;
  if (t.estado === 'corriendo' && !T.solo) pie.append(h('button', {type: 'button', class: 'btn dir', onclick: e => dosClics(e.currentTarget, detener, '¿DETENER? OTRA VEZ')}, 'DETENER'));
  if (t.estado !== 'corriendo' && t.modo === 'simular' && a && !T.solo) {
    if (s && s.canon === t.canon) {
      const vals = JSON.parse(t.canon);
      const b = h('button', {type: 'button', class: 'btn ej ' + (s.ok ? 'armado' : 'igual'),
        onclick: e => s.ok ? lanzar(a, 'ejecutar', {}, vals) : dosClics(e.currentTarget, () => lanzar(a, 'ejecutar', {forzar: true}, vals))},
        s.ok ? 'EJECUTAR DE VERDAD' : 'EJECUTAR IGUAL');
      b.disabled = corriendo() || !!(E.antra && a.antra);
      pie.append(b);
    }
  }
  pie.append(h('button', {type: 'button', class: 'btn sec', onclick: copiar}, 'COPIAR SALIDA'));
}
async function detener() { try { await api('/api/detener', {id: T.id}); } catch (_) {} }
function copiar(e) {
  const b = e.currentTarget, txt = salida.innerText;
  const listo = () => { const o = b.textContent; b.textContent = 'COPIADO'; setTimeout(() => { b.textContent = o; }, 1400); };
  navigator.clipboard.writeText(txt).then(listo).catch(() => { const r = document.createRange(); r.selectNodeContents(salida); const s = getSelection(); s.removeAllRanges(); s.addRange(r); });
}
const LEET = {A: '4', E: '3', I: '1', O: '0', S: '5', T: '7'};
function glitch(el) {
  if (!el || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const orig = el.textContent, alt = orig.replace(/[AEIOST]/g, c => LEET[c]);
  let n = 0; el.dataset.glitch = '1';
  const paso = () => { el.textContent = n % 2 ? orig : alt; if (++n < 7) setTimeout(paso, 60 + Math.random() * 110); else { el.textContent = orig; delete el.dataset.glitch; } };
  paso();
}

/* ─── registro ─── */
async function pintarRegistro(cont) {
  const lista = h('div', {class: 'reg'}); cont.append(lista);
  let r;
  try { r = (await api('/api/registro')).registro; } catch (e) { lista.append(h('div', {class: 'vacio', text: e.message})); return; }
  if (!r.length) { lista.append(h('div', {class: 'vacio', text: 'Todavía no se corrió nada desde el panel.'})); return; }
  for (const x of r) {
    const f = x.fecha, fecha = `${f.slice(6, 8)} ${MESES[Number(f.slice(4, 6)) - 1]} ${f.slice(8, 10)}:${f.slice(10, 12)}`;
    const est = {ok: 'PASS', fallo: 'FAIL', detenido: 'HALTED'}[x.estado] || x.estado.toUpperCase();
    const modo = {simular: 'SIMULACIÓN', ejecutar: 'EJECUCIÓN', correr: ''}[x.modo];
    lista.append(h('button', {type: 'button', onclick: () => verRegistro(x)},
      h('span', {class: 'fila'}, h('span', {text: `${fecha}  ${x.nombre}`}), h('i'), h('b', {class: x.estado === 'ok' ? 'ok' : 'mal', text: [modo, est].filter(Boolean).join(' · ')}))));
  }
}
async function verRegistro(x) {
  let r; try { r = (await api('/api/registro?archivo=' + encodeURIComponent(x.archivo))).registro; } catch (e) { return; }
  clearInterval(tReloj);
  T = {id: null, desde: 0, info: null, pegado: false, solo: true};
  $('#c-tit').textContent = 'REGISTRO/' + x.accion.toUpperCase();
  const f = x.fecha, b = $('#c-est');
  b.textContent = `${f.slice(6, 8)} ${MESES[Number(f.slice(4, 6)) - 1]} ${f.slice(8, 10)}:${f.slice(10, 12)}`; b.className = 'gris';
  $('#c-cmd').textContent = ''; $('#cpie').replaceChildren(h('button', {type: 'button', class: 'btn sec', onclick: copiar}, 'COPIAR SALIDA'));
  salida.replaceChildren(); parcialEl = cursorEl = null;
  agregar(r.replace(/\n$/, '').split('\n'), '', false); salida.scrollTop = 0;
}

/* ─── estado: telemetría, avisos, marcas ─── */
let primera = true;
function pintarEstado() {
  const e = E, c = !!e.calculado && !e.error_pesado;
  $('#r-octo').hidden = !e.octo;
  valor('biblioteca', c ? `${num(e.canciones)} CANCIONES` : '···', c ? 'ok' : 'gris');
  valor('disco', e.libres_gb == null ? '--' : `${num(e.libres_gb)} GB LIBRES`, e.libres_gb != null && e.libres_gb < 100 ? 'mal' : 'ok');
  const nd = e.navidrome || {};
  valor('navidrome', nd.vivo === false ? 'OFFLINE' : nd.vivo ? `ONLINE · ${num(nd.canciones)}` : (nd.canciones != null ? num(nd.canciones) : '--'), nd.vivo === false ? 'mal' : 'ok');
  if (e.octo) valor('octo', e.octo.vivo === false ? 'OFFLINE' : e.octo.vivo ? 'ONLINE' : '--', e.octo.vivo === false ? 'mal' : 'ok');
  valor('antra', e.antra ? 'ACTIVE · DESCARGANDO' : 'DORMANT', e.antra ? 'acento' : 'gris');
  if (c) {
    const sp = e.descargas.length + e.sueltas;
    valor('sinproc', sp ? `${e.descargas.length ? e.descargas.length + ' DESCARGA' + (e.descargas.length > 1 ? 'S' : '') : ''}${e.descargas.length && e.sueltas ? ' · ' : ''}${e.sueltas ? e.sueltas + ' SUELTAS' : ''}` : '0 · NOMINAL', sp ? 'acento' : 'ok');
    valor('conseguir', e.conseguir ? `${num(e.conseguir)} CANCIONES` : '0 · NOMINAL', e.conseguir ? 'acento' : 'ok');
    valor('perdida', e.perdida ? `${num(e.perdida)} CANCIONES` : '0', 'ok');
    valor('dudosas', e.dudosas ? `${num(e.dudosas)} A ESCUCHAR` : '0', 'ok');
    valor('rebajar', num(e.rebajar), 'ok');
    valor('prueba', `${num(e.prueba)} MP3` + (e.promovidas ? ` · ${e.promovidas} GANARON FLAC` : ''), 'ok');
  }
  const s = e.salud;
  valor('salud', s ? `${s.estado === 'OK' ? 'PASS' : s.estado} · ${cuando(Date.parse(s.fecha.replace(' ', 'T')) / 1000)}` : '--', s && s.estado !== 'OK' ? 'mal' : 'ok');
  const au = e.auditoria;
  valor('auditoria', au ? `${au.rojo} ARREGLAR · ${au.amarillo} DECIDIR · ${cuando(au.fecha)}` : 'SIN CORRER', au && au.rojo ? 'mal' : 'ok');
  daemons(e.daemons || []);
  avisos();
  marcas();
  pendientes();
  extraGrupo();
  todosLosBotones();
  if (T.info && !T.solo) {
    if (e.trabajo && e.trabajo.id === T.info.id) { T.info = Object.assign({}, T.info, {estado: e.trabajo.estado, fin: e.trabajo.fin}); }
    pintarPie();
  }
  // al abrir: la última acción (corriendo o terminada); después, solo una que empezó en otra ventana
  if (e.trabajo && !T.solo && (primera ? !T.info : (e.trabajo.estado === 'corriendo' && (!T.info || T.info.id !== e.trabajo.id)))) adjuntar(e.trabajo);
  primera = false;
}
function daemons(ds) {
  const col = $('#col-INTEGRIDAD');
  col.querySelectorAll('.fila.dm').forEach(x => x.remove());
  for (const d of ds) {
    let v, cls = 'ok';
    if (d.estado === 'ausente') { v = 'NO INSTALADO'; cls = 'gris'; }
    else if (d.estado !== 'active') { v = 'INACTIVE'; cls = 'mal'; }
    else if (d.tipo === 'path') v = 'WATCHING';
    else v = d.proximo ? '→ ' + cuando(d.proximo) : (d.ultimo ? 'ACTIVE · ÚLTIMO ' + cuando(d.ultimo).replace('HOY ', '') : 'ACTIVE');
    if (d.resultado && d.resultado !== 'success' && d.estado !== 'ausente') { v = 'FAIL · ' + v; cls = 'mal'; }
    col.append(h('div', {class: 'fila dm'}, h('span', {text: 'DAEMON/' + d.nombre}), h('i'), h('b', {class: cls, text: v})));
  }
}
function avisos() {
  const e = E, l = [];
  if (CAT.contexto.prueba) l.push('ADVERTENCIA: MODO PRUEBA -- biblioteca de mentira en ' + CAT.contexto.prueba);
  if (conectado === false) l.push('ADVERTENCIA: CORE_LINK -- SEVERED · el panel se apagó: ábrelo otra vez desde el menú');
  else if (e) {
    if (e.antra) l.push('ADVERTENCIA: ANTRA ACTIVE -- lo que toca la biblioteca espera a que lo cierres');
    if (e.navidrome && e.navidrome.vivo === false) l.push('ADVERTENCIA: NAVIDROME OFFLINE -- SISTEMA › ARRANCAR');
    if (e.salud && e.salud.estado !== 'OK') l.push(`ADVERTENCIA: SALUD -- ${e.salud.estado} (detalle en logs/salud-ultimo.txt)`);
    if (e.error_pesado) l.push('ADVERTENCIA: no pude leer la biblioteca -- ' + e.error_pesado);
  }
  const cont = $('#avisos'), antes = cont.textContent;
  cont.replaceChildren(...l.map(x => h('div', {text: x})));
  if (cont.textContent !== antes) cont.querySelectorAll('div').forEach(glitch);
}
function marcas() {
  const e = E; if (!e) return;
  const m = (g, t) => { const x = $('#m-' + g); if (x) x.textContent = t || ''; };
  const n = e.calculado && !e.error_pesado ? e.descargas.length + e.sueltas + e.conseguir : 0;
  m('descargas', n ? '·' + n : '');
  m('revision', (e.salud && e.salud.estado !== 'OK') || (e.auditoria && e.auditoria.rojo) ? '!' : '');
  m('embudo', e.promovidas ? '·' + e.promovidas : '');
}
function pendientes() {
  for (const caja of document.querySelectorAll('[data-pend]')) {
    const inp = document.getElementById(caja.dataset.pend), [, accion, clave] = caja.dataset.pend.split('-');
    const a = ACC[accion], k = ((E && E.descargas) || []).join('|');
    if (caja.dataset.k === k) continue;
    caja.dataset.k = k;
    caja.replaceChildren(...((E && E.descargas) || []).map(d => h('span', {class: 'chip pend', title: 'usar esta carpeta', onclick: () => { inp.value = d; cambiar(a, clave, d); }}, h('span', {text: '▸ ' + d}))));
  }
}
function extraGrupo() {
  const x = $('#gextra'); if (!x || !E) return;
  x.replaceChildren();
  if (grupo === 'descargas' && E.calculado && !E.error_pesado) {
    const d = E.descargas, f = (k, v, cls) => h('div', {class: 'fila'}, h('span', {text: k}), h('i'), h('b', {class: cls, text: v}));
    x.append(f('DESCARGAS SIN PROCESAR', d.length ? d.join(' · ') : 'NINGUNA', d.length ? 'acento' : 'gris'));
    if (E.sueltas) x.append(f('CANCIONES SUELTAS', `${E.sueltas} → JUNTAR`, 'acento'));
    if (E.antra) x.append(f('ANTRA', 'ACTIVE · ESPERAR', 'acento'));
  }
}

/* ─── ciclo ─── */
async function ciclo() {
  clearTimeout(tCiclo);
  try {
    E = await api('/api/estado');
    if (conectado !== true) { conectado = true; const l = $('#link'); l.textContent = 'SYNCHRONIZED'; l.className = 'ok'; const s = $('#sello'); s.textContent = '[ NULL-00 -- ACTIVE ]'; s.classList.remove('dormido'); }
    pintarEstado();
  } catch (e) {
    if (e.codigo !== 403 && conectado !== false) {
      conectado = false; const l = $('#link'); l.textContent = 'SEVERED'; l.className = 'mal'; glitch(l);
      const s = $('#sello'); s.textContent = '[ NULL-00 -- DORMANT ]'; s.classList.add('dormido');
      document.body.classList.remove('corriendo'); avisos();
      CAT.acciones.forEach(a => { const art = $('#acc-' + a.id); art?.querySelectorAll('button[data-b]').forEach(b => { b.disabled = true; }); });
    }
  }
  tCiclo = setTimeout(ciclo, conectado === false ? 5000 : (document.hidden ? 300000 : (E && E.calculando ? 1500 : 4000)));
}
function ahora() { clearTimeout(tCiclo); ciclo(); }
document.addEventListener('visibilitychange', () => { if (!document.hidden) ahora(); });

pintarLogo(); pintarTele(); pintarNav(); pintarGrupo(); guia(); ciclo();
setTimeout(() => document.body.classList.remove('arranque'), 1600);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--servir"]:
        servir()
    elif a[:1] == ["--instalar"]:
        instalar()
    elif not a:
        abrir_panel()
    else:
        sys.exit(__doc__)
