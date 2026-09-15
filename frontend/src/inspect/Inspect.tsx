import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";

import { COLORS } from "../lib/tokens";
import "./inspect.css";

// The image inspector at /inspect: upload any image, the detection model
// runs on it (POST /api/inspect, services/core/inspect.py), and the page
// shows what it found. The response types live here rather than in
// src/types.ts because nothing else in the app reads them.

interface LonLat {
  lon: number;
  lat: number;
}

interface InspectImage {
  width: number;
  height: number;
  georeferenced: boolean;
  crs: string | null;
  bbox: [number, number, number, number] | null;
  pixel_size_m: [number, number] | null;
}

interface InspectRender {
  path: "sigma0_db" | "visual_8bit";
  db_window: [number, number] | null;
  note: string;
  preview: { width: number; height: number; scale: number };
  inference?: { width: number; height: number; downsample: number };
}

interface InspectModel {
  name: string;
  classes: string[];
  tile_size: number;
  overlap_px: number;
  n_tiles: number;
}

interface ClassRow {
  name: string;
  pixel_count: number;
  pixel_fraction: number;
  mean_prob: number;
}

interface Detection {
  detection_id: string;
  class_name: string;
  mean_class_prob: number;
  pixel_area: number;
  area_km2: number | null;
  centroid: LonLat | null;
  centroid_px: [number, number];
  bbox_px: [number, number, number, number];
  geometry: { type: "Polygon"; coordinates: number[][][] } | null;
  // Outline in original image pixels. Not in the core contract, so the
  // overlay falls back to bbox_px without it.
  polygon_px?: [number, number][];
}

interface ShipTarget {
  target_id: string;
  centroid_px: [number, number];
  pixel_area: number;
  mean_backscatter_db: number | null;
  centroid: LonLat | null;
}

interface InspectResult {
  filename: string;
  content_type: string | null;
  bytes: number;
  image: InspectImage;
  render: InspectRender;
  model: InspectModel;
  classes: ClassRow[];
  detections: Detection[];
  ships: ShipTarget[];
  gate: null;
  preview_png: string;
  summary: string;
  caveats: string[];
  elapsed_ms: number;
}

const ACCEPT = ".png,.jpg,.jpeg,.tif,.tiff";
const EXTENSIONS = ["png", "jpg", "jpeg", "tif", "tiff"];
const MAX_BYTES = 64 * 1024 * 1024;
const UNREACHABLE = "Could not reach the core service. Check it is running on port 8000, then retry.";

const CLASS_LABEL: Record<string, string> = {
  background: "Background",
  oil_spill: "Oil spill",
  ships: "Ships",
  look_alike: "Look-alike",
  wakes: "Wakes",
  oil: "Oil",
  ship: "Ship",
  wake: "Wake",
};

function classColor(name: string): string {
  if (name === "oil" || name === "oil_spill") return COLORS.oil;
  if (name === "ship" || name === "ships") return COLORS.radar;
  return COLORS.muted;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const int = (n: number) => Math.round(n).toLocaleString("en-US");

function share(fraction: number): string {
  const pct = fraction * 100;
  if (pct > 0 && pct < 0.01) return "<0.01%";
  return `${pct.toFixed(2)}%`;
}

function centroidText(centroid: LonLat | null, px: [number, number]): string {
  if (centroid) return `${centroid.lat.toFixed(5)}, ${centroid.lon.toFixed(5)}`;
  return `${Math.round(px[0])}, ${Math.round(px[1])} px`;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot + 1).toLowerCase();
}

async function readError(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : JSON.stringify(d))).join("; ");
    }
  } catch {
    // not JSON, fall through
  }
  if (res.status === 404) return "The server has no /api/inspect endpoint. The core service needs the inspect router.";
  if (res.status === 502 || res.status === 504 || (res.status === 500 && !text.trim())) return UNREACHABLE;
  return `The server answered HTTP ${res.status}${text.trim() ? `: ${text.trim().slice(0, 240)}` : "."}`;
}

export default function Inspect() {
  const [file, setFile] = useState<File | null>(null);
  const [localUrl, setLocalUrl] = useState<string | null>(null);
  const [localSize, setLocalSize] = useState<[number, number] | null>(null);
  const [dragging, setDragging] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const [result, setResult] = useState<InspectResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showOutlines, setShowOutlines] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const urlRef = useRef<string | null>(null);

  const running = startedAt !== null;

  useEffect(() => {
    if (startedAt === null) return;
    const ticker = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(ticker);
  }, [startedAt]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );

  function choose(next: File | undefined) {
    if (!next || running) return;
    if (!EXTENSIONS.includes(extensionOf(next.name))) {
      setError(`${next.name} is not a PNG, JPG or TIFF file.`);
      return;
    }
    if (next.size > MAX_BYTES) {
      setError(`${next.name} is ${formatBytes(next.size)}, above the 64 MB limit.`);
      return;
    }
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    const isTiff = ["tif", "tiff"].includes(extensionOf(next.name));
    const url = isTiff ? null : URL.createObjectURL(next);
    urlRef.current = url;
    setFile(next);
    setLocalUrl(url);
    setLocalSize(null);
    setResult(null);
    setError(null);
    setActiveId(null);
  }

  function onPick(event: ChangeEvent<HTMLInputElement>) {
    choose(event.target.files?.[0]);
    event.target.value = "";
  }

  function onDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files?.[0]);
  }

  function onDragOver(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    if (!running) setDragging(true);
  }

  async function run() {
    if (!file || running) return;
    const controller = new AbortController();
    abortRef.current = controller;
    const t0 = Date.now();
    setStartedAt(t0);
    setNow(t0);
    setResult(null);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file, file.name);
      const res = await fetch("/api/inspect", { method: "POST", body, signal: controller.signal });
      if (!res.ok) throw new Error(await readError(res));
      setResult((await res.json()) as InspectResult);
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof TypeError) setError(UNREACHABLE);
      else setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setStartedAt(null);
      }
    }
  }

  const elapsed = startedAt === null ? 0 : Math.max(0, Math.floor((now - startedAt) / 1000));

  return (
    <div className="ins-page">
      <header className="ins-header">
        <a className="ins-brand" href="/" aria-label="DRISHTA home">
          <img className="ins-brand-mark" src="/brand/drishta-mark-256.png" width={32} height={32} alt="" />
          <strong>DRISHTA</strong>
          <span>Image inspector</span>
        </a>
        <nav className="ins-nav" aria-label="Pages">
          <a href="/">Overview</a>
          <a href="/run">Console</a>
        </nav>
      </header>

      <main className="ins-main">
        <section
          className={`ins-stage${dragging ? " is-dragging" : ""}`}
          onDragOver={onDragOver}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          aria-label="Image"
        >
          {result ? (
            <ResultImage
              result={result}
              showOutlines={showOutlines}
              activeId={activeId}
              onActive={setActiveId}
            />
          ) : file ? (
            <div className="ins-local">
              {localUrl ? (
                <img
                  src={localUrl}
                  alt={file.name}
                  onLoad={(e) => setLocalSize([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])}
                />
              ) : (
                <p className="ins-muted">No browser preview for TIFF. The model's view appears after the run.</p>
              )}
            </div>
          ) : (
            <div className="ins-drop">
              <p className="ins-drop-title">Drop an image here</p>
              <p className="ins-muted">PNG, JPG or TIFF, up to 64 MB. GeoTIFFs get coordinates and km2.</p>
              <button type="button" className="ins-button" onClick={() => inputRef.current?.click()}>
                Choose file
              </button>
            </div>
          )}
          <input ref={inputRef} type="file" accept={ACCEPT} hidden onChange={onPick} />
        </section>

        <aside className="ins-side">
          <section className="ins-card">
            <h2>Input</h2>
            {file ? (
              <dl className="ins-facts">
                <dt>File</dt>
                <dd title={file.name}>{file.name}</dd>
                <dt>Size</dt>
                <dd>
                  {formatBytes(file.size)}
                  {localSize ? `, ${localSize[0]} x ${localSize[1]} px` : ""}
                </dd>
              </dl>
            ) : (
              <p className="ins-muted">No file chosen.</p>
            )}
            <div className="ins-actions">
              <button type="button" className="ins-button is-primary" onClick={run} disabled={!file || running}>
                {running ? "Running" : result ? "Run again" : "Run detection"}
              </button>
              <button
                type="button"
                className="ins-button"
                onClick={() => inputRef.current?.click()}
                disabled={running}
              >
                {file ? "Choose another" : "Choose file"}
              </button>
            </div>
            {running ? (
              <p className="ins-running" role="status">
                <span className="ins-pulse" aria-hidden="true" />
                Running the model, {elapsed} s. The first run loads the model and takes longer.
              </p>
            ) : null}
          </section>

          {error ? (
            <section className="ins-card ins-error" role="alert">
              <h2>Inspection failed</h2>
              <p>{error}</p>
            </section>
          ) : null}

          {result ? (
            <Results
              result={result}
              showOutlines={showOutlines}
              onToggleOutlines={() => setShowOutlines((v) => !v)}
              activeId={activeId}
              onActive={setActiveId}
            />
          ) : null}
        </aside>
      </main>
    </div>
  );
}

function ResultImage({
  result,
  showOutlines,
  activeId,
  onActive,
}: {
  result: InspectResult;
  showOutlines: boolean;
  activeId: string | null;
  onActive: (id: string | null) => void;
}) {
  const { preview } = result.render;
  // Detections are in original image pixels; the preview is the model's
  // input scaled down, so each axis maps by preview size over image size.
  const sx = preview.width / result.image.width;
  const sy = preview.height / result.image.height;
  const marker = Math.max(4, Math.max(preview.width, preview.height) * 0.008);
  const regionCount: Record<string, number> = {};

  return (
    <figure className="ins-figure">
      <div className="ins-preview">
        <img src={result.preview_png} alt={`${result.filename} as the model saw it`} />
        {showOutlines ? (
          <svg viewBox={`0 0 ${preview.width} ${preview.height}`} preserveAspectRatio="none" aria-hidden="true">
            {result.detections.map((d) => {
              regionCount[d.class_name] = (regionCount[d.class_name] ?? 0) + 1;
              const color = classColor(d.class_name);
              const active = activeId === d.detection_id;
              const [x0, y0, x1, y1] = d.bbox_px;
              const common = {
                fill: active ? `${color}55` : `${color}22`,
                stroke: color,
                strokeWidth: active ? 2.5 : 1.25,
                strokeDasharray: d.class_name === "oil" ? undefined : "4 3",
                vectorEffect: "non-scaling-stroke" as const,
                onMouseEnter: () => onActive(d.detection_id),
                onMouseLeave: () => onActive(null),
              };
              return (
                <g key={d.detection_id}>
                  {d.polygon_px ? (
                    <polygon points={d.polygon_px.map(([x, y]) => `${x * sx},${y * sy}`).join(" ")} {...common} />
                  ) : (
                    <rect x={x0 * sx} y={y0 * sy} width={(x1 - x0) * sx} height={(y1 - y0) * sy} {...common} />
                  )}
                  <text x={x0 * sx} y={Math.max(10, y0 * sy - 3)} fill={color} className="ins-svg-label">
                    {shortLabel(d.class_name)}
                    {regionCount[d.class_name]}
                  </text>
                </g>
              );
            })}
            {result.ships.map((s, i) => (
              <g key={s.target_id}>
                <circle
                  cx={s.centroid_px[0] * sx}
                  cy={s.centroid_px[1] * sy}
                  r={marker}
                  fill="none"
                  stroke={COLORS.radar}
                  strokeWidth={activeId === s.target_id ? 2.5 : 1.5}
                  vectorEffect="non-scaling-stroke"
                  onMouseEnter={() => onActive(s.target_id)}
                  onMouseLeave={() => onActive(null)}
                />
                <text x={s.centroid_px[0] * sx + marker + 2} y={s.centroid_px[1] * sy + 4} fill={COLORS.radar} className="ins-svg-label">
                  S{i + 1}
                </text>
              </g>
            ))}
          </svg>
        ) : null}
      </div>
      <figcaption>
        Model input, {preview.width} x {preview.height} px preview of {result.image.width} x {result.image.height} px.
      </figcaption>
    </figure>
  );
}

function shortLabel(className: string): string {
  if (className === "oil") return "O";
  if (className === "look_alike") return "L";
  return className.slice(0, 1).toUpperCase();
}

function Results({
  result,
  showOutlines,
  onToggleOutlines,
  activeId,
  onActive,
}: {
  result: InspectResult;
  showOutlines: boolean;
  onToggleOutlines: () => void;
  activeId: string | null;
  onActive: (id: string | null) => void;
}) {
  const { image, render, model } = result;
  const counters: Record<string, number> = {};

  return (
    <>
      <section className="ins-card">
        <p className="ins-summary">{result.summary}.</p>
        <dl className="ins-facts">
          <dt>Render</dt>
          <dd>
            <code>{render.path}</code>
            {render.db_window ? ` window ${render.db_window[0]} to ${render.db_window[1]} dB` : ""}
          </dd>
          <dt>Geography</dt>
          <dd>
            {image.georeferenced
              ? `${image.crs}${image.pixel_size_m ? `, ${image.pixel_size_m[0]} x ${image.pixel_size_m[1]} m px` : ""}`
              : "None, pixel space only"}
          </dd>
          {image.bbox ? (
            <>
              <dt>Bounds</dt>
              <dd>
                {image.bbox[1].toFixed(4)}, {image.bbox[0].toFixed(4)} to {image.bbox[3].toFixed(4)},{" "}
                {image.bbox[2].toFixed(4)}
              </dd>
            </>
          ) : null}
          <dt>Model</dt>
          <dd>
            {model.n_tiles} tiles of {model.tile_size} px, {model.overlap_px} px overlap
          </dd>
          <dt>Wind gate</dt>
          <dd>Not run, see caveats</dd>
          <dt>Time</dt>
          <dd>{(result.elapsed_ms / 1000).toFixed(1)} s</dd>
        </dl>
        <p className="ins-note">{render.note}</p>
        <button type="button" className="ins-link" onClick={onToggleOutlines}>
          {showOutlines ? "Hide outlines" : "Show outlines"}
        </button>
      </section>

      <section className="ins-card">
        <h2>Class coverage</h2>
        <table className="ins-table">
          <thead>
            <tr>
              <th>Class</th>
              <th className="num">Pixels</th>
              <th className="num">Share</th>
              <th className="num">Mean prob</th>
            </tr>
          </thead>
          <tbody>
            {result.classes.map((row) => (
              <tr key={row.name}>
                <td>
                  <span className="ins-swatch" style={{ background: classColor(row.name) }} />
                  {CLASS_LABEL[row.name] ?? row.name}
                </td>
                <td className="num">{int(row.pixel_count)}</td>
                <td className="num">
                  <span className="ins-bar" aria-hidden="true">
                    <span style={{ width: `${Math.min(100, row.pixel_fraction * 100)}%`, background: classColor(row.name) }} />
                  </span>
                  {share(row.pixel_fraction)}
                </td>
                <td className="num">{row.pixel_count ? row.mean_prob.toFixed(3) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="ins-card">
        <h2>Detections</h2>
        {result.detections.length ? (
          <div className="ins-scroll">
            <table className="ins-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Id</th>
                  <th>Class</th>
                  <th className="num">Mean prob</th>
                  <th className="num">Pixels</th>
                  <th className="num">km2</th>
                  <th>Centroid</th>
                </tr>
              </thead>
              <tbody>
                {result.detections.map((d) => {
                  counters[d.class_name] = (counters[d.class_name] ?? 0) + 1;
                  return (
                    <tr
                      key={d.detection_id}
                      className={activeId === d.detection_id ? "is-active" : undefined}
                      onMouseEnter={() => onActive(d.detection_id)}
                      onMouseLeave={() => onActive(null)}
                    >
                      <td style={{ color: classColor(d.class_name) }}>
                        {shortLabel(d.class_name)}
                        {counters[d.class_name]}
                      </td>
                      <td className="ins-id" title={d.detection_id}>
                        {d.detection_id}
                      </td>
                      <td>{CLASS_LABEL[d.class_name] ?? d.class_name}</td>
                      <td className="num">{d.mean_class_prob.toFixed(3)}</td>
                      <td className="num">{int(d.pixel_area)}</td>
                      <td className="num">{d.area_km2 === null ? "-" : d.area_km2.toFixed(3)}</td>
                      <td>{centroidText(d.centroid, d.centroid_px)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="ins-muted">No oil or look-alike regions above the size floor.</p>
        )}
      </section>

      {result.ships.length ? (
        <section className="ins-card">
          <h2>Ship targets</h2>
          <div className="ins-scroll">
            <table className="ins-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Id</th>
                  <th className="num">Pixels</th>
                  <th className="num">Backscatter</th>
                  <th>Centroid</th>
                </tr>
              </thead>
              <tbody>
                {result.ships.map((s, i) => (
                  <tr
                    key={s.target_id}
                    className={activeId === s.target_id ? "is-active" : undefined}
                    onMouseEnter={() => onActive(s.target_id)}
                    onMouseLeave={() => onActive(null)}
                  >
                    <td style={{ color: COLORS.radar }}>S{i + 1}</td>
                    <td className="ins-id" title={s.target_id}>
                      {s.target_id}
                    </td>
                    <td className="num">{int(s.pixel_area)}</td>
                    <td className="num">
                      {s.mean_backscatter_db === null ? "-" : `${s.mean_backscatter_db.toFixed(1)} dB`}
                    </td>
                    <td>{centroidText(s.centroid, s.centroid_px)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className="ins-card">
        <h2>Caveats</h2>
        <ul className="ins-caveats">
          {result.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </section>
    </>
  );
}
