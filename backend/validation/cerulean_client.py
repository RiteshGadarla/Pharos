"""Read-only client for the Cerulean (SkyTruth) public API.
See PLAN.md section 17.2.

VALIDATION ONLY. Non-negotiable 5: Cerulean is never in the runtime
path. Nothing under services/ may import this module, and
tests/test_no_cerulean_in_services.py enforces that by scanning the
source tree. If you find yourself wanting a Cerulean call inside a
pipeline stage, the answer is no: the demo must run with the network
cable unplugged, and an external system's operating point must not leak
into DRISHTA's own claims.

The public read API is an OGC API Features service served by tipg at
api.cerulean.skytruth.org. That tipg service does not require the
Bearer key the other cerulean-cloud services need. The repository is
Apache-2.0. Credit SkyTruth on the validation page and in the dossier
provenance section.

Every response is cached to data/cerulean/, so after the first fetch
the whole harness runs offline.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from urllib.parse import urlencode

BASE_URL = "https://api.cerulean.skytruth.org"
DEFAULT_CACHE_DIR = "data/cerulean"
ATTRIBUTION = (
    "Slick records from Cerulean, by SkyTruth (api.cerulean.skytruth.org, "
    "cerulean-cloud is Apache-2.0). Used here for third-party agreement "
    "measurement only, never as ground truth and never in the runtime path."
)

# What Cerulean's operating point is, stated wherever a comparison is
# reported. Their production model runs Sentinel-1 VV scaled to 80 m
# resolution on 512x512 tiles for global throughput; DRISHTA runs at
# full GRD resolution on a single scene. Two systems at different
# operating points will disagree, and that disagreement is not error on
# either side.
OPERATING_POINT_NOTE = (
    "Cerulean's production model runs on Sentinel-1 VV scaled to 80 m resolution with "
    "512x512 tiles, sized for global throughput. DRISHTA runs at full GRD resolution on a "
    "single scene. Disagreement between two systems at different operating points is "
    "expected and is not error on either side."
)


@dataclass(frozen=True)
class CachedResponse:
    path: str
    from_cache: bool
    payload: dict


def _cache_path(cache_dir: str, url: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return os.path.join(cache_dir, f"{digest}.json")


def fetch(path: str, params: dict | None = None, cache_dir: str = DEFAULT_CACHE_DIR, offline: bool = False) -> CachedResponse:
    """GETs one endpoint, caching the response by URL hash.

    offline=True never touches the network: it serves the cache or
    raises. That is the mode the pre-demo check runs in, and it is why
    every response is cached in the first place.
    """
    url = f"{BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    cached_at = _cache_path(cache_dir, url)

    if os.path.exists(cached_at):
        with open(cached_at) as f:
            return CachedResponse(path=cached_at, from_cache=True, payload=json.load(f))

    if offline:
        raise FileNotFoundError(
            f"No cached Cerulean response for {url}. Run the harness online once to "
            f"populate {cache_dir}, then it works with the network cable unplugged."
        )

    import urllib.request

    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310, validation-only
        payload = json.loads(response.read().decode())

    os.makedirs(cache_dir, exist_ok=True)
    with open(cached_at, "w") as f:
        json.dump(payload, f)
    return CachedResponse(path=cached_at, from_cache=False, payload=payload)


def list_collections(cache_dir: str = DEFAULT_CACHE_DIR, offline: bool = False) -> list[str]:
    """Enumerates the service's collections and returns their ids.

    Enumerate first, always. Do not hardcode collection names guessed
    from documentation: the service's own catalogue is the only
    authority on what it actually serves, and a guessed name fails at
    the worst possible moment.
    """
    response = fetch("/collections", cache_dir=cache_dir, offline=offline)
    return [c.get("id", "") for c in response.payload.get("collections", []) if c.get("id")]


def fetch_items(
    collection: str,
    bbox: tuple[float, float, float, float] | None = None,
    datetime_range: str | None = None,
    limit: int = 200,
    cache_dir: str = DEFAULT_CACHE_DIR,
    offline: bool = False,
) -> dict:
    """Fetches GeoJSON items from one collection, filtered by bbox and
    time. Returns the raw FeatureCollection."""
    params: dict = {"limit": limit, "f": "geojson"}
    if bbox:
        params["bbox"] = ",".join(str(v) for v in bbox)
    if datetime_range:
        params["datetime"] = datetime_range
    return fetch(f"/collections/{collection}/items", params, cache_dir=cache_dir, offline=offline).payload


# Field names that, across the Cerulean schema's revisions, have carried
# the human review state. Checked by presence rather than assumed,
# because a hardcoded field name is the same mistake as a hardcoded
# collection name.
REVIEW_FIELDS = ("cls_confidence", "human_confidence", "validated", "review_state")


def filter_reviewed(feature_collection: dict) -> list[dict]:
    """Keeps records whose validation or human confidence fields
    indicate expert review.

    The comparison has to be against reviewed polygons rather than raw
    model output, or the number measures one model against another
    model's unreviewed guesses, which is a weaker claim than it looks.
    """
    reviewed = []
    for feature in feature_collection.get("features", []):
        props = feature.get("properties", {})
        present = [f for f in REVIEW_FIELDS if f in props and props[f] not in (None, "")]
        if not present:
            continue
        if any(_indicates_review(props[f]) for f in present):
            reviewed.append(feature)
    return reviewed


def _indicates_review(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "validated", "reviewed", "high"}
    return False


def dark_records(feature_collection: dict) -> list[dict]:
    """Records whose source category is Dark: Cerulean's vessel
    association could not resolve a broadcasting source.

    This is the higher-value use of the API. Their association
    considers only long linear detections and nearby broadcasting
    vessels, and their AIS carries a delay of up to 72 hours, so Dark
    records are exactly the gap DRISHTA targets. Resolving one is the
    strongest single result available to this project.
    """
    out = []
    for feature in feature_collection.get("features", []):
        props = feature.get("properties", {})
        for key in ("source_type", "source_category", "cls_short_name", "slick_class"):
            value = props.get(key)
            if isinstance(value, str) and value.strip().lower() == "dark":
                out.append(feature)
                break
    return out
