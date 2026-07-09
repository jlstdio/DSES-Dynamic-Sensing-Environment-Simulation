from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math
import numpy as np


@dataclass
class Packet:
    sender_id: int
    payload: dict[str, Any]
    size_bytes: int
    timestamp_ms: int
    mode: str
    target_id: int | None = None


class CommunicationService:
    """Centralized wireless broker for node-to-node communication.

    Protocol-appropriate FEC / repeat coding is applied entirely inside this
    broker (node firmware only calls radio.broadcast()). A coding scheme is
    described by three parameters resolved from comm_config.json:

      - coding_gain_db  : receiver-sensitivity improvement from FEC. Lowers the
                          effective sensitivity floor, raising per-copy PDR.
                          (WiFi5 BCC/LDPC; BLE5 LE Coded S=2/S=8)
      - byte_overhead   : parity/coding bytes multiplier (1 / code_rate). Every
                          transmitted and decoded byte costs this much more
                          energy. (rate 1/2 -> 2x, S=8 -> 8x)
      - redundancy_factor: number of repeated copies sent (BLE advertising on 3
                          channels, WiFi robust-broadcast repeat). A packet is
                          delivered if ANY copy is decoded; TX energy scales with
                          the number of copies.
    """

    def __init__(
        self,
        positions_xz: np.ndarray,
        mode_name: str,
        mode_cfg: dict[str, Any],
        seed: int = 42,
        coding_scheme: str | None = None,
    ) -> None:
        if positions_xz.ndim != 2 or positions_xz.shape[1] != 2:
            raise ValueError("positions_xz must be shaped (N, 2).")
        self.positions_xz = positions_xz.astype(float)
        self.mode_name = mode_name
        self.cfg = mode_cfg
        self.rng = np.random.default_rng(seed)
        self.pending_packets: list[Packet] = []

        # Resolve the active coding scheme from the mode's coding block.
        coding_cfg = dict(mode_cfg.get("coding", {}))
        schemes = dict(coding_cfg.get("schemes", {}))
        scheme_name = coding_scheme or coding_cfg.get("active")
        if scheme_name and scheme_name in schemes:
            self.coding_name = scheme_name
            scheme = schemes[scheme_name]
        elif scheme_name:
            raise KeyError(
                f"Coding scheme '{scheme_name}' not found for mode '{mode_name}'. "
                f"Available: {sorted(schemes.keys())}"
            )
        else:
            # No coding block -> uncoded passthrough.
            self.coding_name = "uncoded"
            scheme = {}

        self.coding_gain_db = float(scheme.get("coding_gain_db", 0.0))
        self.byte_overhead = float(scheme.get("byte_overhead", 1.0))
        self.redundancy_factor = max(1, int(scheme.get("redundancy_factor", 1)))
        self.coding_type = str(scheme.get("type", "none"))
        self.coding_label = str(scheme.get("label", self.coding_name))

        # Spec-based maximum range from the RF link budget (not a hard cap).
        # The usable range is the distance where the median received power
        # (no shadow) equals the receiver sensitivity, i.e. median PDR = 0.5:
        #
        #   tx_dbm - (pl0 + 10*gamma*log10(d/d0)) = sensitivity_dbm
        #
        # FEC coding gain lowers the effective sensitivity, so it extends the
        # range automatically (e.g. +12 dB, gamma 4.3 -> ~1.9x range in forest).
        d0 = max(0.1, float(mode_cfg.get("reference_distance_m", 1.0)))
        tx_dbm = float(mode_cfg.get("tx_power_dbm", 0.0))
        sens_dbm = float(mode_cfg.get("receiver_sensitivity_dbm", -97.0))
        pl0 = float(mode_cfg.get("path_loss_db_at_1m", 40.0))
        gamma = float(mode_cfg.get("path_loss_exponent", 2.5))

        # Uncoded reference range (spec baseline, e.g. WiFi5 ~40 m).
        self.uncoded_range_m = d0 * (10.0 ** ((tx_dbm - sens_dbm - pl0) / (10.0 * gamma)))
        # Effective range including this scheme's coding gain.
        margin_db = tx_dbm - (sens_dbm - self.coding_gain_db) - pl0
        self.effective_max_range_m = d0 * (10.0 ** (margin_db / (10.0 * gamma)))

    def queue_broadcast(self, sender_id: int, payload: dict[str, Any], size_bytes: int, timestamp_ms: int) -> float:
        packet = Packet(
            sender_id=sender_id,
            payload=payload,
            size_bytes=int(size_bytes),
            timestamp_ms=int(timestamp_ms),
            mode=self.mode_name,
        )
        self.pending_packets.append(packet)
        return self._tx_energy_j(packet.size_bytes)

    def queue_unicast(self, sender_id: int, target_id: int, payload: dict[str, Any], size_bytes: int, timestamp_ms: int) -> float:
        packet = Packet(
            sender_id=sender_id,
            payload=payload,
            size_bytes=int(size_bytes),
            timestamp_ms=int(timestamp_ms),
            mode=self.mode_name,
            target_id=int(target_id),
        )
        self.pending_packets.append(packet)
        return self._tx_energy_j(packet.size_bytes)

    def flush(self, can_receive_mask: np.ndarray) -> tuple[dict[int, list[Packet]], dict[int, float], list[dict[str, Any]]]:
        n_nodes = self.positions_xz.shape[0]
        inbox: dict[int, list[Packet]] = {i: [] for i in range(n_nodes)}
        rx_energy_j: dict[int, float] = {i: 0.0 for i in range(n_nodes)}
        delivery_log: list[dict[str, Any]] = []

        for packet in self.pending_packets:
            targets = range(n_nodes) if packet.target_id is None else [packet.target_id]
            for target_id in targets:
                if target_id == packet.sender_id:
                    continue
                if not bool(can_receive_mask[target_id]):
                    continue

                dist = float(np.linalg.norm(self.positions_xz[packet.sender_id] - self.positions_xz[target_id]))
                if dist > self.effective_max_range_m:
                    continue

                # A packet is delivered if ANY of the redundant copies decodes.
                # Each copy sees an independent shadow-fading draw; the coding
                # gain (FEC) is folded into the sensitivity inside _pdr_for_distance.
                per_copy_pdr = self._pdr_for_distance(dist)
                copies = self.redundancy_factor
                p_fail_all = (1.0 - per_copy_pdr) ** copies
                effective_pdr = 1.0 - p_fail_all
                delivered = bool(self.rng.random() < effective_pdr)
                delivery_log.append(
                    {
                        "sender_id": int(packet.sender_id),
                        "target_id": int(target_id),
                        "timestamp_ms": int(packet.timestamp_ms),
                        "distance_m": dist,
                        "pdr": effective_pdr,
                        "per_copy_pdr": per_copy_pdr,
                        "delivered": delivered,
                        "size_bytes": int(packet.size_bytes),
                        "mode": self.mode_name,
                        "coding": self.coding_name,
                        "copies": copies,
                    }
                )
                if delivered:
                    inbox[target_id].append(packet)
                    rx_energy_j[target_id] += self._rx_energy_j(packet.size_bytes)

        self.pending_packets.clear()
        return inbox, rx_energy_j, delivery_log

    def _tx_energy_j(self, size_bytes: int) -> float:
        # FEC parity bytes (byte_overhead) inflate the on-air payload, and each
        # redundant copy is a full transmission (base overhead + payload).
        coded_bytes = float(size_bytes) * self.byte_overhead
        per_copy = float(self.cfg.get("base_overhead_joules", 0.0)) + float(self.cfg.get("tx_joules_per_byte", 0.0)) * coded_bytes
        return per_copy * float(self.redundancy_factor)

    def _rx_energy_j(self, size_bytes: int) -> float:
        # Receiver decodes one successful (coded) copy: RX preamble + coded bytes.
        rx_base = float(self.cfg.get("base_overhead_joules", 0.0)) * 0.25
        coded_bytes = float(size_bytes) * self.byte_overhead
        return rx_base + float(self.cfg.get("rx_joules_per_byte", 0.0)) * coded_bytes

    def _pdr_for_distance(self, distance_m: float) -> float:
        d0 = max(0.1, float(self.cfg.get("reference_distance_m", 1.0)))
        tx_power_dbm = float(self.cfg.get("tx_power_dbm", 0.0))
        noise_floor_dbm = float(self.cfg.get("noise_floor_dbm", -100.0))
        sensitivity_dbm = float(self.cfg.get("receiver_sensitivity_dbm", -97.0))
        gamma = float(self.cfg.get("path_loss_exponent", 2.5))
        pl0 = float(self.cfg.get("path_loss_db_at_1m", 40.0))
        sigma_db = float(self.cfg.get("shadow_sigma_db", 2.0))
        slope_db = float(self.cfg.get("snr_slope_db", 2.5))

        # FEC coding gain effectively lowers the required receiver sensitivity.
        sensitivity_dbm -= self.coding_gain_db

        d = max(distance_m, d0)
        path_loss_db = pl0 + 10.0 * gamma * math.log10(d / d0)
        shadow_db = float(self.rng.normal(0.0, sigma_db)) if sigma_db > 0 else 0.0
        rssi_dbm = tx_power_dbm - path_loss_db + shadow_db
        snr_db = rssi_dbm - noise_floor_dbm
        snr_threshold_db = sensitivity_dbm - noise_floor_dbm

        x = (snr_db - snr_threshold_db) / max(0.1, slope_db)
        p = 1.0 / (1.0 + math.exp(-x))
        return float(min(1.0, max(0.0, p)))
