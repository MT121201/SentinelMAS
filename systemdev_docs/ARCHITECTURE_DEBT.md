# ARCHITECTURE_DEBT.md

> Senior feedback (paraphrased):
> *"As an internal tool it's fine — domain logic is solid. But maintenance and extension? No hope.
> Extending this code is like rewriting it. Design it abstractly so it's easier to change later,
> and add benchmarks."*

This document explains **why** that feedback is correct, **where** exactly the problems are,
and **how** to fix them without a full rewrite.

---

## Why the Feedback Is Valid

The system was built phase-by-phase in a "make it work" style. Domain logic is correct and
the service topology is sound. But every implementation choice made the "happy path" easy and
"future change" hard. The six root causes are:

| Root Cause | Effect |
|---|---|
| No abstract base classes / Protocols | Adding a tool requires editing core dispatch code |
| Tool schemas defined as raw JSON dicts | Schema lives in 2+ places; drift guaranteed |
| `StateGraph(dict)` — untyped state | No IDE help; state key typos are silent bugs |
| Hard-coded `match tool_name:` dispatchers | New tool = edit the dispatcher (O(n) coupling) |
| Direct imports replace dependency injection | Nothing can be mocked; tests need live infra |
| Zero timing instrumentation | Cannot measure what is slow; cannot set SLOs |

---

## Problem 1 — Tool Layer Has No Abstraction

### Where it is

`services/client-agent/tools.py` and `services/inserver-agent/tools.py` each contain:

**A) Raw JSON tool schemas** (repeated in every agent):
```python
TOOL_DEFINITIONS = [
    {
        "name": "rag_search",
        "description": "Search the internal knowledge base...",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "..."},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    # ... repeated for every tool
]
```

**B) A monolithic match dispatcher** (one per agent):
```python
async def dispatch_tool(tool_name: str, tool_input: dict, ...) -> Any:
    match tool_name:
        case "rag_search":   return await rag_search(**tool_input)
        case "web_search":   return await web_search(**tool_input)
        case "ssh_execute":  return await ssh_execute(**tool_input)
        case "log_action":   return await log_action(**tool_input)
        case _:              return {"error": f"Unknown tool: {tool_name}"}
```

### Why this breaks on extension

- **Add a new tool**: edit TOOL_DEFINITIONS + add a `case` + implement the function
- **Share a tool between agents**: duplicate the entry in both TOOL_DEFINITIONS lists
- **Change a tool's signature**: update the JSON schema *and* the function signature separately
- **Mock a tool in tests**: cannot — it is called directly inside `dispatch_tool`

### How to fix it

Create `services/shared/tool_registry.py`:

```python
from typing import Protocol, Any
from pydantic import BaseModel


class ToolHandler(Protocol):
    async def __call__(self, **kwargs: Any) -> dict: ...


class ToolDefinition:
    """Single source of truth: schema + implementation live together."""

    def __init__(self, name: str, description: str, input_model: type[BaseModel],
                 handler: ToolHandler):
        self.name = name
        self.description = description
        self.input_model = input_model
        self.handler = handler

    def to_anthropic_schema(self) -> dict:
        """Auto-generate Anthropic tool JSON from the Pydantic model."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> "ToolRegistry":
        self._tools[tool.name] = tool
        return self

    @property
    def schemas(self) -> list[dict]:
        return [t.to_anthropic_schema() for t in self._tools.values()]

    async def dispatch(self, name: str, inputs: dict, **ctx: Any) -> dict:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Unknown tool: {name}"}
        validated = tool.input_model(**inputs)
        return await tool.handler(**validated.model_dump(), **ctx)
```

Now each agent defines its own registry by composing shared tool definitions:

```python
# client-agent/registry.py
from shared.tool_registry import ToolRegistry, ToolDefinition
from shared.tools.rag import RagSearchInput, rag_search_handler
from shared.tools.ssh import SshExecuteInput, ssh_execute_handler

client_registry = (
    ToolRegistry()
    .register(ToolDefinition("rag_search", "Search knowledge base", RagSearchInput, rag_search_handler))
    .register(ToolDefinition("ssh_execute", "Run SSH command", SshExecuteInput, ssh_execute_handler))
)

# Adding a new tool to client-agent only:
client_registry.register(ToolDefinition("cache_lookup", ..., CacheInput, cache_handler))
# inserver-agent is not affected
```

---

## Problem 2 — Graph Wiring is Hardcoded Monolith

### Where it is

`services/client-agent/graph.py` (and the other agents):

```python
def build_client_graph():
    graph = StateGraph(dict)               # untyped state
    graph.add_node("receive_ticket",   receive_ticket_node)
    graph.add_node("classify_severity", classify_severity_node)
    graph.add_node("rag_lookup",       rag_lookup_node)
    graph.add_node("web_search_node",  web_search_node)
    graph.add_node("resolve_loop",     resolve_loop_node)
    graph.add_node("verify",           verify_node)
    graph.add_node("close_ticket",     close_ticket_node)
    graph.set_entry_point("receive_ticket")
    graph.add_edge("receive_ticket", "classify_severity")
    graph.add_conditional_edges("classify_severity", _route_severity, {...})
    # ... 15 more lines of wiring
    return graph.compile()
```

### Why this breaks on extension

- **Add a node between classify and rag**: remove one edge, add two edges, write a routing
  function, wire conditional edges — all in the same monolithic function
- **Reuse the "classify → route" pattern** in inserver-agent: copy-paste the entire block
- **Test a single node in isolation**: you must invoke the full compiled graph

Crucially, `StateGraph(dict)` means the state has no schema. A typo in a key name
(`state["tiket_id"]` vs `state["ticket_id"]`) is a silent runtime bug, not a lint error.

### How to fix it

**Step 1** — Typed state per agent:

```python
# client-agent/state.py
from typing import TypedDict, Literal

class ClientAgentState(TypedDict, total=False):
    ticket_id:          str
    server_id:          str
    description:        str
    severity:           Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    vault_session:      str | None
    rag_results:        list[dict]
    web_results:        list[dict]
    fix_attempts:       int
    final_status:       Literal["done", "escalated", "failed"]
    resolution_summary: str
    trace_id:           str
```

**Step 2** — Node decorator for cross-cutting concerns (timing, logging, error wrap):

```python
# shared/node.py
import time
from functools import wraps

def node(name: str | None = None, max_retries: int = 0):
    """Decorator: adds timing, structured logging, and optional retry to a graph node."""
    def decorator(func):
        node_name = name or func.__name__
        @wraps(func)
        async def wrapper(state: dict, config: dict) -> dict:
            t0 = time.perf_counter()
            try:
                result = await func(state, config)
                elapsed = time.perf_counter() - t0
                log.info("node_ok", node=node_name, elapsed_s=round(elapsed, 3))
                NODE_DURATION.labels(node=node_name).observe(elapsed)   # Prometheus
                return result
            except Exception as exc:
                log.error("node_error", node=node_name, error=str(exc))
                raise
        return wrapper
    return decorator

# Usage — zero boilerplate in the node itself:
@node("classify_severity")
async def classify_severity_node(state: ClientAgentState, config: dict) -> dict:
    ...
```

**Step 3** — Abstract graph builder for shared structure:

```python
# shared/graph_builder.py
from abc import ABC, abstractmethod
from langgraph.graph import StateGraph

class BaseAgentGraph(ABC):
    @property
    @abstractmethod
    def state_schema(self) -> type: ...

    @abstractmethod
    def build(self) -> StateGraph: ...

    def compile(self):
        return self.build().compile()


class ClientAgentGraph(BaseAgentGraph):
    state_schema = ClientAgentState

    def build(self) -> StateGraph:
        g = StateGraph(self.state_schema)
        g.add_node(...)
        return g
```

---

## Problem 3 — No Dependency Injection

### Where it is

In every agent graph and tool file:

```python
# Top of graph.py
from config import settings

# Inside resolve_loop_node
client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
response = await client.messages.create(model=settings.anthropic_model, ...)
```

`settings.anthropic_api_key` and `settings.anthropic_model` are referenced directly in
five separate node functions across three agents.

### Why this breaks on extension

- **Switch LLM provider** (e.g., OpenAI fallback when Anthropic is down): find and replace
  every `anthropic.AsyncAnthropic(...)` call across all agents
- **Write a unit test for `resolve_loop_node`**: you must either set env vars or patch at the
  module level — impossible to pass a mock client in
- **Use a different model for one agent type**: no hook to override, you modify global config

### How to fix it

```python
# shared/llm.py
from typing import Protocol

class LLMClient(Protocol):
    async def complete(self, system: str, messages: list[dict],
                       tools: list[dict], max_tokens: int) -> dict: ...


class AnthropicLLMClient:
    def __init__(self, api_key: str, model: str):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, system, messages, tools, max_tokens) -> dict:
        return await self._client.messages.create(
            model=self._model, system=system,
            messages=messages, tools=tools, max_tokens=max_tokens,
        )


# graph.py — inject at construction, not at call site
class ClientAgentGraph(BaseAgentGraph):
    def __init__(self, llm: LLMClient, registry: ToolRegistry, db_factory, redis):
        self._llm = llm
        self._registry = registry
        self._db_factory = db_factory
        self._redis = redis

# In tests:
graph = ClientAgentGraph(
    llm=MockLLMClient(fixed_response=...),
    registry=MockToolRegistry(),
    db_factory=AsyncMock(),
    redis=fakeredis.FakeRedis(),
)
```

---

## Problem 4 — No Benchmarks

### Where it is

Everywhere — and nowhere. There is no timing instrumentation in any agent node, tool call,
RAG pipeline step, or vault operation.

### What you cannot answer today

- Which node is the bottleneck in ticket resolution?
- Does RAG lookup degrade above 10k KB entries?
- What is the p95 latency of a full client-agent run under 50 concurrent tickets?
- Did the reranker get slower after upgrading sentence-transformers?

### How to fix it

**Layer 1 — Inline node timing** (the `@node` decorator above pushes to Prometheus automatically).

**Layer 2 — Tool timing wrapper**:

```python
# shared/tool_registry.py — add to ToolRegistry.dispatch()
async def dispatch(self, name: str, inputs: dict, **ctx) -> dict:
    t0 = time.perf_counter()
    result = await tool.handler(**validated.model_dump(), **ctx)
    TOOL_DURATION.labels(tool=name).observe(time.perf_counter() - t0)
    return result
```

**Layer 3 — Performance pytest fixtures**:

```python
# tests/perf/test_rag_perf.py
import pytest, time

@pytest.mark.perf
async def test_rag_search_latency(rag_client, seeded_kb):
    """RAG search must complete in < 2 s for kb_size = 5 000."""
    start = time.perf_counter()
    result = await rag_client.search("GPU memory ECC error", top_k=5)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"RAG search too slow: {elapsed:.2f}s"
    assert len(result["results"]) > 0

@pytest.mark.perf
async def test_concurrent_ticket_throughput(client_agent, n=50):
    """50 concurrent tickets must complete within 120 s (no queue starvation)."""
    tasks = [client_agent.run(make_ticket()) for _ in range(n)]
    t0 = time.perf_counter()
    results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - t0
    resolved = sum(1 for r in results if r["status"] == "done")
    assert elapsed < 120
    assert resolved / n >= 0.9, f"Only {resolved}/{n} resolved"
```

**Layer 4 — Grafana dashboard for agent node latency** (already wired — just push the metrics):

```
Panel: "Node Duration p95"
Query: histogram_quantile(0.95, rate(agent_node_duration_seconds_bucket[5m]))
       by (node)
```

---

## Problem 5 — State Schema Inconsistency

`report-agent/graph.py` correctly uses a TypedDict:
```python
class ReportState(TypedDict, total=False):
    report_id: str
    period: str
    ...
```

`client-agent/graph.py` and `inserver-agent/graph.py` use bare `dict`:
```python
graph = StateGraph(dict)   # no schema validation, no IDE autocomplete
```

### Fix

Define a `TypedDict` per agent (see Problem 2, Step 1 above) and pass it to `StateGraph`.
This costs ~15 lines per agent and gives IDE autocomplete + mypy coverage over state keys.

---

## Remediation Roadmap

> **Full phased task list with atomic checkboxes:** [`TODO_V2.md`](TODO_V2.md)
> Work from TODO_V2.md — this section is the summary only.

These changes do **not** require a rewrite — they are additive refactors. Each step
is independently shippable.

### Step 1 — Shared tool registry (highest ROI)

| Task | Files touched | Effort |
|---|---|---|
| Create `shared/tool_registry.py` (ToolDefinition + ToolRegistry) | 1 new file | S |
| Move shared tool inputs to `shared/tools/` as Pydantic models | 3-5 new files | M |
| Replace `TOOL_DEFINITIONS` JSON with `registry.schemas` in each agent | 3 files edited | S |
| Replace `dispatch_tool match` with `registry.dispatch()` in each agent | 3 files edited | S |

### Step 2 — Typed state schemas

| Task | Files touched | Effort |
|---|---|---|
| Create `ClientAgentState`, `InServerAgentState` TypedDicts | 2 new files | XS |
| Replace `StateGraph(dict)` with typed version | 2 files edited | XS |

### Step 3 — `@node` timing decorator

| Task | Files touched | Effort |
|---|---|---|
| Create `shared/node.py` with `@node` decorator | 1 new file | S |
| Decorate all node functions (6 nodes × 3 agents = 18 additions) | 3 files edited | S |
| Add `agent_node_duration_seconds` Histogram to Prometheus | 1 file edited | XS |

### Step 4 — Dependency injection into graphs

| Task | Files touched | Effort |
|---|---|---|
| Create `shared/llm.py` with `LLMClient` Protocol | 1 new file | S |
| Refactor graph `__init__` to accept injected deps | 3 files edited | M |
| Update tests to inject mocks instead of patching modules | test files | M |

### Step 5 — Performance benchmark suite

| Task | Files touched | Effort |
|---|---|---|
| Create `tests/perf/` with RAG, agent, and vault latency tests | 3-5 new files | M |
| Add `@pytest.mark.perf` to pytest config | 1 file edited | XS |
| Wire p95 node latency panel into existing Grafana dashboard | dashboard JSON | S |

---

## What Not to Change

The senior explicitly said domain logic is fine:

- LangGraph `StateGraph` topology per agent — keep it
- Redis BLPOP consumer pattern — keep it
- AES-256-GCM vault with session tokens — keep it
- Hybrid RAG (Qdrant + BM25 + CrossEncoder) — keep it
- APScheduler cron jobs embedded in orchestrator — keep it

The goal is **layering abstraction on top of working domain logic**, not replacing it.
