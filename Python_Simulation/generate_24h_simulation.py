#!/usr/bin/env python3
"""
24-hour day-night cycle simulation for energy harvesting nodes.
This script generates a complete 24-hour day-night cycle simulation
including shadow dynamics and battery tracking.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

# Path setup
project_root = Path(__file__).resolve().parent.parent.parent
python_root = Path(__file__).resolve().parent
export_dir = python_root / "exports" / "latest"

print("=" * 80)
print("🌅 24-Hour Day-Night Cycle Simulation")
print("=" * 80)

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

# ============================================================================
# 24-hour simulation loop
# ============================================================================
total_duration_hours = 24
sim_dt_ms = 10
total_duration_ms = int(total_duration_hours * 60 * 60 * 1000)
total_steps = total_duration_ms // sim_dt_ms + 1

# 1-second sampling output (no display decimation)
output_step_ms = 1000
frame_stride = max(1, output_step_ms // sim_dt_ms)
frame_indices = np.arange(0, total_steps, frame_stride, dtype=np.int64)
if frame_indices[-1] != total_steps - 1:
    frame_indices = np.append(frame_indices, total_steps - 1)

time_ms = frame_indices * sim_dt_ms
time_hours = time_ms / (1000.0 * 60.0 * 60.0)
n_steps = len(frame_indices)

print(f"\n⏰ Time parameters:")
print(f"  Total duration: {total_duration_hours}h = {total_duration_ms:,}ms")
print(f"  Base dt: {sim_dt_ms}ms")
print(f"  Total steps: {total_steps:,}")
print(f"  Output step: {output_step_ms}ms")
print(f"  Output samples: {n_steps} (stride={frame_stride})")

# Sun arc parameters
min_elev_deg = 8.0
max_elev_deg = 70.0
az_start_deg = 90.0
az_end_deg = 270.0

# Calculate sun position for entire 24-hour cycle
print(f"\n⏳ Computing sun positions and node shadows...")
sun_azimuth_deg_series = np.zeros(n_steps)
sun_elevation_deg_series = np.zeros(n_steps)

for i, hour in enumerate(time_hours):
    if hour < 12:
        # Daytime (0-12h): normal sun arc
        phase = np.pi * (hour / 12.0)
        sun_elevation_deg_series[i] = min_elev_deg + (max_elev_deg - min_elev_deg) * np.sin(phase)
        sun_azimuth_deg_series[i] = az_start_deg + (az_end_deg - az_start_deg) * (hour / 12.0)
    else:
        # Nighttime (12-24h): sun below horizon
        sun_elevation_deg_series[i] = -20.0
        sun_azimuth_deg_series[i] = 270.0

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
    if hour < 12:
        phase = np.pi * (hour / 12.0)
        shadow_elevation_deg_series[i] = min_elev_deg + (max_elev_deg - min_elev_deg) * np.sin(phase)
        shadow_azimuth_deg_series[i] = az_start_deg + (az_end_deg - az_start_deg) * (hour / 12.0)
    else:
        shadow_elevation_deg_series[i] = -20.0
        shadow_azimuth_deg_series[i] = 270.0

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
# Battery simulation with 24-hour day-night cycle
# ============================================================================
print(f"\n🔋 Battery simulation (24h × {len(nodes_df)} nodes)...")

n_nodes = len(nodes_df)
n_time_steps = len(frame_indices)

battery_joules = np.zeros((n_nodes, n_time_steps), dtype=float)
battery_pct = np.zeros((n_nodes, n_time_steps), dtype=float)
charging_rate_mw = np.zeros((n_nodes, n_time_steps), dtype=float)
node_state = np.empty((n_nodes, n_time_steps), dtype=object)
power_consumption_mw = np.zeros((n_nodes, n_time_steps), dtype=float)

# Profile
panel_area_m2 = 0.015625
panel_efficiency = 0.15
profile = {
    "deep_sleep_mw": 0.05,
    "idle_mw": 434.85,
    "sensing_mw": 505.95,
    "computing_mw": 490.0,
    "transmitting_mw": 800.0,
    "max_j": 594.0,
    "init_ratio": 0.5,
    "wake_j": 148.5,   # 25% of 594J
    "sleep_j": 118.8,   # 20% of 594J
    "solar_const": 1361.0,
    "transmit": 0.7,
    "panel_area_m2": panel_area_m2,
    "panel_efficiency": panel_efficiency,
}

initial_j = profile["max_j"] * profile["init_ratio"]
battery_joules[:, 0] = initial_j
battery_pct[:, 0] = 50.0
node_state[:, 0] = "idle"
power_consumption_mw[:, 0] = profile["idle_mw"]

peak_charging = profile["solar_const"] * profile["transmit"] * 1.0 * panel_area_m2 * panel_efficiency * 1000.0
print(f"Peak charging (sunny): {peak_charging:.1f} mW")
print(f"Night charging: 0 mW (irr → 1.0 at darkness)")

# Simulation loop
for t in range(1, n_time_steps):
    if t % max(1, n_time_steps // 10) == 0:
        print(f"  {int(100*t/n_time_steps)}% complete (t={time_hours[t]:.2f}h)")
    
    for node_idx in range(n_nodes):
        prev_j = battery_joules[node_idx, t - 1]
        irr = irradiance_frames[t, node_idx]
        
        harvest_w = profile["solar_const"] * profile["transmit"] * irr * profile["panel_area_m2"] * profile["panel_efficiency"]
        charging_rate_mw[node_idx, t] = harvest_w * 1000.0
        
        if prev_j < profile["sleep_j"]:
            current_state = "deep_sleep"
            power_mw = profile["deep_sleep_mw"]
        elif prev_j >= profile["wake_j"]:
            current_state = "idle"
            power_mw = profile["idle_mw"]
        else:
            current_state = "idle"
            power_mw = profile["idle_mw"]
        
        node_state[node_idx, t] = current_state
        power_consumption_mw[node_idx, t] = power_mw
        
        dt_s = (time_ms[t] - time_ms[t - 1]) / 1000.0
        consumed_mj = power_mw * dt_s
        harvested_mj = charging_rate_mw[node_idx, t] * dt_s
        new_j = prev_j + (harvested_mj - consumed_mj) / 1000.0
        new_j = np.clip(new_j, 0.0, profile["max_j"])
        
        battery_joules[node_idx, t] = new_j
        battery_pct[node_idx, t] = (new_j / profile["max_j"]) * 100.0

print(f"\n✓ Simulation complete!")

# Build dataframe
print(f"\n📊 Building output CSV...")
result_rows = []
for t in range(n_time_steps):
    for node_idx in range(n_nodes):
        node_id = int(nodes_df.iloc[node_idx]["node_id"]) if "node_id" in nodes_df.columns else node_idx
        total_s = int(time_ms[t] // 1000)
        h = total_s // 3600
        m = (total_s % 3600) // 60
        s = total_s % 60
        result_rows.append({
            "time_ms": int(time_ms[t]),
            "time_hours": time_hours[t],
            "time_hhmmss": f"{h:02d}:{m:02d}:{s:02d}",
            "node_id": node_id,
            "node_x": nodes_df.iloc[node_idx]["x"],
            "node_z": nodes_df.iloc[node_idx]["z"],
            "sun_azimuth_deg": sun_azimuth_deg_series[t],
            "sun_elevation_deg": sun_elevation_deg_series[t],
            "irradiance_multiplier": irradiance_frames[t, node_idx],
            "charging_rate_mw": charging_rate_mw[node_idx, t],
            "power_consumption_mw": power_consumption_mw[node_idx, t],
            "battery_joules": battery_joules[node_idx, t],
            "battery_pct": battery_pct[node_idx, t],
            "node_state": node_state[node_idx, t],
        })

df_simulation = pd.DataFrame(result_rows)
csv_path = export_dir / "node_simulation_log.csv"
df_simulation.to_csv(csv_path, index=False)
print(f"✓ Saved: {csv_path} ({len(df_simulation):,} rows)")

# Analysis
print(f"\n📈 Analysis:")
daytime = df_simulation[df_simulation["sun_elevation_deg"] > 0]
nighttime = df_simulation[df_simulation["sun_elevation_deg"] <= 0]

print(f"\n☀️ Daytime (elevation > 0): {len(daytime):,} rows ({len(daytime)/len(df_simulation)*100:.1f}%)")
print(f"   Avg charging: {daytime['charging_rate_mw'].mean():.1f} mW")
print(f"   Max charging: {daytime['charging_rate_mw'].max():.1f} mW")

print(f"\n🌙 Nighttime (elevation ≤ 0): {len(nighttime):,} rows ({len(nighttime)/len(df_simulation)*100:.1f}%)")
print(f"   Avg charging: {nighttime['charging_rate_mw'].mean():.4f} mW")
print(f"   Avg consumption: {nighttime['power_consumption_mw'].mean():.2f} mW")

print(f"\n✅ 24-hour simulation complete!")
