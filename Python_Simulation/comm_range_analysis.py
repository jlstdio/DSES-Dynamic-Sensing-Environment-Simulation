"""
comm_range_analysis.py  (v2 — Redundancy & ECC)
================================================
Pairwise communication analysis for all 100 nodes across 5 coding schemes:

  none       : baseline, single transmission
  repeat_2   : ARQ-style, same packet sent twice; decoded if >= 1 copy arrives
  repeat_3   : same packet sent 3 times
  fec_r0.75  : (4,3) MDS erasure code — 33 % byte overhead, tolerates 1/4 lost
  fec_r0.50  : (4,2) MDS erasure code — 100 % byte overhead, tolerates 2/4 lost

"Should communicate" = XZ distance <= theoretical RF range (RSSI >= sensitivity)

Shadow fading model:
  - repeat_N : each copy has *independent* N(0,sigma) shadow draw (accurate)
  - fec      : single shadow draw -> analytical chunk-recovery probability

Metrics per scheme
------------------
  - Pairs with 100 % delivery  (delivered every trial)
  - Pairs with ANY delivery    (>= 1 trial)
  - Mean effective PDR
  - Byte overhead factor
  - Energy cost per successful delivery relative to baseline
"""
from __future__ import annotations

import json
import math
import pathlib

import numpy as np
import pandas as pd

BASE = pathlib.Path(__file__).parent

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
N_TRIALS       = 300   # broadcast rounds per scheme
PAYLOAD_BYTES  = 64    # data bytes per detection packet
DEFAULT_PL0_DB = 40.0
SEED_BASE      = 42

# ──────────────────────────────────────────────────────────────────────────────
# Coding schemes
# overhead_factor : transmitted bytes = PAYLOAD_BYTES x overhead_factor
# ──────────────────────────────────────────────────────────────────────────────
SCHEMES: list[dict] = [
    {"name": "none",      "type": "none",   "overhead": 1.0},
    {"name": "repeat_2",  "type": "repeat", "N": 2, "overhead": 2.0},
    {"name": "repeat_3",  "type": "repeat", "N": 3, "overhead": 3.0},
    {"name": "fec_r0.75", "type": "fec",    "k": 3, "n": 4, "overhead": 4 / 3},
    {"name": "fec_r0.50", "type": "fec",    "k": 2, "n": 4, "overhead": 2.0},
]

# ──────────────────────────────────────────────────────────────────────────────
# Load nodes & build distance matrix
# ──────────────────────────────────────────────────────────────────────────────
nodes_df = pd.read_csv(BASE / "exports/latest/nodes.csv")
nodes_df = nodes_df.sort_values("node_id").reset_index(drop=True)
pos_xz   = nodes_df[["x", "z"]].values.astype(float)
N        = len(nodes_df)
NODE_IDS = nodes_df["node_id"].values.tolist()

diff        = pos_xz[:, None, :] - pos_xz[None, :, :]
dist_matrix = np.linalg.norm(diff, axis=-1)   # (N, N) metres

comm_cfg = json.loads(
    (BASE / "node_hw_config/esp32-c3-mini/comm_config.json").read_text()
)

# ──────────────────────────────────────────────────────────────────────────────
# Channel model helpers
# ──────────────────────────────────────────────────────────────────────────────
def _pdr_vectorized(
    distances: np.ndarray,
    cfg: dict,
    rng: np.random.Generator,
) -> np.ndarray:
    """Raw single-transmission PDR: log-distance path loss + Gaussian shadow."""
    d0       = float(cfg.get("reference_distance_m", 1.0))
    tx       = float(cfg.get("tx_power_dbm", 0.0))
    noise    = float(cfg.get("noise_floor_dbm", -100.0))
    sens     = float(cfg.get("receiver_sensitivity_dbm", -97.0))
    gamma    = float(cfg.get("path_loss_exponent", 2.5))
    pl0      = float(cfg.get("path_loss_db_at_1m", DEFAULT_PL0_DB))
    sigma_db = float(cfg.get("shadow_sigma_db", 2.0))
    slope_db = float(cfg.get("snr_slope_db", 2.5))

    d         = np.maximum(distances, d0)
    path_loss = pl0 + 10.0 * gamma * np.log10(d / d0)
    shadow    = rng.normal(0.0, sigma_db, size=d.shape) if sigma_db > 0 else 0.0
    rssi      = tx - path_loss + shadow
    snr       = rssi - noise
    threshold = sens - noise
    x         = (snr - threshold) / max(slope_db, 0.1)
    return np.clip(1.0 / (1.0 + np.exp(-x)), 0.0, 1.0)


def _theoretical_range_m(cfg: dict) -> float:
    """Distance where median RSSI equals receiver_sensitivity_dbm (PDR ~ 0.5)."""
    tx   = float(cfg.get("tx_power_dbm", 0.0))
    sens = float(cfg.get("receiver_sensitivity_dbm", -97.0))
    pl0  = float(cfg.get("path_loss_db_at_1m", DEFAULT_PL0_DB))
    g    = float(cfg.get("path_loss_exponent", 2.5))
    d0   = float(cfg.get("reference_distance_m", 1.0))
    return d0 * 10.0 ** ((tx - sens - pl0) / (10.0 * g))


# ──────────────────────────────────────────────────────────────────────────────
# Per-scheme delivery simulation
# ──────────────────────────────────────────────────────────────────────────────
def simulate_scheme(
    pair_dist: np.ndarray,
    cfg: dict,
    scheme: dict,
    n_trials: int,
    seed: int,
) -> np.ndarray:
    """Returns deliver_cnt (n_pairs,) — successful deliveries across n_trials."""
    rng = np.random.default_rng(seed)
    n   = len(pair_dist)
    deliver_cnt = np.zeros(n, dtype=int)

    stype = scheme["type"]

    for _ in range(n_trials):
        if stype == "none":
            # single transmission, single shadow draw per trial
            pdr       = _pdr_vectorized(pair_dist, cfg, rng)
            delivered = rng.random(n) < pdr

        elif stype == "repeat":
            # N copies, each with independent shadow fading
            repeat_n     = int(scheme["N"])
            not_received = np.ones(n, dtype=bool)
            for _ in range(repeat_n):
                pdr          = _pdr_vectorized(pair_dist, cfg, rng)
                not_received &= ~(rng.random(n) < pdr)
            delivered = ~not_received

        elif stype == "fec":
            # (k, n_chunks) MDS erasure code
            # single fading event -> all chunks experience same channel state
            # P(success) = P(at least k of n_chunks arrive)
            k_chunks = int(scheme["k"])
            n_chunks = int(scheme["n"])
            pdr      = _pdr_vectorized(pair_dist, cfg, rng)
            fec_pdr  = np.zeros(n)
            for i in range(k_chunks, n_chunks + 1):
                c        = math.comb(n_chunks, i)
                fec_pdr += c * (pdr ** i) * ((1.0 - pdr) ** (n_chunks - i))
            delivered = rng.random(n) < np.clip(fec_pdr, 0.0, 1.0)
        else:
            raise ValueError(f"Unknown scheme type: {stype}")

        deliver_cnt += delivered.astype(int)

    return deliver_cnt


# ──────────────────────────────────────────────────────────────────────────────
# Protocol-level analysis (all 5 schemes compared)
# ──────────────────────────────────────────────────────────────────────────────
def run_analysis(mode_name: str, cfg: dict) -> None:
    d_theory  = _theoretical_range_m(cfg)
    max_range = cfg.get("max_range_m", 20.0)

    eye_mask    = np.eye(N, dtype=bool)
    should_mask = (dist_matrix <= d_theory) & ~eye_mask
    si, sj      = np.where(should_mask)
    n_should    = int(should_mask.sum())
    pair_dist   = dist_matrix[si, sj]

    bar = "=" * 72
    print(f"\n{bar}")
    print(f"  Protocol : {mode_name.upper()}")
    print(bar)
    print(f"  Configured max_range_m          : {max_range} m")
    print(f"  Theoretical range (sensitivity) : {d_theory:.1f} m  "
          f"(sensitivity = {cfg.get('receiver_sensitivity_dbm')} dBm)")
    print(f"  Total nodes                     : {N}")
    print(f"  Total directed pairs            : {N*(N-1)}")
    print(f"  Should-communicate pairs        : {n_should}  "
          f"({100*n_should/max(1, N*(N-1)):.2f}% of all pairs)")
    print(f"  Trials per scheme               : {N_TRIALS}")
    print()

    if n_should == 0:
        print("  *** No pairs within theoretical range. ***")
        return

    node_reach = np.zeros(N, dtype=int)
    np.add.at(node_reach, si, 1)
    print(f"  Per-node should-reach  (min / median / mean / max):")
    print(f"    {node_reach.min()} / {int(np.median(node_reach))} / "
          f"{node_reach.mean():.1f} / {node_reach.max()}")
    print()

    # ── scheme comparison table ────────────────────────────────────────────────
    COL = f"  {'scheme':<12}  {'100% pairs':>16}  {'any pairs':>16}  " \
          f"{'mean PDR':>9}  {'byte ovhd':>9}  {'J/success rel':>13}"
    SEP = f"  {'-'*86}"
    print(COL)
    print(SEP)

    scheme_results: list[dict] = []
    baseline_pdr = None

    for scheme in SCHEMES:
        deliver_cnt = simulate_scheme(pair_dist, cfg, scheme, N_TRIALS, seed=SEED_BASE)
        pair_pdr    = deliver_cnt / N_TRIALS
        n_100       = int((deliver_cnt == N_TRIALS).sum())
        n_any       = int((deliver_cnt >= 1).sum())
        mean_pdr    = float(pair_pdr.mean())
        overhead    = float(scheme["overhead"])

        if baseline_pdr is None:
            baseline_pdr = mean_pdr

        # Energy per successful delivery: proportional to (overhead / pdr_eff)
        # Normalised to baseline (none) = 1.0
        energy_rel = (overhead / mean_pdr) * baseline_pdr if mean_pdr > 0 else float("inf")
        pdr_gain   = ((mean_pdr - baseline_pdr) / max(baseline_pdr, 1e-9)) * 100

        gain_tag = f"  [PDR +{pdr_gain:.1f}%]" if pdr_gain > 0 else ""
        print(f"  {scheme['name']:<12}  "
              f"{n_100:>6}/{n_should:<6} ({100*n_100/n_should:>5.1f}%)  "
              f"{n_any:>6}/{n_should:<6} ({100*n_any/n_should:>5.1f}%)  "
              f"{mean_pdr:>8.4f}  "
              f"{overhead:>8.2f}x  "
              f"{energy_rel:>12.3f}x"
              + gain_tag)

        if scheme["name"] in ("none", "fec_r0.75", "repeat_3"):
            node_100_arr = np.zeros(N, dtype=int)
            node_any_arr = np.zeros(N, dtype=int)
            node_pdr_sum = np.zeros(N, dtype=float)
            np.add.at(node_100_arr, si, (deliver_cnt == N_TRIALS).astype(int))
            np.add.at(node_any_arr, si, (deliver_cnt >= 1).astype(int))
            np.add.at(node_pdr_sum, si, pair_pdr)
            node_mean_pdr = np.where(node_reach > 0, node_pdr_sum / node_reach, 0.0)
            scheme_results.append({
                "scheme": scheme["name"],
                "deliver_cnt": deliver_cnt.copy(),
                "pair_pdr": pair_pdr.copy(),
                "node_100": node_100_arr,
                "node_any": node_any_arr,
                "node_mean_pdr": node_mean_pdr,
            })

    print()

    # ── per-node breakdown for none / fec_r0.75 / repeat_3 ────────────────────
    key = {r["scheme"]: r for r in scheme_results}
    print("  Per-node breakdown — none / fec_r0.75 / repeat_3  (as sender):")
    print(f"  {'node_id':>7}  {'should':>6}  "
          f"{'none 100%':>9}  {'fec75 100%':>10}  {'rep3 100%':>9}  "
          f"{'none PDR':>8}  {'fec75 PDR':>9}  {'rep3 PDR':>8}")
    print(f"  {'-'*79}")
    for idx in range(N):
        nid = NODE_IDS[idx]
        r   = int(node_reach[idx])
        def _g(s, k):
            return key[s][k][idx] if s in key else 0
        print(f"  {nid:>7}  {r:>6}  "
              f"{int(_g('none',    'node_100')):>9}  "
              f"{int(_g('fec_r0.75','node_100')):>10}  "
              f"{int(_g('repeat_3','node_100')):>9}  "
              f"{float(_g('none',    'node_mean_pdr')):>8.4f}  "
              f"{float(_g('fec_r0.75','node_mean_pdr')):>9.4f}  "
              f"{float(_g('repeat_3','node_mean_pdr')):>8.4f}")

    # ── save CSVs for none and fec_r0.75 ──────────────────────────────────────
    for res in scheme_results:
        if res["scheme"] not in ("none", "fec_r0.75"):
            continue
        rows = [
            {
                "sender_id"   : NODE_IDS[int(si[k])],
                "receiver_id" : NODE_IDS[int(sj[k])],
                "distance_m"  : round(float(dist_matrix[si[k], sj[k]]), 3),
                "delivery_cnt": int(res["deliver_cnt"][k]),
                "pdr"         : round(float(res["pair_pdr"][k]), 5),
                "100pct"      : bool(res["deliver_cnt"][k] == N_TRIALS),
                "any_del"     : bool(res["deliver_cnt"][k] >= 1),
            }
            for k in range(len(si))
        ]
        tag      = res["scheme"].replace(".", "")
        out_path = BASE / f"comm_range_{mode_name}_{tag}.csv"
        pd.DataFrame(rows).to_csv(out_path, index=False)
        print(f"\n  CSV saved -> {out_path.name}")
    print()


# ──────────────────────────────────────────────────────────────────────────────
# Global distance statistics + run
# ──────────────────────────────────────────────────────────────────────────────
upper_tri = dist_matrix[np.triu_indices(N, k=1)]
print(f"\n{'='*72}")
print(f"  Node deployment — global distance statistics ({N} nodes)")
print(f"{'='*72}")
print(f"  Undirected pairs : {len(upper_tri)}")
print(f"  Min / Max        : {upper_tri.min():.1f} m  /  {upper_tri.max():.1f} m")
print(f"  Mean / Median    : {upper_tri.mean():.1f} m  /  {float(np.median(upper_tri)):.1f} m")

for mode_name, mode_cfg in comm_cfg["modes"].items():
    run_analysis(mode_name, mode_cfg)

print(f"\n{'='*72}")
print("  Done.")
print(f"{'='*72}")
