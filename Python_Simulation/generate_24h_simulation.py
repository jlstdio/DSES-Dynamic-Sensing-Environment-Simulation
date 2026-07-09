#!/usr/bin/env python3

"""
Generates 24 hours of environment simulation for a set of nodes and trees, computing sun positions, shadows, irradiance, and charging inputs over time.

Battery capacity and remaining-charge simulation is intentionally handled later by battery_option_scenarios.py.
"""
import argparse
import csv
import json
import math
import wave
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate 24h solar environment simulation and combined visualization HTML.")
    parser.add_argument("--events-per-hour", type=int, default=50, help="Random environmental sound events per hour.")
    parser.add_argument("--sound-dataset", type=str, default="ASC24", help="Sound dataset key (default: ASC24).")
    parser.add_argument("--sound-root", type=Path, default=None, help="Root path containing downloaded sound datasets.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible sound events.")
    parser.add_argument("--event-duration-sec", type=float, default=2.0, help="Default duration per sound event when no metadata is available.")
    parser.add_argument("--event-min-height-m", type=float, default=0.2, help="Minimum source height above terrain in meters.")
    parser.add_argument("--event-max-height-m", type=float, default=5.0, help="Maximum source height above terrain in meters.")
    return parser.parse_args()


args = parse_args()

# Path setup
project_root = Path(__file__).resolve().parent.parent.parent
python_root = Path(__file__).resolve().parent
export_dir = python_root / "exports" / "latest"
sound_root = args.sound_root or (python_root / "audio")


DEFAULT_CONFIG = {
    "dataset": {
        "root": "event_dataset",
        "name": "ASC24",
    },
    "acoustic": {
        "source_audio_db": 50.0,
        "simulation_source_db": 75.0,
        "min_reachable_db": 40.0,
        "reference_distance_m": 1.0,
        "distance_doubling_loss_db": 6.0,
        "speed_of_sound_mps": 343.0,
        "space_width_m": 1000.0,
        "space_height_m": 1000.0,
        "node_grid_max_columns": 10,
        "capture_sample_rate_hz": 16000,
        "fallback_frequency_hz": 440.0,
    }
}


def deep_merge_config(defaults: dict, overrides: dict) -> dict:
    merged = json.loads(json.dumps(defaults))
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        return DEFAULT_CONFIG
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Could not parse config file: {config_path}") from exc
    return deep_merge_config(DEFAULT_CONFIG, loaded)


config = load_config(python_root / "config.json")
acoustic_config = config["acoustic"]
dataset_config = config.get("dataset", {})

dataset_name = str(dataset_config.get("name") or args.sound_dataset)
dataset_root_cfg = str(dataset_config.get("root") or "event_dataset")
sound_root = args.sound_root or (python_root / dataset_root_cfg)

if args.events_per_hour < 0:
    raise ValueError("--events-per-hour must be >= 0")
if args.event_duration_sec <= 0:
    raise ValueError("--event-duration-sec must be > 0")
if args.event_min_height_m <= 0:
    raise ValueError("--event-min-height-m must be > 0")
if args.event_max_height_m <= 0:
    raise ValueError("--event-max-height-m must be > 0")
if args.event_max_height_m > 5.0:
    raise ValueError("--event-max-height-m must be <= 5.0")
if args.event_min_height_m > args.event_max_height_m:
    raise ValueError("--event-min-height-m must be <= --event-max-height-m")
if float(acoustic_config["source_audio_db"]) <= 0:
    raise ValueError("acoustic.source_audio_db must be > 0")
if float(acoustic_config["simulation_source_db"]) <= 0:
    raise ValueError("acoustic.simulation_source_db must be > 0")
if float(acoustic_config["min_reachable_db"]) <= 0:
    raise ValueError("acoustic.min_reachable_db must be > 0")
if float(acoustic_config["reference_distance_m"]) <= 0:
    raise ValueError("acoustic.reference_distance_m must be > 0")
if float(acoustic_config["distance_doubling_loss_db"]) <= 0:
    raise ValueError("acoustic.distance_doubling_loss_db must be > 0")
if float(acoustic_config["speed_of_sound_mps"]) <= 0:
    raise ValueError("acoustic.speed_of_sound_mps must be > 0")
if int(acoustic_config["node_grid_max_columns"]) < 1:
    raise ValueError("acoustic.node_grid_max_columns must be >= 1")

# Load base data
trees_path = export_dir / "trees.csv"
nodes_path = export_dir / "nodes.csv"
trees_df = pd.read_csv(trees_path)
nodes_df = pd.read_csv(nodes_path)

print(f"\n✓ Loaded trees: {len(trees_df)} | nodes: {len(nodes_df)}")

# Geometry setup
tree_x = trees_df["x"].to_numpy(dtype=float)
tree_z = trees_df["z"].to_numpy(dtype=float)
tree_h = trees_df["height"].to_numpy(dtype=float) if "height" in trees_df.columns else np.full(len(trees_df), 18.0)
tree_r = trees_df["radius"].to_numpy(dtype=float) if "radius" in trees_df.columns else np.full(len(trees_df), 2.5)
node_x = nodes_df["x"].to_numpy(dtype=float)
node_z = nodes_df["z"].to_numpy(dtype=float)
P_nodes = np.stack([node_x, node_z], axis=1)

# Shadow parameters
leaf_transmittance = 0.25
edge_softness_m = 1.5

# Etc.
total_duration_hours = 24
sim_dt_ms = 10
total_duration_ms = int(total_duration_hours * 60 * 60 * 1000)
total_steps = total_duration_ms // sim_dt_ms + 1

# 1-second sampling output
output_step_ms = 1000
frame_stride = max(1, output_step_ms // sim_dt_ms)
frame_indices = np.arange(0, total_steps, frame_stride, dtype=np.int64)
if frame_indices[-1] != total_steps - 1:
    frame_indices = np.append(frame_indices, total_steps - 1)

time_ms = frame_indices * sim_dt_ms
time_hours = time_ms / (1000.0 * 60.0 * 60.0)
n_steps = len(frame_indices)

# print(f"# Time parameters:")
# print(f"  Total duration: {total_duration_hours}h = {total_duration_ms:,}ms")
# print(f"  Base dt: {sim_dt_ms}ms")
# print(f"  Total steps: {total_steps:,}")
# print(f"  Output step: {output_step_ms}ms")
# print(f"  Output samples: {n_steps} (stride={frame_stride})")

# Sun arc parameters
min_elev_deg = 8.0
max_elev_deg = 70.0
az_start_deg = 90.0
az_end_deg = 270.0
sunrise_start = 5.0   # 5:00 AM
sunrise_end = 7.0     # 7:00 AM
sunset_start = 17.0   # 5:00 PM
sunset_end = 19.0     # 7:00 PM

def sun_elevation_for_hour(hour):
    """Compute sun elevation with gradual sunrise and sunset."""
    if hour < sunrise_start or hour >= sunset_end:
        return -20.0
    elif hour < sunrise_end:
        # Sunrise phase (5-7h): elevation rises from -20 to max
        phase = (hour - sunrise_start) / (sunrise_end - sunrise_start)  # 0~1
        return -20.0 + 90.0 * np.sin(np.pi * phase / 2.0)
    elif hour < sunset_start:
        # Daytime phase (7-17h): normal sine arc
        phase = np.pi * (hour - sunrise_end) / (sunset_start - sunrise_end)  # 0~π
        return min_elev_deg + (max_elev_deg - min_elev_deg) * np.sin(phase)
    else:
        # Sunset phase (17-19h): elevation falls from max to -20
        phase = (hour - sunset_start) / (sunset_end - sunset_start)  # 0~1
        return max_elev_deg - 90.0 * np.sin(np.pi * phase / 2.0)

def sun_azimuth_for_hour(hour):
    """Compute sun azimuth with smooth transition."""
    if hour < sunrise_start or hour >= sunset_end:
        return 270.0  # West
    else:
        # Azimuth moves from 90 (E) to 270 (W) during daytime
        progress = (hour - sunrise_start) / (sunset_end - sunrise_start)  # 0~1
        return az_start_deg + (az_end_deg - az_start_deg) * progress

# Calculate sun position for entire 24-hour cycle
print(f"# Computing sun positions and node shadows...")
sun_azimuth_deg_series = np.zeros(n_steps)
sun_elevation_deg_series = np.zeros(n_steps)

for i, hour in enumerate(time_hours):
    sun_elevation_deg_series[i] = sun_elevation_for_hour(hour)
    sun_azimuth_deg_series[i] = sun_azimuth_for_hour(hour)

def compute_node_shade_for_sun(azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    if elevation_deg <= 0:
        return np.ones(len(P_nodes), dtype=float)  # Full darkness
    
    elev = np.deg2rad(np.clip(elevation_deg, 1.0, 89.0))
    az = np.deg2rad(azimuth_deg)
    sun_dx = np.sin(az)
    sun_dz = np.cos(az)
    shadow_dx, shadow_dz = -sun_dx, -sun_dz
    norm = np.hypot(shadow_dx, shadow_dz)
    shadow_dx, shadow_dz = shadow_dx / norm, shadow_dz / norm
    shadow_len = tree_h / np.tan(elev)
    shade = np.zeros(len(P_nodes), dtype=float)
    shadow_dir = np.array([shadow_dx, shadow_dz], dtype=float)
    
    for i in range(len(tree_x)):
        A = np.array([tree_x[i], tree_z[i]], dtype=float)
        B = A + shadow_len[i] * shadow_dir
        AB = B - A
        AB2 = float(np.dot(AB, AB))
        if AB2 <= 1e-9:
            continue
        AP = P_nodes - A
        t = np.clip((AP @ AB) / AB2, 0.0, 1.0)
        closest = A + t[:, None] * AB[None, :]
        dist = np.linalg.norm(P_nodes - closest, axis=1)
        signed = dist - tree_r[i]
        contribution = np.clip(1.0 - (signed / max(edge_softness_m, 1e-6)), 0.0, 1.0)
        shade = np.maximum(shade, contribution)
    
    return shade

# Compute irradiance directly at each 1-second output sample.
shadow_azimuth_deg_series = np.zeros(n_steps)
shadow_elevation_deg_series = np.zeros(n_steps)

for i, hour in enumerate(time_hours):
    shadow_elevation_deg_series[i] = sun_elevation_for_hour(hour)
    shadow_azimuth_deg_series[i] = sun_azimuth_for_hour(hour)

irradiance_keyframes = []
for i, (az_deg, el_deg) in enumerate(zip(shadow_azimuth_deg_series, shadow_elevation_deg_series)):
    if i % max(1, n_steps // 10) == 0:
        print(f"  {int(100*i/n_steps)}% complete")

    if el_deg <= 0:
        irr = np.zeros(len(P_nodes), dtype=float)
    else:
        shade = compute_node_shade_for_sun(float(az_deg), float(el_deg))
        irr = 1.0 - shade * (1.0 - leaf_transmittance)

    irradiance_keyframes.append(irr)

irradiance_keyframes = np.stack(irradiance_keyframes, axis=0)
irradiance_frames = irradiance_keyframes
print(f"  ✓ Computed irradiance for {n_steps:,} output samples")

# ============================================================================
# Charging input export only
# ============================================================================
print(f"\n🔋 Building charging input log (24h × {len(nodes_df)} nodes)...")

n_nodes = len(nodes_df)
n_time_steps = len(frame_indices)

panel_area_m2 = 0.015625
panel_efficiency = 0.15
solar_const = 1361.0
transmit = 0.7

charging_rate_mw = np.zeros((n_nodes, n_time_steps), dtype=float)
for t in range(n_time_steps):
    if t % max(1, n_time_steps // 10) == 0:
        print(f"  {int(100*t/n_time_steps)}% complete (t={time_hours[t]:.2f}h)")
    for node_idx in range(n_nodes):
        irr = irradiance_frames[t, node_idx]
        harvest_w = solar_const * transmit * irr * panel_area_m2 * panel_efficiency
        charging_rate_mw[node_idx, t] = harvest_w * 1000.0

print(f"\n✓ Charging inputs complete!")

# Build dataframe
print(f"\n📊 Building output CSV...")
csv_path = export_dir / "node_simulation_log.csv"
csv_columns = [
    "time_ms",
    "time_hours",
    "time_hhmmss",
    "node_id",
    "node_x",
    "node_z",
    "sun_azimuth_deg",
    "sun_elevation_deg",
    "irradiance_multiplier",
    "charging_rate_mw",
]
node_ids_for_csv = nodes_df["node_id"].astype(int).to_numpy() if "node_id" in nodes_df.columns else np.arange(n_nodes)
node_x_for_csv = nodes_df["x"].to_numpy()
node_z_for_csv = nodes_df["z"].to_numpy()

total_rows = n_time_steps * n_nodes
daytime_rows = 0
nighttime_rows = 0
daytime_charging_sum = 0.0
nighttime_charging_sum = 0.0
daytime_charging_max = 0.0

with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
    writer = csv.writer(csv_file)
    writer.writerow(csv_columns)

    rows_written = 0
    for t in range(n_time_steps):
        if t % max(1, n_time_steps // 10) == 0:
            print(f"  CSV {int(100*t/n_time_steps)}% complete (t={time_hours[t]:.2f}h)")

        total_s = int(time_ms[t] // 1000)
        h = total_s // 3600
        m = (total_s % 3600) // 60
        s = total_s % 60
        time_hhmmss = f"{h:02d}:{m:02d}:{s:02d}"
        sun_azimuth = sun_azimuth_deg_series[t]
        sun_elevation = sun_elevation_deg_series[t]
        is_daytime = sun_elevation > 0

        for node_idx in range(n_nodes):
            charge_mw = float(charging_rate_mw[node_idx, t])
            if is_daytime:
                daytime_rows += 1
                daytime_charging_sum += charge_mw
                daytime_charging_max = max(daytime_charging_max, charge_mw)
            else:
                nighttime_rows += 1
                nighttime_charging_sum += charge_mw

            writer.writerow([
                int(time_ms[t]),
                float(time_hours[t]),
                time_hhmmss,
                int(node_ids_for_csv[node_idx]),
                float(node_x_for_csv[node_idx]),
                float(node_z_for_csv[node_idx]),
                float(sun_azimuth),
                float(sun_elevation),
                float(irradiance_frames[t, node_idx]),
                charge_mw,
            ])
            rows_written += 1

print(f"✓ Saved: {csv_path} ({rows_written:,} rows)")

# Analysis
print(f"\n📈 Analysis:")
daytime_avg_charging = daytime_charging_sum / daytime_rows if daytime_rows else 0.0
nighttime_avg_charging = nighttime_charging_sum / nighttime_rows if nighttime_rows else 0.0

print(f"\n☀️ Daytime (elevation > 0): {daytime_rows:,} rows ({daytime_rows/total_rows*100:.1f}%)")
print(f"   Avg charging: {daytime_avg_charging:.1f} mW")
print(f"   Max charging: {daytime_charging_max:.1f} mW")

print(f"\n🌙 Nighttime (elevation ≤ 0): {nighttime_rows:,} rows ({nighttime_rows/total_rows*100:.1f}%)")
print(f"   Avg charging: {nighttime_avg_charging:.4f} mW")

print(f"\n✅ 24-hour simulation complete!")


def load_manifest_bounds(manifest_path: Path):
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    required = ["minX", "maxX", "minZ", "maxZ"]
    if not all(key in manifest for key in required):
        return None
    try:
        min_x = float(manifest["minX"])
        max_x = float(manifest["maxX"])
        min_z = float(manifest["minZ"])
        max_z = float(manifest["maxZ"])
    except Exception:
        return None
    if max_x <= min_x or max_z <= min_z:
        return None
    return min_x, max_x, min_z, max_z


def load_terrain(heightmap_path: Path, manifest_path: Path):
    preview_df = pd.read_csv(heightmap_path)
    lowered = {str(c).strip().lower(): c for c in preview_df.columns}
    if {"x", "y", "z"}.issubset(lowered.keys()):
        df = preview_df.rename(columns={lowered["x"]: "x", lowered["y"]: "y", lowered["z"]: "z"})
        x_vals = np.sort(df["x"].unique())
        z_vals = np.sort(df["z"].unique())
        pivot = df.pivot(index="z", columns="x", values="y").reindex(index=z_vals, columns=x_vals)
        return x_vals, z_vals, pivot.values.astype(float), "xyz"

    grid_df = pd.read_csv(heightmap_path, header=None)
    grid_df = grid_df.dropna(how="all").dropna(axis=1, how="all")
    grid_df = grid_df.apply(pd.to_numeric, errors="coerce")
    grid_df = grid_df.dropna(how="all").dropna(axis=1, how="all")
    if grid_df.empty:
        raise ValueError("heightmap.csv could not be parsed as xyz table or numeric grid.")

    terrain = grid_df.to_numpy(dtype=float)
    x_vals = np.arange(terrain.shape[1], dtype=float)
    z_vals = np.arange(terrain.shape[0], dtype=float)
    bounds = load_manifest_bounds(manifest_path)
    if bounds is not None:
        min_x, max_x, min_z, max_z = bounds
        x_vals = np.linspace(min_x, max_x, num=terrain.shape[1], endpoint=True)
        z_vals = np.linspace(min_z, max_z, num=terrain.shape[0], endpoint=True)
    return x_vals, z_vals, terrain, "grid"


def resolve_dataset_dir(sound_root_path: Path, dataset_name: str) -> Path:
    candidate = sound_root_path / dataset_name
    if not candidate.exists() or not candidate.is_dir():
        raise FileNotFoundError(f"Dataset folder not found: {candidate}")
    return candidate


def load_dataset_metadata(dataset_dir: Path) -> dict:
    meta_path = dataset_dir / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.json not found in dataset root: {dataset_dir}")
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Could not parse metadata.json: {meta_path}") from exc
    audio_meta = metadata.get("audio", {})
    base_dir = str(audio_meta.get("base_dir", "."))
    wav_glob = str(audio_meta.get("glob", "**/*.wav"))
    label_mode = str(audio_meta.get("label_mode", "parent_dir"))
    return {
        "dataset_name": str(metadata.get("dataset_name", dataset_dir.name)),
        "audio_base_dir": base_dir,
        "audio_glob": wav_glob,
        "label_mode": label_mode,
    }


def _wav_label_from_path(wav_path: Path, label_mode: str) -> str:
    if label_mode == "parent_dir":
        return wav_path.parent.name
    if label_mode == "none":
        return "audio_event"
    return wav_path.parent.name


def build_dataset_audio_index(dataset_dir: Path, metadata: dict) -> tuple[list[Path], list[str], list[str]]:
    base_dir = (dataset_dir / metadata["audio_base_dir"]).resolve()
    if not base_dir.exists() or not base_dir.is_dir():
        raise FileNotFoundError(f"Audio base directory not found: {base_dir}")

    wav_files = sorted([p for p in base_dir.glob(metadata["audio_glob"]) if p.is_file() and p.suffix.lower() in {".wav", ".wave"}])
    if not wav_files:
        raise FileNotFoundError(f"No WAV files found using glob '{metadata['audio_glob']}' under {base_dir}")

    readable_wavs: list[Path] = []
    wav_labels: list[str] = []
    unreadable_count = 0
    for wav_path in wav_files:
        if _read_wav_mono(wav_path) is None:
            unreadable_count += 1
            continue
        readable_wavs.append(wav_path)
        wav_labels.append(_wav_label_from_path(wav_path, metadata["label_mode"]))

    if not readable_wavs:
        raise ValueError(f"All WAV files are unreadable under {base_dir}.")

    labels = sorted(set(wav_labels))

    if unreadable_count > 0:
        print(f"⚠ Skipped unreadable wav files: {unreadable_count}")

    return readable_wavs, labels, wav_labels


def bilinear_terrain_height(x: float, z: float, x_vals: np.ndarray, z_vals: np.ndarray, terrain: np.ndarray) -> float:
    x_idx = np.searchsorted(x_vals, x)
    z_idx = np.searchsorted(z_vals, z)
    x0_i = max(0, min(len(x_vals) - 1, x_idx - 1))
    x1_i = max(0, min(len(x_vals) - 1, x_idx))
    z0_i = max(0, min(len(z_vals) - 1, z_idx - 1))
    z1_i = max(0, min(len(z_vals) - 1, z_idx))

    x0 = float(x_vals[x0_i])
    x1 = float(x_vals[x1_i])
    z0 = float(z_vals[z0_i])
    z1 = float(z_vals[z1_i])
    q11 = float(terrain[z0_i, x0_i])
    q21 = float(terrain[z0_i, x1_i])
    q12 = float(terrain[z1_i, x0_i])
    q22 = float(terrain[z1_i, x1_i])

    if x1 == x0 and z1 == z0:
        return q11
    if x1 == x0:
        tz = 0.0 if z1 == z0 else (z - z0) / (z1 - z0)
        return q11 * (1.0 - tz) + q12 * tz
    if z1 == z0:
        tx = (x - x0) / (x1 - x0)
        return q11 * (1.0 - tx) + q21 * tx

    tx = (x - x0) / (x1 - x0)
    tz = (z - z0) / (z1 - z0)
    a = q11 * (1.0 - tx) + q21 * tx
    b = q12 * (1.0 - tx) + q22 * tx
    return a * (1.0 - tz) + b * tz


def generate_sound_events(
    total_hours: float,
    bounds: tuple[float, float, float, float],
    x_vals: np.ndarray,
    z_vals: np.ndarray,
    terrain: np.ndarray,
    labels: list[str],
    dataset_wavs: list[Path],
    dataset_wav_labels: list[str],
    events_per_hour: int,
    duration_sec: float,
    min_height_m: float,
    max_height_m: float,
    seed: int,
) -> pd.DataFrame:
    min_x, max_x, min_z, max_z = bounds
    total_ms = int(total_hours * 3_600_000)
    duration_ms = int(duration_sec * 1000.0)
    rng = np.random.default_rng(seed)
    if len(dataset_wavs) != len(dataset_wav_labels):
        raise ValueError("dataset_wavs and dataset_wav_labels must have identical lengths.")
    if not dataset_wavs:
        raise ValueError("dataset_wavs is empty. Cannot generate events.")
    label_to_index = {label: idx for idx, label in enumerate(labels)}

    rows = [
        {
            "event_id": -1,
            "is_global": 1,
            "start_ms": 0,
            "end_ms": total_ms,
            "x": np.nan,
            "z": np.nan,
            "y": np.nan,
            "ground_y": np.nan,
            "height_above_ground_m": np.nan,
            "label_index": -1,
            "label_name": "white_noise_global",
            "audio_file": "",
            "dataset": "white_noise",
        }
    ]

    event_id = 0
    for hour in range(int(np.ceil(total_hours))):
        for _ in range(events_per_hour):
            start_ms = int((hour + float(rng.random())) * 3_600_000)
            if start_ms >= total_ms:
                continue
            end_ms = min(total_ms, start_ms + duration_ms)

            x = float(rng.uniform(min_x, max_x))
            z = float(rng.uniform(min_z, max_z))
            ground_y = bilinear_terrain_height(x, z, x_vals, z_vals, terrain)
            offset = float(rng.uniform(min_height_m, max_height_m))
            y = ground_y + offset

            wav_idx = int(rng.integers(0, len(dataset_wavs)))
            selected_wav = dataset_wavs[wav_idx]
            label_name = dataset_wav_labels[wav_idx]
            label_index = label_to_index.get(label_name)
            if label_index is None:
                labels.append(label_name)
                label_index = len(labels) - 1
                label_to_index[label_name] = label_index

            rows.append(
                {
                    "event_id": event_id,
                    "is_global": 0,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "x": x,
                    "z": z,
                    "y": y,
                    "ground_y": ground_y,
                    "height_above_ground_m": offset,
                    "label_index": label_index,
                    "label_name": label_name,
                    "audio_file": str(selected_wav),
                    "dataset": args.sound_dataset,
                }
            )
            event_id += 1

    events_df = pd.DataFrame(rows)
    return events_df.sort_values(["start_ms", "event_id"], kind="mergesort").reset_index(drop=True)


def build_shadow_direction(azimuth_deg: float, elevation_deg: float):
    elev = np.deg2rad(np.clip(elevation_deg, 1.0, 89.0))
    az = np.deg2rad(azimuth_deg)
    sun_dx = np.sin(az)
    sun_dz = np.cos(az)
    shadow_dx, shadow_dz = -sun_dx, -sun_dz
    norm = np.hypot(shadow_dx, shadow_dz)
    return shadow_dx / norm, shadow_dz / norm, np.tan(elev)


def compute_node_shade_for_sun(node_xy: np.ndarray, tree_xy: np.ndarray, tree_h: np.ndarray, tree_r: np.ndarray, azimuth_deg: float, elevation_deg: float, edge_softness_m: float) -> np.ndarray:
    if elevation_deg <= 0:
        return np.ones(len(node_xy), dtype=float)
    shadow_dx, shadow_dz, tan_elev = build_shadow_direction(azimuth_deg, elevation_deg)
    shadow_len = tree_h / tan_elev
    shade = np.zeros(len(node_xy), dtype=float)
    shadow_dir = np.array([shadow_dx, shadow_dz], dtype=float)
    for i in range(len(tree_xy)):
        A = tree_xy[i]
        B = A + shadow_len[i] * shadow_dir
        AB = B - A
        AB2 = float(np.dot(AB, AB))
        if AB2 <= 1e-9:
            continue
        AP = node_xy - A
        t = np.clip((AP @ AB) / AB2, 0.0, 1.0)
        closest = A + t[:, None] * AB[None, :]
        dist = np.linalg.norm(node_xy - closest, axis=1)
        signed = dist - tree_r[i]
        contribution = np.clip(1.0 - (signed / max(edge_softness_m, 1e-6)), 0.0, 1.0)
        shade = np.maximum(shade, contribution)
    return shade


def build_shadow_segments(tree_xy: np.ndarray, tree_h: np.ndarray, azimuth_deg: float, elevation_deg: float, sample_count: int):
    shadow_dx, shadow_dz, tan_elev = build_shadow_direction(azimuth_deg, elevation_deg)
    shadow_len = tree_h / tan_elev
    idx = np.linspace(0, len(tree_xy) - 1, num=min(sample_count, len(tree_xy)), dtype=int)
    xs, zs = [], []
    for i in idx:
        x0, z0 = tree_xy[i]
        x1 = x0 + shadow_len[i] * shadow_dx
        z1 = z0 + shadow_len[i] * shadow_dz
        xs.extend([x0, x1, None])
        zs.extend([z0, z1, None])
    return xs, zs


def _round_float_list(values, digits: int = 4) -> list:
    return [round(float(v), digits) for v in values]


def threshold_radius_m(cfg: dict) -> float:
    reference = float(cfg["reference_distance_m"])
    source_db = float(cfg["simulation_source_db"])
    threshold_db = float(cfg["min_reachable_db"])
    loss_db = float(cfg["distance_doubling_loss_db"])
    if loss_db <= 0:
        return reference
    return max(reference, reference * (2.0 ** ((source_db - threshold_db) / loss_db)))


def _active_sound_payload(active: pd.DataFrame, label_map: dict[int, str], reach_radius_m: float) -> dict:
    if active.empty:
        return {"x": [], "z": [], "text": [], "desc": [], "radius_m": []}
    label_idx = active["label_index"].astype(int).tolist()
    count = len(label_idx)
    return {
        "x": _round_float_list(active["x"], 3),
        "z": _round_float_list(active["z"], 3),
        "text": [str(idx) for idx in label_idx],
        "desc": [f"{idx}: {label_map.get(idx, 'unknown')}" for idx in label_idx],
        "radius_m": [round(float(reach_radius_m), 3)] * count,
    }


def received_db_for_distance(distance_m: float, cfg: dict) -> float:
    safe_distance = max(float(distance_m), float(cfg["reference_distance_m"]))
    ratio = safe_distance / float(cfg["reference_distance_m"])
    return float(cfg["simulation_source_db"]) - float(cfg["distance_doubling_loss_db"]) * math.log2(max(ratio, 1.0))


def _read_wav_mono(source_path: Path) -> tuple[np.ndarray, int] | None:
    try:
        with wave.open(str(source_path), "rb") as reader:
            n_channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            sample_rate = reader.getframerate()
            frames = reader.readframes(reader.getnframes())
    except Exception:
        return None
    if sample_width == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        return None
    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)
    return np.clip(data, -1.0, 1.0), sample_rate


def write_attenuated_wav(source_path: Path | None, output_path: Path, duration_sec: float, target_db: float, cfg: dict) -> None:
    if source_path is not None:
        wav_data = _read_wav_mono(source_path)
    else:
        wav_data = None
    if wav_data is None:
        raise FileNotFoundError("Could not decode source WAV for event capture.")

    samples, sample_rate = wav_data
    target_count = max(1, int(duration_sec * sample_rate))
    if len(samples) < target_count:
        repeats = int(np.ceil(target_count / max(1, len(samples))))
        samples = np.tile(samples, repeats)
    samples = samples[:target_count]
    gain = 10.0 ** ((target_db - float(cfg["source_audio_db"])) / 20.0)
    samples = samples * gain
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(samples, -0.95, 0.95)
    pcm_i16 = (pcm * 32767.0).astype("<i2")
    with wave.open(str(output_path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm_i16.tobytes())


def build_acoustic_node_arrivals(
    event_points: pd.DataFrame,
    nodes_df_local: pd.DataFrame,
    cfg: dict,
    export_dir: Path,
) -> pd.DataFrame:
    """Compute source-to-node acoustic propagation and export node capture WAVs."""
    arrivals_dir = export_dir / "acoustic_node_wavs"
    if arrivals_dir.exists():
        for old_wav in arrivals_dir.rglob("*.wav"):
            old_wav.unlink()
        for old_csv in arrivals_dir.rglob("*.csv"):
            old_csv.unlink()
    arrivals_dir.mkdir(parents=True, exist_ok=True)

    node_ids = nodes_df_local["node_id"].astype(int).to_numpy() if "node_id" in nodes_df_local.columns else np.arange(len(nodes_df_local))
    node_x = nodes_df_local["x"].to_numpy(dtype=float)
    node_z = nodes_df_local["z"].to_numpy(dtype=float)
    node_y = nodes_df_local["y"].to_numpy(dtype=float) if "y" in nodes_df_local.columns else np.zeros(len(nodes_df_local), dtype=float)
    threshold_db = float(cfg["min_reachable_db"])
    source_db = float(cfg["simulation_source_db"])
    sound_speed_mps = float(cfg.get("speed_of_sound_mps", 343.0))

    rows = []
    for _, event in event_points.iterrows():
        sx, sy, sz = float(event["x"]), float(event["y"]), float(event["z"])
        dx = node_x - sx
        dy = node_y - sy
        dz = node_z - sz
        dist = np.sqrt(dx * dx + dy * dy + dz * dz)
        received = np.array([received_db_for_distance(d, cfg) for d in dist], dtype=float)
        reachable_idx = np.where(received >= threshold_db)[0]
        label_name = str(event["label_name"])
        source_audio_raw = str(event.get("audio_file", "")).strip()
        if not source_audio_raw:
            raise ValueError(f"Event {int(event['event_id'])} is missing audio_file.")
        source_audio = Path(source_audio_raw)
        if not source_audio.exists():
            raise FileNotFoundError(f"Event source audio not found: {source_audio}")
        for node_idx in reachable_idx:
            node_id = int(node_ids[node_idx])
            received_db = float(received[node_idx])
            node_dir = arrivals_dir / f"node_{node_id:03d}"
            wav_name = f"event_{int(event['event_id']):06d}_{received_db:.1f}db.wav"
            wav_path = node_dir / wav_name
            duration_sec = max(0.05, (float(event["end_ms"]) - float(event["start_ms"])) / 1000.0)
            delay_ms = int(round(float(dist[node_idx]) / sound_speed_mps * 1000.0))
            arrival_start_ms = int(event["start_ms"]) + delay_ms
            arrival_end_ms = int(event["end_ms"]) + delay_ms
            write_attenuated_wav(source_audio, wav_path, duration_sec, received_db, cfg)
            rows.append(
                {
                    "event_id": int(event["event_id"]),
                    "node_id": node_id,
                    "event_start_ms": int(event["start_ms"]),
                    "event_end_ms": int(event["end_ms"]),
                    "arrival_start_ms": arrival_start_ms,
                    "arrival_end_ms": arrival_end_ms,
                    "sound_x": sx,
                    "sound_y": sy,
                    "sound_z": sz,
                    "node_x": float(node_x[node_idx]),
                    "node_y": float(node_y[node_idx]),
                    "node_z": float(node_z[node_idx]),
                    "distance_m": float(dist[node_idx]),
                    "arrival_delay_ms": delay_ms,
                    "source_db": source_db,
                    "received_db": received_db,
                    "threshold_db": threshold_db,
                    "label_index": int(event["label_index"]),
                    "label_name": label_name,
                    "audio_file": str(source_audio),
                    "node_wav_file": str(wav_path.relative_to(export_dir)),
                }
            )

    arrivals_df = pd.DataFrame(rows)
    if not arrivals_df.empty:
        arrivals_df = arrivals_df.sort_values(["arrival_start_ms", "node_id", "event_id"], kind="mergesort").reset_index(drop=True)
    arrivals_df.to_csv(export_dir / "node_acoustic_arrivals.csv", index=False)

    if arrivals_df.empty:
        summary_df = pd.DataFrame(columns=["node_id", "actual_sound_count", "max_received_db", "mean_received_db", "first_arrival_ms", "last_arrival_ms"])
    else:
        summary_df = (
            arrivals_df.groupby("node_id", as_index=False)
            .agg(
                actual_sound_count=("event_id", "count"),
                max_received_db=("received_db", "max"),
                mean_received_db=("received_db", "mean"),
                first_arrival_ms=("arrival_start_ms", "min"),
                last_arrival_ms=("arrival_start_ms", "max"),
            )
            .sort_values("node_id")
        )
    summary_df.to_csv(export_dir / "node_acoustic_summary.csv", index=False)

    if not arrivals_df.empty:
        for node_id, node_rows in arrivals_df.groupby("node_id"):
            node_rows.to_csv(arrivals_dir / f"node_{int(node_id):03d}" / "arrivals.csv", index=False)

    print(f"✓ Saved node acoustic arrivals: {len(arrivals_df):,} rows")
    print(f"✓ Saved acoustic node WAV captures: {arrivals_dir}")
    return arrivals_df


def build_node_environment_arrays(
    arrivals_df: pd.DataFrame,
    node_ids: np.ndarray,
    time_ms: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n_frames = len(time_ms)
    n_nodes = len(node_ids)
    active_counts = np.zeros((n_frames, n_nodes), dtype=np.int16)
    max_active_db = np.zeros((n_frames, n_nodes), dtype=np.float32)
    start_deltas = np.zeros((n_frames + 1, n_nodes), dtype=np.int16)
    node_to_idx = {int(node_id): i for i, node_id in enumerate(node_ids)}

    if arrivals_df.empty:
        return np.zeros((n_frames, n_nodes), dtype=np.int16), active_counts, max_active_db

    for row in arrivals_df.itertuples(index=False):
        node_idx = node_to_idx.get(int(row.node_id))
        if node_idx is None:
            continue
        start_idx = int(np.searchsorted(time_ms, int(row.arrival_start_ms), side="left"))
        end_idx = int(np.searchsorted(time_ms, int(row.arrival_end_ms), side="left"))
        if start_idx >= n_frames:
            continue
        end_idx = max(start_idx + 1, min(end_idx, n_frames))
        active_counts[start_idx:end_idx, node_idx] += 1
        max_active_db[start_idx:end_idx, node_idx] = np.maximum(max_active_db[start_idx:end_idx, node_idx], float(row.received_db))
        start_deltas[start_idx, node_idx] += 1

    actual_counts = np.cumsum(start_deltas[:-1], axis=0).astype(np.int16)
    return actual_counts, active_counts, max_active_db


def export_node_environment_timeseries(
    export_dir: Path,
    time_ms: np.ndarray,
    time_hours: np.ndarray,
    node_ids: np.ndarray,
    charging_frames: np.ndarray,
    actual_counts: np.ndarray,
    active_counts: np.ndarray,
    max_active_db: np.ndarray,
) -> None:
    output_path = export_dir / "node_environment_timeseries.csv"
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "time_ms",
            "time_hours",
            "node_id",
            "solar_charging_mw",
            "actual_sound_count",
            "active_actual_sound_count",
            "max_active_sound_db",
        ])
        for t_idx, ms_val in enumerate(time_ms):
            for n_idx, node_id in enumerate(node_ids):
                max_db = float(max_active_db[t_idx, n_idx])
                writer.writerow([
                    int(ms_val),
                    round(float(time_hours[t_idx]), 8),
                    int(node_id),
                    round(float(charging_frames[t_idx, n_idx]), 4),
                    int(actual_counts[t_idx, n_idx]),
                    int(active_counts[t_idx, n_idx]),
                    round(max_db, 3) if max_db > 0 else "",
                ])
    print(f"✓ Saved node environment time series: {output_path}")


def export_node_arrivals_json(export_dir: Path, output_dir: Path, arrivals_df: pd.DataFrame) -> None:
    payload: dict[str, list[dict]] = {}
    if not arrivals_df.empty:
        for row in arrivals_df.itertuples(index=False):
            node_id = str(int(row.node_id))
            payload.setdefault(node_id, []).append(
                {
                    "event_id": int(row.event_id),
                    "event_start_ms": int(row.event_start_ms),
                    "arrival_start_ms": int(row.arrival_start_ms),
                    "label": str(row.label_name),
                    "distance_m": round(float(row.distance_m), 3),
                    "received_db": round(float(row.received_db), 2),
                    "wav": "../" + str(row.node_wav_file).replace("\\", "/"),
                }
            )
    (output_dir / "node_arrivals.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print("✓ Saved node arrivals popup JSON: node_arrivals.json")


def save_lazy_frame_chunks(
    output_dir: Path,
    frame_indices: np.ndarray,
    time_ms: np.ndarray,
    irradiance_frames: np.ndarray,
    event_points: pd.DataFrame,
    label_map: dict[int, str],
    node_ids: np.ndarray,
    charging_frames: np.ndarray,
    actual_counts: np.ndarray,
    active_counts: np.ndarray,
    max_active_db: np.ndarray,
    reach_radius_m: float,
    chunk_seconds: int = 900,
) -> None:
    """Save compact per-second visualization state chunks for browser-side lazy loading."""
    for old_path in output_dir.glob("frames_*.json"):
        old_path.unlink()
    manifest_path = output_dir / "frame_manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()

    n_frames = len(frame_indices)
    frames_per_chunk = max(1, int(chunk_seconds))
    chunks = []
    for start_idx in range(0, n_frames, frames_per_chunk):
        end_idx = min(start_idx + frames_per_chunk, n_frames)
        start_ms = int(time_ms[start_idx])
        end_ms = int(time_ms[end_idx - 1])
        chunk_name = f"frames_{start_ms // 60000:04d}-{end_ms // 60000:04d}.json"
        frames_payload = []
        for i in range(start_idx, end_idx):
            ms_val = int(time_ms[i])
            active = event_points[(event_points["start_ms"] <= ms_val) & (event_points["end_ms"] > ms_val)]
            frames_payload.append(
                {
                    "i": int(i),
                    "ms": ms_val,
                    "irr": _round_float_list(irradiance_frames[i], 4),
                    "sound": _active_sound_payload(active, label_map, reach_radius_m),
                    "node": {
                        "charge": _round_float_list(charging_frames[i], 3),
                        "actual": [int(v) for v in actual_counts[i]],
                        "active": [int(v) for v in active_counts[i]],
                        "maxdb": [round(float(v), 2) if float(v) > 0 else 0 for v in max_active_db[i]],
                    },
                }
            )
        chunk_payload = {
            "start_index": int(start_idx),
            "end_index": int(end_idx - 1),
            "frames": frames_payload,
        }
        (output_dir / chunk_name).write_text(json.dumps(chunk_payload, separators=(",", ":")), encoding="utf-8")
        chunks.append(
            {
                "file": chunk_name,
                "start_index": int(start_idx),
                "end_index": int(end_idx - 1),
                "start_ms": start_ms,
                "end_ms": end_ms,
            }
        )
        print(f"✓ Saved lazy frame chunk: {chunk_name} ({end_idx - start_idx} frames)")

    manifest = {
        "format": "dses-lazy-frames-v2",
        "total_frames": int(n_frames),
        "output_step_ms": 1000,
        "chunk_seconds": int(chunk_seconds),
        "node_ids": [int(v) for v in node_ids],
        "node_grid_max_columns": min(10, int(acoustic_config.get("node_grid_max_columns", 10))),
        "chunks": chunks,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"✓ Saved frame manifest: {manifest_path.name} ({len(chunks)} chunks)")


def build_combined_environment_html(export_dir: Path) -> Path:
    output_dir = export_dir / "environment_html_viewer"
    output_dir.mkdir(parents=True, exist_ok=True)
    for html_path in output_dir.glob("*.html"):
        html_path.unlink()
    for json_path in output_dir.glob("frames_*.json"):
        json_path.unlink()
    manifest_json = output_dir / "frame_manifest.json"
    if manifest_json.exists():
        manifest_json.unlink()

    heightmap_path = export_dir / "heightmap.csv"
    nodes_path = export_dir / "nodes.csv"
    trees_path = export_dir / "trees.csv"
    manifest_path = export_dir / "manifest.json"

    x_vals, z_vals, terrain_y, terrain_format = load_terrain(heightmap_path, manifest_path)
    max_surface_grid = 220
    if terrain_format == "grid":
        step_x = max(1, len(x_vals) // max_surface_grid)
        step_z = max(1, len(z_vals) // max_surface_grid)
        x_plot = x_vals[::step_x]
        z_plot = z_vals[::step_z]
        terrain_plot = terrain_y[::step_z, ::step_x]
    else:
        x_plot, z_plot, terrain_plot = x_vals, z_vals, terrain_y

    trees_df_local = pd.read_csv(trees_path)
    nodes_df_local = pd.read_csv(nodes_path)

    bounds = load_manifest_bounds(manifest_path)
    if bounds is None:
        bounds = (float(x_vals.min()), float(x_vals.max()), float(z_vals.min()), float(z_vals.max()))

    dataset_dir = resolve_dataset_dir(sound_root, dataset_name)
    dataset_meta = load_dataset_metadata(dataset_dir)
    dataset_wavs, labels, dataset_wav_labels = build_dataset_audio_index(dataset_dir, dataset_meta)
    print(f"✓ Loaded dataset '{dataset_meta['dataset_name']}' from {dataset_dir} ({len(dataset_wavs):,} wav files, {len(labels)} labels)")
    events_df = generate_sound_events(
        total_hours=24.0,
        bounds=bounds,
        x_vals=x_vals,
        z_vals=z_vals,
        terrain=terrain_y,
        labels=labels,
        dataset_wavs=dataset_wavs,
        dataset_wav_labels=dataset_wav_labels,
        events_per_hour=args.events_per_hour,
        duration_sec=args.event_duration_sec,
        min_height_m=args.event_min_height_m,
        max_height_m=args.event_max_height_m,
        seed=args.seed,
    )
    (export_dir / "sound_events.csv").write_text(events_df.to_csv(index=False), encoding="utf-8")
    label_map = {int(i): label for i, label in enumerate(labels)}
    (export_dir / "sound_labels.json").write_text(json.dumps({"dataset": dataset_name, "labels": label_map}, indent=2), encoding="utf-8")

    event_points = events_df[events_df["is_global"] == 0].copy()
    arrivals_df = build_acoustic_node_arrivals(
        event_points=event_points,
        nodes_df_local=nodes_df_local,
        cfg=acoustic_config,
        export_dir=export_dir,
    )

    terrain_fig = go.Figure()
    terrain_fig.add_trace(go.Surface(x=x_plot, y=z_plot, z=terrain_plot, colorscale="Earth", opacity=0.92, name="Terrain", colorbar=dict(title="Height"), showscale=True))
    if {"x", "y", "z"}.issubset(trees_df_local.columns) and not trees_df_local.empty:
        tree_size = trees_df_local["radius"] * 10.0 if "radius" in trees_df_local.columns else np.full(len(trees_df_local), 5.0)
        tree_size = np.clip(tree_size, 3.0, 14.0)
        terrain_fig.add_trace(go.Scatter3d(x=trees_df_local["x"], y=trees_df_local["z"], z=trees_df_local["y"], mode="markers", name="Trees", marker=dict(size=tree_size, color="forestgreen", opacity=0.9, symbol="circle"), text=trees_df_local["name"] if "name" in trees_df_local.columns else None, hovertemplate="Tree<br>x=%{x:.2f}<br>z=%{y:.2f}<br>y=%{z:.2f}<extra></extra>"))
    if {"x", "y", "z"}.issubset(nodes_df_local.columns) and not nodes_df_local.empty:
        node_text = nodes_df_local["node_id"].astype(str).map(lambda v: f"Node {v}") if "node_id" in nodes_df_local.columns else None
        terrain_fig.add_trace(go.Scatter3d(x=nodes_df_local["x"], y=nodes_df_local["z"], z=nodes_df_local["y"], mode="markers+text" if node_text is not None else "markers", text=node_text, textposition="top center", name="Sensor Nodes", marker=dict(size=6, color="crimson", opacity=1.0, symbol="diamond"), hovertemplate="Node<br>x=%{x:.2f}<br>z=%{y:.2f}<br>y=%{z:.2f}<extra></extra>"))
    main_plot_height_px = 680
    terrain_fig.update_layout(title="Interactive 3D Terrain + Trees + Nodes", scene=dict(xaxis_title="X", yaxis_title="Z", zaxis_title="Y (Height)", aspectmode="data"), margin=dict(l=10, r=10, t=45, b=10), legend=dict(x=0.01, y=0.99), height=main_plot_height_px)

    tree_xy = trees_df_local[["x", "z"]].to_numpy(dtype=float)
    tree_h = trees_df_local["height"].to_numpy(dtype=float) if "height" in trees_df_local.columns else np.full(len(trees_df_local), 18.0)
    tree_r = trees_df_local["radius"].to_numpy(dtype=float) if "radius" in trees_df_local.columns else np.full(len(trees_df_local), 2.5)
    node_xy = nodes_df_local[["x", "z"]].to_numpy(dtype=float)
    node_x = nodes_df_local["x"].to_numpy(dtype=float)
    node_z = nodes_df_local["z"].to_numpy(dtype=float)

    max_duration_hours = 24.0
    base_dt_ms = 10
    total_duration_ms = int(max_duration_hours * 60 * 60 * 1000)
    total_steps = total_duration_ms // base_dt_ms + 1
    sample_count = 120
    # Enforce true 1-second timeline resolution for slider and frame updates.
    frame_stride = max(1, 1000 // base_dt_ms)
    frame_indices = np.arange(0, total_steps, frame_stride, dtype=np.int64)
    if frame_indices[-1] != total_steps - 1:
        frame_indices = np.append(frame_indices, total_steps - 1)

    time_ms = frame_indices * base_dt_ms
    time_hours = time_ms / 3_600_000.0
    min_elev_deg = 8.0
    max_elev_deg = 70.0
    az_start_deg = 90.0
    az_end_deg = 270.0
    phase = np.pi * (time_ms / total_duration_ms)
    sun_azimuth_deg_series = az_start_deg + (az_end_deg - az_start_deg) * (time_ms / total_duration_ms)
    sun_elevation_deg_series = min_elev_deg + (max_elev_deg - min_elev_deg) * np.sin(phase)
    leaf_transmittance = 0.25
    edge_softness_m = 1.5

    irradiance_frames = []
    for az_deg, el_deg in zip(sun_azimuth_deg_series, sun_elevation_deg_series):
        shade = compute_node_shade_for_sun(node_xy, tree_xy, tree_h, tree_r, float(az_deg), float(el_deg), edge_softness_m)
        irr = 1.0 - shade * (1.0 - leaf_transmittance)
        irradiance_frames.append(irr)

    irradiance_frames = np.stack(irradiance_frames, axis=0)
    node_ids = nodes_df_local["node_id"].astype(int).to_numpy() if "node_id" in nodes_df_local.columns else np.arange(len(nodes_df_local), dtype=int)
    charging_frames = irradiance_frames * (solar_const * transmit * panel_area_m2 * panel_efficiency * 1000.0)
    actual_counts, active_counts, max_active_db = build_node_environment_arrays(arrivals_df, node_ids, time_ms)
    reach_radius_m = threshold_radius_m(acoustic_config)
    export_node_environment_timeseries(export_dir, time_ms, time_hours, node_ids, charging_frames, actual_counts, active_counts, max_active_db)
    initial_shadow = build_shadow_segments(tree_xy, tree_h, float(sun_azimuth_deg_series[0]), float(sun_elevation_deg_series[0]), sample_count)
    shadow_sample_idx = np.linspace(0, len(tree_xy) - 1, num=min(sample_count, len(tree_xy)), dtype=int)
    mean_irr = irradiance_frames.mean(axis=1)
    min_irr = irradiance_frames.min(axis=1)
    max_irr = irradiance_frames.max(axis=1)
    center_x = 0.5 * (node_x.min() + node_x.max())
    center_z = 0.5 * (node_z.min() + node_z.max())
    center_idx = int(np.argmin((node_x - center_x) ** 2 + (node_z - center_z) ** 2))
    node_track = irradiance_frames[:, center_idx]

    x_min = float(min(tree_xy[:, 0].min(), node_x.min()))
    x_max = float(max(tree_xy[:, 0].max(), node_x.max()))
    z_min = float(min(tree_xy[:, 1].min(), node_z.min()))
    z_max = float(max(tree_xy[:, 1].max(), node_z.max()))

    shadow_fig = go.Figure()
    shadow_fig.add_trace(go.Scattergl(x=tree_xy[:, 0], y=tree_xy[:, 1], mode="markers", name="Trees", marker=dict(size=4, color="forestgreen", opacity=0.55)))
    shadow_fig.add_trace(go.Scattergl(x=initial_shadow[0], y=initial_shadow[1], mode="lines", name="Shadow rays", line=dict(color="rgba(20,20,20,0.22)", width=1)))
    shadow_fig.add_trace(go.Scattergl(x=node_x, y=node_z, mode="markers", name="Nodes irradiance", marker=dict(size=8, color=irradiance_frames[0], cmin=float(leaf_transmittance), cmax=1.0, colorscale="Turbo", colorbar=dict(title="Irradiance")), text=nodes_df_local["node_id"].astype(str) if "node_id" in nodes_df_local.columns else None, hovertemplate="x=%{x:.2f}<br>z=%{y:.2f}<extra></extra>"))
    shadow_fig.add_trace(
        go.Scattergl(
            x=[],
            y=[],
            mode="lines",
            name=f"Reach radius ({float(acoustic_config['min_reachable_db']):.0f} dB)",
            line=dict(color="rgba(239,68,68,0.45)", width=1.4),
            hoverinfo="skip",
        )
    )
    shadow_fig.add_trace(
        go.Scattergl(
            x=[],
            y=[],
            mode="markers+text",
            name="Active sound events",
            marker=dict(size=12, color="#dc2626", symbol="x"),
            text=[],
            textposition="top center",
            hovertemplate="%{customdata}<br>x=%{x:.2f}<br>z=%{y:.2f}<extra></extra>",
            customdata=[],
        )
    )
    shadow_fig.update_layout(title="Sun/Shadow + Acoustic Events | 24h axis, base dt=10ms", xaxis_title="X", yaxis_title="Z", template="plotly_white", xaxis=dict(range=[x_min - 20.0, x_max + 20.0]), yaxis=dict(range=[z_min - 20.0, z_max + 20.0], scaleanchor="x", scaleratio=1), margin=dict(l=10, r=10, t=45, b=60), height=main_plot_height_px)
    shadow_fig.frames = []

    series_fig = go.Figure()
    series_fig.add_trace(go.Scatter(x=time_hours, y=mean_irr, mode="lines", name="Mean"))
    series_fig.add_trace(go.Scatter(x=time_hours, y=min_irr, mode="lines", name="Min", line=dict(dash="dot")))
    series_fig.add_trace(go.Scatter(x=time_hours, y=max_irr, mode="lines", name="Max", line=dict(dash="dot")))
    series_fig.add_trace(go.Scatter(x=time_hours, y=node_track, mode="lines", name="Center node", line=dict(width=3)))
    if not event_points.empty:
        event_hour = event_points["start_ms"].to_numpy(dtype=float) / 3_600_000.0
        event_idx = event_points["label_index"].to_numpy(dtype=int)
        event_text = [f"{idx}: {label_map.get(idx, 'unknown')}" for idx in event_idx]
        y_event = 1.06 + (event_idx % 8) * 0.02
    else:
        event_hour = np.array([])
        event_text = []
        y_event = np.array([])
    series_fig.add_trace(
        go.Scatter(
            x=event_hour,
            y=y_event,
            mode="markers",
            name="Sound starts",
            marker=dict(size=8, color="#0f766e"),
            text=event_text,
            hovertemplate="%{text}<br>t=%{x:.3f}h<extra></extra>",
        )
    )
    series_fig.add_trace(go.Scatter(x=[time_hours[0], time_hours[0]], y=[0.0, 1.24], mode="lines", name="Current time", line=dict(color="#111827", width=2)))
    series_fig.add_trace(go.Scatter(x=[], y=[], mode="markers+text", name="Active sounds", marker=dict(size=9, color="#1e40af"), text=[], textposition="top center", hovertemplate="%{text}<extra></extra>"))
    series_fig.update_layout(
        title="Irradiance + Acoustic Timeline",
        xaxis_title="Time (hours, 0-24)",
        yaxis_title="Irradiance multiplier",
        xaxis=dict(range=[0, max_duration_hours]),
        yaxis=dict(range=[float(leaf_transmittance) - 0.02, 1.26]),
        template="plotly_white",
        margin=dict(l=10, r=10, t=45, b=10),
        height=main_plot_height_px,
    )
    series_fig.frames = []

    # Save compact per-second visualization state for browser-side lazy loading.
    save_lazy_frame_chunks(
        output_dir,
        frame_indices,
        time_ms,
        irradiance_frames,
        event_points,
        label_map,
        node_ids,
        charging_frames,
        actual_counts,
        active_counts,
        max_active_db,
        reach_radius_m,
    )
    export_node_arrivals_json(export_dir, output_dir, arrivals_df)

    shadow_tree_x_json = json.dumps(_round_float_list(tree_xy[shadow_sample_idx, 0], 3), separators=(",", ":"))
    shadow_tree_z_json = json.dumps(_round_float_list(tree_xy[shadow_sample_idx, 1], 3), separators=(",", ":"))
    shadow_tree_h_json = json.dumps(_round_float_list(tree_h[shadow_sample_idx], 3), separators=(",", ":"))
    total_frames = len(frame_indices)

    combined_path = output_dir / "environment_reconstruction.html"
    html_parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8" />',
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
        "  <title>Environment Reconstruction Viewer</title>",
        '  <style>',
        '    body { margin: 0; font-family: Arial, sans-serif; background: #f6f7fb; color: #111; }',
        '    .page { max-width: 1600px; margin: 0 auto; padding: 20px; }',
        '    .card { background: white; border-radius: 14px; padding: 16px; margin-bottom: 18px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); }',
        '    .title { margin: 0 0 8px 0; font-size: 28px; }',
        '    .subtitle { margin: 0 0 12px 0; color: #444; line-height: 1.5; }',
        '    .section-title { margin: 0 0 10px 0; font-size: 20px; }',
        '    .plot-row { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; align-items: stretch; }',
        '    .plot-row .card { min-width: 0; }',
        '    .controls { display: grid; grid-template-columns: auto auto 1fr auto; gap: 10px; align-items: center; margin: 8px 0 14px; }',
        '    .controls button { border: 0; border-radius: 8px; padding: 8px 12px; background: #1e40af; color: white; cursor: pointer; font-weight: 600; }',
        '    .controls button.secondary { background: #475569; }',
        '    .controls input[type="range"] { width: 100%; }',
        '    .time-label { min-width: 98px; font-variant-numeric: tabular-nums; font-weight: 700; color: #111827; }',
        '    .status { color: #475569; font-size: 13px; }',
        '    .node-grid { display: grid; grid-template-columns: repeat(var(--node-cols, 10), minmax(96px, 1fr)); gap: 8px; }',
        '    .node-card { border: 1px solid #dbe3ef; border-radius: 10px; padding: 8px; background: #f8fafc; cursor: pointer; transition: transform 0.12s, border-color 0.12s; }',
        '    .node-card:hover { transform: translateY(-1px); border-color: #1e40af; }',
        '    .node-card.active-sound { background: #eff6ff; border-color: #1e40af; }',
        '    .node-id { font-weight: 800; color: #111827; }',
        '    .node-metric { font-size: 12px; color: #334155; line-height: 1.35; font-variant-numeric: tabular-nums; }',
        '    .modal-backdrop { display: none; position: fixed; inset: 0; background: rgba(15,23,42,0.55); z-index: 1000; align-items: center; justify-content: center; padding: 24px; }',
        '    .modal-backdrop.open { display: flex; }',
        '    .modal { width: min(920px, 96vw); max-height: 86vh; overflow: auto; background: white; border-radius: 14px; padding: 18px; box-shadow: 0 20px 50px rgba(0,0,0,0.25); }',
        '    .modal-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }',
        '    .modal-close { border: 0; border-radius: 8px; background: #ef4444; color: white; padding: 8px 10px; cursor: pointer; }',
        '    .arrival-row { border-top: 1px solid #e2e8f0; padding: 10px 0; display: grid; gap: 6px; }',
        '    .arrival-meta { font-size: 13px; color: #334155; }',
        '    .arrival-row { grid-template-columns: 1fr auto; align-items: center; column-gap: 10px; }',
        '    .play-arrival { border: 0; border-radius: 8px; background: #1d4ed8; color: #fff; font-weight: 700; padding: 8px 12px; cursor: pointer; }',
        '    .play-arrival:hover { background: #1e40af; }',
        '    @media (max-width: 1100px) { .plot-row { grid-template-columns: 1fr; } }',
        '  </style>',
        "</head>",
        "<body>",
        '  <div class="page">',
        '    <div class="card">',
        '      <h1 class="title">Environment Reconstruction Viewer</h1>',
        '      <p class="subtitle">Terrain reconstruction and sun-shadow reconstruction shown together in one page.</p>',
        '    </div>',
        '    <div class="card">',
        '      <h2 class="section-title">1. Terrain + Nodes</h2>',
        f'      {pio.to_html(terrain_fig, include_plotlyjs="cdn", full_html=False, config={"responsive": True}, div_id="terrain_plot")}',
        '    </div>',
        '    <div class="plot-row">',
        '    <div class="card">',
        '      <h2 class="section-title">2. Sun/Shadow + Acoustic Events</h2>',
        '      <div class="controls">',
        '        <button id="play_button" type="button">Play</button>',
        '        <button id="pause_button" class="secondary" type="button">Pause</button>',
        f'        <input id="time_slider" type="range" min="0" max="{total_frames - 1}" step="1" value="0" />',
        '        <span id="time_label" class="time-label">00:00:00</span>',
        '      </div>',
        '      <div id="load_status" class="status">Lazy loading enabled: only the selected 1-second frame chunk is fetched.</div>',
        f'      {pio.to_html(shadow_fig, include_plotlyjs=False, full_html=False, config={"responsive": True}, div_id="shadow_plot")}',
        '    </div>',
        '    <div class="card">',
        '      <h2 class="section-title">3. Irradiance + Acoustic Timeline</h2>',
        f'      {pio.to_html(series_fig, include_plotlyjs=False, full_html=False, config={"responsive": True}, div_id="series_plot")}',
        '    </div>',
        '    </div>',
        '    <div class="card">',
        '      <h2 class="section-title">4. Node Solar + Actual Acoustic Matrix</h2>',
        '      <p class="subtitle">Each node card shows solar charging and simulated acoustic arrivals only. No battery/status/inference state is modeled here.</p>',
        '      <div id="node_grid" class="node-grid"></div>',
        '    </div>',
        '  </div>',
        '  <div id="node_modal_backdrop" class="modal-backdrop">',
        '    <div class="modal">',
        '      <div class="modal-header">',
        '        <h2 id="node_modal_title" class="section-title">Node arrivals</h2>',
        '        <button id="node_modal_close" class="modal-close" type="button">Close</button>',
        '      </div>',
        '      <div id="node_modal_body"></div>',
        '    </div>',
        '  </div>',
        '  <script>',
        '    (function () {',
        '      const shadow = document.getElementById("shadow_plot");',
        '      const series = document.getElementById("series_plot");',
        '      const slider = document.getElementById("time_slider");',
        '      const playButton = document.getElementById("play_button");',
        '      const pauseButton = document.getElementById("pause_button");',
        '      const timeLabel = document.getElementById("time_label");',
        '      const status = document.getElementById("load_status");',
        '      const nodeGrid = document.getElementById("node_grid");',
        '      const modalBackdrop = document.getElementById("node_modal_backdrop");',
        '      const modalTitle = document.getElementById("node_modal_title");',
        '      const modalBody = document.getElementById("node_modal_body");',
        '      const modalClose = document.getElementById("node_modal_close");',
        '      if (!shadow || !series || !slider) return;',
        f'      const totalFrames = {total_frames};',
        f'      const totalDurationMs = {total_duration_ms};',
        f'      const treeX = {shadow_tree_x_json};',
        f'      const treeZ = {shadow_tree_z_json};',
        f'      const treeH = {shadow_tree_h_json};',
        f'      const reachThresholdDb = {float(acoustic_config["min_reachable_db"]):.3f};',
        '      const minElevDeg = 8.0;',
        '      const maxElevDeg = 70.0;',
        '      const azStartDeg = 90.0;',
        '      const azEndDeg = 270.0;',
        '      const frameCache = new Map();',
        '      let manifestPromise = null;',
        '      let arrivalsPromise = null;',
        '      let nodeIds = [];',
        '      let playing = false;',
        '      let currentIndex = 0;',
        '      let modalAudio = null;',
        '      function pad2(v) { return String(v).padStart(2, "0"); }',
        '      function formatTime(ms) {',
        '        const s = Math.floor(ms / 1000);',
        '        return `${pad2(Math.floor(s / 3600))}:${pad2(Math.floor((s % 3600) / 60))}:${pad2(s % 60)}`;',
        '      }',
        '      function loadManifest() {',
        '        if (!manifestPromise) manifestPromise = fetch("./frame_manifest.json").then(r => r.json());',
        '        return manifestPromise;',
        '      }',
        '      function loadNodeArrivals() {',
        '        if (!arrivalsPromise) arrivalsPromise = fetch("./node_arrivals.json").then(r => r.json()).catch(() => ({}));',
        '        return arrivalsPromise;',
        '      }',
        '      async function loadFrame(frameIndex) {',
        '        const manifest = await loadManifest();',
        '        const chunk = manifest.chunks.find(c => frameIndex >= c.start_index && frameIndex <= c.end_index);',
        '        if (!chunk) throw new Error(`No chunk for frame ${frameIndex}`);',
        '        if (!frameCache.has(chunk.file)) {',
        '          status.textContent = `Loading ${chunk.file}...`;',
        '          frameCache.set(chunk.file, fetch(`./${chunk.file}`).then(r => r.json()));',
        '        }',
        '        const data = await frameCache.get(chunk.file);',
        '        status.textContent = `Loaded ${chunk.file} (${Object.keys(frameCache).length || frameCache.size} cached chunks)`;',
        '        return data.frames[frameIndex - data.start_index];',
        '      }',
        '      function renderNodeGrid(manifest) {',
        '        if (!nodeGrid) return;',
        '        nodeIds = manifest.node_ids || [];',
        '        const cols = Math.min(10, Math.max(1, manifest.node_grid_max_columns || 10));',
        '        nodeGrid.style.setProperty("--node-cols", String(cols));',
        '        nodeGrid.innerHTML = nodeIds.map((nodeId, idx) => `',
        '          <div class="node-card" data-node-id="${nodeId}" data-node-index="${idx}">',
        '            <div class="node-id">Node ${nodeId}</div>',
        '            <div class="node-metric charge">Solar: -- mW</div>',
        '            <div class="node-metric actual">Actual count: 0</div>',
        '          </div>`).join("");',
        '        nodeGrid.querySelectorAll(".node-card").forEach(card => {',
        '          card.addEventListener("click", () => openNodeModal(card.dataset.nodeId));',
        '        });',
        '      }',
        '      function updateNodeGrid(frame) {',
        '        if (!nodeGrid || !frame.node) return;',
        '        const cards = nodeGrid.querySelectorAll(".node-card");',
        '        cards.forEach(card => {',
        '          const idx = Number(card.dataset.nodeIndex);',
        '          const charge = frame.node.charge?.[idx] ?? 0;',
        '          const actual = frame.node.actual?.[idx] ?? 0;',
        '          const active = frame.node.active?.[idx] ?? 0;',
        '          card.querySelector(".charge").textContent = `Solar: ${Number(charge).toFixed(1)} mW`;',
        '          card.querySelector(".actual").textContent = `Actual count: ${actual}`;',
        '          card.classList.toggle("active-sound", active > 0);',
        '        });',
        '      }',
        '      function stopModalAudio() {',
        '        if (!modalAudio) return;',
        '        try { modalAudio.pause(); } catch (_) {}',
        '        modalAudio = null;',
        '      }',
        '      function playArrival(src) {',
        '        stopModalAudio();',
        '        modalAudio = new Audio(src);',
        '        modalAudio.play().catch(err => { console.error(err); status.textContent = `Audio play failed: ${String(err)}`; });',
        '      }',
        '      async function openNodeModal(nodeId) {',
        '        const arrivals = await loadNodeArrivals();',
        '        const rows = arrivals[String(nodeId)] || [];',
        '        modalTitle.textContent = `Node ${nodeId} Actual Acoustic Arrivals (${rows.length})`;',
        '        if (!rows.length) {',
        '          modalBody.innerHTML = "<p>No simulated sound arrived at or above the configured threshold.</p>";',
        '        } else {',
        '          modalBody.innerHTML = rows.map(row => `',
        '            <div class="arrival-row">',
        '              <div class="arrival-meta"><b>Event:</b> ${formatTime(row.event_start_ms)} | <b>Arrival:</b> ${formatTime(row.arrival_start_ms)} | <b>Received:</b> ${Number(row.received_db).toFixed(1)} dB | event=${row.event_id} | ${row.label}</div>',
        '              <button class="play-arrival" type="button" data-src="${row.wav}">Play</button>',
        '            </div>`).join("");',
        '          modalBody.querySelectorAll(".play-arrival").forEach(btn => {',
        '            btn.addEventListener("click", () => playArrival(btn.dataset.src));',
        '          });',
        '        }',
        '        modalBackdrop.classList.add("open");',
        '      }',
        '      modalClose.addEventListener("click", () => { stopModalAudio(); modalBackdrop.classList.remove("open"); });',
        '      modalBackdrop.addEventListener("click", evt => { if (evt.target === modalBackdrop) { stopModalAudio(); modalBackdrop.classList.remove("open"); } });',
        '      function sunPosition(ms) {',
        '        const ratio = ms / totalDurationMs;',
        '        const phase = Math.PI * ratio;',
        '        return {',
        '          az: azStartDeg + (azEndDeg - azStartDeg) * ratio,',
        '          el: minElevDeg + (maxElevDeg - minElevDeg) * Math.sin(phase)',
        '        };',
        '      }',
        '      function shadowRays(ms) {',
        '        const sun = sunPosition(ms);',
        '        const elev = Math.max(1.0, Math.min(89.0, sun.el)) * Math.PI / 180.0;',
        '        const az = sun.az * Math.PI / 180.0;',
        '        let dx = -Math.sin(az);',
        '        let dz = -Math.cos(az);',
        '        const norm = Math.hypot(dx, dz) || 1.0;',
        '        dx /= norm; dz /= norm;',
        '        const tanElev = Math.tan(elev);',
        '        const xs = [];',
        '        const zs = [];',
        '        for (let i = 0; i < treeX.length; i++) {',
        '          const len = treeH[i] / tanElev;',
        '          xs.push(treeX[i], treeX[i] + len * dx, null);',
        '          zs.push(treeZ[i], treeZ[i] + len * dz, null);',
        '        }',
        '        return {x: xs, z: zs};',
        '      }',
        '      function soundRangeCircles(sound) {',
        '        const xs = [];',
        '        const zs = [];',
        '        const cx = sound.x || [];',
        '        const cz = sound.z || [];',
        '        const rs = sound.radius_m || [];',
        '        const seg = 48;',
        '        for (let i = 0; i < cx.length; i++) {',
        '          const x0 = Number(cx[i]);',
        '          const z0 = Number(cz[i]);',
        '          const r = Number(rs[i] ?? 0);',
        '          if (!Number.isFinite(x0) || !Number.isFinite(z0) || !Number.isFinite(r) || r <= 0) continue;',
        '          for (let k = 0; k <= seg; k++) {',
        '            const th = (2.0 * Math.PI * k) / seg;',
        '            xs.push(x0 + r * Math.cos(th));',
        '            zs.push(z0 + r * Math.sin(th));',
        '          }',
        '          xs.push(null);',
        '          zs.push(null);',
        '        }',
        '        return {x: xs, z: zs};',
        '      }',
        '      let frameRequestToken = 0;',
        '      async function goToFrame(frameIndex) {',
        '        const requestToken = ++frameRequestToken;',
        '        frameIndex = Math.max(0, Math.min(totalFrames - 1, frameIndex));',
        '        currentIndex = frameIndex;',
        '        const frame = await loadFrame(frameIndex);',
        '        if (!frame || frameIndex !== currentIndex || requestToken !== frameRequestToken) return;',
        '        const rays = shadowRays(frame.ms);',
        '        const tHour = frame.ms / 3600000.0;',
        '        const sound = frame.sound || {x: [], z: [], text: [], desc: [], radius_m: []};',
        '        const soundCircles = soundRangeCircles(sound);',
        '        const activeY = (sound.text || []).map((_, i) => 1.18 + 0.015 * i);',
        '        const activeX = (sound.text || []).map(() => tHour);',
        '        const summary = (sound.desc && sound.desc.length) ? [...new Set(sound.desc)].join(", ") : "none";',
        '        slider.value = String(frameIndex);',
        '        timeLabel.textContent = formatTime(frame.ms);',
        '        if (requestToken !== frameRequestToken) return;',
        '        await Plotly.restyle(shadow, {x: [rays.x], y: [rays.z]}, [1]);',
        '        if (requestToken !== frameRequestToken) return;',
        '        await Plotly.restyle(shadow, {"marker.color": [frame.irr]}, [2]);',
        '        if (requestToken !== frameRequestToken) return;',
        '        await Plotly.restyle(shadow, {x: [soundCircles.x], y: [soundCircles.z]}, [3]);',
        '        if (requestToken !== frameRequestToken) return;',
        '        await Plotly.restyle(shadow, {x: [sound.x], y: [sound.z], text: [sound.text], customdata: [sound.desc]}, [4]);',
        '        if (requestToken !== frameRequestToken) return;',
        '        await Plotly.relayout(shadow, {title: `Sun/Shadow + Acoustic Events | t=${formatTime(frame.ms)} | active=${summary} | radius=${reachThresholdDb.toFixed(0)}dB`});',
        '        if (requestToken !== frameRequestToken) return;',
        '        await Plotly.restyle(series, {x: [[tHour, tHour]], y: [[0.0, 1.24]]}, [5]);',
        '        if (requestToken !== frameRequestToken) return;',
        '        await Plotly.restyle(series, {x: [activeX], y: [activeY], text: [sound.desc]}, [6]);',
        '        updateNodeGrid(frame);',
        '      }',
        '      let pending = null;',
        '      let rafScheduled = false;',
        '      function requestFrame(index) {',
        '        pending = index;',
        '        if (rafScheduled) return;',
        '        rafScheduled = true;',
        '        requestAnimationFrame(() => {',
        '          const next = pending;',
        '          pending = null;',
        '          rafScheduled = false;',
        '          goToFrame(next).catch(err => { console.error(err); status.textContent = String(err); });',
        '        });',
        '      }',
        '      slider.addEventListener("input", () => { playing = false; requestFrame(parseInt(slider.value, 10)); });',
        '      playButton.addEventListener("click", () => {',
        '        playing = true;',
        '        const tick = async () => {',
        '          if (!playing) return;',
        '          const next = Math.min(totalFrames - 1, currentIndex + 1);',
        '          await goToFrame(next).catch(err => { console.error(err); status.textContent = String(err); playing = false; });',
        '          if (next >= totalFrames - 1) playing = false;',
        '          else setTimeout(tick, 40);',
        '        };',
        '        tick();',
        '      });',
        '      pauseButton.addEventListener("click", () => { playing = false; });',
        '      loadManifest().then((manifest) => { renderNodeGrid(manifest); return goToFrame(0); });',
        '    })();',
        '  </script>',
        '</body>',
        '</html>',
    ]
    combined_path.write_text("\n".join(html_parts), encoding="utf-8")
    return combined_path


combined_html_path = build_combined_environment_html(export_dir)
print(f"✓ Saved combined environment HTML: {combined_html_path}")
