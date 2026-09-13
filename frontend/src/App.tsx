import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { loadDemoBundle } from "./api";
import Navbar, { type RightTab } from "./components/Navbar";
import ForcingReadout from "./components/ForcingReadout";
import LayerToggles from "./components/LayerToggles";
import MapLegend from "./components/MapLegend";
import MapView, { type LayerToggles as Toggles } from "./components/MapView";
import SuspectsPanel from "./components/SuspectsPanel";
import EliminationLog from "./components/EliminationLog";
import LedgerTables from "./components/LedgerTables";
import DriftPanel from "./components/DriftPanel";
import ScenePanel from "./components/ScenePanel";
import StageRail from "./components/StageRail";
import TimeScrubber from "./components/TimeScrubber";
import CaseBuildPanel from "./components/CaseBuildPanel";
import VerdictCard from "./components/VerdictCard";
import VesselFocusCard from "./components/VesselFocusCard";
import ViewPresets from "./components/ViewPresets";
import { useViewPresets, type ViewKey } from "./lib/views";
import { STAGES, stageAt } from "./lib/stages";
import { buildTimeline, clampToRange, frameField, nearestFrame } from "./lib/timeline";
import type { DemoBundle } from "./types";
import { isDarkAt } from "./lib/geo";
import { fieldSliceSpreadKm } from "./lib/fieldRaster";
import "./App.css";

export default function App() {
  const [bundle, setBundle] = useState<DemoBundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDemoBundle()
      .then(setBundle)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <div className="fatal-error">
        <p>Could not load the demo bundle: {error}</p>
        <p>Run the core service (make run-core) or make seed-demo, then reload.</p>
      </div>
    );
  }

  if (!bundle) {
    return <div className="loading">Loading demo bundle...</div>;
  }

  return <Console bundle={bundle} />;
}

// How long one full sweep of the visible time window should take,
// whatever that window works out to in timesteps. Pinned to a duration
// rather than a per-step delay: the backward field has 98 steps on a 48
// hour horizon, and a fixed 400 ms step made that a 39 second wait.
const SWEEP_DURATION_MS = 16000;
const MIN_STEP_MS = 60;

// Split from App so every hook below can assume a loaded bundle. Putting
// them in App would put hook calls after the loading and error returns.
function Console({ bundle }: { bundle: DemoBundle }) {
  const timeline = useMemo(() => buildTimeline(bundle), [bundle]);

  const [stageIndex, setStageIndex] = useState(0);
  const stage = stageAt(stageIndex);

  // Opens at the acquisition instant, because that is where
  // the evidence starts: this is the slick, this is when we saw it.
  // Play then runs backwards from there (PLAN.md section 16, "Signature
  // element"), so the probability cloud blooms as the hindcast runs out
  // of knowledge rather than collapsing into it.
  const acquisitionFrame = useMemo(
    () => nearestFrame(timeline, new Date(bundle.scene.acquired_at).getTime()),
    [timeline, bundle.scene.acquired_at],
  );
  const [frameIndex, setFrameIndex] = useState(acquisitionFrame);
  const [playing, setPlaying] = useState(false);
  const [toggles, setToggles] = useState<Toggles>(STAGES[0].layers);
  const [hoveredMmsi, setHoveredMmsi] = useState<string | null>(null);
  const [selectedMmsi, setSelectedMmsi] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<RightTab>("case");
  const [viewKey, setViewKey] = useState<ViewKey>(STAGES[0].view);
  const intervalRef = useRef<number | null>(null);

  const presets = useViewPresets(bundle);
  const viewBounds = useMemo(
    () => (presets.find((p) => p.key === viewKey) ?? presets[1]).bounds,
    [presets, viewKey],
  );

  // What the scrubber may reach in this stage. Stage 1 is a single
  // instant, so it collapses to the acquisition frame.
  const range: [number, number] = useMemo(() => {
    if (stage.timeline === "none") return [acquisitionFrame, acquisitionFrame];
    if (stage.timeline === "backward") return timeline.backwardRange;
    return [0, timeline.frames.length - 1];
  }, [stage.timeline, timeline, acquisitionFrame]);

  // Entering a stage resets the camera, the layers and the cursor to
  // that stage's own starting point. The layers stay live afterwards, so
  // any of them can still be pulled forward by hand within the stage.
  const goToStage = useCallback(
    (ordinal: number) => {
      const next = stageAt(ordinal - 1);
      setStageIndex(next.ordinal - 1);
      setToggles(next.layers);
      setViewKey(next.view);
      setPlaying(false);
      setFrameIndex((i) =>
        clampToRange(
          // Each stage opens at the acquisition instant when it can
          // reach it, which is the one moment every stage shares.
          next.timeline === "none" ? acquisitionFrame : i,
          next.timeline === "backward" ? timeline.backwardRange : [0, timeline.frames.length - 1],
        ),
      );
    },
    [timeline, acquisitionFrame],
  );

  // Left and right step through the stages, space plays and pauses.
  // PLAN.md section 16A: every beat has to be keyboard reachable, since
  // during questions a presenter needs a specific stage instantly.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowRight") goToStage(stage.ordinal + 1);
      else if (e.key === "ArrowLeft") goToStage(stage.ordinal - 1);
      else if (e.key >= "1" && e.key <= String(STAGES.length)) goToStage(Number(e.key));
      else if (e.key === " ") {
        e.preventDefault();
        if (stage.timeline !== "none") setPlaying((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goToStage, stage.ordinal, stage.timeline]);

  useEffect(() => {
    if (!playing) return;
    const steps = range[1] - range[0] + 1;
    if (steps <= 1) return;
    const stepMs = Math.max(MIN_STEP_MS, SWEEP_DURATION_MS / steps);
    intervalRef.current = window.setInterval(() => {
      // Backwards, wrapping round to the top of the stage's window.
      setFrameIndex((i) => (i <= range[0] ? range[1] : i - 1));
    }, stepMs);
    return () => {
      if (intervalRef.current) window.clearInterval(intervalRef.current);
    };
  }, [playing, range]);

  const frame = timeline.frames[clampToRange(frameIndex, range)];
  const activeField = frameField(bundle, frame);
  const darkNow = bundle.vessels.filter((v) => isDarkAt(v, frame.ms));
  const spreadKm = useMemo(
    () => (activeField ? fieldSliceSpreadKm(activeField, frame.index) : 0),
    [activeField, frame.index],
  );

  // The selected vessel's best opportunity to be the source, handed to
  // the scrubber so the caret can sit against the origin-window band.
  // Only on stage 3: on the earlier stages there is no ranking yet and
  // a marker would be answering a question nobody has asked.
  const opportunity = useMemo(() => {
    if (stage.key !== "attribution" || !selectedMmsi) return null;
    const t = bundle.vessel_timing?.[selectedMmsi];
    if (!t || t.lag_hours === null) return null;
    return {
      mmsi: selectedMmsi,
      lagHours: t.lag_hours,
      state: t.within_band ? "inside" : t.within_uncertainty ? "margin" : "outside",
    };
  }, [bundle, selectedMmsi, stage.key]);

  const focusVessel = (mmsi: string) => {
    setSelectedMmsi(mmsi);
    setRightTab("suspects");
  };

  return (
    <div className="app-shell">
      <Navbar
        stage={stage.ordinal}
        rightTab={rightTab}
        onNavigate={(ordinal, tab) => {
          goToStage(ordinal);
          if (tab) setRightTab(tab);
        }}
      />
      <StageRail bundle={bundle} stage={stage} onSelect={goToStage} />
      <div className="app-body">
        <div className="map-pane">
          <MapView
            bundle={bundle}
            timeMs={frame.ms}
            frame={frame}
            toggles={toggles}
            viewBounds={viewBounds}
            hoveredMmsi={hoveredMmsi}
            selectedMmsi={selectedMmsi}
            onHoverVessel={setHoveredMmsi}
            onSelectVessel={setSelectedMmsi}
          />
          <LayerToggles toggles={toggles} onChange={setToggles} bundle={bundle} />
          <ViewPresets presets={presets} active={viewKey} onSelect={setViewKey} />
          <MapLegend
            stage={stage.key}
            toggles={toggles}
            hasForecast={Boolean(bundle.forecast_field)}
            hasForcing={Boolean(bundle.forcing)}
          />
          {/* Only where the forcing is on screen. A conditions readout
              beside a map that is not drawing the conditions invites the
              room to connect two things that are not connected. */}
          {(toggles.current || toggles.wind) && <ForcingReadout bundle={bundle} timeMs={frame.ms} />}
          {/* Only meaningful once the traffic is on screen, which is
              stage 3. Earlier it would name vessels the room has not
              been shown yet. */}
          {toggles.traffic && darkNow.length > 0 && (
            <div className="dark-now-chip">
              {darkNow.length} vessel{darkNow.length > 1 ? "s" : ""} dark at this instant:{" "}
              {darkNow.map((v) => v.mmsi).join(", ")}
            </div>
          )}
        </div>
        <aside className="side-pane">
          {stage.panel === "scene" && <ScenePanel bundle={bundle} />}
          {stage.panel === "drift" && <DriftPanel bundle={bundle} frame={frame} spreadKm={spreadKm} />}
          {stage.panel === "attribution" && (
            <>
              {selectedMmsi ? (
                <VesselFocusCard
                  bundle={bundle}
                  mmsi={selectedMmsi}
                  timeMs={frame.ms}
                  onClear={() => setSelectedMmsi(null)}
                />
              ) : (
                <VerdictCard bundle={bundle} onFocusVessel={focusVessel} />
              )}
              <div className="tab-bar">
                {bundle.case_build && (
                  <button className={rightTab === "case" ? "active" : ""} onClick={() => setRightTab("case")}>
                    How the case was built
                  </button>
                )}
                <button className={rightTab === "suspects" ? "active" : ""} onClick={() => setRightTab("suspects")}>
                  Suspects ({bundle.suspects.length})
                </button>
                <button
                  className={rightTab === "eliminations" ? "active" : ""}
                  onClick={() => setRightTab("eliminations")}
                >
                  Elimination log ({bundle.eliminations.length})
                </button>
                <button className={rightTab === "ledgers" ? "active" : ""} onClick={() => setRightTab("ledgers")}>
                  Ledgers
                </button>
              </div>
              <div className="tab-content">
                {rightTab === "case" && bundle.case_build && (
                  <CaseBuildPanel bundle={bundle} onFocusVessel={focusVessel} />
                )}
                {rightTab === "suspects" && (
                  <SuspectsPanel
                    bundle={bundle}
                    hoveredMmsi={hoveredMmsi}
                    selectedMmsi={selectedMmsi}
                    onHoverVessel={setHoveredMmsi}
                    onSelectVessel={setSelectedMmsi}
                  />
                )}
                {rightTab === "eliminations" && <EliminationLog bundle={bundle} />}
                {rightTab === "ledgers" && <LedgerTables />}
              </div>
            </>
          )}
        </aside>
      </div>
      {/* Stage 1 is a single acquisition instant. A scrubber there would
          imply the SAR image is a movie, so it is not drawn at all. */}
      {stage.timeline !== "none" && (
        <TimeScrubber
          timeline={timeline}
          range={range}
          frameIndex={clampToRange(frameIndex, range)}
          playing={playing}
          acquiredAt={bundle.scene.acquired_at}
          originWindow={bundle.origin_window}
          opportunity={opportunity}
          spreadKm={spreadKm}
          onChangeIndex={(i) => {
            setPlaying(false);
            setFrameIndex(i);
          }}
          onTogglePlay={() => setPlaying((p) => !p)}
        />
      )}
    </div>
  );
}
