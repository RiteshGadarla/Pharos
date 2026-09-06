# deck/

Phase P-1 output: the four figures the presentation is built around.
See PLAN.md section 19, "P-1: deck assets, do this first".

These scripts are **throwaway**. They exist to produce publishable
images with no infrastructure, and they must not turn into the real
pipeline. Nothing under `backend/` imports anything here, and nothing
here is on the demo path.

One difference from the plan's original intent, stated plainly because
it changes what these figures are worth: by the time this phase was
written, the real pipeline through P11 already existed. So rather than
standing up a second, parallel OpenDrift script whose output would only
resemble the product, these scripts read
`backend/data/precomputed/demo_bundle.json`, which is the output of a
genuine end to end run on the committed fixtures. The figures are
therefore pictures of the real system's real output, which is strictly
better than what P-1 was originally asking for. What they are not is
real Sentinel-1 data or real AIS: see the README's status section for
exactly what is and is not real in that bundle.

Run them from the repository root:

```
backend/.venv/bin/python deck/scripts/make_figures.py
```

Figures land in `deck/figures/`.

| Figure | File | What it shows |
|---|---|---|
| 1 | `01_slick_on_sar.png` | The detected slick over the SAR scene, with the wind gate verdict |
| 2 | `02_origin_field.png` | The origin probability field at three time slices. **The money image.** |
| 3 | `03_ais_over_field.png` | Every vessel over the field, culprit's dark gap dashed with its envelope |
| 4 | `04_scoring_table.txt` | The scoring table and the elimination log, as terminal output |
