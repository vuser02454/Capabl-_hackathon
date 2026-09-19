"""In-memory record of agent health, surfaced by GET /api/agents/status."""

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from schemas import AgentStatus

AGENTS = (
    ("air", "Air Quality Agent"),
    ("water", "Water Quality Agent"),
    ("waste", "Waste Detection Agent"),
    ("coordinator", "Coordinator Agent"),
)


class AgentRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: Dict[str, dict] = {}

    def record(self, agent_id: str, status: str, duration_ms: int, provider: str) -> None:
        with self._lock:
            self._runs[agent_id] = {
                "status": status,
                "duration_ms": duration_ms,
                "provider": provider,
                "at": datetime.now(timezone.utc),
            }

    def snapshot(self, providers: Dict[str, str]) -> List[AgentStatus]:
        with self._lock:
            statuses = []
            for agent_id, name in AGENTS:
                run: Optional[dict] = self._runs.get(agent_id)
                statuses.append(
                    AgentStatus(
                        id=agent_id,  # type: ignore[arg-type]
                        name=name,
                        status="degraded" if run and run["status"] != "complete" else "operational",
                        provider=run["provider"] if run else providers.get(agent_id, "—"),
                        last_run_at=run["at"] if run else None,
                        last_duration_ms=run["duration_ms"] if run else None,
                    )
                )
            return statuses


registry = AgentRegistry()
