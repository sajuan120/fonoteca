#!/usr/bin/env python3
"""Reglas de GÉNEROS en un módulo que todos importan (30 sep 2026: antes revisar.py y auditoria.py sacaban el mapa de
generos.py con exec() y prueba.py con ast). Lo usan generos.py (el paso 6 del procesado), prueba.py, revisar.py y
auditoria.py.
  · MAPA: la lista corta de 20 géneros, en inglés (la app de Navidrome navega por género), y qué géneros de Deezer o
    Apple se traducen a cada uno. Nunca usar «/» en un nombre de género: Navidrome lo parte en dos.
  · G2: género de origen → uno de los 20.
  · fijos(): artista → género que gana siempre (decisiones/generos-fijos.tsv: lo decide cada biblioteca).
"""
import os
from comun import decision

MAPA = {
    "Rock": ["Rock", "Hard Rock", "Rock & Alternative", "Alternative Rock", "Indie Rock", "Power Pop", "Rock y Alternativo"],
    "Latin Rock": ["Latin Rock", "Rock Latino"],
    "Metal": ["Metal"],
    "Alternative": ["Alternative", "Neo-Psychedelia", "Indie Pop", "Vaihtoehtoinen", "Alternativo"],
    "Pop": ["Pop", "French Pop", "J-Pop", "K-Pop", "Punjabi Pop", "Arabic Pop", "Holiday", "Musicals", "Vocal", "Easy Listening"],
    "Hip Hop": ["Rap/Hip Hop", "Conscious Hip Hop", "Hip-Hop/Rap"],
    "R&B": ["R&B", "Soul & Funk", "Disco", "R&B/Soul"],
    "Electronic": ["Electro", "Dance", "House", "Afro House", "Elektro", "Electronica"],
    "Latin": ["Latin Music", "Latin Pop", "Pop latino", "Pop Latino", "Latino"],
    "Reggaeton": ["Reggaeton", "Latin Urban", "Latin Rap", "Urbano latino", "Reggaetón"],
    "Tropical": ["Tropical Music", "Salsa", "Música tropical", "Bolero"],
    "Mexican": ["Mexican Music", "Ranchera", "Traditional Mexican", "Traditional Mexicano", "Música Mexicana"],
    "Flamenco": ["Flamenco"],
    "Reggae": ["Reggae", "Roots Reggae"],
    "Country": ["Country", "Folk", "Americana", "Singer & Songwriter", "Singer/Songwriter", "Roots", "Raíces"],
    "Jazz": ["Jazz"],
    "Classical": ["Classical", "Classical Crossover", "Orchestral", "Instrumental", "New Age", "Meditation", "Clásica"],
    "Soundtrack": ["アニメ", "サウンドトラック", "Films/Games", "Original Score", "Video Game", "Anime", "TV Soundtrack", "Películas/Juegos"],
    "Kids": ["Kids", "Children's Music", "Lullabies", "Infantil"],
    "World": ["Worldwide", "African Music", "Asian Music", "Arabic", "Brazilian Music", "Brazilian", "Afrobeats", "Sports", "Música Asiática", "Música Brasileña", "Música Africana", "Deportes"],
}
G2 = {g: n for n, gs in MAPA.items() for g in gs}
G2.update({n: n for n in MAPA})   # los nombres ya normalizados también votan
# nombres viejos con "/" (Navidrome parte el género en la barra: "R&B / Soul" salía como 2 géneros)
G2.update({"R&B / Soul": "R&B", "Country / Folk": "Country", "Jazz / Blues": "Jazz"})


def fijos():
    """{artista: género} de decisiones/generos-fijos.tsv (artista<TAB>género[<TAB>nota]; # = comentario)."""
    p, res = decision("generos-fijos.tsv"), {}
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            c = l.rstrip("\n").split("\t")
            if l.strip() and not l.startswith("#") and len(c) >= 2:
                assert c[1] in MAPA, f"generos-fijos.tsv: «{c[1]}» no es uno de los 20 géneros ({c[0]})"
                res[c[0]] = c[1]
    return res
