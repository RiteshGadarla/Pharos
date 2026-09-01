import { useEffect, useMemo, useRef, useState } from "react";
import { loadDemoBundle } from "./api";
import Header from "./components/Header";
import LayerToggles from "./components/LayerToggles";
import MapView, { type LayerToggles as Toggles } from "./components/MapView";
import SuspectsPanel from "./components/SuspectsPanel";
import EliminationLog from "./components/EliminationLog";
import EvidencePanel from "./components/EvidencePanel";
import TimeScrubber from "./components/TimeScrubber";
import VerdictCard from "./components/VerdictCard";
import ViewPresets from "./components/ViewPresets";
import { useViewPresets, type ViewKey } from "./lib/views";
import type { DemoBundle } from "./types";
import { isDarkAt } from "./lib/geo";
import { fieldSliceSpreadKm } from "./lib/fieldRaster";
import "./App.css";

type RightTab = "suspects" | "eliminations";

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

// How long one full sweep of the origin window should take, whatever
// the backward horizon works out to in timesteps. Pinned to a duration
// rather than a per-step delay: the field has 98 steps on a 48 hour
// horizon, and a fixed 400 ms step made that a 39 second wait.
const SWEEP_DURATION_MS = 16000;
const MIN_STEP_MS = 60;

// Split from App so every hook below can assume a loaded bundle. Putting
// them in App would put hook calls after the loading and error returns.
function Console({ bundle }: { bundle: DemoBundle }) {
  // Opens at the acquisition time, the newest step, because that is
  // where the evidence starts: this is the slick, this is when we saw
  // it. Play then runs backwards from there (PLAN.md section 12,
  // "Signature element"), so the probability cloud blooms as the
  // hindcast runs out of knowledge rather than collapsing into it.
  const lastIndex = bundle.origin_field.time.length - 1;
  const [timeIndex, setTimeIndex] = useState(lastIndex);
  const [playing, setPlaying] = useState(false);
  const [toggles, setToggles] = useState<Toggles>({
    scene: true,
    detections: true,
    field: true,
    traffic: true,
  });
  const [hoveredMmsi, setHoveredMmsi] = useState<string | null>(null);
  const [selectedMmsi, setSelectedMmsi] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<RightTab>("suspects");
  const [viewKey, setViewKey] = useState<ViewKey>("origin");
  const intervalRef = useRef<number | null>(null);

  const presets = useViewPresets(bundle);
  const viewBounds = useMemo(
    () => (presets.find((p) => p.key === viewKey) ?? presets[1]).bounds,
    [presets, viewKey],
  );

  useEffect(() => {
    if (!playing) return;
    const steps = bundle.origin_field.time.length;
    const stepMs = Math.max(MIN_STEP_MS, SWEEP_DURATION_MS / steps);
    intervalRef.current = window.setInterval(() => {
      // Backwards, wrapping round to the acquisition time.
      setTimeIndex((i) => (i === 0 ? steps - 1 : i - 1));
    }, stepMs);
    return () => {
      if (intervalRef.current) window.clearInterval(intervalRef.current);
    };
  }, [playing, bundle]);

  const timeMs = new Date(bundle.origin_field.time[timeIndex]).getTime();
  const darkNow = bundle.vessels.filter((v) => isDarkAt(v, timeMs));
  const spreadKm = useMemo(
    () => fieldSliceSpreadKm(bundle.origin_field, timeIndex),
    [bundle.origin_field, timeIndex],
  );

  const focusVessel = (mmsi: string) => {
    setSelectedMmsi(mmsi);
    setRightTab("suspects");
  };

  return (
    <div className="app-shell">
      <Header bundle={bundle} />
      <div className="app-body">
        <div className="map-pane">
          <MapView
            bundle={bundle}
            timeMs={timeMs}
            timeIndex={timeIndex}
            toggles={toggles}
            viewBounds={viewBounds}
            hoveredMmsi={hoveredMmsi}
            selectedMmsi={selectedMmsi}
            onHoverVessel={setHoveredMmsi}
            onSelectVessel={setSelectedMmsi}
          />
          <LayerToggles toggles={toggles} onChange={setToggles} bundle={bundle} />
          <ViewPresets presets={presets} active={viewKey} onSelect={setViewKey} />
          {darkNow.length > 0 && (
            <div className="dark-now-chip">
              {darkNow.length} vessel{darkNow.length > 1 ? "s" : ""} dark at this instant:{" "}
              {darkNow.map((v) => v.mmsi).join(", ")}
            </div>
          )}
        </div>
        <aside className="side-pane">
          <VerdictCard bundle={bundle} onFocusVessel={focusVessel} />
          <div className="tab-bar">
            <button className={rightTab === "suspects" ? "active" : ""} onClick={() => setRightTab("suspects")}>
              Suspects ({bundle.suspects.length})
            </button>
            <button
              className={rightTab === "eliminations" ? "active" : ""}
              onClick={() => setRightTab("eliminations")}
            >
              Elimination log ({bundle.eliminations.length})
            </button>
          </div>
          <div className="tab-content">
            {rightTab === "suspects" ? (
              <SuspectsPanel
                bundle={bundle}
                hoveredMmsi={hoveredMmsi}
                selectedMmsi={selectedMmsi}
                onHoverVessel={setHoveredMmsi}
                onSelectVessel={setSelectedMmsi}
              />
            ) : (
              <EliminationLog bundle={bundle} />
            )}
          </div>
          <EvidencePanel bundle={bundle} />
        </aside>
      </div>
      <TimeScrubber
        times={bundle.origin_field.time}
        timeIndex={timeIndex}
        playing={playing}
        acquiredAt={bundle.scene.acquired_at}
        spreadKm={spreadKm}
        onChangeIndex={(i) => {
          setPlaying(false);
          setTimeIndex(i);
        }}
        onTogglePlay={() => setPlaying((p) => !p)}
      />
    </div>
  );
}
