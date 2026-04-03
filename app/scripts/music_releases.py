#!/usr/bin/env python3
"""
music_releases.py — Script semanal (viernes)

Uso:
    python -m app.scripts.music_releases /ruta/a/Biblioteca.xml

Pasos:
  1. Parsea el XML de Apple Music (formato plist).
  2. Extrae artistas con más de 5 pistas en la biblioteca.
  3. Consulta MusicBrainz API (gratuita, sin clave) para obtener
     el último lanzamiento de cada artista.
  4. Guarda el resultado en app/static/music_releases.json.
"""

import sys
import json
import time
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

import urllib.request
import urllib.parse
import urllib.error

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
MIN_TRACKS: int = 5
OUTPUT_PATH: Path = Path("app/static/music/music_releases.json")
MUSICBRAINZ_BASE: str = "https://musicbrainz.org/ws/2"
USER_AGENT: str = "trmnl-music-widget/1.0 (https://github.com/nebur)"
REQUEST_DELAY: float = 1.1  # MusicBrainz permite 1 req/s

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Parseo del XML de Apple Music (plist)
# ---------------------------------------------------------------------------

import plistlib

def extract_artists(xml_path: Path) -> Counter:
    """
    Parsea el XML de la biblioteca iTunes/Apple Music y devuelve un Counter
    con {nombre_artista: num_pistas}.

    Usa plistlib para cargar el XML correctamente.
    """
    logger.info("Parseando biblioteca: %s", xml_path)
    artist_counter: Counter = Counter()

    try:
        with open(xml_path, 'rb') as f:
            data = plistlib.load(f)
        
        tracks = data.get("Tracks", {})
        for track_id, track in tracks.items():
            artist = track.get("Artist", "").strip()
            if artist:
                artist_counter[artist] += 1
                
    except Exception as exc:
        logger.error("Error cargando el XML con plistlib: %s", exc)

    logger.info("Total artistas únicos encontrados: %d", len(artist_counter))
    return artist_counter


def filter_top_artists(counter: Counter, min_tracks: int = MIN_TRACKS) -> list[str]:
    """Devuelve artistas con más de `min_tracks` pistas, ordenados por frecuencia."""
    top = [artist for artist, count in counter.most_common() if count > min_tracks]
    logger.info("Artistas con más de %d pistas: %d", min_tracks, len(top))
    return top


# ---------------------------------------------------------------------------
# 2. Consulta MusicBrainz
# ---------------------------------------------------------------------------

def _mb_get(path: str, params: dict) -> Optional[dict]:
    """Hace una petición GET a MusicBrainz y devuelve el JSON o None."""
    qs = urllib.parse.urlencode(params)
    url = f"{MUSICBRAINZ_BASE}/{path}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        logger.warning("Error consultando MusicBrainz (%s): %s", url, exc)
        return None


def get_artist_mbid(artist_name: str) -> Optional[str]:
    """Busca el MBID del artista más relevante en MusicBrainz."""
    data = _mb_get(
        "artist",
        {
            "query": f'artist:"{artist_name}"',
            "limit": 1,
            "fmt": "json",
        },
    )
    if not data:
        return None
    artists = data.get("artists", [])
    if not artists:
        logger.debug("No se encontró MBID para: %s", artist_name)
        return None
    return artists[0].get("id")


def get_latest_release(mbid: str, artist_name: str) -> Optional[dict]:
    """
    Obtiene el release-group más reciente de un artista dado su MBID.
    Devuelve dict con: title, date, type o None si no hay datos.
    """
    data = _mb_get(
        "release-group",
        {
            "artist": mbid,
            "type": "album|single|ep",
            "limit": 100,
            "fmt": "json",
        },
    )
    if not data:
        return None

    groups = data.get("release-groups", [])
    # Filtrar los que tienen fecha y ordenar desc
    dated = [
        g for g in groups
        if g.get("first-release-date", "").strip()
    ]
    if not dated:
        return None

    dated.sort(key=lambda g: g["first-release-date"], reverse=True)
    latest = dated[0]

    return {
        "artist": artist_name,
        "title": latest.get("title", ""),
        "date": latest.get("first-release-date", ""),
        "type": latest.get("primary-type", ""),
        "mbid": latest.get("id", ""),
    }


# ---------------------------------------------------------------------------
# 3. Orquestación y guardado
# ---------------------------------------------------------------------------

def run(xml_path: Path) -> None:
    """Pipeline principal."""
    if not xml_path.exists():
        logger.error("No existe el fichero: %s", xml_path)
        sys.exit(1)

    # Paso 1: extraer artistas
    counter = extract_artists(xml_path)
    top_artists = filter_top_artists(counter)

    if not top_artists:
        logger.warning("No hay artistas con más de %d pistas. Saliendo.", MIN_TRACKS)
        return

    # Paso 3: guardar resultado incrementalmente
    releases: list[dict] = []
    total = len(top_artists)

    for idx, artist in enumerate(top_artists, start=1):
        logger.info("[%d/%d] Consultando: %s", idx, total, artist)

        try:
            mbid = get_artist_mbid(artist)
            time.sleep(REQUEST_DELAY)

            if mbid:
                release = get_latest_release(mbid, artist)
                if release:
                    releases.append(release)
                    logger.info("  → %s (%s)", release["title"], release["date"])
            
            # Guardado incremental cada 10 artistas
            if idx % 10 == 0 or idx == total:
                _save_results(releases, top_artists, xml_path)
                
            time.sleep(REQUEST_DELAY)

        except KeyboardInterrupt:
            logger.info("Interrupción por el usuario. Guardando progreso...")
            _save_results(releases, top_artists, xml_path)
            sys.exit(0)
        except Exception as e:
            logger.error("Error procesando %s: %s", artist, e)

def _save_results(releases: list[dict], top_artists: list[str], xml_path: Path):
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_library": str(xml_path),
        "total_artists_checked": len(top_artists),
        "releases": releases,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("✓ Progreso guardado (%d releases)", len(releases))

# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Uso: python -m app.scripts.music_releases <ruta_Biblioteca.xml>")
        sys.exit(1)

    run(Path(sys.argv[1]))
