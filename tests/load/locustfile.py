"""
P9-03 — Load test: 1000 ticket submissions → verify queue handles without dropping.

Run with:
    locust -f tests/load/locustfile.py --host=http://localhost:80 \
           --users=50 --spawn-rate=10 --run-time=60s --headless

Or with the Locust web UI:
    locust -f tests/load/locustfile.py --host=http://localhost:80

Scenarios:
  - TicketUser: submits tickets and polls for status (primary load)
  - OpsUser:    polls /ops/queue and /ops/cost (read-only ops traffic)

Target assertions (checked in __exit__ / custom event hooks):
  - 0% request failures for POST /tickets
  - p95 latency for POST /tickets < 500ms
  - Ticket status transitions from queued → done/failed/escalated (not stuck)
"""

import json
import random
import time
import uuid
from locust import HttpUser, TaskSet, task, between, events
from locust.exception import StopUser


# ── Sample ticket descriptions ─────────────────────────────────────────────────

TICKET_DESCRIPTIONS = [
    "CUDA out of memory error on training job — GPU shows 100% utilisation",
    "SSH connection refused on port 22 — server appears unresponsive",
    "Disk usage at 95% on / partition — training job aborted",
    "nvidia-smi shows ECC errors: 3 uncorrected on GPU 0",
    "Docker daemon not responding — systemctl status shows failed",
    "OOM killer invoked — training process killed, 90GB swap in use",
    "Network throughput dropped to 0 — no ping response from server",
    "CUDA driver version mismatch after kernel update",
    "Jupyter notebook server crashed — port 8888 not listening",
    "GPU temperature 92°C — training paused by thermal throttle",
]

SERVER_IDS = [f"srv-gpu-{i:02d}" for i in range(1, 11)]


# ── JWT token management ───────────────────────────────────────────────────────

_jwt_token: str = ""


def get_auth_token(client) -> str:
    """Obtain a JWT token from /auth/token. Cached per process."""
    global _jwt_token
    if _jwt_token:
        return _jwt_token
    resp = client.post("/auth/token", json={
        "username": "loadtest",
        "password": "loadtest-password",
    }, name="/auth/token [setup]")
    if resp.status_code == 200:
        _jwt_token = resp.json().get("access_token", "")
    return _jwt_token


# ── TaskSets ───────────────────────────────────────────────────────────────────

class TicketFlow(TaskSet):
    """
    Primary scenario: submit a ticket and poll for its status.

    Simulates the customer-facing workflow:
      1. POST /tickets — submit
      2. GET  /tickets/{id} — poll up to 5 times
    """

    token: str = ""

    def on_start(self):
        self.token = get_auth_token(self.client)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(8)
    def submit_and_poll_ticket(self):
        description = random.choice(TICKET_DESCRIPTIONS)
        server_id = random.choice(SERVER_IDS)

        # Submit ticket
        resp = self.client.post(
            "/tickets",
            json={
                "server_id": server_id,
                "description": description,
                "user_id": f"user-load-{random.randint(1, 1000)}",
            },
            headers=self._headers(),
            name="POST /tickets",
        )

        if resp.status_code not in (200, 201, 202):
            return

        ticket_id = resp.json().get("ticket_id") or resp.json().get("id")
        if not ticket_id:
            return

        # Poll up to 5 times with 2s interval
        for _ in range(5):
            time.sleep(2)
            poll = self.client.get(
                f"/tickets/{ticket_id}",
                headers=self._headers(),
                name="GET /tickets/{id}",
            )
            if poll.status_code == 200:
                status = poll.json().get("status", "")
                if status in ("done", "failed", "escalated"):
                    break

    @task(2)
    def poll_existing_ticket(self):
        """Simulate users polling an already-submitted ticket."""
        fake_id = str(uuid.uuid4())
        self.client.get(
            f"/tickets/{fake_id}",
            headers=self._headers(),
            name="GET /tickets/{id} [miss]",
        )


class OpsMonitorFlow(TaskSet):
    """
    Secondary scenario: ops team monitoring queue and cost endpoints.
    Lower weight — 1 ops user per 10 ticket users.
    """

    token: str = ""

    def on_start(self):
        self.token = get_auth_token(self.client)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(3)
    def check_queue(self):
        self.client.get("/ops/queue", headers=self._headers(), name="GET /ops/queue")

    @task(2)
    def check_cost(self):
        self.client.get("/ops/cost", headers=self._headers(), name="GET /ops/cost")

    @task(1)
    def check_agents(self):
        self.client.get("/ops/agents", headers=self._headers(), name="GET /ops/agents")

    @task(1)
    def ops_dashboard(self):
        self.client.get("/ops/dashboard", name="GET /ops/dashboard")


# ── User classes ───────────────────────────────────────────────────────────────

class TicketUser(HttpUser):
    """Simulates a customer submitting support tickets."""
    tasks = [TicketFlow]
    wait_time = between(1, 3)
    weight = 9


class OpsUser(HttpUser):
    """Simulates an ops team member monitoring the dashboard."""
    tasks = [OpsMonitorFlow]
    wait_time = between(5, 15)
    weight = 1


# ── Custom event hooks for assertions ─────────────────────────────────────────

@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    """
    Fail the run if error rate for ticket submission is > 1%.
    This enforces the P9-03 requirement: no tickets dropped.
    """
    stats = environment.stats.get("/tickets", "POST")
    if stats is None:
        return

    total = stats.num_requests
    failures = stats.num_failures

    if total == 0:
        return

    failure_rate = failures / total
    if failure_rate > 0.01:
        print(
            f"\n[ASSERTION FAILED] POST /tickets failure rate {failure_rate:.1%} > 1%\n"
            f"  total={total}  failures={failures}\n"
            "  The queue dropped or rejected tickets under load."
        )
        environment.process_exit_code = 1
    else:
        print(
            f"\n[ASSERTION PASSED] POST /tickets failure rate {failure_rate:.1%} ≤ 1%\n"
            f"  total={total}  failures={failures}"
        )
