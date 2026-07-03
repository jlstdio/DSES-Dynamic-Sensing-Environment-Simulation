from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd


DEFAULT_CHUNK_SIZE = 500_000
DEFAULT_CHUNK_HOURS = 1
DEFAULT_INITIAL_WINDOW_HOURS = 0.5
MIN_WINDOW_HOURS = 1.0 / 3600.0
MAX_WINDOW_HOURS = 1.0
STATE_TO_CODE = {
  "dead": 0,
  "deep_sleep": 1,
  "sensing": 2,
  "inference": 3,
  "communication": 4,
}


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Lazy Status Viewer</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; background: #f5f5f5; color: #111; }
    .wrap { padding: 20px; }
    .toolbar { display: grid; grid-template-columns: repeat(5, max-content); gap: 12px; align-items: end; margin-bottom: 16px; }
    .toolbar label { display: flex; flex-direction: column; font-size: 13px; gap: 4px; }
    .toolbar input, .toolbar select, .toolbar button { padding: 8px 10px; font-size: 14px; }
    .toolbar button { cursor: pointer; }
    .note { font-size: 13px; color: #555; margin-bottom: 12px; }
    .legendbox { background: white; border-radius: 10px; padding: 12px 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-bottom: 16px; font-size: 13px; line-height: 1.5; }
    .legendbox strong { display: inline-block; min-width: 180px; }
    .chart { background: white; border-radius: 10px; padding: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-bottom: 16px; }
    #status { font-size: 13px; color: #444; margin-bottom: 12px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Lazy Status Viewer</h1>
    <div class="note">Open this folder through a local web server, for example: <code>python3 -m http.server</code>, then open this HTML via <code>http://localhost:8000/...</code>.</div>
    <div class="legendbox">
      <div><strong>Main plot:</strong> always loads the selected range at the original 10ms resolution.</div>
      <div><strong>Navigator bar:</strong> shows the full time span and controls which 10ms window is loaded above.</div>
      <div><strong>Sunlight:</strong> <code>irradiance_multiplier</code></div>
      <div><strong>Battery Charge:</strong> <code>charging_rate_mw</code></div>
      <div><strong>Energy Use:</strong> <code>power_consumption_mw</code></div>
      <div><strong>Battery Remaining:</strong> battery percentage or joules depending on export setting</div>
      <div><strong>State Code:</strong> 0 dead, 1 deep_sleep, 2 sensing, 3 inference, 4 communication</div>
      <div><strong>Allowed range width:</strong> minimum 1 second, maximum 1 hour, default 30 minutes</div>
    </div>
    <div class="toolbar">
      <label>Node
        <select id="nodeSelect"></select>
      </label>
      <label>Start Hour
        <input id="startHour" type="number" step="0.001" min="0" />
      </label>
      <label>End Hour
        <input id="endHour" type="number" step="0.001" min="0" />
      </label>
      <label>Window Length (Hours)
        <input id="windowHours" type="number" step="0.001" min="0.000278" max="1" />
      </label>
      <button id="applyRange">Load 10ms Range</button>
      <button id="resetRange">Reset 30m Window</button>
    </div>
    <div id="status">Loading manifest...</div>
    <div class="chart"><div id="mainPlot"></div></div>
    <div class="chart"><div id="navigatorPlot"></div></div>
  </div>
  <script>
    const STATE_TICKS = [0, 1, 2, 3, 4];
    const STATE_TEXT = ['0 dead', '1 deep_sleep', '2 sensing', '3 inference', '4 communication'];
    const manifestPath = 'manifest.json';
    let manifest = null;
    let navigatorSyncEnabled = true;
    let pendingRangeLoad = null;

    function defaultWindowHours(totalHours) {
      return Math.min(totalHours, %DEFAULT_INITIAL_WINDOW_HOURS%);
    }

    function setStatus(text) {
      document.getElementById('status').textContent = text;
    }

    function clampWindowLength(hours) {
      return Math.min(%MAX_WINDOW_HOURS%, Math.max(%MIN_WINDOW_HOURS%, hours));
    }

    function clampRange(startHour, endHour) {
      let start = Math.max(0, Math.min(startHour, manifest.totalHours));
      let end = Math.max(start, Math.min(endHour, manifest.totalHours));
      let width = end - start;
      if (width < %MIN_WINDOW_HOURS%) {
        end = Math.min(manifest.totalHours, start + %MIN_WINDOW_HOURS%);
        width = end - start;
        if (width < %MIN_WINDOW_HOURS%) {
          start = Math.max(0, end - %MIN_WINDOW_HOURS%);
        }
      }
      width = end - start;
      if (width > %MAX_WINDOW_HOURS%) {
        end = Math.min(manifest.totalHours, start + %MAX_WINDOW_HOURS%);
        if (end - start > %MAX_WINDOW_HOURS%) {
          start = Math.max(0, end - %MAX_WINDOW_HOURS%);
        }
      }
      return [start, end];
    }

    function setRangeInputs(startHour, endHour) {
      document.getElementById('startHour').value = startHour.toFixed(6);
      document.getElementById('endHour').value = endHour.toFixed(6);
      document.getElementById('windowHours').value = (endHour - startHour).toFixed(6);
    }

    async function syncNavigatorRange(startHour, endHour) {
      const navigatorEl = document.getElementById('navigatorPlot');
      if (!navigatorEl || !navigatorEl.data || navigatorEl.data.length === 0) {
        return;
      }
      navigatorSyncEnabled = false;
      await Plotly.relayout('navigatorPlot', {'xaxis.range': [startHour, endHour]});
      navigatorSyncEnabled = true;
    }

    function scheduleRangeLoad(syncNavigator = true) {
      if (pendingRangeLoad !== null) {
        clearTimeout(pendingRangeLoad);
      }
      pendingRangeLoad = window.setTimeout(async () => {
        pendingRangeLoad = null;
        try {
          await loadRawRange(syncNavigator);
        } catch (error) {
          setStatus(error.message);
        }
      }, 120);
    }

    function parseCsv(text) {
      const lines = text.trim().split(/\\r?\\n/);
      const header = lines[0].split(',');
      return lines.slice(1).filter(Boolean).map(line => {
        const values = line.split(',');
        const row = {};
        header.forEach((key, index) => { row[key] = values[index]; });
        return row;
      });
    }

    async function fetchCsv(path) {
      const response = await fetch(path);
      if (!response.ok) {
        throw new Error(`Failed to fetch ${path}: ${response.status}`);
      }
      return parseCsv(await response.text());
    }

    function numberArray(rows, key) {
      return rows.map(row => Number(row[key]));
    }

    function buildTraceSet(x, series) {
      return [
        {y: series.irradiance, color: '#d97706', name: 'Sunlight'},
        {y: series.charging, color: '#16a34a', name: 'Battery Charge (mW)'},
        {y: series.consumption, color: '#dc2626', name: 'Energy Use (mW)'},
        {y: series.battery, color: '#2563eb', name: manifest.batteryLabel},
        {y: series.state, color: '#111827', name: 'State Code'},
      ].map((item, index) => ({
        type: index === 4 ? 'scatter' : 'scattergl',
        mode: 'lines',
        x,
        y: item.y,
        line: index === 4 ? {color: item.color, width: 1, shape: 'hv'} : {color: item.color, width: 1},
        name: item.name,
        xaxis: `x${index + 1}`,
        yaxis: `y${index + 1}`,
        showlegend: false,
      }));
    }

    function renderMainPlot(titlePrefix, x, series, startHour, endHour) {
      const layout = {
        title: `${titlePrefix} 10ms Raw View`,
        grid: {rows: 5, columns: 1, pattern: 'independent'},
        height: 1100,
        hovermode: 'x unified',
        template: 'plotly_white',
      };
      const traces = buildTraceSet(x, series);
      layout.yaxis5 = {tickvals: STATE_TICKS, ticktext: STATE_TEXT, range: [-0.5, 4.5]};
      layout.xaxis5 = {title: 'Elapsed Hours', range: [startHour, endHour]};
      Plotly.newPlot('mainPlot', traces, layout, {responsive: true});
    }

    function renderNavigator(titlePrefix, startHour, endHour) {
      const layout = {
        title: `${titlePrefix} Navigator`,
        height: 240,
        hovermode: 'x unified',
        template: 'plotly_white',
        margin: {t: 50, r: 20, b: 40, l: 60},
        xaxis: {
          title: 'Elapsed Hours',
          range: [0, manifest.totalHours],
          rangeslider: {visible: true, range: [0, manifest.totalHours]},
        },
        yaxis: {title: manifest.batteryLabel},
      };
      const trace = [{
        type: 'scattergl',
        mode: 'lines',
        x: [0, manifest.totalHours],
        y: [0, 0],
        line: {color: '#2563eb', width: 1},
        name: 'Full time span',
        showlegend: false,
      }];
      Plotly.newPlot('navigatorPlot', trace, layout, {responsive: true}).then(() => {
        navigatorSyncEnabled = false;
        Plotly.relayout('navigatorPlot', {'xaxis.range': [startHour, endHour]});
        navigatorSyncEnabled = true;
        const navEl = document.getElementById('navigatorPlot');
        navEl.removeAllListeners?.('plotly_relayout');
        navEl.on('plotly_relayout', async (event) => {
          if (!navigatorSyncEnabled) {
            return;
          }
          const start = event['xaxis.range[0]'] ?? event['xaxis.rangeslider.range[0]'];
          const end = event['xaxis.range[1]'] ?? event['xaxis.rangeslider.range[1]'];
          if (start === undefined || end === undefined) {
            return;
          }
          const [clampedStart, clampedEnd] = clampRange(Number(start), Number(end));
          setRangeInputs(clampedStart, clampedEnd);
          scheduleRangeLoad(false);
        });
      });
    }

    async function loadManifest() {
      const response = await fetch(manifestPath);
      if (!response.ok) {
        throw new Error(`Failed to fetch manifest: ${response.status}`);
      }
      manifest = await response.json();
      const select = document.getElementById('nodeSelect');
      manifest.nodeIds.forEach(nodeId => {
        const option = document.createElement('option');
        option.value = nodeId;
        option.textContent = `Node ${nodeId}`;
        select.appendChild(option);
      });
      const initialWindow = defaultWindowHours(manifest.totalHours);
      setRangeInputs(0, initialWindow);
      document.getElementById('startHour').max = manifest.totalHours.toFixed(6);
      document.getElementById('endHour').max = manifest.totalHours.toFixed(6);
      document.getElementById('windowHours').min = %MIN_WINDOW_HOURS%.toFixed(6);
      document.getElementById('windowHours').max = %MAX_WINDOW_HOURS%.toFixed(6);
      setStatus(`Manifest loaded | nodes=${manifest.nodeIds.length} | totalHours=${manifest.totalHours}`);
    }

    async function loadRawRange(syncNavigator = true) {
      const nodeId = document.getElementById('nodeSelect').value;
      const requestedStartHour = Number(document.getElementById('startHour').value);
      const requestedEndHour = Number(document.getElementById('endHour').value);
      if (!(requestedEndHour > requestedStartHour)) {
        throw new Error('End hour must be greater than start hour');
      }

      const [startHour, endHour] = clampRange(requestedStartHour, requestedEndHour);
      setRangeInputs(startHour, endHour);
      if (!(endHour > startHour)) {
        throw new Error(`Requested range is outside the available data. totalHours=${manifest.totalHours}`);
      }

      const chunkMs = manifest.chunkHours * 3600000;
      const startMs = Math.floor(startHour * 3600000);
      const endMs = Math.ceil(endHour * 3600000);
      const startChunk = Math.floor(startMs / chunkMs);
      const endChunk = Math.floor((endMs - 1) / chunkMs);
      setStatus(`Loading raw 10ms detail for node ${nodeId}, chunks ${startChunk}-${endChunk}...`);

      let rows = [];
      let missingChunks = 0;
      for (let chunkIndex = startChunk; chunkIndex <= endChunk; chunkIndex += 1) {
        try {
          const chunkRows = await fetchCsv(`chunks/node_${nodeId}/chunk_${String(chunkIndex).padStart(3, '0')}.csv`);
          rows = rows.concat(chunkRows);
        } catch (error) {
          missingChunks += 1;
        }
      }

      rows = rows.filter(row => {
        const hour = Number(row.elapsed_hours);
        return hour >= startHour && hour <= endHour;
      });
      if (rows.length === 0) {
        setStatus(`No raw 10ms data yet in requested range | requested=${requestedStartHour}-${requestedEndHour}h | actual=${startHour}-${endHour}h | missingChunks=${missingChunks}`);
        return;
      }

      const x = numberArray(rows, 'elapsed_hours');
      renderMainPlot(`Node ${nodeId}`, x, {
        irradiance: numberArray(rows, 'irradiance_multiplier'),
        charging: numberArray(rows, 'charging_rate_mw'),
        consumption: numberArray(rows, 'power_consumption_mw'),
        battery: numberArray(rows, 'battery_value'),
        state: numberArray(rows, 'state_code'),
      }, startHour, endHour);
      if (syncNavigator) {
        await syncNavigatorRange(startHour, endHour);
      }
      setStatus(`Raw detail loaded | node=${nodeId} | points=${rows.length.toLocaleString()} | requested=${requestedStartHour}-${requestedEndHour}h | actual=${startHour}-${endHour}h | resolution=10ms | missingChunks=${missingChunks}`);
    }

    function applyStartAndWindow() {
      const startHour = Number(document.getElementById('startHour').value);
      const windowHours = clampWindowLength(Number(document.getElementById('windowHours').value));
      const [clampedStart, clampedEnd] = clampRange(startHour, startHour + windowHours);
      setRangeInputs(clampedStart, clampedEnd);
      scheduleRangeLoad(true);
    }

    function applyStartAndEnd() {
      const startHour = Number(document.getElementById('startHour').value);
      const endHour = Number(document.getElementById('endHour').value);
      const [clampedStart, clampedEnd] = clampRange(startHour, endHour);
      setRangeInputs(clampedStart, clampedEnd);
      scheduleRangeLoad(true);
    }

    async function bootstrap() {
      await loadManifest();
      renderNavigator(`Node ${document.getElementById('nodeSelect').value}`, Number(document.getElementById('startHour').value), Number(document.getElementById('endHour').value));
      await loadRawRange();
      document.getElementById('applyRange').addEventListener('click', () => scheduleRangeLoad(true));
      document.getElementById('resetRange').addEventListener('click', async () => {
        const windowHours = defaultWindowHours(manifest.totalHours);
        setRangeInputs(0, windowHours);
        scheduleRangeLoad(true);
      });
      document.getElementById('windowHours').addEventListener('input', applyStartAndWindow);
      document.getElementById('startHour').addEventListener('input', applyStartAndWindow);
      document.getElementById('endHour').addEventListener('input', applyStartAndEnd);
      document.getElementById('nodeSelect').addEventListener('change', async () => {
        try {
          renderNavigator(`Node ${document.getElementById('nodeSelect').value}`, Number(document.getElementById('startHour').value), Number(document.getElementById('endHour').value));
          await loadRawRange();
        } catch (error) {
          setStatus(error.message);
        }
      });
    }

    bootstrap().catch(error => setStatus(error.message));
  </script>
</body>
</html>
""".replace("%DEFAULT_INITIAL_WINDOW_HOURS%", str(DEFAULT_INITIAL_WINDOW_HOURS)).replace("%MIN_WINDOW_HOURS%", str(MIN_WINDOW_HOURS)).replace("%MAX_WINDOW_HOURS%", str(MAX_WINDOW_HOURS))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build lazy-loading HTML assets for large 10ms node timeseries datasets."
    )
    parser.add_argument("input_csv", type=Path, help="Path to node_timeseries_*.csv")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for generated lazy HTML assets. Defaults to <input parent>/node_status_lazy_html.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="Rows per pandas CSV chunk while scanning the source file.",
    )
    parser.add_argument(
        "--chunk-hours",
        type=int,
        default=DEFAULT_CHUNK_HOURS,
        help="Raw-detail chunk width in hours.",
    )
    parser.add_argument(
        "--battery-column",
        choices=["battery_pct", "battery_joules"],
        default="battery_pct",
        help="Battery value to export into the viewer.",
    )
    parser.add_argument(
        "--node-ids",
        nargs="*",
        type=int,
        default=None,
        help="Optional subset of node IDs to export.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.chunk_hours <= 0:
        raise ValueError("--chunk-hours must be > 0")


def ensure_input_exists(input_csv: Path) -> None:
  if not input_csv.exists():
    raise FileNotFoundError(f"Input CSV not found: {input_csv}")
  if not input_csv.is_file():
    raise ValueError(f"Input path is not a file: {input_csv}")


def ensure_dirs(output_dir: Path, node_ids: np.ndarray) -> None:
    (output_dir / "chunks").mkdir(parents=True, exist_ok=True)
    for node_id in node_ids:
        (output_dir / "chunks" / f"node_{int(node_id)}").mkdir(parents=True, exist_ok=True)


def clear_previous_assets(output_dir: Path) -> None:
    removed = 0
    for path in output_dir.rglob("*.csv"):
        path.unlink()
        removed += 1
    for path in output_dir.glob("*.html"):
        path.unlink()
        removed += 1
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
        removed += 1
    overview_dir = output_dir / "overview"
    if overview_dir.exists():
      shutil.rmtree(overview_dir)
      removed += 1
    if removed > 0:
        print(f"Cleared {removed} stale lazy-viewer asset files from {output_dir}")


def append_chunk_csv(output_path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(output_path, mode="a", header=not output_path.exists(), index=False)


def estimate_total_hours_from_csv(input_csv: Path) -> float:
  with input_csv.open("rb") as handle:
    handle.seek(0, 2)
    position = handle.tell()
    buffer = bytearray()
    while position > 0:
      position -= 1
      handle.seek(position)
      byte = handle.read(1)
      if byte == b"\n" and buffer:
        break
      buffer.extend(byte)
  last_line = bytes(reversed(buffer)).decode("utf-8").strip()
  if not last_line:
    return 0.0
  time_ms = int(last_line.split(",", 1)[0])
  return time_ms / 3_600_000.0


def build_lazy_assets(args: argparse.Namespace) -> tuple[Path, np.ndarray, float]:
    usecols = [
        "time_ms",
        "node_id",
        "irradiance_multiplier",
        "charging_rate_mw",
        "power_consumption_mw",
        args.battery_column,
        "node_state",
    ]
    reader = pd.read_csv(args.input_csv, usecols=usecols, chunksize=args.chunk_size)
    first_chunk = next(reader, None)
    if first_chunk is None:
        raise ValueError(f"Input CSV is empty: {args.input_csv}")

    node_ids = np.sort(first_chunk["node_id"].unique().astype(np.int64))
    if args.node_ids is not None:
        node_ids = node_ids[np.isin(node_ids, sorted(set(args.node_ids)))]
        if len(node_ids) == 0:
            raise ValueError("None of the requested --node-ids were found in the CSV")

    output_dir = args.output_dir or (args.input_csv.parent / "node_status_lazy_html")
    output_dir.mkdir(parents=True, exist_ok=True)
    clear_previous_assets(output_dir)
    ensure_dirs(output_dir, node_ids)

    max_time_ms = 0
    raw_chunk_ms = args.chunk_hours * 3_600_000
    estimated_total_hours = estimate_total_hours_from_csv(args.input_csv)

    manifest = {
      "nodeIds": [int(node_id) for node_id in node_ids.tolist()],
      "batteryColumn": args.battery_column,
      "batteryLabel": "Battery Remaining (%)" if args.battery_column == "battery_pct" else "Battery Remaining (J)",
      "chunkHours": args.chunk_hours,
      "totalHours": estimated_total_hours,
      "inputCsv": str(args.input_csv.name),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output_dir / "index.html").write_text(HTML_TEMPLATE, encoding="utf-8")

    def process_chunk(chunk: pd.DataFrame, chunk_number: int) -> None:
        nonlocal max_time_ms
        chunk = chunk[chunk["node_id"].isin(node_ids)].copy()
        if chunk.empty:
            return

        chunk["state_code"] = chunk["node_state"].map(STATE_TO_CODE).fillna(-1).astype(np.int8)
        chunk["elapsed_hours"] = chunk["time_ms"].astype(np.float64) / 3_600_000.0
        chunk["raw_chunk"] = (chunk["time_ms"] // raw_chunk_ms).astype(np.int64)

        max_time_ms = max(max_time_ms, int(chunk["time_ms"].max()))

        raw_export = chunk[[
            "time_ms",
            "elapsed_hours",
            "irradiance_multiplier",
            "charging_rate_mw",
            "power_consumption_mw",
            args.battery_column,
            "state_code",
            "node_id",
            "raw_chunk",
        ]]
        raw_export = raw_export.rename(columns={args.battery_column: "battery_value"})
        raw_export = raw_export.sort_values(["node_id", "raw_chunk", "time_ms"], kind="stable")

        for (node_id, raw_chunk), group in raw_export.groupby(["node_id", "raw_chunk"], sort=False):
            output_path = output_dir / "chunks" / f"node_{int(node_id)}" / f"chunk_{int(raw_chunk):03d}.csv"
            append_chunk_csv(output_path, group.drop(columns=["node_id", "raw_chunk"]))

        if chunk_number % 25 == 0:
            print(f"Processed source chunk {chunk_number:,}")

    process_chunk(first_chunk, 1)
    for chunk_number, chunk in enumerate(reader, start=2):
        process_chunk(chunk, chunk_number)

    manifest["totalHours"] = max_time_ms / 3_600_000.0
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return output_dir, node_ids, manifest["totalHours"]


def main() -> None:
    args = parse_args()
    ensure_input_exists(args.input_csv)
    validate_args(args)
    output_dir, node_ids, total_hours = build_lazy_assets(args)
    print(
        f"Lazy HTML assets written to: {output_dir} | nodes={len(node_ids)} | totalHours={total_hours:.3f}"
    )


if __name__ == "__main__":
    main()