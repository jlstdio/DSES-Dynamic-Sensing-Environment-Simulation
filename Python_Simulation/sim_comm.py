from __future__ import annotations

from typing import Any
import json

from communication_service import CommunicationService


class SimRadio:
    """Simulation-side communication library used by node_runtime.py."""

    def __init__(self, node_id: int, broker: CommunicationService) -> None:
        self.node_id = int(node_id)
        self.broker = broker

    def estimate_payload_bytes(self, payload: dict[str, Any]) -> int:
        return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def broadcast(self, payload: dict[str, Any], timestamp_ms: int, size_bytes: int | None = None) -> float:
        packet_size = int(size_bytes) if size_bytes is not None else self.estimate_payload_bytes(payload)
        return self.broker.queue_broadcast(self.node_id, payload, packet_size, timestamp_ms)

    def unicast(self, target_id: int, payload: dict[str, Any], timestamp_ms: int, size_bytes: int | None = None) -> float:
        packet_size = int(size_bytes) if size_bytes is not None else self.estimate_payload_bytes(payload)
        return self.broker.queue_unicast(self.node_id, int(target_id), payload, packet_size, timestamp_ms)
