# Cómo funciona fonoteca

Esta guía explica el flujo completo, las reglas con las que se cura la biblioteca y las lecciones que dejaron los
errores. Las herramientas están en `fonoteca/` y cada una explica su uso con `-h` (o sin argumentos).

**La meta:** tener «tu propio Spotify». Toda la música que se escucha en casa, completa y bien etiquetada, sin archivos
malos ni duplicados, para varias personas, y que se mantenga casi sola.

---

## 1. El recorrido de una canción

```
historial de Spotify ──► seleccion_usuario.py ──► lista de enlaces ──► Antra (baja sin pérdida)
                                                                          │
                       aviso «Antra terminó» ◄────────────────────────────┘
                                │
                                ▼
                 procesar_descarga.py (simular → ejecutar)
   integridad → ¿es la canción? → etiquetas → orden → duplicados → géneros → números → carátulas,
   letras, ReplayGain → Navidrome (las escuchas pasan a la ruta nueva) → pendientes, salud y kit
                                │
                                ▼
                 Navidrome ──► las apps de cada persona (Subsonic)
```

### 1.1 Elegir qué bajar (`seleccion_usuario.py`)
Con el *historial extendido* de Spotify de una persona (lo pide cada uno en su cuenta: «Datos de la cuenta» →
«Historial de reproducción ampliado»). Una canción entra si cumple cualquiera de estas condiciones:
- se escuchó en días distintos;
- se eligió a propósito (no por aleatorio ni por autoplay);
- se escuchó muchas veces hasta el final.

Escucha = 30 segundos o más. También entran las playlists propias que se le pasen y, con `--albumes`, los discos que
escucha «como disco» (70 % del disco, en 3 días o más), completados con la página pública del disco en Spotify. La
salida es una lista de enlaces: se pega en una playlist nueva de Spotify (cliente de escritorio) y Antra la baja.

### 1.2 Bajar (Antra)
Siempre con *strict matching* activado. Antra deja la playlist en una carpeta de la biblioteca y anota la descarga en su
`history.json`. La unidad `musica-descarga-lista.path` vigila ese archivo y muestra un aviso con un botón: **Simular
procesado**. Abre una Konsole que espera a que cierres Antra, simula y pregunta antes de ejecutar.

Las canciones bajadas desde su enlace (no desde una playlist) Antra las deja sueltas
(`<artistas>/<año> - <disco>/<artistas> - <título>`). `juntar_descarga.py` las reúne en una carpeta antes de procesar.

### 1.3 Procesar (`procesar_descarga.py "<carpeta>" [--execute]`)
Es el único comando después de cada descarga. Sin `--execute` simula hasta el reparto y muestra qué haría.

| Paso | Qué hace | Herramienta |
|---|---|---|
| 1 | Integridad: `flac -t` en FLAC; en los demás formatos se decodifica entero y se compara la duración con la de la cabecera (un MP3 cortado «decodifica bien» hasta donde llega). Corruptas → se borran, se anotan para re-bajar y el comando para. | `borrar_canciones.py` |
| 1b | Las que Antra no bajó: se anotan, salvo que ya estén con otro ID (mismo artista y título). | `comun.spotify_cancion` |
| 2 | Respaldo de las etiquetas de toda la biblioteca. | `tags_backup.py` |
| 3 | Duración contra el ISRC en Deezer (más de 3 s de diferencia = sospechosa), género de Deezer, ID de grabación de MusicBrainz por ISRC (solo si es ESA grabación), año. | `enriquecer.py` |
| 3b | Sospechosas → AcoustID. Si no la confirma, contra la canción EXACTA de Spotify: duración y vista previa de 30 s. No es ese audio (parecido < 0,75) → se borra y se anota para re-bajar; lo es y dura igual → bien; lo demás → dudosa (a escuchar). | `acoustid_check.py`, `comun.parecido_spotify` |
| 3c | ID de disco de MusicBrainz (un lanzamiento con el MISMO nombre del disco). | `mb_disco.py` |
| 4 | Un solo artista del disco por disco (las bandas sonoras y recopilatorios no se parten). | `artista_album.py` |
| 5 | Repartir en `Artista/Año - Álbum/NN - Título.ext`. | `repartir.py` |
| 5c | Duplicados: una sola copia por grabación. | `duplicados.py` |
| 6 | Una fecha por disco; géneros (lista de 20, hasta 2 por artista). | `fechas.py`, `generos.py` |
| 7 | Números de pista, carátulas faltantes, letras, ReplayGain; las que se borraron y volvieron, a sus playlists. | `numeros_pista.py`, `caratulas.py`, `letras.py`, `replaygain.py`, `devolver_playlists.py` |
| 8 | Navidrome: escaneo; escuchas, estrellas, historial y playlists a la ruta nueva. | `nd_actualizar.py` |
| 9 | Documento de pendientes y «conseguir en FLAC», chequeo de salud, kit de recuperación. | `revisar.py`, `musica-salud.py`, `kit_recuperacion.py` |

### 1.4 Mantener
- **Cada semana** (`musica-salud.timer`): Navidrome arriba y con las mismas canciones que el disco; ninguna descarga sin
  procesar; playlists sin rutas rotas; espacio libre. Si todo está bien no avisa.
- **Cuando quieras:** `revisar.py` (pendientes) y `auditoria.py` (revisión completa, solo lee: 🔴 arreglar, 🟡 decidir,
  ⚪ info).
- **Kit de recuperación** (`kit_recuperacion.py`, lo regenera el procesado): enlaces de todas las canciones, todas sus
  etiquetas, playlists, escuchas y la configuración, sin claves. Si el disco muere, se re-baja todo con Antra y
  `tags_backup.py desde-kit` devuelve cada etiqueta exacta.

### 1.5 Descubrir (opcional: Octo-Fiesta + ListenBrainz)
- **Dos puertas:** Navidrome en `:4533` para el día a día (biblioteca limpia) y Octo-Fiesta en `:5274` para buscar algo
  nuevo: lo que se toca se baja en MP3 de prueba a `<biblioteca>/_Prueba/`.
- `prueba.py marcar` (cada 5 min): les pone sus géneros reales más «Prueba». Así se ven aparte, y el Instant Mix de
  Navidrome, que rellena con canciones al azar del mismo género, no queda solo con canciones de prueba.
- `prueba.py revisar --execute` (cada día):
  - 3 o más escuchas en 4 semanas → el enlace va a `PARA-FLAC.txt` para Antra;
  - si su FLAC llega (o la canción ya estaba), el MP3 se cambia por la copia de la biblioteca, con sus escuchas;
  - si a los 14 días no llegó, entra a la biblioteca en MP3 y queda en «conseguir en FLAC»;
  - 6 semanas sin escucharse → se borra, avisando una semana antes; con estrella, nunca.
- `descubrir.py --execute` (cada lunes): recomendaciones de ListenBrainz que nunca escuchaste ni tienes → Octo-Fiesta
  las baja → playlist «Descubrir» de cada persona.

---

## 2. Reglas de curación

- **Un archivo malo se borra y se re-baja**; nunca se «arregla» un audio equivocado.
- **«La misma canción»** (`comun.clave_titulo`): se ignoran remaster, radio edit, single version, «From X» y feat.;
  remix, en vivo, acústica, regrabación, instrumental o sped up son **otra** canción.
- **¿El audio es esa canción?** La prueba fuerte es la canción EXACTA de Spotify: su duración (±max(3 s, 1 %)) y su vista
  previa de 30 s comparada por huella (correctas 0,89-0,99; otro audio 0,50-0,75). Un remix que comparte partes con el
  original llega a ~0,93: por eso se miran las dos cosas.
- **Duplicados:** una sola copia por grabación. Primero la sin pérdida; si no, la del disco con más canciones; si empatan,
  la más escuchada. Un archivo pertenece a un solo disco (el disco está escrito dentro del archivo).
- **IDs de MusicBrainz:** una canción lleva el ID de SU grabación o ninguno (mejor sin ID que con uno ajeno). Se decide
  por título + duración o ISRC + duración (`comun.grabacion_corresponde`), NUNCA por número de pista.
- **Números de pista:** UNA edición de Deezer con el mismo nombre que tenga TODAS las canciones del disco; si no hay, una
  de MusicBrainz; si ninguna, el disco no se toca. Nunca se elige por el nombre de los archivos: así la segunda corrida
  no cambia nada.
- **Géneros:** una lista corta de 20, en inglés (la app navega por género), hasta 2 por artista: el 2º solo si tiene al
  menos el 20 % y 3 de sus canciones. Various Artists, por disco. Nunca «/» en un nombre de género (Navidrome lo parte
  en dos). Las bandas sonoras llevan los géneros de su artista más «Soundtrack».
- **Bandas sonoras** (`ost.py`): un disco «Soundtrack <Obra>» por franquicia, con artista del disco «Soundtracks», solo
  con 3 canciones o más; cada canción conserva su artista y su fecha original.
- **Formatos:** una descarga con pérdida entra en su formato; convertirla a FLAC no le da calidad.
- **Lo que se hace pocas veces no va al procesado automático:** el procesado más largo tiene más formas de fallar.
- **Simulación primero, respaldo siempre:** sin `--execute` nada se escribe; con `--execute`, antes se respalda.

---

## 3. Lecciones (errores que ya pasaron)

- **Toda lista que guarda rutas** (el state de Antra, las playlists, las equivalencias, los IDs aceptados) tiene que
  seguir a la canción cuando se mueve. Cuando cada script tenía su copia de ese código, a varias les faltaba una lista.
  Hoy todo el que mueve o quita canciones usa `comun.cambiar_rutas`.
- **Una falla de red no es un «no existe».** Si se guarda en la caché como «no encontrado», la canción queda sin letra o
  sin ID para siempre. Todo lo que se pide a internet pasa por `red.py`.
- **AcoustID «no la conoce» no significa que esté bien**, y AcoustID está contaminado: una huella puede estar ligada
  también a grabaciones equivocadas (otros usuarios con el mismo error). Nunca aceptar un ID solo porque AcoustID lo
  lista: tiene que coincidir el título o el ISRC.
- **El mismo ISRC no siempre es la misma canción** (un disco puede traer el audio de otra pista con su ISRC), y algunos
  ISRC están equivocados: emparejar por ISRC exige además una duración parecida.
- **Picard emparejó por posición.** Cuando los números de pista eran el orden de descarga, cientos de canciones quedaron
  con el ID de otra. La auditoría por choques veía un tercio del problema; hubo que revisar cada ID contra su grabación.
- **Navidrome:** los registros de cambios se aplican EN ORDEN (A→B y luego B→C = A→C) o se pierden escuchas, y una
  canción borrada que espera re-descarga no se borra de su base (guarda escuchas y estrellas).
- **Navidrome rellena el Instant Mix con canciones al azar del mismo género** cuando los servicios externos no dan
  parecidas. Un género artificial para todo un grupo de canciones las encierra en su propio mix.
- **Antra deja sin fecha** algunas canciones bajadas sueltas, y Navidrome parte un disco sin YEAR o con distinto artista
  del disco entre sus canciones.
- **El orden de una playlist de Spotify no siempre es el de la lista de enlaces:** las no bajadas se buscan por ID,
  artista + título o ISRC, nunca por posición.
- **Datos de otra tienda:** los ISRC leídos crudos de un M4A pueden quedar escritos como texto de bytes (`B'…'`), y
  Spotify a veces guarda entidades HTML en los títulos (`&apos;`). La auditoría revisa los dos.
- **Una clave repetida en un diccionario de Python gana la última en silencio.** Un analizador (`ruff`) lo detecta.

---

## 4. Herramientas para lo que se hace a mano

Todas simulan sin `--execute` y usan `comun.cambiar_rutas`: nada se pierde.

| Caso | Herramienta |
|---|---|
| El mismo audio en dos archivos (otro título o ISRC) | `quitar_copia.py <sobra> <queda>` |
| Una canción que no se quiere (no es mala: no se re-baja) | `quitar_copia.py --sin-reemplazo <archivo>` |
| Dos ediciones del mismo disco, o un sencillo que es de un disco que tenemos | `unir_discos.py <destino> <otra> --seguir` |
| Un disco que `numeros_pista.py` no puede numerar solo | `numeros_pista.py --a-mano <carpeta> --deezer <id> ["Título=N"]` |
| Bandas sonoras por obra | `ost.py --seguir` (mapa en `decisiones/ost-franquicias.json`) |
| Canciones que Antra no consiguió | `buscar_fuentes.py` → pegar `FUENTES-<n>.txt` en Antra → `buscar_fuentes.py --poner-spotify-id "<carpeta>"` |
| Canciones bajadas a mano | `importar_manual.py "<carpeta>"` → `procesar_descarga.py "manual-<fecha>"` |
| Carátulas | `caratulas.py faltantes \| mezcladas \| mejorar \| ia preparar \| ia aplicar NN=2` |
| IDs de MusicBrainz ajenos | `ids_mb.py [<carpetas>]` |
| Un archivo malo | `borrar_canciones.py <lista> --motivo corrupta\|equivocada` |
| Escuchar dudosas al lado de su vista previa | `escuchar.py <tema> <lista.txt>` |
| Escuchas y playlists de Spotify de una persona → Navidrome | `nd_escuchas_spotify.py`, `playlists_cuenta.py`, `playlist_historial.py` |

**El panel** (`panel.py`, con `--instalar` queda en el menú como «Fonoteca»): todo lo de esta tabla, el procesado y la
revisión, con botones. Arma el mismo comando que se escribiría a mano (se ve debajo de cada botón), exige la simulación
antes de ejecutar igual que la terminal, corre una acción a la vez con la salida en vivo y la guarda en `logs/panel/`.
Al ejecutar algo que mueve canciones, corre `nd_actualizar.py` con el log que dejó; si terminó con error, avisa y no lo
pasa. Solo escucha en `127.0.0.1`, con un token por sesión.

---

## 5. Configuración y decisiones

- `fonoteca/config.toml` (copia de `config.example.toml`): rutas, contacto para MusicBrainz, usuarios de «Descubrir».
  Es privado.
- `fonoteca/decisiones/`: lo que decidiste para TU biblioteca (ejemplos en `ejemplos/decisiones/`):

| Archivo | Qué guarda |
|---|---|
| `equivalencias.tsv` | Canciones de Spotify que están con otro título o artista. |
| `ids-mb-aceptados.json` | IDs de MusicBrainz que el audio confirma aunque el título no cuadre. |
| `generos-fijos.tsv` | El género de un artista que Deezer clasifica mal. |
| `discos-distintos.tsv` | Pares de carpetas que parecen el mismo disco y no lo son. |
| `artistas-distintos.json` | Artistas con nombre casi igual que son distintos. |
| `artistas-nombres.tsv` | Cómo se escribe en la biblioteca un artista que MusicBrainz escribe distinto. |
| `caratulas-elegidas.tsv` | Carátulas elegidas a ojo. |
| `caratulas-no-tocar.txt` | Carátulas que no hay que cambiar. |
| `duplicados-verificados.txt` | ISRC de duplicados revisados a mano. |
| `ost-franquicias.json` | Qué discos son de qué obra. |

- Claves, cada una en su archivo junto a los scripts (nunca en el código): `.acoustid_key` y `.qobuz_token`.

---

## 6. Probar cambios

- `banco_pruebas.py`: corre el procesado completo sobre una biblioteca de mentira (copias de canciones reales de tu
  biblioteca: la lista está al principio del archivo y hay que adaptarla a tus discos) y comprueba cada paso. No toca la
  biblioteca real ni Navidrome.
- `ruff check --select F,E9 fonoteca/*.py`: imports y variables sin usar, claves repetidas, nombres sin definir.
- Toda herramienta se puede probar aislada: con `MUSIC_ROOT` y `MUSIC_DATOS` apuntando a carpetas temporales, nada toca
  la biblioteca real, y `nd_actualizar.py` se niega a tocar Navidrome.
