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
  4. Guarda el resultado en app/static/musica/music_releases.json.
"""

import sys
import json
import time
import logging
import plistlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import urllib.request
import urllib.parse
import urllib.error

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
MIN_TRACKS: int = 5
OUTPUT_PATH: Path = Path("app/static/musica/music_releases.json")
MUSICBRAINZ_BASE: str = "https://musicbrainz.org/ws/2"
USER_AGENT: str = "trmnl-music-widget/1.0 (https://github.com/nebur)"
REQUEST_DELAY: float = 1.1   # MusicBrainz permite 1 req/s
MAX_RETRIES: int = 3          # Reintentos ante 429 / 503
MIN_SCORE: int = 85           # Umbral mínimo de relevancia en la búsqueda de artista

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Parseo del XML de Apple Music (plist)
# ---------------------------------------------------------------------------

def extract_artists(xml_path: Path) -> Counter:
    """
    Parsea el XML de la biblioteca iTunes/Apple Music y devuelve un Counter
    con {nombre_artista: num_pistas}.

    Usa plistlib para cargar el XML correctamente.
    """
    logger.info("Parseando biblioteca: %s", xml_path)
    artist_counter: Counter = Counter()

    try:
        with open(xml_path, "rb") as f:
            data = plistlib.load(f)

        tracks = data.get("Tracks", {})
        for _track_id, track in tracks.items():
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
    """
    Hace una petición GET a MusicBrainz y devuelve el JSON o None.

    Reintenta automáticamente ante códigos 429 (rate-limit) y 503
    con backoff exponencial hasta MAX_RETRIES veces.
    """
    qs = urllib.parse.urlencode(params)
    url = f"{MUSICBRAINZ_BASE}/{path}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                wait = REQUEST_DELAY * (2 ** attempt)  # backoff exponencial
                logger.warning(
                    "HTTP %d en %s — reintentando en %.1fs (intento %d/%d)",
                    exc.code, url, wait, attempt, MAX_RETRIES,
                )
                time.sleep(wait)
            else:
                logger.warning("HTTP %d consultando MusicBrainz (%s)", exc.code, url)
                return None
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            logger.warning("Error consultando MusicBrainz (%s): %s", url, exc)
            return None

    logger.error("Se agotaron los reintentos para: %s", url)
    return None


def _sleep() -> None:
    """Respeta el límite de 1 req/s de MusicBrainz."""
    time.sleep(REQUEST_DELAY)


def get_artist_mbid(artist_name: str) -> Optional[str]:
    """
    Busca el MBID del artista más relevante en MusicBrainz.

    Filtra por un umbral mínimo de score (MIN_SCORE) para evitar
    emparejar con artistas incorrectos.
    """
    data = _mb_get(
        "artist",
        {
            "query": f'artist:"{artist_name}"',
            "limit": 3,
            "fmt": "json",
        },
    )
    _sleep()

    if not data:
        return None

    artists = data.get("artists", [])
    if not artists:
        logger.debug("No se encontró MBID para: %s", artist_name)
        return None

    # Tomar el primero que supere el umbral de relevancia
    for candidate in artists:
        score = int(candidate.get("score", 0))
        if score >= MIN_SCORE:
            logger.debug("MBID encontrado para '%s' (score %d)", artist_name, score)
            return candidate.get("id")

    logger.info("  ⚠ Ningún resultado con score ≥%d para: %s", MIN_SCORE, artist_name)
    return None


ALLOWED_TYPES: set[str] = {"Album", "Single", "EP"}


def get_latest_release(mbid: str, artist_name: str) -> Optional[dict]:
    """
    Obtiene el release-group más reciente de un artista dado su MBID.

    Nota: el parámetro 'type' de MusicBrainz no se puede pasar con múltiples
    valores vía urlencode sin que el '|' quede codificado como '%7C' (HTTP 400).
    Se obtienen todos los release-groups y se filtra por tipo en Python.
    Devuelve dict con: title, date, type, mbid o None si no hay datos.
    """
    data = _mb_get(
        "release-group",
        {
            "artist": mbid,
            "limit": 100,
            "fmt": "json",
        },
    )
    _sleep()

    if not data:
        return None

    groups = data.get("release-groups", [])
    # Filtrar por tipo (Album / Single / EP) y que tengan fecha
    dated = [
        g for g in groups
        if g.get("primary-type", "") in ALLOWED_TYPES
        and g.get("first-release-date", "").strip()
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

    counter = extract_artists(xml_path)
    top_artists = filter_top_artists(counter)

    if not top_artists:
        logger.warning("No hay artistas con más de %d pistas. Saliendo.", MIN_TRACKS)
        return

    releases: list[dict] = []
    total = len(top_artists)
    not_found: int = 0

    for idx, artist in enumerate(top_artists, start=1):
        logger.info("[%d/%d] Consultando: %s", idx, total, artist)

        try:
            mbid = get_artist_mbid(artist)

            if not mbid:
                not_found += 1
                logger.info("  ✗ Sin MBID: %s", artist)
                continue

            release = get_latest_release(mbid, artist)
            if release:
                releases.append(release)
                logger.info("  → %s (%s)", release["title"], release["date"])
            else:
                logger.info("  ✗ Sin releases con fecha: %s", artist)

            # Guardado incremental cada 10 artistas
            if idx % 10 == 0 or idx == total:
                _save_results(releases, top_artists, xml_path)

        except KeyboardInterrupt:
            logger.info("Interrupción por el usuario. Guardando progreso...")
            _save_results(releases, top_artists, xml_path)
            sys.exit(0)
        except Exception as exc:
            logger.error("Error procesando '%s': %s", artist, exc)

    logger.info(
        "Completado: %d releases encontrados, %d artistas sin MBID (de %d)",
        len(releases), not_found, total,
    )
    _save_results(releases, top_artists, xml_path)


def _save_results(releases: list[dict], top_artists: list[str], xml_path: Path) -> None:
    """Persiste el resultado actual en el JSON de salida."""
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_library": str(xml_path),
        "total_artists_checked": len(top_artists),
        "releases": releases,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("✓ Progreso guardado (%d releases)", len(releases))


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m app.scripts.music_releases <ruta_Biblioteca.xml>")
        sys.exit(1)

    run(Path(sys.argv[1]))
