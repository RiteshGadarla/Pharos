import xarray as xr

from services.core.ais.synthetic import field_peak, field_time_bounds, generate_demo_scenario

FIELD_FIXTURE = "data/fixtures/synthetic_origin_field.nc"

AIS_CONFIG = {"dark_gap_min_minutes": 20, "max_plausible_speed_kn": 30}


def _field():
    return xr.open_dataset(FIELD_FIXTURE)


def test_field_peak_is_inside_the_grid_bounds():
    field_ds = _field()
    lat, lon, time = field_peak(field_ds)
    assert field_ds["lat"].values.min() <= lat <= field_ds["lat"].values.max()
    assert field_ds["lon"].values.min() <= lon <= field_ds["lon"].values.max()
    t_min, t_max = field_time_bounds(field_ds)
    assert t_min <= time <= t_max


def test_generate_demo_scenario_returns_four_tracks_with_expected_ids():
    field_ds = _field()
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143)
    assert len(tracks) == 4
    mmsis = {t.mmsi for t in tracks}
    assert mmsis == {"419000001", "419000002", "419000003", "419000004"}


def test_generate_demo_scenario_is_deterministic():
    field_ds = _field()
    tracks_a = generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143)
    tracks_b = generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143)
    for a, b in zip(tracks_a, tracks_b):
        assert [p.ts for p in a.points] == [p.ts for p in b.points]
        assert [p.lat for p in a.points] == [p.lat for p in b.points]


def test_culprit_has_a_dark_gap():
    field_ds = _field()
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143)
    culprit = next(t for t in tracks if t.mmsi == "419000001")
    assert len(culprit.dark_gaps) >= 1


def test_dark_far_hard_negative_has_a_dark_gap_far_from_the_field():
    field_ds = _field()
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143)
    dark_far = next(t for t in tracks if t.mmsi == "419000003")
    culprit = next(t for t in tracks if t.mmsi == "419000001")
    assert len(dark_far.dark_gaps) >= 1
    # far from the culprit's gap location
    far_entry = dark_far.dark_gaps[0].entry_point
    culprit_entry = culprit.dark_gaps[0].entry_point
    dist = ((far_entry[0] - culprit_entry[0]) ** 2 + (far_entry[1] - culprit_entry[1]) ** 2) ** 0.5
    assert dist > 0.1


def test_constant_speed_hard_negative_has_no_dark_gap():
    field_ds = _field()
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143)
    constant_speed = next(t for t in tracks if t.mmsi == "419000004")
    assert constant_speed.dark_gaps == []


def test_wrong_time_hard_negative_is_outside_the_field_window():
    field_ds = _field()
    t_min, _ = field_time_bounds(field_ds)
    tracks = generate_demo_scenario(field_ds, AIS_CONFIG, seed=26143)
    wrong_time = next(t for t in tracks if t.mmsi == "419000002")
    assert all(p.ts < t_min for p in wrong_time.points)
