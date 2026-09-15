"""Shared synthetic met-ocean generator: 10 m wind, 2 m air temperature,
surface currents and sea surface temperature.

Not a reanalysis. Nothing in here is ERA5, GFS, CMEMS or HYCOM output,
and no value in these files was ever measured. The fields are
illustrative stand-ins, generated so that the drift ensemble has
something with realistic structure to integrate through and so that the
console draws a field that behaves like weather rather than like a
formula. Each component below is one named physical process at a
plausible magnitude for the Eastern Arabian Sea, stated so it can be
argued with, and every random draw is seeded so two runs are identical.

The file schema is the one the rest of the system already reads and
does not change here: u10, v10, t2m on (time, lat, lon) for the wind
file, uo, vo, thetao on (time, lat, lon) for the currents file, CF
attributes, hourly steps. Only the contents are built differently.

Wind, in the order it is assembled:

  synoptic flow     The large-scale pressure-gradient wind: one mean
                    vector that veers (turns clockwise) and strengthens
                    or eases steadily over the window, with a broad
                    linear gradient across the domain. Synoptic systems
                    take days to cross, so this is the slowest part.
  mesoscale field   A spatially correlated random field at a correlation
                    length of tens of kilometres, advected with the mean
                    flow and slowly decorrelating in time. Built from
                    random Fourier modes drawn from a Gaussian spectrum,
                    which gives a Gaussian covariance at exactly the
                    configured length. This is what stops neighbouring
                    arrows being identical.
  front             Optional. A convergence line or gust front: a sharp
                    step in speed a few kilometres wide that moves across
                    the domain. Only cases that need one configure it.
  land-sea breeze   A diurnal wind vector that points onshore in the
                    local afternoon and offshore before dawn, rotating
                    clockwise through the day as it does in the northern
                    hemisphere. Its amplitude decays away from the Indian
                    west coast, so it is weak this far offshore and
                    strongest on the eastern edge of the domain.
  gustiness         Multiplicative red noise: temporally autocorrelated
                    (AR(1) at an hour or two) and spatially smoothed at
                    convective-cell scale. Hourly fields cannot resolve
                    individual gusts, so this is the sub-synoptic
                    variability that survives hourly averaging.
  speed distribution  Finally the speeds are given the shape of a
                    Weibull distribution, the standard model for surface
                    wind speed, which is positively skewed. Only the
                    shape is imposed, not a climatological spread (see
                    weibull_quantile_map), and the mapping is monotone,
                    so every spatial and temporal pattern above keeps its
                    ordering. The whole field is then scaled so the speed
                    at the configured pass point, at the acquisition
                    hour, is the scenario's stated wind.

Currents:

  background flow   The seasonal large-scale surface current.
  mesoscale eddies  Gaussian geostrophic eddies, cyclonic or
                    anticyclonic, tens of kilometres across, drifting
                    westward at a Rossby wave speed of a few kilometres a
                    day. Cyclonic eddies carry a cold core in SST and
                    anticyclonic ones a warm core.
  submesoscale      A weak non-divergent random field from a random
                    streamfunction, at a correlation length of about
                    twenty kilometres.
  M2 tide           The principal lunar semidiurnal tide, period
                    12.42 h, as a narrow ellipse. Small this far offshore.
  near-inertial     A clockwise rotating current at the local Coriolis
                    frequency, which at 17 N is a period of about 41 h
                    and varies with latitude across the domain. Its
                    amplitude decays after the wind event that excited
                    it, and its phase varies slowly in space.

Scene-scale speeds are kept inside realistic ranges: surface currents of
a few tenths of a metre per second, winds of a few to a dozen metres per
second.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field, fields

import numpy as np
import xarray as xr
from scipy import ndimage

KM_PER_DEG = 111.32
OMEGA_EARTH = 7.2921e-5  # rad/s
M2_PERIOD_H = 12.4206

# The Indian west coast near the domain, as a straight line through
# 17 N 73.3 E running north-northwest (bearing about 340). Good enough to
# set the direction and the decay of the land-sea breeze, which is all it
# is used for; onshore is perpendicular to it.
COAST_POINT = (17.0, 73.3)  # lat, lon
ONSHORE_BEARING_DEG = 70.0


def default_times(acquired_at: datetime.datetime, hours_before: int = 60, hours_after: int = 30) -> np.ndarray:
    t0 = np.datetime64(acquired_at.replace(tzinfo=None), "s")
    return t0 + np.arange(-hours_before, hours_after + 1) * np.timedelta64(1, "h")


def grid(domain: dict | None) -> tuple[np.ndarray, np.ndarray]:
    d = {"lat": [16.0, 18.0], "lon": [67.0, 69.0], "step_deg": 0.05, **(domain or {})}
    step = float(d["step_deg"])
    lats = np.round(np.arange(d["lat"][0], d["lat"][1] + step / 2, step), 3)
    lons = np.round(np.arange(d["lon"][0], d["lon"][1] + step / 2, step), 3)
    return lats, lons


def _from_dict(cls, values: dict | None):
    known = {f.name for f in fields(cls)}
    values = values or {}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(f"unknown {cls.__name__} parameter(s): {', '.join(unknown)}")
    return cls(**values)


def _km_coords(lats: np.ndarray, lons: np.ndarray, lat0: float, lon0: float) -> tuple[np.ndarray, np.ndarray]:
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    x = (lon_grid - lon0) * KM_PER_DEG * math.cos(math.radians(lat0))
    y = (lat_grid - lat0) * KM_PER_DEG
    return x, y


def _hours(times: np.ndarray, ref: np.datetime64) -> np.ndarray:
    return (times - ref) / np.timedelta64(1, "h")


def _solar_hour(times: np.ndarray, lon: float) -> np.ndarray:
    utc_hour = (times - times.astype("datetime64[D]")) / np.timedelta64(1, "h")
    return (utc_hour + lon / 15.0) % 24.0


def _bearing_unit(bearing_deg: float) -> tuple[float, float]:
    """(east, north) unit vector pointing TOWARDS a compass bearing."""
    b = math.radians(bearing_deg)
    return math.sin(b), math.cos(b)


def fourier_field(
    rng: np.random.Generator,
    x_km: np.ndarray,
    y_km: np.ndarray,
    t_h: np.ndarray,
    length_km: float,
    tau_h: float,
    advect_kmh: tuple[float, float] = (0.0, 0.0),
    n_modes: int = 96,
) -> np.ndarray:
    """A unit-variance Gaussian random field on (time, y, x).

    Random Fourier features: wavenumbers drawn from a Gaussian spectrum
    of width 1/length_km give a spatial covariance exp(-r^2 / 2L^2), and
    per-mode frequencies of width 1/tau_h give the same shape in time.
    The pattern is carried downstream at `advect_kmh`, which is Taylor's
    frozen turbulence hypothesis with decay. Continuous in space and
    time by construction, so hourly fields never jump.
    """
    out = np.zeros((len(t_h),) + x_km.shape, dtype=np.float64)
    kx = rng.normal(0.0, 1.0 / length_km, n_modes)
    ky = rng.normal(0.0, 1.0 / length_km, n_modes)
    omega = rng.normal(0.0, 1.0 / max(tau_h, 1e-6), n_modes)
    phase = rng.uniform(0.0, 2 * np.pi, n_modes)
    cx, cy = advect_kmh
    for k in range(n_modes):
        spatial = kx[k] * x_km + ky[k] * y_km  # (y, x)
        temporal = (omega[k] - kx[k] * cx - ky[k] * cy) * t_h + phase[k]  # (t,)
        out += np.cos(spatial[None, :, :] + temporal[:, None, None])
    return out * math.sqrt(2.0 / n_modes)


def red_noise_field(
    rng: np.random.Generator,
    shape: tuple[int, int, int],
    tau_h: float,
    length_cells: float,
) -> np.ndarray:
    """Unit-variance AR(1) noise in time, spatially smoothed each step.

    phi = exp(-dt / tau) with dt of one hour, so the lag-one
    autocorrelation is what an hourly gust record shows, rather than the
    independent draws of white noise.
    """
    n_t, n_y, n_x = shape
    phi = math.exp(-1.0 / max(tau_h, 1e-6))
    innovation = math.sqrt(1.0 - phi * phi)

    def smooth_white() -> np.ndarray:
        w = ndimage.gaussian_filter(rng.normal(size=(n_y, n_x)), sigma=length_cells, mode="reflect")
        return w / (w.std() or 1.0)

    out = np.empty(shape, dtype=np.float64)
    out[0] = smooth_white()
    for i in range(1, n_t):
        out[i] = phi * out[i - 1] + innovation * smooth_white()
    return out


def weibull_quantile_map(speed: np.ndarray, shape_k: float) -> np.ndarray:
    """Gives the speeds a Weibull-shaped distribution without changing
    their mean or their spread.

    A plain quantile map onto a climatological Weibull would be wrong
    for a three day window: a climatology spans every weather regime of
    a season, so its spread is several times what one synoptic situation
    produces, and mapping onto it would turn a steady monsoon day into
    wind swinging from calm to gale across a single afternoon. So only
    the SHAPE is taken from the Weibull: ranks are mapped onto
    standardised Weibull quantiles, then rescaled to this field's own
    mean and standard deviation. The result keeps every spatial and
    temporal ordering, keeps the physical amplitudes above, and carries
    the positive skew of a Weibull with this shape parameter. Ties are
    broken by position, which is deterministic.
    """
    flat = speed.ravel()
    order = np.argsort(flat, kind="stable")
    p = (np.arange(flat.size) + 0.5) / flat.size
    q = (-np.log1p(-p)) ** (1.0 / shape_k)
    q = (q - q.mean()) / q.std()
    mapped = np.empty_like(flat)
    mapped[order] = flat.mean() + flat.std() * q
    return np.maximum(mapped, 0.05).reshape(speed.shape)


def _nearest_index(values: np.ndarray, target: float) -> int:
    return int(np.abs(values - target).argmin())


# ---------------------------------------------------------------------------
# Wind


@dataclass
class WindRegime:
    """Parameters for one case's wind. Every field has a physical meaning,
    see the module docstring; defaults are a moderate January northeast
    monsoon day over the open Eastern Arabian Sea."""

    # The scenario's stated wind: speed at pass_point at the acquisition hour.
    pass_speed_ms: float = 6.2
    pass_point: list = field(default_factory=lambda: [17.05, 68.0])  # lat, lon
    # Synoptic mean direction the wind blows TOWARDS at acquisition,
    # degrees clockwise from north. 135 is a northwesterly.
    toward_deg: float = 135.0
    # Change in synoptic speed per day, as a fraction of the pass speed.
    trend_per_day: float = 0.08
    # Veer of the synoptic direction, degrees per day, clockwise positive.
    veer_deg_per_day: float = 10.0
    # Broad synoptic gradient, fraction of speed per 100 km (north, east).
    gradient_per_100km: list = field(default_factory=lambda: [0.10, -0.04])
    # Mesoscale random field.
    meso_length_km: float = 60.0
    meso_tau_h: float = 14.0
    meso_amplitude_frac: float = 0.10
    # Direction scatter of the mesoscale field, as a fraction of the
    # speed scatter applied to the cross-wind component. Light winds are
    # directionally unsteady, so low-wind cases raise this.
    meso_crosswind_ratio: float = 0.8
    # Land-sea breeze amplitude at the domain centre, m/s, and its decay
    # length away from the coast.
    breeze_amplitude_ms: float = 0.6
    breeze_decay_km: float = 350.0
    # Multiplicative gustiness.
    gust_intensity: float = 0.05
    gust_tau_h: float = 3.0
    gust_length_km: float = 14.0
    # Weibull shape. 2 is typical open ocean; lower is gustier and more
    # skewed, which is what light and variable winds look like.
    weibull_k: float = 2.1
    # Optional moving front: {delta_ms, width_km, normal_toward_deg,
    # through: [lat, lon] at acquisition, speed_kmh}. Positive delta is
    # stronger wind on the side the normal points to.
    front: dict | None = None
    # 2 m air temperature.
    t2m_base_c: float = 24.8
    t2m_lat_gradient_c: float = -0.9
    t2m_diurnal_c: float = 1.4
    t2m_noise_c: float = 0.25


def make_wind_dataset(
    regime: WindRegime | dict | None,
    acquired_at: datetime.datetime,
    seed: int,
    domain: dict | None = None,
    hours_before: int = 60,
    hours_after: int = 30,
) -> xr.Dataset:
    if not isinstance(regime, WindRegime):
        regime = _from_dict(WindRegime, regime)
    rng = np.random.default_rng(seed)

    lats, lons = grid(domain)
    times = default_times(acquired_at, hours_before, hours_after)
    lat0, lon0 = float(lats.mean()), float(lons.mean())
    x, y = _km_coords(lats, lons, lat0, lon0)
    t_h = _hours(times, np.datetime64(acquired_at.replace(tzinfo=None), "s"))
    n_t = len(times)
    cell_km = float(np.diff(lats).mean()) * KM_PER_DEG

    base = float(regime.pass_speed_ms)

    # Synoptic flow: speed trend and veer over time, broad gradient in space.
    syn_speed_t = base * (1.0 + regime.trend_per_day * t_h / 24.0)
    syn_speed_t = np.maximum(syn_speed_t, 0.3 * base)
    gn, ge = regime.gradient_per_100km
    spatial_gain = 1.0 + gn * y / 100.0 + ge * x / 100.0
    syn_dir = regime.toward_deg + regime.veer_deg_per_day * t_h / 24.0  # (t,)
    syn_e = np.sin(np.radians(syn_dir))[:, None, None]
    syn_n = np.cos(np.radians(syn_dir))[:, None, None]
    speed = syn_speed_t[:, None, None] * spatial_gain[None, :, :]
    u = speed * syn_e
    v = speed * syn_n

    # Mesoscale field, advected with the mean flow (km/h), along-wind and
    # cross-wind components drawn independently.
    # Mesoscale features are steered by the flow through the boundary
    # layer rather than carried at the full 10 m speed, hence 0.6.
    adv = (0.6 * base * math.sin(math.radians(regime.toward_deg)) * 3.6,
           0.6 * base * math.cos(math.radians(regime.toward_deg)) * 3.6)
    along = fourier_field(rng, x, y, t_h, regime.meso_length_km, regime.meso_tau_h, adv)
    cross = fourier_field(rng, x, y, t_h, regime.meso_length_km, regime.meso_tau_h, adv)
    amp = regime.meso_amplitude_frac * base
    u = u + amp * (along * syn_e + regime.meso_crosswind_ratio * cross * syn_n)
    v = v + amp * (along * syn_n - regime.meso_crosswind_ratio * cross * syn_e)

    # Front: a moving tanh step in speed along the local wind direction.
    if regime.front:
        fr = regime.front
        ne, nn = _bearing_unit(float(fr["normal_toward_deg"]))
        f_lat, f_lon = fr["through"]
        fx = (f_lon - lon0) * KM_PER_DEG * math.cos(math.radians(lat0))
        fy = (f_lat - lat0) * KM_PER_DEG
        dist = (x - fx) * ne + (y - fy) * nn  # km along the normal, (y, x)
        moved = float(fr.get("speed_kmh", 0.0)) * t_h  # (t,)
        step = 0.5 * (1.0 + np.tanh((dist[None, :, :] - moved[:, None, None]) / float(fr["width_km"])))
        mag = np.hypot(u, v) + 1e-9
        u = u + float(fr["delta_ms"]) * step * u / mag
        v = v + float(fr["delta_ms"]) * step * v / mag

    # Land-sea breeze: onshore at 15 local, rotating clockwise, decaying
    # with distance from the coast.
    cx = (COAST_POINT[1] - lon0) * KM_PER_DEG * math.cos(math.radians(lat0))
    cy = (COAST_POINT[0] - lat0) * KM_PER_DEG
    # Perpendicular distance to the coast line, positive offshore.
    oe, on = _bearing_unit(ONSHORE_BEARING_DEG)
    offshore_km = -((x - cx) * oe + (y - cy) * on)
    centre_offshore = float(-((0 - cx) * oe + (0 - cy) * on))
    breeze_amp = regime.breeze_amplitude_ms * np.exp(-(offshore_km - centre_offshore) / regime.breeze_decay_km)
    angle = np.radians(360.0 / 24.0 * (_solar_hour(times, lon0) - 15.0))  # clockwise rotation
    # Rotate the onshore unit vector clockwise by `angle`: a vector on
    # bearing b turned to b + a is cos(a) (sin b, cos b) + sin(a) (cos b,
    # -sin b). Along-shore excursion is half the cross-shore one, since
    # breeze ellipses are flattened against the coast.
    be = np.cos(angle) * oe + 0.5 * np.sin(angle) * on
    bn = np.cos(angle) * on - 0.5 * np.sin(angle) * oe
    u = u + breeze_amp[None, :, :] * be[:, None, None]
    v = v + breeze_amp[None, :, :] * bn[:, None, None]

    # Gustiness: multiplicative red noise on speed.
    gust = red_noise_field(rng, (n_t,) + x.shape, regime.gust_tau_h, regime.gust_length_km / cell_km)
    speed = np.hypot(u, v) * np.clip(1.0 + regime.gust_intensity * gust, 0.5, 1.8)
    direction = np.arctan2(u, v)  # radians, bearing towards

    # Weibull speed distribution, then pin the stated wind at the pass point.
    speed = weibull_quantile_map(speed, regime.weibull_k)
    ti = _nearest_index(t_h, 0.0)
    yi = _nearest_index(lats, float(regime.pass_point[0]))
    xi = _nearest_index(lons, float(regime.pass_point[1]))
    speed *= base / float(speed[ti, yi, xi])

    u10 = (speed * np.sin(direction)).astype(np.float32)
    v10 = (speed * np.cos(direction)).astype(np.float32)

    # 2 m air temperature: meridional gradient, diurnal cycle peaking mid
    # afternoon local, a little correlated noise.
    solar = _solar_hour(times, lon0)
    t2m_noise = fourier_field(rng, x, y, t_h, 80.0, 18.0, adv, n_modes=48)
    t2m = (
        regime.t2m_base_c
        + regime.t2m_lat_gradient_c * (y / KM_PER_DEG)[None, :, :]
        + regime.t2m_diurnal_c * np.sin(2 * np.pi * (solar - 9.0) / 24.0)[:, None, None]
        + regime.t2m_noise_c * t2m_noise
    ).astype(np.float32)

    skew = float(((speed - speed.mean()) ** 3).mean() / (speed.std() ** 3))
    return xr.Dataset(
        {
            "u10": (("time", "lat", "lon"), u10, {"standard_name": "x_wind", "units": "m s-1"}),
            "v10": (("time", "lat", "lon"), v10, {"standard_name": "y_wind", "units": "m s-1"}),
            # ERA5 name for 2 m air temperature, so a real CDS subset drops
            # in without a rename. Celsius here, and the units say so.
            "t2m": (("time", "lat", "lon"), t2m, {"standard_name": "air_temperature", "units": "degree_Celsius"}),
        },
        coords={
            "time": times.astype("datetime64[ns]"),
            "lat": ("lat", lats, {"standard_name": "latitude", "units": "degrees_north"}),
            "lon": ("lon", lons, {"standard_name": "longitude", "units": "degrees_east"}),
        },
        attrs={
            "source": "synthetic fixture, not real ERA5/GFS data",
            "note": "Illustrative values, not a reanalysis. See scripts/synthetic_metocean.py for each component.",
            "components": (
                "synoptic flow with veer and trend; mesoscale Gaussian random field; "
                + ("moving front; " if regime.front else "")
                + "diurnal land-sea breeze; multiplicative red-noise gustiness; Weibull speed distribution"
            ),
            "pass_speed_ms": base,
            "weibull_k": float(regime.weibull_k),
            "speed_mean_ms": round(float(speed.mean()), 3),
            "speed_skewness": round(skew, 3),
            "seed": int(seed),
            "Conventions": "CF-1.8",
        },
    )


# ---------------------------------------------------------------------------
# Currents


@dataclass
class CurrentRegime:
    """Parameters for one case's surface currents and SST. Defaults are a
    January open-ocean regime: weak southwestward drift, two eddies."""

    mean_toward_deg: float = 250.0
    mean_speed_ms: float = 0.14
    # Eddies: list of {lat, lon, radius_km, vmax_ms, sense}. sense is
    # "cyclonic" (anticlockwise, cold core) or "anticyclonic".
    eddies: list = field(default_factory=lambda: [
        {"lat": 17.0, "lon": 68.05, "radius_km": 45.0, "vmax_ms": 0.16, "sense": "anticyclonic"},
        {"lat": 16.45, "lon": 67.45, "radius_km": 35.0, "vmax_ms": 0.12, "sense": "cyclonic"},
    ])
    eddy_drift_km_per_day: float = 5.0  # westward
    submeso_amplitude_ms: float = 0.03
    submeso_length_km: float = 20.0
    submeso_tau_h: float = 20.0
    m2_amplitude_ms: float = 0.035
    m2_axis_deg: float = 55.0  # bearing of the major axis
    m2_minor_ratio: float = 0.25
    m2_phase_deg: float = 0.0
    inertial_amplitude_ms: float = 0.06
    # Hours relative to acquisition at which the exciting wind event
    # peaked, and the e-folding decay of the oscillation after it.
    inertial_event_h: float = -54.0
    inertial_decay_h: float = 72.0
    sst_base_c: float = 26.6
    sst_lat_gradient_c: float = -0.7
    sst_eddy_c: float = 0.5
    sst_diurnal_c: float = 0.3


def make_currents_dataset(
    regime: CurrentRegime | dict | None,
    acquired_at: datetime.datetime,
    seed: int,
    domain: dict | None = None,
    hours_before: int = 60,
    hours_after: int = 30,
) -> xr.Dataset:
    if not isinstance(regime, CurrentRegime):
        regime = _from_dict(CurrentRegime, regime)
    rng = np.random.default_rng(seed)

    lats, lons = grid(domain)
    times = default_times(acquired_at, hours_before, hours_after)
    lat0, lon0 = float(lats.mean()), float(lons.mean())
    x, y = _km_coords(lats, lons, lat0, lon0)
    t_h = _hours(times, np.datetime64(acquired_at.replace(tzinfo=None), "s"))
    n_t = len(times)
    shape3 = (n_t,) + x.shape

    me, mn = _bearing_unit(regime.mean_toward_deg)
    u = np.full(shape3, regime.mean_speed_ms * me)
    v = np.full(shape3, regime.mean_speed_ms * mn)
    sst_anom = np.zeros(shape3)

    # Mesoscale eddies: Gaussian geostrophic vortices drifting westward.
    for eddy in regime.eddies:
        radius = float(eddy["radius_km"])
        sense = 1.0 if eddy.get("sense", "cyclonic") == "cyclonic" else -1.0
        ex0 = (float(eddy["lon"]) - lon0) * KM_PER_DEG * math.cos(math.radians(lat0))
        ey0 = (float(eddy["lat"]) - lat0) * KM_PER_DEG
        ex = ex0 - regime.eddy_drift_km_per_day * t_h / 24.0  # (t,)
        dx = x[None, :, :] - ex[:, None, None]
        dy = y[None, :, :] - ey0
        r = np.hypot(dx, dy) + 1e-6
        v_theta = float(eddy["vmax_ms"]) * (r / radius) * np.exp(0.5 * (1.0 - (r / radius) ** 2))
        # Anticlockwise tangential unit vector is (-dy, dx) / r.
        u += sense * v_theta * (-dy / r)
        v += sense * v_theta * (dx / r)
        sst_anom += -sense * regime.sst_eddy_c * np.exp(-0.5 * (r / radius) ** 2)

    # Submesoscale: non-divergent, from a random streamfunction.
    psi = fourier_field(rng, x, y, t_h, regime.submeso_length_km, regime.submeso_tau_h)
    cell_km_y = float(np.diff(lats).mean()) * KM_PER_DEG
    cell_km_x = float(np.diff(lons).mean()) * KM_PER_DEG * math.cos(math.radians(lat0))
    dpsi_dy = np.gradient(psi, cell_km_y, axis=1)
    dpsi_dx = np.gradient(psi, cell_km_x, axis=2)
    norm = regime.submeso_length_km / math.sqrt(2.0)
    u += regime.submeso_amplitude_ms * (-dpsi_dy * norm)
    v += regime.submeso_amplitude_ms * (dpsi_dx * norm)

    # M2 tide: a narrow ellipse along the major axis, uniform over a
    # domain far smaller than the tidal wavelength.
    phase = 2 * np.pi * t_h / M2_PERIOD_H + math.radians(regime.m2_phase_deg)
    ae, an = _bearing_unit(regime.m2_axis_deg)
    major = regime.m2_amplitude_ms * np.cos(phase)
    minor = regime.m2_amplitude_ms * regime.m2_minor_ratio * np.sin(phase)
    u += (major * ae + minor * an)[:, None, None]
    v += (major * an - minor * ae)[:, None, None]

    # Near-inertial oscillation: clockwise at the local Coriolis frequency,
    # decaying after the event that excited it, phase varying in space.
    lat_grid = np.meshgrid(lons, lats)[1]
    f_local = 2 * OMEGA_EARTH * np.sin(np.radians(lat_grid)) * 3600.0  # rad/h
    since = t_h - regime.inertial_event_h
    envelope = np.where(since >= 0, np.exp(-since / regime.inertial_decay_h), np.exp(since / 6.0))
    phase_field = 2 * np.pi * fourier_field(rng, x, y, np.array([0.0]), 120.0, 1e6, n_modes=32)[0] * 0.15
    theta = f_local[None, :, :] * since[:, None, None] + phase_field[None, :, :]
    amp = regime.inertial_amplitude_ms * envelope[:, None, None]
    u += amp * np.cos(theta)
    v += -amp * np.sin(theta)

    # SST: meridional gradient, eddy cores, diurnal warming peaking early
    # afternoon local, a trace of the submesoscale field.
    solar = _solar_hour(times, lon0)
    thetao = (
        regime.sst_base_c
        + regime.sst_lat_gradient_c * (y / KM_PER_DEG)[None, :, :]
        + sst_anom
        + regime.sst_diurnal_c * np.sin(2 * np.pi * (solar - 8.0) / 24.0)[:, None, None]
        + 0.08 * psi
    )

    speed = np.hypot(u, v)
    return xr.Dataset(
        {
            "uo": (("time", "lat", "lon"), u.astype(np.float32), {
                "standard_name": "eastward_sea_water_velocity", "units": "m s-1"}),
            "vo": (("time", "lat", "lon"), v.astype(np.float32), {
                "standard_name": "northward_sea_water_velocity", "units": "m s-1"}),
            # CMEMS name, so a real Copernicus Marine subset drops in.
            "thetao": (("time", "lat", "lon"), thetao.astype(np.float32), {
                "standard_name": "sea_water_potential_temperature", "units": "degree_Celsius"}),
        },
        coords={
            "time": times.astype("datetime64[ns]"),
            "lat": ("lat", lats, {"standard_name": "latitude", "units": "degrees_north"}),
            "lon": ("lon", lons, {"standard_name": "longitude", "units": "degrees_east"}),
        },
        attrs={
            "source": "synthetic fixture, not real CMEMS/HYCOM data",
            "note": "Illustrative values, not a reanalysis. See scripts/synthetic_metocean.py for each component.",
            "time_variation": (
                "background flow; westward-drifting mesoscale eddies; submesoscale random streamfunction; "
                "M2 tide (12.42 h); near-inertial oscillation at the local Coriolis period "
                f"({2 * math.pi / (2 * OMEGA_EARTH * math.sin(math.radians(lat0))) / 3600.0:.1f} h at {lat0:.1f} N)"
            ),
            "speed_mean_ms": round(float(speed.mean()), 3),
            "speed_max_ms": round(float(speed.max()), 3),
            "seed": int(seed),
            "Conventions": "CF-1.8",
        },
    )


def gate_zone_wind(
    zones: list[tuple[float, float, float, float]],
    lats: np.ndarray,
    lons: np.ndarray,
    times: np.ndarray,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """The wind gate's unit fixture: speed zones by longitude, each with
    natural texture that never leaves its zone's band.

    zones are (lon_min, nominal_ms, band_lo, band_hi). Texture is a
    correlated random field in speed and a slowly wandering direction;
    both are clipped so every cell stays inside the band its zone is
    meant to exercise.
    """
    rng = np.random.default_rng(seed)
    x, y = _km_coords(lats, lons, float(lats.mean()), float(lons.mean()))
    t_h = _hours(times, times[0])
    speed_noise = fourier_field(rng, x, y, t_h, 40.0, 10.0, n_modes=64)
    dir_noise = fourier_field(rng, x, y, t_h, 80.0, 16.0, n_modes=64)
    u = np.zeros((len(times),) + x.shape, dtype=np.float32)
    v = np.zeros_like(u)
    for j, lon in enumerate(lons):
        zone = [z for z in zones if lon >= z[0] - 1e-9][-1]
        _, nominal, lo, hi = zone
        half = min(nominal - lo, hi - nominal)
        speed = np.clip(nominal + 0.6 * half * speed_noise[:, :, j], lo, hi)
        bearing = np.radians(90.0 + 18.0 * dir_noise[:, :, j])
        u[:, :, j] = speed * np.sin(bearing)
        v[:, :, j] = speed * np.cos(bearing)
    return u, v
