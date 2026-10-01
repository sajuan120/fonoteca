# fonoteca

*Spanish for "sound library".* Tools to build and look after your own lossless music library, starting from what you
actually listen to, and to serve it to the whole family with [Navidrome](https://www.navidrome.org/).

> 🇪🇸 [Leer en español](README.es.md) · The code and its comments are in Spanish; this page explains everything in English.

fonoteca does not download music by itself. It works around [Antra](https://github.com/anandprtp/Antra), which
downloads lossless files, and [Navidrome](https://www.navidrome.org/), which streams them. The value is in the
**curation**: every download is checked, tagged and filed by the same rules, and nothing you have already listened to
(plays, stars, playlists) is ever lost when a file is fixed, renamed or replaced.

## What it does

**1. Choose what to download.** From your Spotify *extended streaming history*, `seleccion_usuario.py` picks the songs
you really listen to (played on different days, chosen on purpose, finished) and, optionally, the albums you listen to
as albums. You get a list of links to paste into Antra.

**2. Process every download automatically.** When Antra finishes, a desktop notification offers to *simulate* the
processing. You read what would change, then confirm. The steps (`procesar_descarga.py`):

| Step | What happens |
|---|---|
| Integrity | `flac -t` (or a full decode with ffmpeg for MP3/AAC/Opus). Corrupt files are deleted and listed to download again. |
| Right song? | Durations are compared with the recording's ISRC. Suspicious files go through AcoustID and are compared with the **exact Spotify track**: its duration and its 30-second preview, matched by audio fingerprint. Wrong audio is deleted and listed to download again. |
| Tags | Genre, MusicBrainz recording and release IDs (only when they really belong to *this* recording), album artist, year. |
| Filing | `Artist/Year - Album/NN - Title.ext`, keeping each format as it is. |
| Duplicates | One copy per recording. Lossless beats lossy; otherwise the album with more songs wins, or the most played copy. |
| Genres | A short list of 20, in English, at most two per artist. |
| Numbers | Track numbers from **one** Deezer edition that contains every song of the album, so a second run never changes anything. |
| Covers, lyrics, volume | Covers (Deezer or iTunes), synced lyrics (LRCLIB), ReplayGain 2.0. |
| Navidrome | Rescan. Plays, stars, history and playlist entries move to the new paths. |
| Report | A to-do document, a weekly health check, and a recovery kit (links plus every tag). |

**3. Keep it healthy.**
- `auditoria.py` reviews the whole library: corrupt files, wrong audio, foreign MusicBrainz IDs, mixed covers, split
  albums… Each finding is classed as *fix* 🔴, *decide* 🟡 or *info* ⚪.
- A weekly timer checks that Navidrome matches the disk.
- A test bench (`banco_pruebas.py`) runs the whole pipeline on a fake library.

**4. Discover new music without filling the library with junk** (optional, with
[Octo-Fiesta](https://github.com/V1ck3s/octo-fiesta) and [ListenBrainz](https://listenbrainz.org/)).
- Songs you find or get recommended arrive as low-quality trial MP3s in a separate folder.
- A song played 3+ times in four weeks "earns" its FLAC.
- A song nobody plays is deleted after six weeks, with a warning first.
- A weekly «Descubrir» playlist is built from ListenBrainz recommendations you have never heard.

**5. Tools for the hand-made parts.** Every operation that used to be a one-off script is now a general tool:

| Tool | Use |
|---|---|
| `quitar_copia.py` | Remove a copy; everything it had moves to the one that stays. |
| `unir_discos.py` | Merge editions of the same album, or put a single back into its album. |
| `numeros_pista.py --a-mano` | Number an album by hand against a Deezer release. |
| `ost.py` | Group soundtracks by franchise ("Soundtrack Hades"), with at least 3 songs each. |
| `buscar_fuentes.py` | Look for missing songs on Deezer, Tidal, Apple Music and Qobuz (Antra accepts their links). |
| `importar_manual.py` | Bring in songs downloaded by hand, in any format. |
| `caratulas.py` | Covers: missing ones, mixed ones, small ones, and AI upscaling (Real-ESRGAN) chosen by eye. |

## Principles

- **Simulation first.** Every tool only shows what it would do. `--execute` writes, after making a backup.
- **Nothing is lost.** Every move goes through one function (`comun.cambiar_rutas`) that updates Antra's state, the
  `.m3u` playlists, the decision lists and the log that carries Navidrome plays to the new path.
- **One rule per question.** "Is this the same song?" (`comun.clave_titulo`), "is this MusicBrainz ID its recording?"
  (`comun.grabacion_corresponde`) and "does this file contain that Spotify track?" (`comun.parecido_spotify`) each have
  exactly one implementation, used everywhere.
- **No Spotify API.** Spotify's Web API now requires the app owner to pay for Premium. fonoteca reads Spotify's public
  pages instead (track, album, playlist embed), slowly and with a cache. Deezer, MusicBrainz, LRCLIB, AcoustID and iTunes
  are used through their free APIs (`red.py` keeps each service's rate limit, and never caches a network failure as "not
  found").
- **Your decisions live in files, not in the code.** `decisiones/` holds your library's choices: songs that are the same
  under another name, fixed genres per artist, soundtrack franchises, covers to keep…

## Requirements

- Linux, Python 3.11+, and `pip install -r requirements.txt` (mutagen, Pillow, numpy).
- `flac`, `ffmpeg`, `fpcalc` (Chromaprint) and `curl`.
- [Navidrome](https://www.navidrome.org/) (Docker example in `docker/`) and [Antra](https://github.com/anandprtp/Antra).
- Optional:
  - an [AcoustID](https://acoustid.org/) API key in `fonoteca/.acoustid_key`;
  - a ListenBrainz account, and Octo-Fiesta for the trial funnel;
  - [Upscayl](https://upscayl.org/) for AI covers;
  - a Qobuz session token for `buscar_fuentes.py`.
- The notifications use `notify-send`, and processing opens a Konsole (KDE). Elsewhere, run the commands in a terminal.

## Getting started

```bash
git clone https://github.com/<you>/fonoteca ~/fonoteca && cd ~/fonoteca
pip install -r requirements.txt
cp config.example.toml fonoteca/config.toml          # your paths, your contact for MusicBrainz, your users
cp -r ejemplos/decisiones fonoteca/decisiones        # optional: example decision files to start from
cd fonoteca
python3 auditoria.py                                 # read-only review of your library
python3 procesar_descarga.py "<folder Antra created>"            # simulation
python3 procesar_descarga.py "<folder Antra created>" --execute  # for real
```

Timers and notifications: copy `systemd/*` to `~/.config/systemd/user/`, then run `systemctl --user daemon-reload` and
`systemctl --user enable --now musica-salud.timer musica-descarga-lista.path`. Add the `musica-prueba-*` and
`musica-descubrir` units only if you use Octo-Fiesta. The units assume the repository is at `~/fonoteca`.

### The panel

Every tool also has a button. `python3 fonoteca/panel.py --instalar` adds **Fonoteca** to your applications menu.
Opening it starts a small local server and shows the panel in its own browser window: the library's status at the top,
the tools grouped by module, and a console with the live output. The interface is in Spanish, like the tools.

- The same rules as in the terminal. **EJECUTAR** (run) only lights up after a **SIMULAR** (simulate) of that same action
  with the same inputs, and the server enforces it too. Anything without a simulation asks for a second click.
- Whatever moves or renames songs hands their plays, stars and playlists to Navidrome when it finishes, like the
  processing does.
- It listens only on `127.0.0.1`, every request carries a per-session token, and it shuts itself down after 20 idle
  minutes. It needs nothing beyond the standard library. Every run is saved in `logs/panel/`.

More: [docs/como-funciona.md](docs/como-funciona.md) explains the whole flow, the curation rules and the lessons
learned (in Spanish).

## Status

This is a personal project made for one household's library (about 6,000 songs, four listeners). It is shared as it is,
in the hope that the rules and the checks are useful to someone else. Use it for music you are entitled to keep, and
respect the terms of the services involved and the law where you live. fonoteca is not affiliated with Spotify, Deezer,
Navidrome, Antra or any other service.

## License

[MIT](LICENSE)
