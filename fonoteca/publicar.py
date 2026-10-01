#!/usr/bin/env python3
"""Copia a la carpeta PÚBLICA (el repositorio de fonoteca) solo lo publicable, y se NIEGA si encuentra un dato personal.
30 sep 2026: así el código que se usa y el que se publica son el MISMO, y mejorar uno y actualizar el otro es un comando.

Uso: publicar.py <carpeta del repositorio> [--execute]
  Sin --execute: muestra qué copiaría y corre el chequeo de privacidad sobre TODO lo que quedaría en el repositorio.

Qué copia (lista blanca):
  · los scripts de esta carpeta (*.py)                         → <repo>/fonoteca/
  · los avisos y la salud semanal (rutas.scripts de la config)  → <repo>/scripts/
  · las unidades de systemd de usuario (musica-*, antra-update) → <repo>/systemd/  (con las rutas del repositorio)
  Lo demás del repositorio (README, LICENSE, docs/, docker/, ejemplos/, config.example.toml) vive allá y no se toca,
  pero TAMBIÉN pasa por el chequeo.
Qué no copia NUNCA: config.toml, las claves (.qobuz_token, .acoustid_key…), decisiones/, usuarios/, logs/, cache/,
  respaldos/, planes/, puntuales/ ni los archivos de estado (*.json, *.tsv, *.md de esta carpeta).
Chequeo de privacidad: cada archivo se revisa contra [privacidad] de config.toml (textos, y palabras sueltas) y contra
  patrones generales (correos, IPs de una red de casa o de Tailscale, rutas /home/<usuario>). Si encuentra algo, no
  escribe NADA y muestra archivo:línea para arreglarlo en el original.
"""
import glob, os, re, sys
from comun import CONF, HERE, SCRIPTS

args = sys.argv[1:]
if not args or args[0].startswith("-"):
    sys.exit(__doc__)
REPO = os.path.abspath(os.path.expanduser(args[0]))
EXECUTE = "--execute" in args
SYSTEMD = os.path.expanduser("~/.config/systemd/user")
NUNCA = {"config.toml", ".qobuz_token", ".acoustid_key", ".deezer_arl", ".robot", ".env"}
UNIDADES = ("musica-*.service", "musica-*.timer", "musica-*.path", "antra-update.service", "antra-update.timer")
SCRIPTS_PUB = ("musica-salud.py", "musica-descarga-lista.sh", "musica-procesar.sh", "antra-update.sh")
# en las unidades, las rutas de esta instalación → las del repositorio clonado en ~/fonoteca
_h = lambda p: p.replace(os.path.expanduser("~"), "%h", 1).rstrip("/") + "/"
RUTAS_UNIDADES = [(_h(SCRIPTS), "%h/fonoteca/scripts/"), (_h(HERE), "%h/fonoteca/fonoteca/")]

priv = CONF.get("privacidad", {})
TEXTOS = [t.lower() for t in priv.get("textos", [])]
PALABRAS = [re.compile(rf"\b{re.escape(p)}\b", re.I) for p in priv.get("palabras", [])]
GENERALES = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "correo"),
    (re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"), "IP de una red de casa"),
    (re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"), "IP de Tailscale"),
    (re.compile(r"/home/\w+"), "ruta de un usuario"),
]
PERMITIDO = re.compile(r"noreply|example|ejemplo|tu-correo|usuario@|you@", re.I)   # correos de ejemplo en la documentación


def plan():
    """[(origen, destino relativo, transformar)]"""
    out = []
    for p in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        if os.path.basename(p) not in NUNCA:
            out.append((p, os.path.join("fonoteca", os.path.basename(p)), None))
    for n in SCRIPTS_PUB:
        p = os.path.join(SCRIPTS, n)
        if os.path.exists(p):
            out.append((p, os.path.join("scripts", n), None))
    for patron in UNIDADES:
        for p in sorted(glob.glob(os.path.join(SYSTEMD, patron))):
            out.append((p, os.path.join("systemd", os.path.basename(p)), RUTAS_UNIDADES))
    return out


def problemas(texto, nombre):
    res = []
    for i, l in enumerate(texto.splitlines(), 1):
        bajo = l.lower()
        for t in TEXTOS:
            if t in bajo: res.append(f"{nombre}:{i}: «{t}» → {l.strip()[:120]}")
        for p in PALABRAS:
            if p.search(l): res.append(f"{nombre}:{i}: «{p.pattern}» → {l.strip()[:120]}")
        for p, que in GENERALES:
            for m in p.finditer(l):
                if not PERMITIDO.search(m.group(0)): res.append(f"{nombre}:{i}: {que} «{m.group(0)}» → {l.strip()[:120]}")
    return res


def transformar(texto, reemplazos):
    for a, b in reemplazos or []:
        texto = texto.replace(a, b)
    return texto


copias = plan()
hallazgos, nuevos = [], {}
for src, rel, rep in copias:
    texto = transformar(open(src, encoding="utf-8").read(), rep)
    nuevos[rel] = texto
    hallazgos += problemas(texto, rel)
# lo que ya vive en el repositorio (README, docs, ejemplos…) también se revisa: exactamente lo que git subiría (lo
# que está en .gitignore —la caché, los logs y las decisiones que se crean al usar las herramientas ahí— no se revisa
# porque nunca se sube); sin git, todo menos esas carpetas
DATOS_DIRS = {"decisiones", "usuarios", "logs", "cache", "respaldos", "planes", "__pycache__"}
if os.path.isdir(os.path.join(REPO, ".git")):
    import subprocess
    en_repo = subprocess.run(["git", "-C", REPO, "ls-files", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, text=True, check=True).stdout.splitlines()
else:
    en_repo = [os.path.relpath(os.path.join(d, f), REPO) for d, dirs, fs in os.walk(REPO)
               if not (set(os.path.relpath(d, REPO).split(os.sep)) & (DATOS_DIRS | {".git"})) for f in fs]
for rel in en_repo:
    f = os.path.basename(rel)
    if rel in nuevos or f.endswith((".png", ".jpg", ".gif")): continue
    partes = rel.split(os.sep)
    if f in NUNCA or (set(partes[:-1]) & DATOS_DIRS and partes[0] != "ejemplos"):
        hallazgos.append(f"{rel}: este archivo NO debe estar en el repositorio público (¿falta en .gitignore?)"); continue
    try:
        hallazgos += problemas(open(os.path.join(REPO, rel), encoding="utf-8").read(), rel)
    except (UnicodeDecodeError, FileNotFoundError):
        pass
cambia = [rel for rel, t in nuevos.items() if not os.path.exists(os.path.join(REPO, rel)) or open(os.path.join(REPO, rel), encoding="utf-8").read() != t]
print(f"{len(nuevos)} archivos publicables ({len(cambia)} nuevos o cambiados) → {REPO}")
for rel in cambia: print("  ·", rel)
if hallazgos:
    print(f"\n⛔ {len(hallazgos)} dato(s) personal(es): NO se copia nada. Arreglarlos en el original:")
    for h in hallazgos: print("  ", h)
    sys.exit(1)
print("\n✅ Chequeo de privacidad: limpio.")
if not EXECUTE:
    sys.exit("Simulación: no se copió nada. Usa --execute.")
for rel, t in nuevos.items():
    dst = os.path.join(REPO, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "w", encoding="utf-8").write(t)
    if rel.endswith((".py", ".sh")): os.chmod(dst, 0o755)
viejos = [os.path.relpath(p, REPO) for sub in ("fonoteca", "scripts", "systemd")
          for p in glob.glob(os.path.join(REPO, sub, "*"))
          if os.path.isfile(p) and p.endswith((".py", ".sh", ".service", ".timer", ".path"))
          and os.path.relpath(p, REPO) not in nuevos]
for rel in viejos:   # un script que se borró o se unió aquí también se va del repositorio
    os.remove(os.path.join(REPO, rel)); print("  borrado del repositorio:", rel)
print(f"HECHO: {len(nuevos)} archivos en {REPO}. Revisa con «git -C {REPO} status» y «git diff» antes de subir.")
