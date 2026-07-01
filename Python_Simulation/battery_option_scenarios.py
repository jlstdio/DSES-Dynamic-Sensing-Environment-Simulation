from pathlib import Path
import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd


NOMINAL_BATTERY_VOLTAGE = 3.3
BATTERY_OPTIONS_MAH = [10, 50, 100, 150, 200, 250, 500, 1000]
DEFAULT_SIMULATION_DAYS = 30
DEFAULT_DT_MS = 1000
INITIAL_BATTERY_RATIO = 0.5
WAKE_THRESHOLD_RATIO = 0.25
SLEEP_THRESHOLD_RATIO = 0.20
DEEP_SLEEP_POWER_MW = 0.05
SENSING_POWER_MW = 505.95
INFERENCE_POWER_MW = 490.0
COMMUNICATION_POWER_MW = 800.0


def mah_to_joules(capacity_mah: float, voltage_v: float = NOMINAL_BATTERY_VOLTAGE) -> float:
    watt_hours = (capacity_mah / 1000.0) * voltage_v
    return watt_hours * 3600.0


def load_base_cycle(base_log_path: Path, max_nodes: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load 24h base cycle sampled at 1s.

    Consumption and state are recomputed per scenario.
    """
    base_df = pd.read_csv(
        base_log_path,
        usecols=["time_ms", "node_id", "charging_rate_mw", "irradiance_multiplier"],
    )

    if max_nodes is not None:
        allowed_nodes = np.sort(base_df["node_id"].unique())[:max_nodes]
        base_df = base_df[base_df["node_id"].isin(allowed_nodes)]

    base_df = base_df.sort_values(["time_ms", "node_id"], kind="mergesort")

    time_values = np.sort(base_df["time_ms"].unique())
    node_ids = np.sort(base_df["node_id"].unique())
    n_time_steps = len(time_values)
    n_nodes = len(node_ids)

    charging = base_df["charging_rate_mw"].to_numpy(dtype=float).reshape(n_time_steps, n_nodes)
    irradiance = base_df["irradiance_multiplier"].to_numpy(dtype=float).reshape(n_time_steps, n_nodes)

    return time_values.astype(np.int64), node_ids.astype(np.int64), charging, irradiance


def active_phase(step_in_second: int, steps_per_second: int) -> tuple[str, float]:
    """Simple active-state duty cycle within each second.

    sensing 60%, inference 25%, communication 15%
    """
    sensing_end = int(0.60 * steps_per_second)
    inference_end = int(0.85 * steps_per_second)

    if step_in_second < sensing_end:
        return "sensing", SENSING_POWER_MW
    if step_in_second < inference_end:
        return "inference", INFERENCE_POWER_MW
    return "communication", COMMUNICATION_POWER_MW


@dataclass
class TimeSeriesWriter:
    file_path: Path
    node_ids: np.ndarray
    chunk_steps: int

    def __post_init__(self) -> None:
        self._header_written = False
        self._time_ms: list[int] = []
        self._day_index: list[int] = []
        self._charging: list[np.ndarray] = []
        self._irradiance: list[np.ndarray] = []
        self._consumption: list[np.ndarray] = []
        self._battery_j: list[np.ndarray] = []
        self._battery_pct: list[np.ndarray] = []
        self._state: list[np.ndarray] = []

    def add_step(
        self,
        time_ms: int,
        day_index: int,
        charging_mw: np.ndarray,
        irradiance_multiplier: np.ndarray,
        consumption_mw: np.ndarray,
        battery_joules: np.ndarray,
        battery_pct: np.ndarray,
        node_state: np.ndarray,
    ) -> None:
        self._time_ms.append(int(time_ms))
        self._day_index.append(int(day_index))
        self._charging.append(charging_mw.copy())
        self._irradiance.append(irradiance_multiplier.copy())
        self._consumption.append(consumption_mw.copy())
        self._battery_j.append(battery_joules.copy())
        self._battery_pct.append(battery_pct.copy())
        self._state.append(node_state.copy())

        if len(self._time_ms) >= self.chunk_steps:
            self.flush()

    def flush(self) -> None:
        if not self._time_ms:
            return

        n_steps = len(self._time_ms)
        n_nodes = len(self.node_ids)

        time_arr = np.repeat(np.asarray(self._time_ms, dtype=np.int64), n_nodes)
        day_arr = np.repeat(np.asarray(self._day_index, dtype=np.int32), n_nodes)
        node_arr = np.tile(self.node_ids, n_steps)

        charging_arr = np.vstack(self._charging).reshape(-1)
        irr_arr = np.vstack(self._irradiance).reshape(-1)
        consumption_arr = np.vstack(self._consumption).reshape(-1)
        battery_j_arr = np.vstack(self._battery_j).reshape(-1)
        battery_pct_arr = np.vstack(self._battery_pct).reshape(-1)
        state_arr = np.vstack(self._state).reshape(-1)

        out_df = pd.DataFrame(
            {
                "time_ms": time_arr,
                "day_index": day_arr,
                "node_id": node_arr,
                "irradiance_multiplier": irr_arr,
                "charging_rate_mw": charging_arr,
                "power_consumption_mw": consumption_arr,
                "battery_joules": battery_j_arr,
                "battery_pct": battery_pct_arr,
                "node_state": state_arr,
            }
        )

        out_df.to_csv(
            self.file_path,
            mode="a",
            header=not self._header_written,
            index=False,
        )
        self._header_written = True

        self._time_ms.clear()
        self._day_index.clear()
        self._charging.clear()
        self._irradiance.clear()
        self._consumption.clear()
        self._battery_j.clear()
        self._battery_pct.clear()
        self._state.clear()


def build_capacity_summary_and_optional_timeseries(
    time_values: np.ndarray,
    node_ids: np.ndarray,
    charging_cycle_1s: np.ndarray,
    irradiance_cycle_1s: np.ndarray,
    capacity_mah: int,
    simulation_days: int,
    dt_ms: int,
    writer: TimeSeriesWriter | None,
) -> pd.DataFrame:
    max_battery_j = mah_to_joules(capacity_mah)
    wake_threshold_j = max_battery_j * WAKE_THRESHOLD_RATIO
    sleep_threshold_j = max_battery_j * SLEEP_THRESHOLD_RATIO
    initial_battery_j = max_battery_j * INITIAL_BATTERY_RATIO

    sec_count = len(time_values) - 1
    n_nodes = len(node_ids)
    day_span_ms = int(time_values[-1])
    dt_s = dt_ms / 1000.0
    steps_per_second = 1000 // dt_ms

    battery_j = np.full(n_nodes, initial_battery_j, dtype=float)
    in_deep_sleep = np.zeros(n_nodes, dtype=bool)

    deep_sleep_steps = np.zeros(n_nodes, dtype=np.int64)
    revival_count = np.zeros(n_nodes, dtype=np.int64)
    first_death_time_ms = np.full(n_nodes, np.nan, dtype=float)
    first_revival_time_ms = np.full(n_nodes, np.nan, dtype=float)

    sample_count = np.zeros(n_nodes, dtype=np.int64)
    charging_sum_mw = np.zeros(n_nodes, dtype=float)
    consumption_sum_mw = np.zeros(n_nodes, dtype=float)
    net_power_sum_mw = np.zeros(n_nodes, dtype=float)
    min_battery_pct = np.full(n_nodes, 100.0, dtype=float)
    max_battery_pct = np.zeros(n_nodes, dtype=float)

    for day_index in range(simulation_days):
        day_start_ms = day_index * day_span_ms

        for sec_idx in range(sec_count):
            charging_mw = charging_cycle_1s[sec_idx]
            irradiance = irradiance_cycle_1s[sec_idx]
            sec_base_time_ms = int(time_values[sec_idx])

            for sub_idx in range(steps_per_second):
                state_name, active_power_mw = active_phase(sub_idx, steps_per_second)

                newly_sleeping = (~in_deep_sleep) & (battery_j <= sleep_threshold_j)
                in_deep_sleep |= newly_sleeping

                dead_mask = (battery_j <= 0.0) & (charging_mw <= 0.0)
                consumption_mw = np.where(
                    dead_mask,
                    0.0,
                    np.where(in_deep_sleep, DEEP_SLEEP_POWER_MW, active_power_mw),
                )
                net_power_mw = charging_mw - consumption_mw

                if not (day_index == 0 and sec_idx == 0 and sub_idx == 0):
                    battery_j = np.clip(battery_j + (net_power_mw * dt_s / 1000.0), 0.0, max_battery_j)

                death_mask = np.isnan(first_death_time_ms) & in_deep_sleep
                if np.any(death_mask):
                    current_time_ms = day_start_ms + sec_base_time_ms + sub_idx * dt_ms
                    first_death_time_ms[death_mask] = current_time_ms

                wake_mask = in_deep_sleep & (battery_j >= wake_threshold_j)
                if np.any(wake_mask):
                    current_time_ms = day_start_ms + sec_base_time_ms + sub_idx * dt_ms
                    first_revival_mask = wake_mask & np.isnan(first_revival_time_ms)
                    first_revival_time_ms[first_revival_mask] = current_time_ms
                    revival_count[wake_mask] += 1
                    in_deep_sleep[wake_mask] = False

                deep_sleep_steps += in_deep_sleep.astype(np.int64)
                sample_count += 1
                charging_sum_mw += charging_mw
                consumption_sum_mw += consumption_mw
                net_power_sum_mw += net_power_mw

                battery_pct = (battery_j / max_battery_j) * 100.0 if max_battery_j > 0 else 0.0
                min_battery_pct = np.minimum(min_battery_pct, battery_pct)
                max_battery_pct = np.maximum(max_battery_pct, battery_pct)

                if writer is not None:
                    node_state = np.full(n_nodes, state_name, dtype=object)
                    node_state[in_deep_sleep] = "deep_sleep"
                    node_state[dead_mask] = "dead"

                    writer.add_step(
                        time_ms=day_start_ms + sec_base_time_ms + sub_idx * dt_ms,
                        day_index=day_index + 1,
                        charging_mw=charging_mw,
                        irradiance_multiplier=irradiance,
                        consumption_mw=consumption_mw,
                        battery_joules=battery_j,
                        battery_pct=battery_pct,
                        node_state=node_state,
                    )

    if writer is not None:
        writer.flush()

    summary_df = pd.DataFrame(
        {
            "battery_option_mah": capacity_mah,
            "node_id": node_ids,
            "max_battery_joules": max_battery_j,
            "initial_battery_joules": initial_battery_j,
            "wake_threshold_joules": wake_threshold_j,
            "sleep_threshold_joules": sleep_threshold_j,
            "avg_charging_mw": charging_sum_mw / sample_count,
            "avg_consumption_mw": consumption_sum_mw / sample_count,
            "avg_net_power_mw": net_power_sum_mw / sample_count,
            "min_battery_pct": min_battery_pct,
            "max_battery_pct": max_battery_pct,
            "final_battery_pct": (battery_j / max_battery_j) * 100.0,
            "final_battery_joules": battery_j,
            "deep_sleep_pct": (deep_sleep_steps / sample_count) * 100.0,
            "active_pct": 100.0 - (deep_sleep_steps / sample_count) * 100.0,
            "depleted_once": ~np.isnan(first_death_time_ms),
            "revival_count": revival_count,
            "revived_once": revival_count > 0,
            "first_death_time_ms": first_death_time_ms,
            "first_death_day": np.where(~np.isnan(first_death_time_ms), first_death_time_ms / day_span_ms, np.nan),
            "first_revival_time_ms": first_revival_time_ms,
            "first_revival_day": np.where(~np.isnan(first_revival_time_ms), first_revival_time_ms / day_span_ms, np.nan),
        }
    )
    return summary_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-only", action="store_true", help="Write only summary CSVs and the comparison CSV")
    parser.add_argument("--emit-timeseries", action="store_true", help="Write per-step timeseries CSV")
    parser.add_argument("--days", type=int, default=DEFAULT_SIMULATION_DAYS, help="Number of simulation days")
    parser.add_argument("--dt-ms", type=int, default=DEFAULT_DT_MS, help="Simulation timestep in milliseconds")
    parser.add_argument("--capacities", nargs="*", type=int, default=BATTERY_OPTIONS_MAH, help="Battery capacities in mAh")
    parser.add_argument("--chunk-steps", type=int, default=2000, help="Timeseries write chunk size in steps")
    parser.add_argument("--max-nodes", type=int, default=None, help="Optional limit for number of nodes")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.dt_ms <= 0:
        raise ValueError("--dt-ms must be > 0")
    if 1000 % args.dt_ms != 0:
        raise ValueError("--dt-ms must divide 1000 (e.g., 1000, 100, 50, 20, 10)")
    if args.days <= 0:
        raise ValueError("--days must be > 0")

    project_root = Path(__file__).resolve().parent
    export_dir = project_root / "exports" / "latest"
    base_log_path = export_dir / "node_simulation_log.csv"
    output_dir = export_dir / f"battery_options_{args.days}d_{args.dt_ms}ms"
    output_dir.mkdir(parents=True, exist_ok=True)

    time_values, node_ids, charging_cycle, irradiance_cycle = load_base_cycle(base_log_path, max_nodes=args.max_nodes)

    total_steps = args.days * (len(time_values) - 1) * (1000 // args.dt_ms)
    estimated_rows_per_capacity = total_steps * len(node_ids)
    print(f"Simulation steps per capacity: {total_steps:,}")
    print(f"Estimated rows per capacity (timeseries): {estimated_rows_per_capacity:,}")

    comparison_rows = []

    for capacity_mah in args.capacities:
        writer = None
        if args.emit_timeseries:
            ts_path = output_dir / f"node_timeseries_{capacity_mah}mAh.csv"
            if ts_path.exists():
                ts_path.unlink()
            writer = TimeSeriesWriter(ts_path, node_ids=node_ids, chunk_steps=args.chunk_steps)

        summary_df = build_capacity_summary_and_optional_timeseries(
            time_values=time_values,
            node_ids=node_ids,
            charging_cycle_1s=charging_cycle,
            irradiance_cycle_1s=irradiance_cycle,
            capacity_mah=capacity_mah,
            simulation_days=args.days,
            dt_ms=args.dt_ms,
            writer=writer,
        )

        summary_path = output_dir / f"node_summary_{capacity_mah}mAh.csv"
        summary_df.to_csv(summary_path, index=False)

        if not args.summary_only and not args.emit_timeseries:
            raise NotImplementedError("Use --emit-timeseries for per-step output, or --summary-only for compact output.")

        comparison_rows.append(
            {
                "battery_option_mah": capacity_mah,
                "max_battery_joules": mah_to_joules(capacity_mah),
                "mean_final_battery_pct": summary_df["final_battery_pct"].mean(),
                "min_final_battery_pct": summary_df["final_battery_pct"].min(),
                "max_final_battery_pct": summary_df["final_battery_pct"].max(),
                "mean_avg_charging_mw": summary_df["avg_charging_mw"].mean(),
                "mean_avg_consumption_mw": summary_df["avg_consumption_mw"].mean(),
                "mean_avg_net_power_mw": summary_df["avg_net_power_mw"].mean(),
                "nodes_with_deep_sleep": int((summary_df["deep_sleep_pct"] > 0).sum()),
                "revived_nodes": int(summary_df["revived_once"].sum()),
                "total_revivals": int(summary_df["revival_count"].sum()),
                "median_first_death_day": summary_df["first_death_day"].dropna().median(),
                "earliest_first_death_day": summary_df["first_death_day"].dropna().min(),
                "latest_first_death_day": summary_df["first_death_day"].dropna().max(),
                "median_first_revival_day": summary_df["first_revival_day"].dropna().median(),
                "nodes_below_10pct_end": int((summary_df["final_battery_pct"] < 10.0).sum()),
                "nodes_below_1pct_end": int((summary_df["final_battery_pct"] < 1.0).sum()),
            }
        )

    comparison_df = pd.DataFrame(comparison_rows)
    comparison_df.to_csv(output_dir / "battery_option_comparison.csv", index=False)

    print("Battery option scenarios written to:")
    print(output_dir)
    print(comparison_df.to_string(index=False))


if __name__ == "__main__":
    main()
