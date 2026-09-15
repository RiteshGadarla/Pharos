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

# Collection ids, confirmed against a live /collections enumeration
# rather than guessed. The service exposes 58 collections; these are the
# four this project uses. `slick_plus` is the detection layer with the
# review and source fields joined on, `source_plus` is the per source
# attribution layer, `cls` is the classification lookup that gives
# hitl_cls its meaning, and `sentinel1_grd` is the scene index.
SLICK_COLLECTION = "public.slick_plus"
SOURCE_COLLECTION = "public.source_plus"
CLS_COLLECTION = "public.cls"
SCENE_COLLECTION = "public.sentinel1_grd"

# Source type keys used by source_plus. Type 3 (DARK) is the one this
# project cares about: Cerulean saw a slick and could not tie it to a
# broadcasting vessel.
SOURCE_TYPE_DARK = "DARK"

# The slick_plus array field holding dark source ids. Types 1, 2 and 3
# are vessel, infrastructure and dark respectively.
DARK_SOURCE_IDS_FIELD = "source_type_3_ids"

# Cerulean's own guidance on source_collated_score, which runs -5 to +5:
# treat > 0 as credible, raise to 0.5 or 1.0 to trade recall for
# precision. Recorded here so a threshold in the harness is traceable to
# the publisher's recommendation rather than picked by us.
CREDIBLE_SCORE_THRESHOLD = 0.0
STRICT_SCORE_THRESHOLD = 0.5

# Cerulean recommends starting at git_tag 1.1.0, after breaking changes
# to scoring introduced post 1.0.11. Scores below that are not
# comparable with scores above it.
MIN_COMPARABLE_GIT_TAG = (1, 1, 0)
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
    cql_filter: str | None = None,
    sortby: str | None = None,
    offset: int | None = None,
    cache_dir: str = DEFAULT_CACHE_DIR,
    offline: bool = False,
    **extra,
) -> dict:
    """Fetches GeoJSON items from one collection. Returns the raw
    FeatureCollection.

    cql_filter is a CQL-2 expression evaluated by the server, for
    example "NOT hitl_cls IS NULL" or "max_source_collated_score GT 0".
    Filtering server side rather than locally is not an optimisation, it
    is a correctness matter: the Arabian Sea box holds about 8900 slicks
    of which 83 are human reviewed, so pulling one page and filtering it
    in Python finds nothing and reports that as an empty result.

    extra passes through exact match fields the service exposes as
    query parameters, such as s1_scene_id or source_type.
    """
    params: dict = {"limit": limit, "f": "geojson"}
    if bbox:
        params["bbox"] = ",".join(str(v) for v in bbox)
    if datetime_range:
        params["datetime"] = datetime_range
    if cql_filter:
        params["filter"] = cql_filter
    if sortby:
        params["sortby"] = sortby
    if offset is not None:
        params["offset"] = offset
    params.update({k: v for k, v in extra.items() if v is not None})
    return fetch(f"/collections/{collection}/items", params, cache_dir=cache_dir, offline=offline).payload


def fetch_scene_slicks(
    s1_scene_id: str, cache_dir: str = DEFAULT_CACHE_DIR, offline: bool = False
) -> dict:
    """Every Cerulean slick detected in one Sentinel-1 scene.

    This is the join key for PLAN.md 17.2 step 5. Both systems name the
    same GRD product the same way, so the scene id is what makes an IoU
    comparison a comparison of two readings of one image rather than of
    two different images that happen to overlap.
    """
    return fetch_items(
        SLICK_COLLECTION, limit=999, s1_scene_id=s1_scene_id, cache_dir=cache_dir, offline=offline
    )


def fetch_reviewed(
    bbox: tuple[float, float, float, float] | None = None,
    datetime_range: str | None = None,
    limit: int = 200,
    cache_dir: str = DEFAULT_CACHE_DIR,
    offline: bool = False,
) -> dict:
    """Slicks carrying a SkyTruth human review verdict.

    Asks the server for the reviewed records instead of pulling a page
    and hoping some of them are reviewed. Review is sparse, about 1
    percent of detections in the Arabian Sea, so it has to be a filter.
    """
    return fetch_items(
        SLICK_COLLECTION,
        bbox=bbox,
        datetime_range=datetime_range,
        limit=limit,
        cql_filter="NOT hitl_cls IS NULL",
        sortby="-slick_timestamp",
        cache_dir=cache_dir,
        offline=offline,
    )


def fetch_dark_sources(
    bbox: tuple[float, float, float, float] | None = None,
    datetime_range: str | None = None,
    min_score: float = CREDIBLE_SCORE_THRESHOLD,
    limit: int = 200,
    cache_dir: str = DEFAULT_CACHE_DIR,
    offline: bool = False,
) -> dict:
    """Slick to source matches where the source is a dark vessel.

    This is the higher value use of the API, per PLAN.md 17.2. Their
    association considers only long linear detections and nearby
    broadcasting vessels, and their AIS carries a delay of up to 72
    hours, so a record here is a slick their pipeline could not tie to
    anyone who was transmitting. That is exactly the gap DRISHTA
    targets, and each record carries a slick_url that opens the case in
    their UI beside the Sentinel-1 image.
    """
    return fetch_items(
        SOURCE_COLLECTION,
        bbox=bbox,
        datetime_range=datetime_range,
        limit=limit,
        source_type=SOURCE_TYPE_DARK,
        cql_filter=f"source_collated_score GT {min_score}",
        sortby="-source_collated_score",
        cache_dir=cache_dir,
        offline=offline,
    )


# The human review fields, confirmed present on a live slick_plus
# record. hitl_cls is the integer class chosen by a SkyTruth reviewer
# and hitl_cls_name is its label; both are null on unreviewed records,
# which is the overwhelming majority. Look these ids up in
# CLS_COLLECTION rather than hardcoding their meaning: the class
# hierarchy has a supercls column, so Vessel and Infrastructure both sit
# under Anthropogenic, and a reviewer normally records the specific
# subclass rather than the superclass.
REVIEW_FIELDS = ("hitl_cls", "hitl_cls_name")


def filter_reviewed(feature_collection: dict) -> list[dict]:
    """Keeps records carrying a human review verdict.

    The comparison has to be against reviewed polygons rather than raw
    model output, or the number measures one model against another
    model's unreviewed guesses, which is a weaker claim than it looks.

    Use fetch_reviewed to ask the server for these directly. This
    function is for filtering a collection already in hand.
    """
    reviewed = []
    for feature in feature_collection.get("features", []):
        props = feature.get("properties", {})
        if props.get("hitl_cls") is not None:
            reviewed.append(feature)
    return reviewed


def dark_records(feature_collection: dict) -> list[dict]:
    """Records whose source association points at a dark vessel.

    Accepts either shape: a source_plus collection, where each record
    carries source_type directly, or a slick_plus collection, where a
    dark association shows up as a non empty source_type_3_ids array.
    """
    out = []
    for feature in feature_collection.get("features", []):
        props = feature.get("properties", {})
        source_type = props.get("source_type")
        if isinstance(source_type, str) and source_type.strip().upper() == SOURCE_TYPE_DARK:
            out.append(feature)
            continue
        if props.get(DARK_SOURCE_IDS_FIELD):
            out.append(feature)
    return out


def parse_git_tag(value: str | None) -> tuple[int, ...] | None:
    """Cerulean's scoring version as a comparable tuple, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError:
        return None


def filter_comparable_scores(features: list[dict]) -> list[dict]:
    """Drops records scored by a version whose scores are not
    comparable with current ones.

    Cerulean introduced breaking scoring changes after git_tag 1.0.11
    and recommends starting at 1.1.0. Mixing a pre and post break score
    in one table compares two different scales.
    """
    kept = []
    for feature in features:
        tag = parse_git_tag(feature.get("properties", {}).get("git_tag"))
        if tag is not None and tag >= MIN_COMPARABLE_GIT_TAG:
            kept.append(feature)
    return kept


def slick_url(feature: dict) -> str | None:
    """The Cerulean UI link for a record, for provenance.

    Every claim of agreement or disagreement should be checkable against
    the imagery it came from, and this is the link that does it.
    """
    return feature.get("properties", {}).get("slick_url")
