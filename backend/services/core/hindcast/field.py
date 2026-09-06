"""Converts ensemble particle samples into a normalised origin probability
field P(lat, lon, t). See PLAN.md section 9.3.

Never collapses over time: the joint (lat, lon, t) distribution is what
lets the AIS scoring reward a vessel for being in the right place at
the right time (PLAN.md non-negotiable 1 and section 10's F1). Smoothing
is spatial only, per time slice, so no probability mass leaks across
time bins.
"""

from __future__ import annotations

import uuid

import numpy as np
import xarray as xr
from scipy import ndimage

from services.core.schemas import OriginField


def _samples_from_array(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One DriftKernel member's (n_particles, n_steps, 3) output, with
    NaN rows dropped. A NaN position is how a kernel reports a particle
    that stranded or otherwise stopped being a sample of where the
    slick could have been."""
    from services.core.drift.kernel import samples_to_arrays

    return samples_to_arrays(samples)


def _samples_from_dataset(result: xr.Dataset) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One OpenDrift result Dataset, dims (trajectory, time). Kept
    because OpenDrift's own Dataset is the natural thing to hand-build
    in a test, and because a kernel is free to return one."""
    lats: list[np.ndarray] = []
    lons: list[np.ndarray] = []
    times: list[np.ndarray] = []

    lat = result["lat"].values  # (trajectory, time)
    lon = result["lon"].values
    status = result["status"].values
    time = result["time"].values  # (time,)

    for ti in range(lat.shape[1]):
        active = status[:, ti] == 0  # OpenDrift: 0 is the active/moving status
        if not active.any():
            continue
        lats.append(lat[active, ti])
        lons.append(lon[active, ti])
        times.append(np.full(int(active.sum()), time[ti]))

    if not lats:
        return np.array([]), np.array([]), np.array([], dtype="datetime64[s]")
    return np.concatenate(lats), np.concatenate(lons), np.concatenate(times)


def collect_samples(member_results: list) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flattens every active particle at every timestep, across all
    ensemble members, into parallel (lat, lon, time) arrays.

    Accepts either a DriftKernel's (n_particles, n_steps, 3) sample
    array or an OpenDrift result Dataset per member, so the field
    builder does not care which kernel produced the ensemble."""
    lats: list[np.ndarray] = []
    lons: list[np.ndarray] = []
    times: list[np.ndarray] = []

    for result in member_results:
        if isinstance(result, np.ndarray):
            lat, lon, time = _samples_from_array(result)
        else:
            lat, lon, time = _samples_from_dataset(result)
        if len(lat) == 0:
            continue
        lats.append(lat)
        lons.append(lon)
        times.append(time.astype("datetime64[ns]"))

    if not lats:
        raise ValueError("no active particle samples across any ensemble member")

    return np.concatenate(lats), np.concatenate(lons), np.concatenate(times)


def member_horizon_hours(member_results: list) -> float:
    """The horizon the run covered, in hours: the median span of a single
    ensemble member.

    Per member, not across the whole sample set. Members are seeded with
    jittered start times, so the span of all samples pooled together is
    the horizon plus the jitter spread, and reporting that as the horizon
    would inflate a 24 hour forecast to 24.1. And not the binned time
    axis either, which holds bin centres and can run a step past the last
    sample depending on where the kernel's steps fall.
    """
    spans: list[float] = []
    for result in member_results:
        if isinstance(result, np.ndarray):
            _, _, times = _samples_from_array(result)
        else:
            _, _, times = _samples_from_dataset(result)
        if len(times) < 2:
            continue
        spans.append(float((times.max() - times.min()) / np.timedelta64(1, "h")))
    if not spans:
        return 0.0
    return float(np.median(spans))


def build_origin_field(
    member_results: list,
    grid_resolution_deg: float,
    time_step_minutes: float,
    gaussian_bandwidth_deg: float,
    seed: int,
    kernel: str = "openoil",
    forcing_source: str = "unspecified",
    direction: str = "backward",
) -> xr.Dataset:
    """Bins ensemble samples onto a (time, lat, lon) grid, Gaussian-smooths
    spatially within each time slice, and normalises so the field sums to
    1 over the whole space-time volume.

    The binning is direction agnostic: it is the same operation on a
    backward ensemble and a forward one. `direction` only records which
    was run, so nothing downstream can read a forecast as an origin.
    Forward callers should go through forecast/forward.py rather than
    passing direction="forward" here."""
    if direction not in ("backward", "forward"):
        raise ValueError(f"direction must be 'backward' or 'forward', got {direction!r}")
    lats, lons, times = collect_samples(member_results)
    n_members = len(member_results)

    time_step = np.timedelta64(int(round(time_step_minutes)), "m")
    t_min, t_max = times.min(), times.max()
    time_bins = np.arange(t_min, t_max + time_step, time_step)
    if len(time_bins) < 2:
        time_bins = np.array([t_min, t_min + time_step])

    pad = 3 * gaussian_bandwidth_deg
    lat_bins = np.arange(lats.min() - pad, lats.max() + pad + grid_resolution_deg, grid_resolution_deg)
    lon_bins = np.arange(lons.min() - pad, lons.max() + pad + grid_resolution_deg, grid_resolution_deg)

    n_t = len(time_bins) - 1
    field = np.zeros((n_t, len(lat_bins) - 1, len(lon_bins) - 1), dtype=np.float64)

    # np.digitize can't compare datetime64 directly, bin in seconds-since-t_min instead
    times_s = (times - t_min) / np.timedelta64(1, "s")
    time_bins_s = (time_bins - t_min) / np.timedelta64(1, "s")
    time_idx = np.clip(np.digitize(times_s, time_bins_s) - 1, 0, n_t - 1)
    sigma_px = gaussian_bandwidth_deg / grid_resolution_deg

    for ti in range(n_t):
        mask = time_idx == ti
        if not mask.any():
            continue
        hist, _, _ = np.histogram2d(lats[mask], lons[mask], bins=[lat_bins, lon_bins])
        field[ti] = ndimage.gaussian_filter(hist, sigma=sigma_px)

    total = field.sum()
    if total > 0:
        field = field / total

    lat_centers = (lat_bins[:-1] + lat_bins[1:]) / 2
    lon_centers = (lon_bins[:-1] + lon_bins[1:]) / 2
    time_centers = time_bins[:-1] + time_step / 2

    return xr.Dataset(
        {"probability": (("time", "lat", "lon"), field)},
        coords={"time": time_centers, "lat": lat_centers, "lon": lon_centers},
        attrs={
            "seed": int(seed),
            "n_members": int(n_members),
            "kernel": str(kernel),
            "forcing_source": str(forcing_source),
            "direction": str(direction),
            # The horizon the run covered. Not the span of this grid's
            # time coordinate: that holds bin centres and can run a step
            # past the last sample, which reports a 48 hour hindcast as
            # 49. Captions and dossier text must quote this.
            "horizon_hours": member_horizon_hours(member_results),
            "description": (
                "Backward drift origin probability field. Sums to 1 over "
                "the whole space-time volume. Never collapse over time "
                "before scoring, see PLAN.md non-negotiable 1."
                if direction == "backward"
                else (
                    "Forward drift forecast field: where the slick goes "
                    "next. Sums to 1 over the whole space-time volume. "
                    "Never an input to attribution, see PLAN.md section 15."
                )
            ),
        },
    )


def write_origin_field(field_ds: xr.Dataset, detection_id: str, out_path: str) -> OriginField:
    """Writes the field to NetCDF and returns the OriginField record."""
    field_ds.to_netcdf(out_path)
    time_values = field_ds["time"].values
    return OriginField(
        field_id=str(uuid.uuid4()),
        detection_id=detection_id,
        path=out_path,
        t_min=np.datetime_as_string(time_values.min(), unit="s"),
        t_max=np.datetime_as_string(time_values.max(), unit="s"),
        n_members=int(field_ds.attrs["n_members"]),
        seed=int(field_ds.attrs["seed"]),
        kernel=str(field_ds.attrs.get("kernel", "openoil")),
        direction=str(field_ds.attrs.get("direction", "backward")),
    )
