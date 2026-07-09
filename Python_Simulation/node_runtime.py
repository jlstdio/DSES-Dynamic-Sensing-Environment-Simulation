from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from communication_service import Packet
from sim_comm import SimRadio


@dataclass
class NodeTickMetrics:
    state: str
    consumption_mw: float
    tx_energy_j: float
    rx_energy_j: float
    rx_count: int


class NodeRuntime:
    """Per-node runtime intended to feel like an ESP MicroPython application."""

    def __init__(
        self,
        node_id: int,
        hw_cfg: dict[str, Any],
        mcu_cfg: dict[str, Any],
        radio: SimRadio,
    ) -> None:
        self.node_id = int(node_id)
        self.hw_cfg = hw_cfg
        self.mcu_cfg = mcu_cfg
        self.radio = radio

        v = float(hw_cfg["battery_voltage_v"])
        capacity_mah = float(hw_cfg["battery_capacity_mah"])
        self.max_battery_j = (capacity_mah / 1000.0) * v * 3600.0
        self.battery_j = self.max_battery_j * float(hw_cfg["initial_battery_ratio"])
        self.wake_threshold_j = self.max_battery_j * float(hw_cfg["wake_threshold_ratio"])
        self.sleep_threshold_j = self.max_battery_j * float(hw_cfg["sleep_threshold_ratio"])

        self.in_deep_sleep = False
        self.dead = False
        self.pending_detection: dict[str, Any] | None = None

        self.inbox: list[Packet] = []
        self.pending_rx_energy_j = 0.0

        self.sent_packets = 0
        self.received_packets = 0
        self.collab_events = 0

    def enqueue_received(self, packets: list[Packet], rx_energy_j: float) -> None:
        if packets:
            self.inbox.extend(packets)
        self.pending_rx_energy_j += float(rx_energy_j)

    def tick(
        self,
        current_time_ms: int,
        dt_ms: int,
        charging_mw: float,
        sound_events: list[dict[str, Any]],
        sub_step: int,
        steps_per_second: int,
    ) -> NodeTickMetrics:
        dt_s = float(dt_ms) / 1000.0
        charging_j = float(charging_mw) * dt_s / 1000.0

        # Deep sleep and death transitions
        if self.in_deep_sleep and self.battery_j >= self.wake_threshold_j:
            self.in_deep_sleep = False
            self.dead = False
        if self.battery_j <= self.sleep_threshold_j:
            self.in_deep_sleep = True
        if self.battery_j <= 0.0 and charging_mw <= 0.0:
            self.dead = True

        tx_energy_j = 0.0
        rx_energy_j = self.pending_rx_energy_j
        self.pending_rx_energy_j = 0.0
        rx_count = len(self.inbox)

        base_consumption_mw = 0.0
        dynamic_compute_j = 0.0
        state = "deep_sleep"

        if self.dead:
            state = "dead"
            base_consumption_mw = 0.0
            self.inbox.clear()
        elif self.in_deep_sleep:
            state = "deep_sleep"
            base_consumption_mw = float(self.hw_cfg["deep_sleep_power_mw"])
            self.inbox.clear()
        else:
            sensing_end = int(0.60 * steps_per_second)
            inference_end = int(0.85 * steps_per_second)

            if sub_step < sensing_end:
                state = "sensing"
                base_consumption_mw = float(self.hw_cfg["sensor_power_mw"])
                if sound_events:
                    strongest = max(sound_events, key=lambda e: float(e.get("received_db", 0.0)))
                    self.pending_detection = {
                        "event_id": int(strongest.get("event_id", -1)),
                        "label": str(strongest.get("label_name", "unknown")),
                        "received_db": float(strongest.get("received_db", 0.0)),
                        "source": "local",
                    }
            elif sub_step < inference_end:
                state = "inference"
                base_consumption_mw = float(self.hw_cfg["base_inference_power_mw"])
                infer_bytes = int(self.hw_cfg.get("inference_input_bytes", 512))
                dynamic_compute_j += self._compute_energy_j(infer_bytes, "cycles_per_byte_inference")
            else:
                state = "communication"
                base_consumption_mw = float(self.hw_cfg["base_communication_power_mw"])
                if self.pending_detection is not None:
                    payload = {
                        "type": "detection",
                        "node_id": self.node_id,
                        "event_id": int(self.pending_detection["event_id"]),
                        "label": str(self.pending_detection["label"]),
                        "received_db": float(self.pending_detection["received_db"]),
                        "timestamp_ms": int(current_time_ms),
                    }
                    payload_bytes = self.radio.estimate_payload_bytes(payload)
                    dynamic_compute_j += self._compute_energy_j(payload_bytes, "cycles_per_byte_tx_prep")
                    tx_energy_j += float(self.radio.broadcast(payload, current_time_ms, size_bytes=payload_bytes))
                    self.sent_packets += 1
                    self.pending_detection = None

            # Handle collaboration packets while awake.
            if self.inbox:
                self.received_packets += len(self.inbox)
                for packet in self.inbox:
                    if str(packet.payload.get("type", "")) == "detection":
                        self.collab_events += 1
                self.inbox.clear()

        base_consumption_j = base_consumption_mw * dt_s / 1000.0
        total_consumption_j = base_consumption_j + dynamic_compute_j + tx_energy_j + rx_energy_j

        self.battery_j = min(self.max_battery_j, max(0.0, self.battery_j + charging_j - total_consumption_j))

        effective_mw = (total_consumption_j * 1000.0 / dt_s) if dt_s > 0 else 0.0
        return NodeTickMetrics(
            state=state,
            consumption_mw=float(effective_mw),
            tx_energy_j=float(tx_energy_j),
            rx_energy_j=float(rx_energy_j),
            rx_count=rx_count,
        )

    def _compute_energy_j(self, byte_count: int, cycles_key: str) -> float:
        if byte_count <= 0:
            return 0.0
        cycles_per_byte = float(self.mcu_cfg["compute_model"].get(cycles_key, 0.0))
        joules_per_cycle = float(self.mcu_cfg["power"].get("joules_per_cycle_160mhz", 0.0))
        return float(byte_count) * cycles_per_byte * joules_per_cycle
