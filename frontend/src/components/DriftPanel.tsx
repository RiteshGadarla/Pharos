import Accordion from "./Accordion";
import Stat from "./Stat";
import type { DemoBundle } from "../types";
import type { TimelineFrame } from "../lib/timeline";
import { hoursFromAcquisition } from "../lib/timeline";
import { fieldSpanHours } from "../lib/stages";

interface Props {
  bundle: DemoBundle;
  frame: TimelineFrame;
  spreadKm: number;
}

// Stage 2's side panel: the ensemble that produced whichever field is
// currently on screen, and what that field is allowed to be used for.
//
// The two fields are shown as two cards rather than one, and the live
// one is marked, because the single most important thing the room has
// to take away from this stage is that they are different claims.
// Backward is evidence: it is what the ranking in stage 3 integrates
// over. Forward is a forecast: it informs a response and never touches
// the ranking. Drawing them in one colour with one caption would blur
// exactly the distinction the pipeline is careful about internally.
//
// The number that leads is the spread, because the colour ramp is
// normalised per timestep and the eye cannot judge how much certainty
// was lost as the field runs back. The spread says it.
export default function DriftPanel({ bundle, frame, spreadKm }: Props) {
  const origin = bundle.origin_field;
  const forecast = bundle.forecast_field;
  const offsetH = hoursFromAcquisition(frame, bundle.scene.acquired_at);
  const backwardHours = fieldSpanHours(origin);
  const showingBackward = frame.direction === "backward";

  return (
    <>
      <section className="panel-hero">
        <span className={`panel-kicker live ${showingBackward ? "backward" : "forward"}`}>
          <span className={`swatch ${showingBackward ? "backward" : "forward"}`} aria-hidden="true" />
          {showingBackward ? "Origin field on screen" : "Forecast on screen"}
        </span>
        <div className="stat-row">
          <Stat
            size="hero"
            label="Spread now"
            value={spreadKm.toFixed(1)}
            unit="km"
            tone={showingBackward ? "oil" : "forecast"}
            title="Mass-weighted spread of the field at this instant. It grows as the hindcast runs backwards and knowledge runs out."
          />
          <Stat
            size="lg"
            label="Cursor"
            value={`${offsetH >= 0 ? "+" : ""}${offsetH.toFixed(1)}`}
            unit="h"
            sub="from acquisition"
          />
        </div>
        <p className="panel-hero-sub">
          {showingBackward
            ? "Evidence. The only field the ranking in stage 3 reads."
            : "A forecast for response planning. Never an input to the ranking."}
        </p>
      </section>

      <section className="panel-section">
        <div className="field-cards">
          <div className={`field-card backward${showingBackward ? " live" : ""}`}>
            <span className="field-card-name">
              <span className="swatch backward" aria-hidden="true" />
              Backward
            </span>
            <span className="field-card-value mono">
              {backwardHours.toFixed(0)}
              <span className="stat-unit">h</span>
            </span>
            <span className="field-card-sub mono">
              {origin.n_members} members
            </span>
          </div>
          <div className={`field-card forward${!showingBackward ? " live" : ""}${forecast ? "" : " empty"}`}>
            <span className="field-card-name">
              <span className="swatch forward" aria-hidden="true" />
              Forward
            </span>
            {forecast ? (
              <>
                <span className="field-card-value mono">
                  {fieldSpanHours(forecast).toFixed(0)}
                  <span className="stat-unit">h</span>
                </span>
                <span className="field-card-sub mono">{forecast.n_members} members</span>
              </>
            ) : (
              <span className="field-card-sub">not in this bundle</span>
            )}
          </div>
        </div>
      </section>

      <div className="panel-accordions">
        <Accordion title="Backward: origin field" swatch="backward" live={showingBackward}>
          <dl className="facts">
            <dt>Kernel</dt>
            <dd className="mono">{origin.kernel ?? "openoil"}</dd>
            <dt>Members</dt>
            <dd className="mono">{origin.n_members}</dd>
            <dt>Horizon</dt>
            <dd className="mono">{backwardHours.toFixed(0)} h back</dd>
            <dt>Seed</dt>
            <dd className="mono">{origin.seed}</dd>
            {/* Only while this field is the one on screen. The spread is
                measured from whichever slice is drawn, so showing it here
                during a forecast frame would label the forecast's spread
                as the origin field's. */}
            {showingBackward && (
              <>
                <dt>Spread now</dt>
                <dd className="mono">{spreadKm.toFixed(1)} km</dd>
              </>
            )}
          </dl>
          <p className="prose">
            A probability over latitude, longitude and time that sums to 1. It is never collapsed to a point, and it is
            the only field the vessel ranking in stage 3 reads.
          </p>
        </Accordion>

        <Accordion title="Forward: forecast" swatch="forward" live={Boolean(forecast) && !showingBackward}>
          {forecast ? (
            <>
              <dl className="facts">
                <dt>Kernel</dt>
                <dd className="mono">{forecast.kernel ?? "openoil"}</dd>
                <dt>Members</dt>
                <dd className="mono">{forecast.n_members}</dd>
                <dt>Horizon</dt>
                <dd className="mono">{fieldSpanHours(forecast).toFixed(0)} h ahead</dd>
                {!showingBackward && (
                  <>
                    <dt>Spread now</dt>
                    <dd className="mono">{spreadKm.toFixed(1)} km</dd>
                  </>
                )}
              </dl>
              {forecast.horizon_truncated && (
                <p className="prose warn">
                  Short of the {forecast.requested_horizon_hours?.toFixed(0)} hours requested: the forcing data ends
                  before the horizon does.
                </p>
              )}
              <p className="prose">
                Same kernel and the same seed particles, run with a positive time step. This is a response planning
                product and is never an input to the ranking.
              </p>
            </>
          ) : (
            <p className="prose muted">No forecast field in this bundle. Run make seed-demo to build one.</p>
          )}
        </Accordion>

        {bundle.origin_window && (
          <Accordion
            title={`Origin window: ${bundle.origin_window.earliest_hours_before.toFixed(0)} to ${bundle.origin_window.latest_hours_before.toFixed(0)} h`}
            swatch="window"
          >
            <dl className="facts">
              <dt>Age band</dt>
              <dd className="mono">{bundle.origin_window.age_band}</dd>
              <dt>Discharge</dt>
              <dd className="mono">
                {bundle.origin_window.earliest_hours_before.toFixed(0)} to{" "}
                {bundle.origin_window.latest_hours_before.toFixed(0)} h before
              </dd>
            </dl>
            {/* The only evidence in the case about WHEN, and until this
                existed it never reached the ranking. */}
            <p className="prose">{bundle.origin_window.statement}</p>
          </Accordion>
        )}

        <Accordion title="Provenance" swatch="provenance">
          <dl className="facts">
            <dt>Forcing</dt>
            <dd className="mono wrap">{origin.forcing_source ?? "unspecified"}</dd>
            <dt>At cursor</dt>
            <dd className="mono">
              {offsetH >= 0 ? "+" : ""}
              {offsetH.toFixed(1)} h
            </dd>
          </dl>
          {/* PLAN.md section 16A: every animated layer names its source. */}
          <p className="prose muted">
            Both fields come from the same precomputed bundle. Nothing on screen is interpolated between them: the
            origin field owns every instant up to acquisition, the forecast owns every instant after it.
          </p>
        </Accordion>
      </div>
    </>
  );
}
