# fonoteca

Herramientas para armar y cuidar tu propia biblioteca de música sin pérdida, a partir de lo que de verdad escuchas,
y servirla a toda la familia con [Navidrome](https://www.navidrome.org/).

> 🇬🇧 [Read in English](README.md)

fonoteca no baja música por sí misma. Trabaja alrededor de [Antra](https://github.com/anandprtp/Antra), que baja los
archivos sin pérdida, y de [Navidrome](https://www.navidrome.org/), que los sirve. Lo que aporta es la **curación**:
cada descarga se revisa, se etiqueta y se guarda con las mismas reglas, y nada de lo que ya escuchaste (escuchas,
estrellas, playlists) se pierde cuando un archivo se arregla, se renombra o se reemplaza.

## Qué hace

**1. Elegir qué bajar.** Con tu *historial extendido* de Spotify, `seleccion_usuario.py` elige las canciones que de
verdad escuchas (en días distintos, elegidas a propósito, escuchadas hasta el final) y, si quieres, los discos que
escuchas como disco. El resultado es una lista de enlaces para pegar en Antra.

**2. Procesar cada descarga, solo.** Cuando Antra termina, un aviso ofrece *simular* el procesado: miras qué cambiaría
y confirmas. Los pasos (`procesar_descarga.py`):

| Paso | Qué hace |
|---|---|
| Integridad | `flac -t` (o decodificar entero con ffmpeg en MP3/AAC/Opus). Las corruptas se borran y quedan para re-bajar. |
| ¿Es la canción? | La duración se compara con la del ISRC. Las sospechosas pasan por AcoustID y se comparan con la canción **exacta** de Spotify: su duración y su vista previa de 30 s, por huella de audio. Si no es ese audio, se borra y queda para re-bajar. |
| Etiquetas | Género, IDs de MusicBrainz de grabación y de disco (solo si son de ESTA grabación), artista del disco, año. |
| Orden | `Artista/Año - Álbum/NN - Título.ext`, cada formato tal cual. |
| Duplicados | Una sola copia por grabación. Sin pérdida antes que con pérdida; si no, la del disco con más canciones, o la más escuchada. |
| Géneros | Una lista corta de 20, en inglés, hasta 2 por artista. |
| Números | Con **una** edición de Deezer que tenga todas las canciones del disco, así una 2ª corrida no cambia nada. |
| Carátulas, letras, volumen | Carátulas (Deezer o iTunes), letras sincronizadas (LRCLIB), ReplayGain 2.0. |
| Navidrome | Escaneo. Escuchas, estrellas, historial y playlists pasan a la ruta nueva. |
| Informe | Documento de pendientes, chequeo semanal y kit de recuperación (enlaces y todas las etiquetas). |

**3. Mantenerla sana.**
- `auditoria.py` revisa toda la biblioteca: corruptas, audio equivocado, IDs de MusicBrainz ajenos, carátulas
  mezcladas, discos partidos… Cada hallazgo va como 🔴 *arreglar*, 🟡 *decidir* o ⚪ *info*.
- Un timer semanal comprueba que Navidrome tenga lo mismo que el disco.
- Un banco de pruebas (`banco_pruebas.py`) corre todo el procesado sobre una biblioteca de mentira.

**4. Descubrir música nueva sin llenar la biblioteca de basura** (opcional, con
[Octo-Fiesta](https://github.com/V1ck3s/octo-fiesta) y [ListenBrainz](https://listenbrainz.org/)).
- Lo que buscas o te recomiendan llega en MP3 de prueba, en una carpeta aparte.
- Con 3 o más escuchas en 4 semanas «gana» su FLAC.
- Lo que nadie escucha se borra a las 6 semanas, avisando antes.
- Cada semana se arma una playlist «Descubrir» con recomendaciones de ListenBrainz que nunca escuchaste.

**5. Herramientas para lo que se hace a mano.** Lo que antes era un script de una sola vez ahora es una herramienta general:

| Herramienta | Para qué |
|---|---|
| `quitar_copia.py` | Quitar una copia; todo lo suyo pasa a la que queda. |
| `unir_discos.py` | Unir ediciones del mismo disco, o devolver un sencillo a su disco. |
| `numeros_pista.py --a-mano` | Numerar un disco a mano con un disco de Deezer. |
| `ost.py` | Bandas sonoras por obra («Soundtrack Hades»), mínimo 3 canciones. |
| `buscar_fuentes.py` | Buscar las que faltan en Deezer, Tidal, Apple Music y Qobuz (Antra acepta sus enlaces). |
| `importar_manual.py` | Meter canciones bajadas a mano, en cualquier formato. |
| `caratulas.py` | Carátulas: faltantes, mezcladas, chicas y agrandadas con IA (Real-ESRGAN), elegidas a ojo. |

## Principios

- **Primero la simulación.** Toda herramienta solo muestra lo que haría. `--execute` escribe, después de un respaldo.
- **Nada se pierde.** Todo movimiento pasa por una sola función (`comun.cambiar_rutas`), que actualiza el state de
  Antra, las playlists `.m3u`, las listas de decisiones y el registro que lleva las escuchas de Navidrome a la ruta nueva.
- **Una regla por pregunta.** «¿Es la misma canción?» (`comun.clave_titulo`), «¿este ID de MusicBrainz es de su
  grabación?» (`comun.grabacion_corresponde`) y «¿este archivo tiene el audio de esa canción de Spotify?»
  (`comun.parecido_spotify`) tienen una sola implementación cada una, la misma en todos lados.
- **Sin la API de Spotify.** La Web API ahora exige que el dueño de la app pague Premium. fonoteca lee las páginas
  públicas de Spotify (canción, disco, playlist), despacio y con caché. Deezer, MusicBrainz, LRCLIB, AcoustID e iTunes se
  usan por sus APIs gratuitas (`red.py` respeta el ritmo de cada servicio y nunca guarda una falla de red como «no existe»).
- **Tus decisiones van en archivos, no en el código.** `decisiones/` guarda lo que decidiste para tu biblioteca:
  canciones que son la misma con otro nombre, géneros fijos por artista, franquicias de bandas sonoras, carátulas que no
  hay que tocar…

## Requisitos

- Linux, Python 3.11+ y `pip install -r requirements.txt` (mutagen, Pillow, numpy).
- `flac`, `ffmpeg`, `fpcalc` (Chromaprint) y `curl`.
- [Navidrome](https://www.navidrome.org/) (ejemplo con Docker en `docker/`) y [Antra](https://github.com/anandprtp/Antra).
- Opcional:
  - una clave de [AcoustID](https://acoustid.org/) en `fonoteca/.acoustid_key`;
  - cuenta de ListenBrainz, y Octo-Fiesta para el embudo de prueba;
  - [Upscayl](https://upscayl.org/) para las carátulas con IA;
  - un token de sesión de Qobuz para `buscar_fuentes.py`.
- Los avisos usan `notify-send`, y el procesado abre una Konsole (KDE). En otro escritorio, los comandos se corren en una terminal.

## Para empezar

```bash
git clone https://github.com/<tu-usuario>/fonoteca ~/fonoteca && cd ~/fonoteca
pip install -r requirements.txt
cp config.example.toml fonoteca/config.toml          # tus rutas, tu contacto para MusicBrainz, tus usuarios
cp -r ejemplos/decisiones fonoteca/decisiones        # opcional: ejemplos de los archivos de decisiones
cd fonoteca
python3 auditoria.py                                 # revisión de tu biblioteca (solo lee)
python3 procesar_descarga.py "<carpeta que creó Antra>"            # simulación
python3 procesar_descarga.py "<carpeta que creó Antra>" --execute  # de verdad
```

Timers y avisos: copiar `systemd/*` a `~/.config/systemd/user/` y correr `systemctl --user daemon-reload` y
`systemctl --user enable --now musica-salud.timer musica-descarga-lista.path`. Las unidades `musica-prueba-*` y
`musica-descubrir` solo hacen falta si usas Octo-Fiesta. Las unidades suponen que el repositorio está en `~/fonoteca`.

### El panel

Cada herramienta tiene también su botón. `python3 fonoteca/panel.py --instalar` agrega **Fonoteca** al menú de
aplicaciones. Al abrirlo arranca un pequeño servidor local y el panel aparece en su propia ventana del navegador: arriba el
estado de la biblioteca, las herramientas agrupadas por módulo y una consola con la salida en vivo.

- Las mismas reglas que en la terminal. **EJECUTAR** se enciende solo después de **SIMULAR** esa misma acción con los
  mismos datos, y el servidor también lo exige. Lo que no tiene simulación pide un segundo clic.
- Lo que mueve o renombra canciones pasa al terminar sus escuchas, estrellas y playlists a Navidrome, como hace el
  procesado.
- Escucha solo en `127.0.0.1`, cada pedido lleva un token de la sesión y se apaga solo tras 20 minutos sin uso. No
  necesita nada más que la biblioteca estándar. Cada corrida queda guardada en `logs/panel/`.

Más: [docs/como-funciona.md](docs/como-funciona.md) explica todo el flujo, las reglas de curación y las lecciones
aprendidas.

## Estado

Es un proyecto personal, hecho para la biblioteca de una casa (unas 6.000 canciones, cuatro personas). Se comparte tal
cual, por si las reglas y las verificaciones le sirven a alguien más. Úsalo con música que tengas derecho a guardar, y
respeta los términos de los servicios que usa y la ley de tu país. fonoteca no tiene relación con Spotify, Deezer,
Navidrome, Antra ni ningún otro servicio.

## Licencia

[MIT](LICENSE)
