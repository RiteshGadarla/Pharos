#!/usr/bin/env bash
# Fetches external datasets into data/raw/ and writes data/raw/MANIFEST.json.
# See PLAN.md section 4A for the full source list, credentials and the
# --offline verification contract this script must satisfy.
#
# Not yet implemented. Implementing it is blocked on the human account
# registrations in PLAN.md section 4A and on picking the hero incident in
# config/demo.yaml. This file records exactly what it has to do, so that
# whoever picks it up is not reverse engineering the requirement from the
# plan.
#
# WHAT IT MUST FETCH (PLAN.md section 4A):
#
#   Zenodo Sentinel-1 SAR oil spill dataset, Parts I to III
#       DOIs 10.5281/zenodo.8346860, 8253899, 13761290. No auth.
#       The PRIMARY evaluation corpus, and named in the problem statement.
#       Sigma0 in decibels, 2048x2048x2 TIFF, binary masks with foreground
#       1 and background 0. Part I alone is roughly 40.7 GB, so this is the
#       longest lead item in the whole project: start it first.
#       Record the published MD5 per file in the manifest alongside our
#       own SHA-256.
#
#   Five class SAR oil spill dataset (Krestenitis style)
#       By request, cannot be scripted blind. The SECONDARY corpus.
#       Classes: sea surface, oil spill, look alike, ship, land.
#       Required for the wind gate false positive measurement and for the
#       ships class section 11 depends on. The Zenodo set is binary and
#       can provide neither.
#
#   Segmentation model, sahilvishwa2108/oil-spill-deeplab
#       No auth. Already handled by `make fetch-model`, which caches to
#       data/models/ and loads from disk so the demo works offline.
#
#   Sentinel-1 GRD, via asf_search, Earthdata login
#       ASF, not CDSE: CDSE serves original GRD products older than a year
#       with deferred availability, and the hero scene will be older than
#       a year. Roughly 1 GB per scene.
#
#   Ocean currents, CMEMS Global Ocean Physics via `copernicusmarine subset`
#       Fallback with no account: HYCOM over OPeNDAP via xarray.
#
#   Wind, ERA5 single levels 10 m U and V, via cdsapi
#       ERA5 requests QUEUE and can take hours. Submit on day one.
#       Fallback with no auth: NOAA GFS from the public S3 bucket, but
#       verify archive coverage for the incident date before relying on it.
#
#   AIS reference statistics, MarineCadastre daily zips
#       No auth. The format authority the problem statement names. Used
#       only to fit lane, speed, type and dropout distributions and to fix
#       the schema. US waters, so NOT the demo data.
#
#   Optical, Sentinel-2 L1C or Sentinel-3 OLCI
#       Only a coincidence search plus one scene, for section 7.
#
#   Coastline and land mask, Natural Earth or GSHHG
#       No auth. Tile skipping, and distance to nearest land for the
#       MARPOL layer in section 13. Replaces the generalised placeholder
#       in data/fixtures/coastline.geojson.
#
#   Offshore infrastructure, a public offshore platform point layer
#       No auth. Section 14. Replaces the placeholder in
#       data/fixtures/offshore_infrastructure.geojson.
#
#   Drifter trajectories, NOAA AOML Global Drifter Program
#       No auth. Section 17.3, the drift engine's physical validation.
#
# Cerulean slick records are deliberately NOT fetched here. They are
# validation only (PLAN.md non-negotiable 5) and are pulled and cached by
# backend/validation/cerulean_client.py into data/cerulean/, which nothing
# under services/ may import.
#
# CONTRACT THIS SCRIPT MUST SATISFY:
#   - Writes data/raw/MANIFEST.json recording, per file, the source URL or
#     dataset id, the retrieval timestamp, the byte size and the SHA-256.
#     The dossier provenance page reads from this manifest, so fetching is
#     part of the evidence chain rather than a setup chore.
#   - Idempotent: re-running skips files already present with a matching hash.
#   - Resumable: Sentinel-1 scenes are large and hackathon wifi is not.
#   - --offline flag verifies the manifest and exits without touching the
#     network. This is the pre-demo check.
#   - Credentials only from the environment variables in .env.example.
#     Never hardcoded, never committed.
set -euo pipefail

if [ "${1:-}" = "--offline" ]; then
  echo "fetch_data.sh --offline: not yet implemented." >&2
  echo "The offline demo path does not depend on this script: it runs from the" >&2
  echo "committed fixtures in data/fixtures/ and the precomputed bundle in" >&2
  echo "data/precomputed/. See README.md, 'Running the demo'." >&2
  exit 1
fi

echo "fetch_data.sh: not yet implemented, see the comment block above and PLAN.md section 4A" >&2
exit 1
