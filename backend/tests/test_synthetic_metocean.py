"""The synthetic wind and currents have to behave like met-ocean data.
See scripts/synthetic_metocean.py.

Not a reanalysis, and these tests do not pretend it is one. They check
the physical properties each named component claims: the stated wind at
the pass point, a positively skewed speed distribution, spatial
correlation at a finite length, red-noise persistence in time, a veering
synoptic direction, a near-inertial period set by the local Coriolis
parameter, eddies with the right SST core, realistic magnitudes, and
determinism from the seed. The wind gate's zone fixture is checked to
stay inside its bands, since test_gate_wind.py depends on that.
"""

import datetime
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import synthetic_metocean as met  # noqa: E402

ACQ = datetime.datetime(2026, 1, 15, 2, 30)


@pytest.fixture(scope="module")
def wind():
    return met.make_wind_dataset({}, ACQ, seed=1)


@pytest.fixture(scope="module")
def currents():
    return met.make_currents_dataset({}, ACQ, seed=2)


def _speed(ds):
    return np.hypot(ds["u10"].values, ds["v10"].values)


def test_wind_schema_is_unchanged(wind):
    assert set(wind.data_vars) == {"u10", "v10", "t2m"}
    for name in wind.data_vars:
        assert wind[name].dims == ("time", "lat", "lon")
    step = np.diff(wind["time"].values) / np.timedelta64(1, "h")
    assert np.all(step == 1.0)


def test_the_stated_wind_is_the_wind_at_the_pass_point(wind):
    regime = met.WindRegime()
    point = wind.sel(lat=regime.pass_point[0], lon=regime.pass_point[1], time=np.datetime64(ACQ), method="nearest")
    assert float(np.hypot(point["u10"], point["v10"])) == pytest.approx(regime.pass_speed_ms, abs=1e-3)


def test_speed_distribution_is_positively_skewed_and_realistic(wind):
    s = _speed(wind)
    skew = float(((s - s.mean()) ** 3).mean() / s.std() ** 3)
    assert skew > 0.2
    assert 2.0 < float(s.mean()) < 12.0
    assert float(np.percentile(s, 99)) < 20.0


def test_wind_is_spatially_correlated_not_white(wind):
    s = _speed(wind)[40]
    anomaly = s - s.mean()
    neighbour = np.corrcoef(anomaly[:, :-1].ravel(), anomaly[:, 1:].ravel())[0, 1]
    far = np.corrcoef(anomaly[:, :-20].ravel(), anomaly[:, 20:].ravel())[0, 1]
    assert neighbour > 0.9, "adjacent 5 km cells should be strongly correlated"
    assert far < neighbour - 0.2, "correlation must fall off with distance"
    assert float(s.std()) > 0.2, "the field is not uniform in space"


def test_wind_persists_hour_to_hour(wind):
    s = _speed(wind)[:, 20, 20]
    lag1 = np.corrcoef(s[:-1], s[1:])[0, 1]
    assert lag1 > 0.7
    assert float(np.abs(np.diff(s)).max()) < 4.0, "hourly changes stay physical"


def test_synoptic_direction_veers_over_the_window(wind):
    regime = met.WindRegime()
    u, v = wind["u10"].values.mean(axis=(1, 2)), wind["v10"].values.mean(axis=(1, 2))
    bearing = np.degrees(np.arctan2(u, v)) % 360.0
    turned = (bearing[-12:].mean() - bearing[:12].mean() + 180.0) % 360.0 - 180.0
    expected = regime.veer_deg_per_day * (len(bearing) - 12) / 24.0
    assert turned > 0.3 * expected


def test_same_seed_same_wind_different_seed_different_wind():
    a = met.make_wind_dataset({"pass_speed_ms": 4.0}, ACQ, seed=5)
    b = met.make_wind_dataset({"pass_speed_ms": 4.0}, ACQ, seed=5)
    c = met.make_wind_dataset({"pass_speed_ms": 4.0}, ACQ, seed=6)
    assert np.array_equal(a["u10"].values, b["u10"].values)
    assert not np.array_equal(a["u10"].values, c["u10"].values)


def test_a_front_makes_a_sharp_step_across_its_line():
    regime = {
        "pass_speed_ms": 10.0, "pass_point": [17.0, 67.9],
        "front": {"delta_ms": 3.0, "width_km": 3.0, "normal_toward_deg": 90.0, "through": [17.0, 68.0], "speed_kmh": 0.0},
    }
    ds = met.make_wind_dataset(regime, ACQ, seed=3)
    at = ds.sel(time=np.datetime64(ACQ), lat=17.0, method="nearest")
    west = float(np.hypot(at["u10"], at["v10"]).sel(lon=67.9, method="nearest"))
    east = float(np.hypot(at["u10"], at["v10"]).sel(lon=68.1, method="nearest"))
    assert east - west > 1.5


def test_unknown_regime_parameters_are_refused():
    with pytest.raises(ValueError, match="unknown WindRegime"):
        met.make_wind_dataset({"pass_sped_ms": 5.0}, ACQ, seed=1)


def test_currents_schema_and_magnitudes(currents):
    assert set(currents.data_vars) == {"uo", "vo", "thetao"}
    speed = np.hypot(currents["uo"].values, currents["vo"].values)
    assert 0.03 < float(speed.mean()) < 0.5
    assert float(speed.max()) < 1.0
    sst = currents["thetao"].values
    assert 20.0 < float(sst.min()) and float(sst.max()) < 32.0


def test_near_inertial_oscillation_has_the_local_coriolis_period():
    """With every other component switched off, the current rotates
    clockwise at 2 pi / f. At 17 N that is about 41 hours."""
    quiet = {
        "mean_speed_ms": 0.0, "eddies": [], "submeso_amplitude_ms": 0.0, "m2_amplitude_ms": 0.0,
        "inertial_amplitude_ms": 0.1, "inertial_event_h": -60.0, "inertial_decay_h": 1e9,
    }
    ds = met.make_currents_dataset(quiet, ACQ, seed=4)
    point = ds.sel(lat=17.0, lon=68.0, method="nearest")
    u, v = point["uo"].values.astype(float), point["vo"].values.astype(float)
    angle = np.unwrap(np.arctan2(v, u))
    rad_per_hour = -np.polyfit(np.arange(len(angle)), angle, 1)[0]
    period_h = 2 * math.pi / rad_per_hour
    assert rad_per_hour > 0, "northern hemisphere inertial motion turns clockwise"
    assert period_h == pytest.approx(40.9, abs=0.6)


def test_cyclonic_eddies_have_cold_cores_and_turn_anticlockwise():
    regime = {
        "mean_speed_ms": 0.0, "submeso_amplitude_ms": 0.0, "m2_amplitude_ms": 0.0, "inertial_amplitude_ms": 0.0,
        "eddy_drift_km_per_day": 0.0, "sst_lat_gradient_c": 0.0, "sst_diurnal_c": 0.0,
        "eddies": [{"lat": 17.0, "lon": 68.0, "radius_km": 40.0, "vmax_ms": 0.2, "sense": "cyclonic"}],
    }
    ds = met.make_currents_dataset(regime, ACQ, seed=4).isel(time=0)
    centre = float(ds["thetao"].sel(lat=17.0, lon=68.0, method="nearest"))
    edge = float(ds["thetao"].sel(lat=17.0, lon=68.9, method="nearest"))
    assert centre < edge
    # East of an anticlockwise vortex the flow is northward.
    assert float(ds["vo"].sel(lat=17.0, lon=68.38, method="nearest")) > 0.1


def test_gate_zone_fixture_stays_inside_each_band():
    lats = np.round(np.arange(19.0, 20.01, 0.1), 2)
    lons = np.round(np.arange(72.0, 73.51, 0.1), 2)
    times = met.default_times(ACQ, 60, 6)
    zones = [(72.0, 1.5, 1.0, 2.1), (72.5, 3.0, 2.7, 3.3), (72.9, 6.0, 5.0, 7.0), (73.2, 13.0, 12.0, 14.5)]
    u, v = met.gate_zone_wind(zones, lats, lons, times, seed=26143)
    speed = np.hypot(u, v)
    for j, lon in enumerate(lons):
        _, _, lo, hi = [z for z in zones if lon >= z[0] - 1e-9][-1]
        assert speed[:, :, j].min() >= lo - 1e-4 and speed[:, :, j].max() <= hi + 1e-4
    assert speed.std(axis=0).mean() > 0.0, "the texture varies in time"
