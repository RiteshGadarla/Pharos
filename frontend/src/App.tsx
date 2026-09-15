import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  dossierCandidates,
  initialCaseId,
  loadCaseBundle,
  loadCasesIndex,
  loadDemoBundle,
  scenePreviewCandidates,
  type LoadedCases,
} from "./api";
import Navbar from "./components/Navbar";
import AttributionPanel, { type AttributionSection } from "./components/AttributionPanel";
import CaseSwitcher from "./components/CaseSwitcher";
import ForcingReadout from "./components/ForcingReadout";
import LayerToggles from "./components/LayerToggles";
import MapLegend from "./components/MapLegend";
import MapProvenance from "./components/MapProvenance";
import MapView, { type FitPadding, type LayerToggles as Toggles } from "./components/MapView";
import DriftPanel from "./components/DriftPanel";
import ScenePanel from "./components/ScenePanel";
import StageRail from "./components/StageRail";
import TimeScrubber from "./components/TimeScrubber";
import ViewPresets from "./components/ViewPresets";
import { useViewPresets, type ViewKey } from "./lib/views";
import { STAGES, stageAt } from "./lib/stages";
import { buildTimeline, clampToRange, frameField, nearestFrame } from "./lib/timeline";
import type { CaseSummary, DemoBundle } from "./types";
import { isDarkAt } from "./lib/geo";
import { fieldSliceSpreadKm } from "./lib/fieldRaster";
import "./App.css";

interface Loaded {
  bundle: DemoBundle;
  // The case the bundle belongs to, or null for the single demo bundle a
  // checkout without a case index has always loaded.
  caseId: string | null;
}

export default function App() {
  const [cases, setCases] = useState<LoadedCases | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  // The case index is optional. Without one the console loads the one
  // demo bundle exactly as it always has and draws no switcher; with one
  // it opens on the case named in the URL, or the index's default.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const index = await loadCasesIndex();
      if (cancelled) return;
      if (index) {
        setCases(index);
        const id = initialCaseId(index.index);
        const entry = index.index.cases.find((c) => c.id === id)!;
        try {
          const bundle = await loadCaseBundle(entry, index.source);
          if (!cancelled) setLoaded({ bundle, caseId: id });
          return;
        } catch (e) {
          // A broken case must not take the console down with it. Fall
          // back to the single bundle and say which case failed.
          if (!cancelled) setSwitchError(String(e));
        }
      }
      try {
        const bundle = await loadDemoBundle();
        if (!cancelled) setLoaded({ bundle, caseId: null });
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectCase = useCallback(
    async (id: string) => {
      setMenuOpen(false);
      if (!cases || id === loaded?.caseId) return;
      const entry = cases.index.cases.find((c) => c.id === id);
      if (!entry) return;
      setLoadingId(id);
      setSwitchError(null);
      try {
        const bundle = await loadCaseBundle(entry, cases.source);
        setLoaded({ bundle, caseId: id });
        // Kept in the address bar so a reload, or a second screen, opens
        // on the same case. The page itself is still chosen by path.
        const url = new URL(window.location.href);
        url.searchParams.set("case", id);
        window.history.replaceState(null, "", url);
      } catch (e) {
        setSwitchError(String(e));
      } finally {
        setLoadingId(null);
      }
    },
    [cases, loaded?.caseId],
  );

  if (error) {
    return (
      <div className="fatal-error">
        <p>Could not load the demo bundle: {error}</p>
        <p>Run the core service (make run-core) or make seed-demo, then reload.</p>
      </div>
    );
  }

  if (!loaded) {
    return <div className="loading">Loading demo bundle...</div>;
  }

  const activeCase = cases?.index.cases.find((c) => c.id === loaded.caseId) ?? null;
  const switcher =
    cases && cases.index.cases.length > 0 ? (
      <CaseSwitcher
        cases={cases.index.cases}
        activeId={loaded.caseId}
        loadingId={loadingId}
        open={menuOpen}
        onOpenChange={setMenuOpen}
        onSelect={selectCase}
      />
    ) : undefined;

  return (
    <>
      {/* Keyed by case, so switching remounts the console and every piece
          of its state starts again at stage 1: stage, layers, camera,
          cursor and selection all belong to the case they were set on. */}
      <Console
        key={loaded.caseId ?? "single"}
        bundle={loaded.bundle}
        activeCase={activeCase}
        casesSource={cases?.source ?? null}
        caseSwitcher={switcher}
      />
      {loadingId && <div className="case-loading" aria-live="polite">Loading case...</div>}
      {switchError && (
        <div className="case-error" role="alert">
          {switchError}
          <button onClick={() => setSwitchError(null)}>Dismiss</button>
        </div>
      )}
    </>
  );
}

// How long one full sweep of the visible time window should take,
// whatever that window works out to in timesteps. Pinned to a duration
// rather than a per-step delay: the backward field has 98 steps on a 48
// hour horizon, and a fixed 400 ms step made that a 39 second wait.
const SWEEP_DURATION_MS = 16000;

// The map chrome each stage carries, as padding the camera fits inside.
// The top is the view and layer buttons, the left is the legend, which
// by stage 3 is a tall column of eleven marks. Without this the traffic
// view put the three surviving vessels, which is the whole answer,
// directly underneath that legend.
const FIT_PADDING: Record<string, FitPadding> = {
  acquisition: { top: 84, right: 48, bottom: 48, left: 48 },
  drift: { top: 96, right: 60, bottom: 60, left: 120 },
  attribution: { top: 84, right: 60, bottom: 56, left: 430 },
};
const MIN_STEP_MS = 60;

interface ConsoleProps {
  bundle: DemoBundle;
  activeCase: CaseSummary | null;
  casesSource: LoadedCases["source"] | null;
  caseSwitcher?: ReactNode;
}

// Split from App so every hook below can assume a loaded bundle. Putting
// them in App would put hook calls after the loading and error returns.
function Console({ bundle, activeCase, casesSource, caseSwitcher }: ConsoleProps) {
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
  const [section, setSection] = useState<AttributionSection>("case");
  const [viewKey, setViewKey] = useState<ViewKey>(STAGES[0].view);
  const intervalRef = useRef<number | null>(null);

  const presets = useViewPresets(bundle);
  const viewBounds = useMemo(
    () => (presets.find((p) => p.key === viewKey) ?? presets[1]).bounds,
    [presets, viewKey],
  );
  const previewUrls = useMemo(() => scenePreviewCandidates(activeCase, casesSource), [activeCase, casesSource]);
  const dossierUrls = useMemo(() => dossierCandidates(activeCase, casesSource), [activeCase, casesSource]);

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
  // during questions a presenter needs a specific stage instantly. Keys
  // the case switcher has already taken (it listens first, and marks
  // them handled) are left alone.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowRight") goToStage(stage.ordinal + 1);
      else if (e.key === "ArrowLeft") goToStage(stage.ordinal - 1);
      else if (e.key >= "1" && e.key <= String(STAGES.length)) goToStage(Number(e.key));
      else if (e.key === "Escape" && selectedMmsi) setSelectedMmsi(null);
      else if (e.key === " ") {
        e.preventDefault();
        if (stage.timeline !== "none") setPlaying((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goToStage, stage.ordinal, stage.timeline, selectedMmsi]);

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

  const showForcing = Boolean(bundle.forcing) && (toggles.current || toggles.wind);
  const showDarkNow = toggles.traffic && darkNow.length > 0;

  return (
    <div className="app-shell">
      <Navbar dossierUrls={dossierUrls} caseSwitcher={caseSwitcher} />
      <StageRail bundle={bundle} stage={stage} onSelect={goToStage} />
      <div className="app-body">
        <div className="map-pane">
          <MapView
            bundle={bundle}
            timeMs={frame.ms}
            frame={frame}
            toggles={toggles}
            viewBounds={viewBounds}
            fitPadding={FIT_PADDING[stage.key]}
            hoveredMmsi={hoveredMmsi}
            selectedMmsi={selectedMmsi}
            previewUrls={previewUrls}
            onHoverVessel={setHoveredMmsi}
            onSelectVessel={setSelectedMmsi}
          />

          {/* The map carries four corners of chrome and nothing floating
              in between: live readouts top left, camera and layers top
              right, the legend bottom left, provenance bottom right. */}
          <div className="map-corner top-left">
            {/* Only where the forcing is on screen. A conditions readout
                beside a map that is not drawing the conditions invites the
                room to connect two things that are not connected. */}
            {showForcing && <ForcingReadout bundle={bundle} timeMs={frame.ms} />}
            {/* Only once the traffic is on screen. Earlier it would name
                vessels the room has not been shown yet. */}
            {showDarkNow && (
              <div className="dark-now-chip map-card" aria-live="polite">
                <span className="dark-now-count mono">{darkNow.length}</span>
                <span className="dark-now-text">
                  <span className="dark-now-label">dark at this instant</span>
                  <span className="mono dark-now-list">{darkNow.map((v) => v.mmsi).join("  ")}</span>
                </span>
              </div>
            )}
          </div>
          <div className="map-corner top-right">
            <ViewPresets presets={presets} active={viewKey} onSelect={setViewKey} />
            <LayerToggles toggles={toggles} onChange={setToggles} bundle={bundle} />
          </div>
          <div className="map-corner bottom-left">
            <MapLegend
              stage={stage.key}
              toggles={toggles}
              hasForecast={Boolean(bundle.forecast_field)}
              hasForcing={Boolean(bundle.forcing)}
            />
          </div>
          <div className="map-corner bottom-right">
            <MapProvenance bundle={bundle} toggles={toggles} />
          </div>
        </div>
        <aside className={`side-pane panel-${stage.panel}`}>
          {stage.panel === "scene" && (
            <div className="pane-scroll">
              <ScenePanel bundle={bundle} />
            </div>
          )}
          {stage.panel === "drift" && (
            <div className="pane-scroll">
              <DriftPanel bundle={bundle} frame={frame} spreadKm={spreadKm} />
            </div>
          )}
          {stage.panel === "attribution" && (
            <AttributionPanel
              bundle={bundle}
              timeMs={frame.ms}
              section={section}
              onSectionChange={setSection}
              hoveredMmsi={hoveredMmsi}
              selectedMmsi={selectedMmsi}
              onHoverVessel={setHoveredMmsi}
              onSelectVessel={setSelectedMmsi}
            />
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
