# TODO_V2 — Architecture Debt Remediation

> **Why this exists:** Senior engineer review flagged that V1 domain logic is solid but the
> implementation has no abstraction — extending any part requires rewriting that part.
> Full diagnosis: [`ARCHITECTURE_DEBT.md`](ARCHITECTURE_DEBT.md)
>
> **Rule:** Read `ARCHITECTURE_DEBT.md` before working on any task here.
> Mark `[x]` when done. Work phase-by-phase, top-to-bottom within each phase.
> Do NOT start a phase until the previous phase's tests pass.

---

## Scope of V2

V2 is a **pure refactoring** — no new features, no domain logic changes.
The five changes are additive layers on top of working V1 code.

| Phase | What changes | What stays the same |
|---|---|---|
| V2-P1 Tool Registry | How tools are registered and dispatched | Tool logic, vault calls, RAG calls |
| V2-P2 Typed State | `StateGraph(dict)` → `StateGraph(TypedDict)` | Graph topology, node functions |
| V2-P3 Node Decorator | Add `@node` to every node function | Node function bodies |
| V2-P4 Dependency Injection | Graph constructors accept context object | Graph wiring, prompts |
| V2-P5 Benchmarks | New `tests/perf/` suite added | Existing unit + integration tests |

**Do not change:** vault crypto, RAG pipeline internals, Redis consumer, APScheduler jobs,
database migrations, Dockerfiles, nginx config, Grafana dashboards (except P3 additions),
or any V1 test that is currently passing.

---

## Migration Risk Map

Before starting: identify tests that will break during refactor so they are expected, not surprises.

| Phase | Tests expected to break (temporarily) | Fix strategy |
|---|---|---|
| V2-P1 | `test_tools.py` in client-agent + inserver-agent (import paths change) | Update imports after registry is wired |
| V2-P2 | Any test that passes bare `dict` state into graph nodes | Update fixture state dicts to match TypedDict fields |
| V2-P3 | None — decorator is additive | — |
| V2-P4 | All graph executor tests that patch `anthropic.AsyncAnthropic` at module level | Replace patches with injected `MockLLMClient` |
| V2-P5 | None — new files only | — |

---

## V2-PHASE 1 — Tool Registry

**Goal:** Replace hardcoded `TOOL_DEFINITIONS` JSON lists and `match tool_name:` dispatchers
with a `ToolRegistry` that is the single source of truth for schema + implementation.

**Definition of done:** `registry.schemas` produces identical JSON to the old `TOOL_DEFINITIONS`,
`registry.dispatch()` produces identical results to the old `dispatch_tool()`, all existing
tool tests pass.

### Shared infrastructure

- [ ] `V2-P1-01` Create `services/shared/tool_registry.py`
  - `ToolDefinition(name, description, input_model: type[BaseModel], handler: Callable)`
  - `ToolDefinition.to_anthropic_schema() -> dict` — auto-generates from `input_model.model_json_schema()`
  - `ToolRegistry` with `.register(tool) -> self`, `.schemas -> list[dict]`, `async .dispatch(name, inputs, **ctx) -> dict`
  - `dispatch` validates inputs through `input_model` before calling handler; returns `{"error": "..."}` on unknown tool
  - Add `tool_duration_seconds` Prometheus `Histogram` inside `dispatch` (labels: `tool`)

- [ ] `V2-P1-02` Create `services/shared/tools/` package (`__init__.py` only — no logic)

- [ ] `V2-P1-03` Create `services/shared/tools/rag_tool.py`
  - `RagSearchInput(BaseModel)` — fields: `query: str`, `top_k: int = 5`, `tags: list[str] = []`
  - `async rag_search_handler(query, top_k, tags, **ctx) -> dict` — identical body to current `client-agent/tools.py:rag_search`
  - Keep existing `rag_search` in `client-agent/tools.py` as a thin wrapper calling the handler (backwards compat during migration)

- [ ] `V2-P1-04` Create `services/shared/tools/ssh_tool.py`
  - `SshExecuteInput(BaseModel)` — fields: `server_id: str`, `command: str`, `session_token: str | None = None`
  - `HardRestartInput(BaseModel)` — fields: `server_id: str`, `reason: str`
  - `async ssh_execute_handler(server_id, command, session_token, **ctx) -> dict`
  - `async hard_restart_handler(server_id, reason, **ctx) -> dict`

- [ ] `V2-P1-05` Create `services/shared/tools/web_tool.py`
  - `WebSearchInput(BaseModel)` — fields: `query: str`, `max_results: int = 5`
  - `WebFetchInput(BaseModel)` — fields: `url: str`
  - Handlers wrapping current Tavily/httpx calls

- [ ] `V2-P1-06` Create `services/shared/tools/ticket_tool.py`
  - `UpdateTicketInput(BaseModel)` — fields: `ticket_id: str`, `status: str`, `message: str | None = None`
  - `StoreFixPatternInput(BaseModel)` — fields: `error_pattern: str`, `fix_steps: str`, `tags: list[str] = []`, `confidence: float = 0.8`
  - Handlers wrapping current DB calls (accept `db: AsyncSession` from `**ctx`)

- [ ] `V2-P1-07` Create `services/shared/tools/system_tool.py`
  - `LogActionInput(BaseModel)` — fields: `action: str`, `details: str`, `server_id: str`
  - `GetServerInfoInput(BaseModel)` — fields: `server_id: str`
  - Handlers wrapping current calls

### Wire registry into client-agent

- [ ] `V2-P1-08` Create `services/client-agent/registry.py`
  - Build `client_registry = ToolRegistry()` by registering tools from `shared/tools/`
  - Export `CLIENT_TOOL_SCHEMAS = client_registry.schemas` (replaces old `TOOL_DEFINITIONS`)

- [ ] `V2-P1-09` Update `services/client-agent/tools.py`
  - Remove `TOOL_DEFINITIONS` list entirely
  - Remove `dispatch_tool` match function
  - Import `client_registry` from `registry.py`
  - Expose `dispatch_tool = client_registry.dispatch` for backward compat with graph.py callers
  - Expose `TOOL_DEFINITIONS = client_registry.schemas`

### Wire registry into inserver-agent

- [ ] `V2-P1-10` Create `services/inserver-agent/registry.py`
  - Build `inserver_registry = ToolRegistry()` with inserver-specific tools only
  - `ssh_execute`, `hard_restart`, `log_action`, `get_server_info` (no RAG, no web search)

- [ ] `V2-P1-11` Update `services/inserver-agent/tools.py`
  - Same pattern as V2-P1-09 (remove TOOL_DEFINITIONS + dispatch_tool, expose via registry)

### Tests

- [ ] `V2-P1-12` Write `services/shared/tests/test_tool_registry.py`
  - `test_schema_generation` — `registry.schemas` output matches the old hardcoded JSON shape
  - `test_dispatch_known_tool` — dispatches to correct handler, passes validated inputs
  - `test_dispatch_unknown_tool` — returns `{"error": "Unknown tool: ..."}` without raising
  - `test_dispatch_invalid_input` — bad input type raises `ValidationError` before handler is called
  - `test_tool_duration_metric_recorded` — after dispatch, Prometheus counter has a value

- [ ] `V2-P1-13` Update existing `client-agent` and `inserver-agent` tool tests
  - Import paths that changed: update to use `client_registry.dispatch` instead of `dispatch_tool`
  - Confirm all existing assertions still hold

---

## V2-PHASE 2 — Typed Agent State

**Goal:** Replace `StateGraph(dict)` with `StateGraph(TypedDict)` in client-agent and
inserver-agent. Report-agent already has a `ReportState` TypedDict — leave it.

**Definition of done:** `mypy services/client-agent/graph.py services/inserver-agent/graph.py`
reports zero new errors on state key access.

- [ ] `V2-P2-01` Create `services/client-agent/state.py`
  ```python
  class ClientAgentState(TypedDict, total=False):
      ticket_id:           str
      server_id:           str
      description:         str
      user_id:             str
      severity:            Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
      vault_session:       str | None
      rag_results:         list[dict]
      web_results:         list[dict]
      ssh_output:          str
      fix_attempts:        int
      max_fix_attempts:    int
      verify_passed:       bool
      final_status:        Literal["done", "escalated", "failed"]
      resolution_summary:  str
      trace_id:            str
      agent_id:            str
      error:               str | None
  ```
  Include a docstring mapping each field to the node that writes it.

- [ ] `V2-P2-02` Create `services/inserver-agent/state.py`
  ```python
  class InServerAgentState(TypedDict, total=False):
      task_id:        str
      server_ids:     list[str]
      current_server: str
      probe_results:  dict[str, dict]   # server_id -> metrics dict
      fix_log:        list[dict]
      snapshot_ids:   list[int]
      unreachable:    list[str]
      trace_id:       str
      agent_id:       str
      error:          str | None
  ```

- [ ] `V2-P2-03` Update `services/client-agent/graph.py`
  - `from state import ClientAgentState`
  - Replace `StateGraph(dict)` with `StateGraph(ClientAgentState)`
  - Update all node function signatures: `state: dict` → `state: ClientAgentState`
  - Replace bare `state.get("key")` with `state.get("key")` — same calls, now type-checked
  - Replace bare `return {...}` with explicit typed dict returns

- [ ] `V2-P2-04` Update `services/inserver-agent/graph.py`
  - Same as V2-P2-03 for `InServerAgentState`

- [ ] `V2-P2-05` Update all test fixtures that build state dicts for node unit tests
  - Add missing TypedDict fields (at minimum the `required` ones)
  - No logic changes — just data shape alignment

- [ ] `V2-P2-06` Run `mypy services/client-agent/ services/inserver-agent/ --ignore-missing-imports`
  - Fix any type errors surfaced (do not use `# type: ignore` to suppress — fix the root cause)
  - Record any pre-existing errors that are out of V2 scope in a `# TODO-V3` comment

---

## V2-PHASE 3 — Node Timing Decorator

**Goal:** Every LangGraph node emits structured timing logs and a Prometheus histogram
observation automatically — zero boilerplate in the node function body.

**Definition of done:** After running 10 tickets, Grafana shows per-node p95 latency bars.

- [ ] `V2-P3-01` Create `services/shared/metrics.py`
  - Define all Prometheus instruments in one place:
    ```python
    from prometheus_client import Histogram, Counter

    NODE_DURATION = Histogram(
        "agent_node_duration_seconds",
        "Time spent in each LangGraph node",
        labelnames=["agent", "node"],
        buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
    )
    TOOL_DURATION = Histogram(
        "agent_tool_duration_seconds",
        "Time spent in each tool call",
        labelnames=["tool"],
        buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5],
    )
    NODE_ERROR_COUNT = Counter(
        "agent_node_errors_total",
        "Number of node execution errors",
        labelnames=["agent", "node"],
    )
    ```
  - Update `services/shared/tool_registry.py` (V2-P1-01) to import and use `TOOL_DURATION`

- [ ] `V2-P3-02` Create `services/shared/node.py`
  ```python
  def node(agent: str, name: str | None = None):
      """
      Decorator for LangGraph node functions.
      - Emits structured log with elapsed_s on success
      - Emits error log + increments NODE_ERROR_COUNT on exception
      - Observes NODE_DURATION histogram
      - Re-raises exception so LangGraph error handling still works
      """
      def decorator(func: Callable) -> Callable:
          node_name = name or func.__name__
          @wraps(func)
          async def wrapper(state, config=None):
              t0 = time.perf_counter()
              try:
                  result = await func(state, config)
                  elapsed = time.perf_counter() - t0
                  log.info("node_ok", agent=agent, node=node_name, elapsed_s=round(elapsed, 3))
                  NODE_DURATION.labels(agent=agent, node=node_name).observe(elapsed)
                  return result
              except Exception as exc:
                  elapsed = time.perf_counter() - t0
                  NODE_ERROR_COUNT.labels(agent=agent, node=node_name).inc()
                  log.error("node_error", agent=agent, node=node_name,
                            elapsed_s=round(elapsed, 3), error=str(exc))
                  raise
          return wrapper
      return decorator
  ```

- [ ] `V2-P3-03` Apply `@node("client-agent")` to all nodes in `services/client-agent/graph.py`
  - `receive_ticket_node`, `classify_severity_node`, `rag_lookup_node`,
    `web_search_node`, `resolve_loop_node`, `verify_node`, `close_ticket_node`
  - Node body is unchanged — only add the decorator line

- [ ] `V2-P3-04` Apply `@node("inserver-agent")` to all nodes in `services/inserver-agent/graph.py`
  - `check_all_servers_node`, `per_server_health_node`, `fix_if_allowed_node`, `emit_snapshot_node`

- [ ] `V2-P3-05` Apply `@node("report-agent")` to all nodes in `services/report-agent/graph.py`
  - `aggregate_node`, `format_node`, `send_node`

- [ ] `V2-P3-06` Update `infra/grafana/dashboards/agent_overview.json`
  - Add panel: **Node Duration p95** (per agent + node breakdown)
    ```
    Query: histogram_quantile(0.95,
             rate(agent_node_duration_seconds_bucket[5m])
           ) by (agent, node)
    ```
  - Add panel: **Tool Duration p95**
    ```
    Query: histogram_quantile(0.95,
             rate(agent_tool_duration_seconds_bucket[5m])
           ) by (tool)
    ```
  - Add panel: **Node Errors / min** (counter rate by agent + node)

- [ ] `V2-P3-07` Write `services/shared/tests/test_node_decorator.py`
  - `test_timing_logged_on_success` — after calling decorated node, log contains `elapsed_s`
  - `test_histogram_observed` — `NODE_DURATION.labels(...).observe` called with positive value
  - `test_error_counter_incremented` — on node raise, `NODE_ERROR_COUNT` increments
  - `test_exception_re_raised` — exception propagates through decorator

---

## V2-PHASE 4 — Dependency Injection

**Goal:** Agent graphs accept dependencies through a context object instead of importing
them directly. This makes unit tests possible without live infrastructure.

**Definition of done:** A full agent graph test can run using `MockLLMClient` and
`fakeredis` with no Anthropic API calls and no real database.

- [ ] `V2-P4-01` Create `services/shared/llm.py`
  ```python
  from typing import Protocol, runtime_checkable

  @runtime_checkable
  class LLMClient(Protocol):
      async def complete(
          self,
          system: str,
          messages: list[dict],
          tools: list[dict],
          max_tokens: int = 4096,
      ) -> dict: ...   # returns Anthropic message dict shape

  class AnthropicLLMClient:
      def __init__(self, api_key: str, model: str):
          self._client = anthropic.AsyncAnthropic(api_key=api_key)
          self._model = model

      async def complete(self, system, messages, tools, max_tokens=4096) -> dict:
          return await self._client.messages.create(
              model=self._model, system=system,
              messages=messages, tools=tools, max_tokens=max_tokens,
          )

  class MockLLMClient:
      """For tests — returns a fixed or scripted response."""
      def __init__(self, responses: list[dict]):
          self._responses = iter(responses)

      async def complete(self, **_) -> dict:
          return next(self._responses)
  ```

- [ ] `V2-P4-02` Create `services/shared/agent_context.py`
  ```python
  from dataclasses import dataclass, field
  from sqlalchemy.ext.asyncio import AsyncSessionmaker
  from redis.asyncio import Redis
  from shared.llm import LLMClient
  from shared.tool_registry import ToolRegistry

  @dataclass
  class AgentContext:
      llm:        LLMClient
      registry:   ToolRegistry
      db_factory: AsyncSessionmaker
      redis:      Redis
      tracer:     object          # Langfuse tracer or _NoOpTrace
      agent_id:   str = "agent"
  ```

- [ ] `V2-P4-03` Refactor `services/client-agent/graph.py`
  - Change `build_client_graph()` → `ClientAgentGraph(context: AgentContext)`
  - Store `self._ctx = context`; nodes access `self._ctx.llm.complete(...)` instead of
    creating `anthropic.AsyncAnthropic` inline
  - `async def run(self, task: dict) -> dict` replaces the standalone executor function
  - Keep `build_client_graph()` as a factory function that constructs `AgentContext` from
    `settings` and returns a `ClientAgentGraph` — this preserves backward compat with executor

- [ ] `V2-P4-04` Refactor `services/inserver-agent/graph.py`
  - Same pattern as V2-P4-03 for `InServerAgentGraph(context: AgentContext)`

- [ ] `V2-P4-05` Refactor `services/report-agent/graph.py`
  - `ReportAgentGraph(context: AgentContext)` — inject DB and Redis from context

- [ ] `V2-P4-06` Update `services/client-agent/executor.py`
  - Build `AgentContext` from `settings` (one place only)
  - Construct `ClientAgentGraph(context)` once at startup; reuse for each task

- [ ] `V2-P4-07` Update `services/inserver-agent/executor.py` — same as V2-P4-06

- [ ] `V2-P4-08` Update `services/report-agent/main.py` — same as V2-P4-06

- [ ] `V2-P4-09` Write `services/client-agent/tests/test_graph_injected.py`
  - Build `AgentContext` with `MockLLMClient`, `fakeredis`, `AsyncMock` db_factory
  - Run a full ticket through `ClientAgentGraph.run({...})`
  - Assert final state has `final_status == "done"` without any Anthropic API call
  - Assert correct tools were dispatched (via mock registry)

- [ ] `V2-P4-10` Write `services/inserver-agent/tests/test_graph_injected.py`
  - Same pattern — run health check with mock LLM and SSH tool
  - Assert snapshot is emitted for each server in input list

---

## V2-PHASE 5 — Performance Benchmark Suite

**Goal:** A `pytest -m perf` suite that enforces latency SLOs and reveals regressions.
All benchmarks run against real (or seeded docker) infrastructure — not mocks.

**Definition of done:** `make bench` exits 0 on a dev machine; each test has a documented
SLO threshold and fails visibly when breached.

- [ ] `V2-P5-01` Create `tests/perf/conftest.py`
  - `rag_client` fixture — httpx AsyncClient pointing at `RAG_SERVICE_URL` (from env)
  - `seeded_kb` fixture — ingest 1 000 / 5 000 / 10 000 entries before test, teardown after
  - `vault_client` fixture — httpx AsyncClient pointing at `SSH_VAULT_URL`
  - `agent_graph` fixture — `ClientAgentGraph` with `AnthropicLLMClient` (real, small model)
  - Add `@pytest.mark.perf` skip condition: skip if `PERF_TESTS=1` not set (so CI doesn't run by default)

- [ ] `V2-P5-02` Create `tests/perf/test_rag_perf.py`
  ```
  SLOs:
  - rag_search: p95 < 2 s at 1 000 KB entries
  - rag_search: p95 < 5 s at 10 000 KB entries
  - cache hit path: p95 < 100 ms (embedding lookup only)
  - ingest single entry: < 3 s
  ```
  - `test_search_latency_1k_kb` — 20 sequential searches, assert p95 < 2 s
  - `test_search_latency_10k_kb` — 20 sequential searches at 10k entries, assert p95 < 5 s
  - `test_cache_hit_latency` — search same query twice, second call < 100 ms
  - `test_concurrent_search` — 10 concurrent searches, all complete < 5 s

- [ ] `V2-P5-03` Create `tests/perf/test_agent_perf.py`
  ```
  SLOs:
  - Single ticket resolution (RAG hit path): < 60 s end-to-end
  - 10 concurrent tickets: all resolve < 120 s
  - Classify severity node alone: < 5 s
  ```
  - `test_single_ticket_resolution_time`
  - `test_concurrent_ticket_throughput_10` — 10 concurrent, assert ≥ 9/10 resolve in 120 s
  - `test_classify_node_latency` — call classify node directly, assert < 5 s

- [ ] `V2-P5-04` Create `tests/perf/test_vault_perf.py`
  ```
  SLOs:
  - Session create (decrypt + paramiko connect): < 500 ms per session
  - 20 concurrent session creates: all < 10 s
  - Command execute (round-trip SSH): < 2 s for simple command
  ```
  - `test_session_create_latency`
  - `test_concurrent_sessions`
  - `test_command_execute_latency`

- [ ] `V2-P5-05` Create `tests/perf/test_rate_limiter_perf.py`
  ```
  SLOs:
  - 1 000 sequential acquire() calls: < 1 s total (Lua script overhead)
  - 100 concurrent acquire() calls: < 500 ms (no lock contention)
  ```
  - `test_sequential_acquire_throughput`
  - `test_concurrent_acquire_no_contention`

- [ ] `V2-P5-06` Update `pyproject.toml`
  - Add `perf` to `[tool.pytest.ini_options] markers`
    ```toml
    [tool.pytest.ini_options]
    markers = [
        "perf: performance benchmarks — run with PERF_TESTS=1",
        "integration: requires live docker stack",
        "smoke: quick sanity checks",
    ]
    ```

- [ ] `V2-P5-07` Add `make bench` target to `Makefile`
  ```makefile
  bench:   ## Run performance benchmark suite (requires running stack)
      PERF_TESTS=1 pytest tests/perf/ -v --tb=short -m perf
  ```

- [ ] `V2-P5-08` Add SLO summary table to `docs/RUNBOOK.md`
  - Document each threshold from tests above
  - Add "How to investigate a latency regression" section pointing to Grafana node panels

---

## Completion Checklist

Before closing V2:

- [ ] All `[ ]` tasks above are `[x]`
- [ ] `pytest -q` (unit + integration) passes with zero failures
- [ ] `PERF_TESTS=1 pytest tests/perf/ -q` passes all SLO thresholds
- [ ] `mypy services/ --ignore-missing-imports` shows no regressions vs V1 baseline
- [ ] `ruff check services/` passes
- [ ] Grafana agent_overview dashboard shows node + tool latency panels (screenshot in PR)
- [ ] `dev_note.md` updated in every service directory touched
- [ ] `ARCHITECTURE_DEBT.md` updated — mark each root cause as resolved with the fix PR link

---

## What V2 Does NOT Change

These are explicitly out of scope — do not touch during V2:

- Vault crypto (AES-256-GCM) — already solid
- RAG pipeline internals (BM25, RRF, cross-encoder) — already solid
- Redis BLPOP consumer pattern — already solid
- APScheduler job definitions — already solid
- All Alembic migrations — do not add or modify
- Dockerfiles — do not modify unless a new shared module requires a COPY addition
- `infra/` (nginx, prometheus, loki) — do not touch except Grafana dashboard JSON
- Any passing V1 test — do not delete, only update if import paths change
