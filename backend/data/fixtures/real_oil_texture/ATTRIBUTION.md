# Real oil-slick SAR texture, source and license

One patch (image + binary oil mask, 256x256, index 277 of the
dataset's `sentinel` split) from the **Deep-SAR SOS Oil Spill Detection
Dataset** by bitsandlayers, Kaggle:
<https://www.kaggle.com/datasets/bitsandlayers/sar-oil-spill-segmentation-dataset-sos>

Licensed **CC BY 4.0** (Attribution 4.0 International). Real Sentinel-1A
imagery over the Persian Gulf, not the Arabian Sea and not the
SLICKTRACE demo's own illustrative scene location.

- `sentinel_277_image.png` / `sentinel_277_label.png`

Chosen over the other candidates in this split for having its oil
region fully inside the 256x256 tile with a wide margin (real sea on
all sides), so compositing it into the synthetic background doesn't
leave a visible rectangular seam.

## Why this exists

`backend/scripts/make_fixture_scene.py` composites the real oil pixels
from `sentinel_277_image.png` (masked by `sentinel_277_label.png`) into
the synthetic Arabian Sea scene fixture, replacing a hand-drawn
Gaussian ellipse with real Sentinel-1 oil-slick backscatter texture and
speckle statistics. The scene's own geolocation, acquisition time and
surrounding sea remain synthetic; only the slick's texture pattern is
real. See `make_fixture_scene.py` and the README's data-provenance
section for the full disclosure this feeds into the UI and dossier.

The gated 5-class Krestenitis/M4D dataset the model's own training
taxonomy is closer to (PLAN.md section 4A item 4) requires a formal
institutional request and was not obtainable in the demo timeline; this
CC-BY dataset is the closest freely-available real substitute.
