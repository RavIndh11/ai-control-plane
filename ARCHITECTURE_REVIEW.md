# Enterprise AI Control Plane — Architecture Review & Redesign Proposal

> **Author**: Architecture Review (AI)  
> **Date**: 2026-07-28  
> **Scope**: Full codebase analysis + proposed target architecture incorporating LangGraph, Internal MCP Server, Microsoft Agent Governance Toolkit (AGT), LiteLLM Gateway, Langfuse, and a proper IAM Plane

---

## Table of Contents
1. [What You Have Now — Honest Assessment](#1-what-you-have-now--honest-assessment)
2. [What's Strong](#2-whats-strong)
3. [Critical Gaps & Problems](#3-critical-gaps--problems)
4. [Proposed Target Architecture](#4-proposed-target-architecture)
5. [Component-by-Component Breakdown](#5-component-by-component-breakdown)
6. [Data & Control Flows](#6-data--control-flows)
7. [Add / Change / Remove Summary](#7-add--change--remove-summary)
8. [Implementation Roadmap](#8-implementation-roadmap)

---

## 1. What You Have Now — Honest Assessment

You've built a solid **reference skeleton** that correctly maps out all the right concepts. Here's a neutral read:

```
apps/
  agent-orchestrator/   → 1771-line monolith FastAPI + LangGraph (4 nodes)
  governance-engine/    → 680-line FastAPI evidence store
  dashboard/            → React UI
  integration-adapters/
    mcp-bridge/         → 7-line placeholder (literally just a print statement)
    grc-connectors/     → likely placeholder
    oidc-federation/    → likely placeholder
    otlp-exporter/      → likely placeholder

platform/
  runtime/litellm/      → good: LiteLLM config with Langfuse logging wired
  policy/cerbos/        → good: 2 ABAC policies (agent_threads, compliance_evidence)
  identity/keycloak/    → present but not wired
  identity/spire/       → present but not wired
  observability/langfuse/ → present
  observability/elastic-eck/ → present
  discovery/local_daemon.py → clever: polls Ollama, reports shadow AI assets
```

The LangGraph pipeline (`guardrail → agent_node → governance_shield → generation`) is the real core, and it's conceptually correct. But the individual pieces have serious internal inconsistencies.

---

## 2. What's Strong

| Area | Strength |
|---|---|
| **LangGraph pipeline design** | 4-node graph (`guardrail → agent_node → governance_shield → generation`) is production-grade thinking |
| **HITL interrupt pattern** | `pending_action / action_approved` state fields + checkpoint resume is the right pattern for Microsoft AGT-style governance |
| **Dual auth modes** | JWT (Keycloak JWKS) + header fallback is developer-ergonomic |
| **Cerbos ABAC** | Tenant-scoped resource policies are correct and properly isolated |
| **LiteLLM + Langfuse wiring** | `LITELLM_LOGGING=["langfuse"]` with env-injected keys is clean |
| **PostgreSQL RLS** | Schema-per-tenant + `SET LOCAL app.current_tenant_id` is a real enterprise pattern |
| **Discovery daemon** | `platform/discovery/local_daemon.py` scanning shadow Ollama instances and reporting to Governance is genuinely good |
| **SSE Streaming** | `/api/v1/threads/{id}/runs/stream` with per-node SSE events is production quality |

---

## 3. Critical Gaps & Problems

### 3.1 The MCP Bridge is a Stub
```python
# apps/integration-adapters/mcp-bridge/main.py
def main():
    print("MCP Bridge initialized.")
```
This is the **most critical missing piece**. Without a real MCP server, the agent has no structured way to call enterprise tools. Right now tools are hardcoded JSON schemas in `AGENT_TOOLS` inside `main.py`. That doesn't scale.

**Impact**: No real tool ecosystem. Agents can't call real enterprise APIs without custom code per tool.

### 3.2 NeMo Guardrails is a Mis-fit
NeMo Guardrails is an NVIDIA product designed for their NIM stack. It uses a custom Colang DSL and is heavyweight for a LAN-first, air-gapped deployment. The actual guardrail check pings it and falls back to string pattern matching anyway:
```python
if any(phrase in nemo_reply.lower() for phrase in ["i cannot", "i'm sorry", ...]):
    is_safe = False
```
This is fragile. A jailbroken model can respond "Sure!" and pass.

**Impact**: False sense of security. NeMo adds ops complexity for little gain in your architecture.

### 3.3 Governance Engine is a Log Sink, Not a Real Policy Engine
The governance engine receives evidence POSTs and calculates a compliance score, but:
- It has no **real-time policy evaluation** capability
- It does not **block** anything — it only records after the orchestrator already decided
- The controls DB is 3 hardcoded entries (`SOC2-CC-6.1`, `GDPR-Art-32`, `EU-AI-Act-Art-9`)
- There's no **audit trail integrity** (no signing, no tamper evidence beyond "it's in the DB")

**Impact**: Compliance theatre. A real GRC auditor would reject this.

### 3.4 No Agent Memory / Context Management
The `generation_node` does a one-shot Qdrant RAG lookup per request. There's no:
- Persistent conversation memory across turns
- Agent working memory (scratchpad)
- Tool result accumulation across multi-step tasks

**Impact**: Agents can't do multi-step reasoning or maintain context across a conversation.

### 3.5 Orchestrator is a God Class
`apps/agent-orchestrator/main.py` is 1771 lines and contains:
- DB models + migrations
- LangGraph graph definition
- All 4 node functions
- JWT auth logic
- Cerbos ABAC logic
- LiteLLM call logic
- Qdrant RAG logic
- All REST API endpoints
- Streaming SSE logic
- OpenTelemetry setup

This is unmaintainable at enterprise scale.

### 3.6 IAM Plane is Surface-Level
Keycloak and SPIRE are present as folder names with YAML configs but:
- No SPIFFE workload identity is actually used at runtime — agents call each other via plain HTTP with `X-User-Role` headers
- No service mesh / mTLS between microservices
- No token exchange flow between Keycloak and internal services

### 3.7 No Agent Registry / Catalog
There's no way to discover, register, or version agents. The `agent_type` field in `ThreadCreate` is just a string that gets stored and ignored.

### 3.8 Langfuse Wiring is One-Layer Deep
Langfuse is only wired at the LiteLLM layer. You're capturing LLM calls, but not:
- LangGraph node traces (which node took how long)
- Tool call traces
- Human approval latency
- Full session replay

---

## 4. Proposed Target Architecture

This is the architecture I'd build, incorporating your new requirements:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ENTERPRISE AI CONTROL PLANE                          │
│                                                                             │
│  ┌─────────────┐    ┌──────────────────────────────────────────────────┐   │
│  │  IAM Plane  │    │                  Data Plane                       │   │
│  │             │    │                                                    │   │
│  │  Keycloak   │    │  ┌─────────┐  ┌─────────┐  ┌─────────────────┐  │   │
│  │  (OIDC/JWT) │    │  │Postgres │  │  Redis  │  │     Qdrant      │  │   │
│  │             │    │  │ (RLS)   │  │ (State) │  │  (Vector RAG)   │  │   │
│  │  SPIRE      │    │  └─────────┘  └─────────┘  └─────────────────┘  │   │
│  │  (SPIFFE)   │    │              ┌─────────┐                          │   │
│  │             │    │              │  MinIO  │                          │   │
│  │  Cerbos     │    │              │(Evidence│                          │   │
│  │  (ABAC PDP) │    │              │ Store)  │                          │   │
│  └─────────────┘    │              └─────────┘                          │   │
│                     └──────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         Control Plane                                 │  │
│  │                                                                       │  │
│  │  ┌────────────────┐   ┌─────────────────┐   ┌────────────────────┐  │  │
│  │  │  Agent Gateway │   │  Internal MCP   │   │  AI Gateway        │  │  │
│  │  │  (Orchestrator)│──▶│  Server         │──▶│  (LiteLLM)         │  │  │
│  │  │                │   │                 │   │                    │  │  │
│  │  │  LangGraph     │   │  Tool Registry  │   │  Model Routing     │  │  │
│  │  │  Pipelines     │◀──│  Enterprise     │   │  Rate Limiting     │  │  │
│  │  │  Agent Catalog │   │  Connectors     │   │  Token Budgets     │  │  │
│  │  └────────────────┘   └─────────────────┘   └────────────────────┘  │  │
│  │           │                                                           │  │
│  │           ▼                                                           │  │
│  │  ┌────────────────┐   ┌─────────────────┐                           │  │
│  │  │  Governance    │   │  MS AGT          │                           │  │
│  │  │  Engine        │──▶│  Shield Layer   │                           │  │
│  │  │                │   │                 │                           │  │
│  │  │  GRC Evidence  │   │  HITL Approvals │                           │  │
│  │  │  Policy Eval   │   │  Risk Scoring   │                           │  │
│  │  │  Compliance    │   │  Audit Log      │                           │  │
│  │  └────────────────┘   └─────────────────┘                           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                      Observability Plane                              │  │
│  │                                                                       │  │
│  │  ┌────────────┐   ┌────────────────┐   ┌──────────────────────────┐ │  │
│  │  │  Langfuse  │   │ OTel Collector  │   │   Elastic / Kibana       │ │  │
│  │  │  (LLM      │   │ (Spans/Metrics) │   │   (Logs / Search)        │ │  │
│  │  │   Traces)  │   └────────────────┘   └──────────────────────────┘ │  │
│  │  └────────────┘                                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         Model Plane                                   │  │
│  │                                                                       │  │
│  │  ┌──────────────────────────────────────────────────────────────┐   │  │
│  │  │  Ollama (Local LAN)   |  vLLM   |  Cloud APIs (optional)     │   │  │
│  │  └──────────────────────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Component-by-Component Breakdown

### 5.1 IAM Plane (Enhance — Currently Surface-Level)

**Keep**: Keycloak + SPIRE  
**Add**: Proper token exchange, workload identity usage at runtime

| Component | Purpose | Status → Action |
|---|---|---|
| **Keycloak** | User OIDC, JWT issuance, realm management | ✅ Keep — extend realm config, add client scopes for MCP |
| **SPIRE/SPIFFE** | Workload identity for service-to-service auth | ⚠️ Present but unused → **Wire it**: inject SVID certs into all services, replace X-headers with mTLS |
| **Cerbos** | ABAC policy decision point | ✅ Keep — add policies for MCP tools and agent actions |
| **Token Exchange** | Convert user JWT → agent scoped token | ❌ Missing → Add Keycloak token exchange flow so agents get scoped-down tokens per task |

**New flow**:
```
User → Keycloak (login) → JWT (realm roles + tenant_id claim)
     → Agent Orchestrator (validates JWT via JWKS)
     → Keycloak Token Exchange → Agent-scoped JWT (narrow permissions)
     → MCP Server (validates agent JWT via SPIFFE mTLS)
```

---

### 5.2 Agent Orchestrator (Refactor — Break the Monolith)

**Current problem**: 1771-line god class  
**Action**: Split into focused modules

```
apps/agent-orchestrator/
  main.py                    → FastAPI app + lifespan only (~100 lines)
  agents/
    graph.py                 → LangGraph graph definition + compilation
    state.py                 → AgentState TypedDict
    nodes/
      guardrail.py           → guardrail_node
      reasoning.py           → agent_node (ReAct loop)
      governance_shield.py   → governance_shield_node  
      generation.py          → generation_node
      memory.py              → NEW: memory consolidation node
  auth/
    jwt.py                   → Keycloak JWT verification
    principal.py             → get_principal dependency
  authz/
    cerbos.py                → is_authorized() + Cerbos client
  db/
    models.py                → SQLAlchemy models
    session.py               → get_db dependency + schema setup
  api/
    threads.py               → /api/v1/threads routes
    runs.py                  → /api/v1/threads/{id}/runs routes
    agents.py                → NEW: agent catalog routes
  mcp/
    client.py                → NEW: MCP client to call internal MCP server
```

**LangGraph Pipeline (Revised)**:

```
[INPUT]
   │
   ▼
┌──────────────┐  unsafe  ┌──────────────────┐
│  guardrail   │─────────▶│  governance_     │──▶ [END + evidence]
│  node        │          │  report_node     │
└──────────────┘          └──────────────────┘
   │ safe
   ▼
┌──────────────┐
│  memory      │  (load conversation history + RAG context)
│  node        │
└──────────────┘
   │
   ▼
┌──────────────┐  tool_call  ┌──────────────────┐
│  agent       │────────────▶│  governance_     │
│  reasoning   │             │  shield_node     │
│  (ReAct)     │             │  (MS AGT HITL)   │
└──────────────┘             └──────────────────┘
   │ direct answer              │ approved
   │                            ▼
   │                    ┌──────────────────┐
   │                    │  mcp_tool_       │
   │                    │  executor_node   │
   │                    └──────────────────┘
   │                            │
   ▼                            ▼
┌──────────────────────────────────┐
│           generation_node        │
│   (final response + Langfuse     │
│    trace + memory write-back)    │
└──────────────────────────────────┘
   │
   ▼
[OUTPUT + SSE stream]
```

---

### 5.3 Internal MCP Server (Build This — Currently a Stub)

This is the highest-priority new component. Replace the hardcoded `AGENT_TOOLS` JSON with a real MCP server that agents discover and call at runtime.

**What it is**: A Python FastAPI service implementing the [Model Context Protocol](https://spec.modelcontextprotocol.io/) — a standardized JSON-RPC 2.0 protocol for agents to discover and call tools.

**Structure**:
```
apps/mcp-server/
  main.py                   → FastAPI + MCP protocol handler
  tools/
    __init__.py             → Tool registry
    filesystem.py           → file_reader, file_writer tools
    knowledge.py            → knowledge_search (Qdrant RAG)
    database.py             → database_query (read-only), database_mutator (HITL required)
    terminal.py             → terminal_executor (HIGH-RISK, HITL required)
    web_search.py           → web_search tool (if external access allowed)
    governance.py           → log_evidence, get_compliance_status
  auth/
    spiffe.py               → SPIFFE workload identity verification
    cerbos.py               → per-tool ABAC checks
  registry.py               → Tool catalog with risk ratings
  resources.py              → MCP Resource (read-only data) handlers
  prompts.py                → MCP Prompt templates
```

**MCP Protocol Flow**:
```
Agent Orchestrator           MCP Server
      │                          │
      │──── POST /mcp/discover ──▶│
      │◀─── tool_catalog[] ───────│
      │                          │
      │──── POST /mcp/call ──────▶│ (tool: knowledge_search)
      │                    [Cerbos ABAC check]
      │                    [Execute Qdrant search]
      │◀─── tool_result ──────────│
      │                          │
      │──── POST /mcp/call ──────▶│ (tool: terminal_executor)
      │                    [Cerbos: EFFECT_DENY for tenant-user]
      │◀─── 403 Forbidden ────────│ (or: flag for HITL)
```

**Tool Risk Classification** (MCP metadata):
```python
TOOLS = [
    Tool(name="knowledge_search",  risk="low",    hitl_required=False),
    Tool(name="file_reader",       risk="low",    hitl_required=False),
    Tool(name="web_search",        risk="medium", hitl_required=False),
    Tool(name="file_writer",       risk="high",   hitl_required=True),
    Tool(name="terminal_executor", risk="critical", hitl_required=True),
    Tool(name="database_mutator",  risk="high",   hitl_required=True),
]
```

---

### 5.4 Microsoft Agent Governance Toolkit (AGT) Integration (Expand — Partially Done)

You already have the HITL interrupt pattern in `governance_shield_node`. This is the right approach. Here's how to make it fully AGT-aligned:

**What AGT actually provides**:
- **`AgentEvaluationPolicy`**: Define which agent actions require human review
- **`BreakGlass` approvals**: Emergency override paths with audit trails
- **Risk scoring**: Automatic risk score per agent action based on context
- **Audit immutability**: Signed audit entries (HMAC or blockchain-style append-only log)

**Current gap vs. what to build**:

| AGT Feature | Current State | Target |
|---|---|---|
| HITL interrupts | ✅ Implemented via `pending_action` state | Enhance: add timeout + escalation |
| Risk scoring | ❌ None | Add: per-action risk score in `AgentState` |
| Approval workflows | ⚠️ Basic true/false | Add: multi-step approval chains (user → admin → compliance) |
| Audit immutability | ❌ Plain DB rows | Add: HMAC-signed evidence entries |
| BreakGlass | ❌ None | Add: super-admin bypass with mandatory audit |
| Policy as code | ⚠️ Hardcoded tool list | Move to: Cerbos policies + MCP tool metadata |

**AGT Governance Shield (Enhanced State)**:
```python
class AgentState(TypedDict):
    # ... existing fields ...
    pending_action: Optional[Dict[str, Any]]
    action_approved: Optional[bool]
    action_risk_score: Optional[float]        # NEW: 0.0–1.0
    approval_chain: Optional[List[str]]       # NEW: who needs to approve
    approval_timeout_at: Optional[datetime]   # NEW: auto-reject after timeout
    break_glass_used: Optional[bool]          # NEW: emergency override flag
    audit_hmac: Optional[str]                 # NEW: integrity signature
```

---

### 5.5 AI Gateway — LiteLLM (Keep + Enhance)

LiteLLM is the right choice. It handles model routing, rate limiting, and spend tracking. Your current config is minimal. Expand it:

**Keep**:
- Ollama routing (`ollama/llama2` → local LAN)
- Langfuse logging integration
- Redis for caching

**Add**:
```yaml
# platform/runtime/litellm/values.yaml additions
config: |
  model_list:
    - model_name: llama3-70b        # Primary production model
      litellm_params:
        model: ollama/llama3:70b
        api_base: http://ollama-lan-host:11434
        tpm: 500000
        rpm: 100
        
    - model_name: embedding-model   # Dedicated embeddings
      litellm_params:
        model: ollama/nomic-embed-text
        api_base: http://ollama-lan-host:11434

  router_settings:
    routing_strategy: least-busy    # Load balance across model replicas
    num_retries: 3
    timeout: 30
    
  general_settings:
    # Per-virtual-key spend limits (tenant budget enforcement)
    max_budget: 100.0               # USD equivalent for cloud models
    budget_duration: 30d
    
    # Guardrails at the gateway level (catch before agent)
    guardrails:
      - guardrail_name: "prompt-injection-check"
        litellm_params:
          guardrail: lakera_prompt_injection  # or custom
```

**Add tenant virtual keys**: Issue one LiteLLM virtual key per tenant. This gives you automatic spend tracking and per-tenant rate limiting without any code changes.

---

### 5.6 Observability — Langfuse (Enhance) + Add LangGraph Traces

**Current state**: LiteLLM logs LLM calls to Langfuse. That's good but shallow.

**Add LangGraph-level tracing**:
```python
# agents/nodes/guardrail.py
from langfuse.decorators import observe, langfuse_context

@observe(name="guardrail_node")
def guardrail_node(state: AgentState) -> AgentState:
    langfuse_context.update_current_observation(
        input={"prompt": state["input"], "tenant_id": state["tenant_id"]},
        metadata={"node": "guardrail", "patterns_checked": len(blocked_patterns)}
    )
    # ... node logic ...
    langfuse_context.update_current_observation(
        output={"is_safe": state["is_safe"], "violation_reason": violation_reason},
        level="WARNING" if not state["is_safe"] else "DEFAULT"
    )
    return state
```

**Add session-level traces**: Each agent thread = one Langfuse session. Each node = one span. This gives you complete replay of every agent run.

**Observability Stack**:
```
Langfuse         → LLM call traces, token counts, latency, session replay
OTel Collector   → Infrastructure metrics, custom spans from FastAPI middleware
Elastic/Kibana   → Centralized log aggregation (governance events, auth events)
```

**Remove**: Elastic ECK is heavyweight for a LAN deployment. Consider **Grafana Loki** instead for log aggregation — much lighter, integrates with OTel.

---

### 5.7 Guardrails (Replace NeMo — Change)

**Remove**: NeMo Guardrails (NVIDIA-specific, heavyweight, requires cloud model by default)

**Replace with a layered approach**:

| Layer | Tool | Where |
|---|---|---|
| **Layer 1: Gateway** | LiteLLM custom guardrails hook | Before prompt hits LLM |
| **Layer 2: Application** | **Guardrails AI** (open source) | Inside `guardrail_node` — structured validators |
| **Layer 3: Semantic** | Custom embedding similarity check | Detect semantic jailbreaks via Qdrant |
| **Layer 4: Output** | Guardrails AI output validators | After LLM response, before returning |

**Guardrails AI** replaces NeMo for your use case:
```python
# agents/nodes/guardrail.py
from guardrails import Guard
from guardrails.hub import ToxicLanguage, PromptInjection, DetectSecrets

guard = Guard().use_many(
    ToxicLanguage(on_fail="exception"),
    PromptInjection(on_fail="exception"),
    DetectSecrets(on_fail="exception"),
)

def guardrail_node(state: AgentState) -> AgentState:
    try:
        guard.validate(state["input"])
        state["is_safe"] = True
    except Exception as e:
        state["is_safe"] = False
        state["output"] = str(e)
        # push evidence to governance engine
```

---

### 5.8 Governance Engine (Major Rework)

Current role: passive log sink.  
Target role: **active policy evaluation engine**.

**Add**:
1. **Policy evaluation endpoint**: `/api/v1/policies/evaluate` — synchronous policy check that the orchestrator calls before acting (not just after)
2. **Control mapping engine**: Map events to specific regulatory controls automatically
3. **Evidence integrity**: HMAC-sign every evidence entry
4. **Compliance dashboarding**: Real aggregated score with trend data, not just a count
5. **Alert webhooks**: Push to Slack/Teams/PagerDuty on critical severity events

```python
# New governance endpoint
@app.post("/api/v1/policies/evaluate")
def evaluate_policy(req: PolicyEvalRequest, principal = Depends(get_principal)):
    """
    Real-time policy evaluation before agent acts.
    Returns: ALLOW / DENY / REQUIRE_APPROVAL
    """
    # Check against Cerbos ABAC
    # Check against compliance rules DB
    # Calculate risk score
    # Return decision with reasoning
```

---

### 5.9 Agent Catalog (New Component)

You're currently storing `agent_type` as a raw string. Add a proper agent registry:

```
apps/agent-catalog/          ← NEW microservice (or add to orchestrator)
  agents/
    customer-support.yaml    ← Agent definition: name, version, graph, tools, risk_profile
    data-analyst.yaml
    code-assistant.yaml
  api.py                     ← GET /api/v1/agents  (list all agent types)
                             ← GET /api/v1/agents/{id}  (get agent definition)
                             ← POST /api/v1/agents  (register new agent type)
```

Agent definition:
```yaml
name: customer-support-agent
version: "1.2.0"
description: Handles customer billing and support queries
max_risk_score: 0.3           # Won't execute actions above this risk
allowed_tools:
  - knowledge_search
  - file_reader
denied_tools:
  - terminal_executor
  - database_mutator
hitl_threshold: 0.6           # Actions above this risk score require HITL
compliance_controls:
  - SOC2-CC-6.1
  - GDPR-Art-32
```

---

## 6. Data & Control Flows

### Flow A: Standard Safe Query (Happy Path)

```
User Request (JWT Bearer)
     │
     ▼
[Agent Orchestrator API] → validate JWT (Keycloak JWKS)
     │                   → check Cerbos ABAC (can user write to this thread?)
     │
     ▼
[LangGraph: guardrail_node]
     │  → Guardrails AI: ToxicLanguage, PromptInjection validators
     │  → DB rules engine: pattern matching against compliance_rules
     │  → is_safe = True
     │
     ▼
[LangGraph: memory_node]
     │  → Load last N messages from Postgres (conversation memory)
     │  → Qdrant RAG: semantic search for relevant context
     │  → Augment AgentState with memory + context
     │
     ▼
[LangGraph: agent_reasoning_node] (ReAct)
     │  → Call LiteLLM (POST /v1/chat/completions)
     │  → LiteLLM → Langfuse trace logged
     │  → LiteLLM → Ollama (LAN) → LLM generates response
     │  → LLM: no tool call needed → direct response
     │
     ▼
[LangGraph: generation_node]
     │  → Finalize response
     │  → Write conversation turn to memory
     │  → Langfuse: update session trace with node metadata
     │
     ▼
SSE stream → User
```

### Flow B: High-Risk Tool Call (HITL Path)

```
User Request
     │
     ▼
[guardrail_node] → PASS
     │
     ▼
[memory_node] → context loaded
     │
     ▼
[agent_reasoning_node]
     │  → LLM decides: call terminal_executor tool
     │  → MCP Client: POST /mcp/call {tool: "terminal_executor", args: {...}}
     │  → MCP Server: Cerbos check → ALLOW (user has terminal_executor permission)
     │  → MCP Server: tool_metadata.risk = "critical" → hitl_required = True
     │  → MCP Server returns: {status: "pending_approval", action_id: "act_xyz"}
     │
     ▼
[governance_shield_node]
     │  → AGT: log agent_action_intercepted evidence to Governance Engine
     │  → AGT: calculate risk_score = 0.95 (critical tool)
     │  → AGT: set approval_chain = ["tenant-admin"]
     │  → AGT: set approval_timeout_at = now + 30min
     │  → LangGraph: INTERRUPT — save checkpoint to DB
     │
     ▼
[API returns 200 with status: "action_required"]
     │
     ▼
Dashboard: Admin sees pending action alert
Admin reviews: POST /api/v1/threads/{id}/runs {approve_action: true}
     │
     ▼
[LangGraph: resume from checkpoint]
[governance_shield_node]
     │  → action_approved = True
     │  → AGT: log approval evidence (HMAC-signed)
     │
     ▼
[MCP Client: POST /mcp/call {tool: "terminal_executor", approved: true}]
     │  → MCP Server executes tool safely (sandboxed)
     │  → Returns result
     │
     ▼
[generation_node] → final response
```

### Flow C: Guardrail Violation (Block + Audit)

```
User Request (prompt injection attempt)
     │
     ▼
[guardrail_node]
     │  → Guardrails AI: PromptInjection validator fires
     │  → is_safe = False
     │  → HTTP POST to Governance Engine /api/v1/evidence
     │      {control_id: "EU-AI-Act-Art-9", severity: "high", payload: {...}}
     │  → Governance Engine: HMAC-signs evidence entry
     │  → Governance Engine: Recalculates tenant compliance score
     │  → Governance Engine: Alert webhook (if severity == critical)
     │
     ▼
[LangGraph routes to END — no LLM call made]
     │
     ▼
[API returns 200 with status: "blocked", response: "Policy violation: ..."]
```

### Flow D: MCP Tool Execution (Low Risk)

```
[agent_reasoning_node] → LLM calls knowledge_search
     │
     ▼
[MCP Client POST /mcp/call]
     │  → MCP Server receives request
     │  → Verify agent SPIFFE ID (mTLS)
     │  → Cerbos ABAC: agent has knowledge_search permission? YES
     │  → Tool: knowledge_search.risk = "low", hitl_required = False
     │  → Execute: Qdrant vector search
     │  → Return results
     │
     ▼
[agent_reasoning_node continues ReAct loop with tool result]
```

---

## 7. Add / Change / Remove Summary

### ✅ KEEP (These are Good)
| Component | Reason |
|---|---|
| **LangGraph** | Correct framework for stateful, interruptible agent workflows |
| **Cerbos ABAC** | Right PDP choice — declarative, testable, tenant-aware |
| **LiteLLM** | Best AI gateway for self-hosted multi-model routing |
| **Langfuse** | Best-in-class LLM observability, already wired correctly |
| **Keycloak** | Enterprise SSO standard |
| **SPIRE/SPIFFE** | Right workload identity system |
| **PostgreSQL RLS** | Correct multi-tenant data isolation pattern |
| **MinIO** | Right evidence object store |
| **Qdrant** | Right vector DB for RAG |
| **SSE Streaming** | Production-grade streaming implementation |
| **HITL interrupt pattern** | Core AGT alignment is correct |
| **Discovery daemon** | Clever shadow AI detection |

### ➕ ADD (Missing Pieces)
| Component | Priority | Why |
|---|---|---|
| **Internal MCP Server** | 🔴 Critical | Replace hardcoded tools JSON; enable proper tool ecosystem |
| **Agent Catalog / Registry** | 🟠 High | Version and manage agent definitions; enable per-agent policy |
| **Memory Node (LangGraph)** | 🟠 High | Persistent conversation memory across turns |
| **Guardrails AI** | 🟠 High | Replace NeMo with open-source, LAN-compatible validators |
| **AGT: Risk scoring** | 🟠 High | Score each action 0-1; drive HITL threshold dynamically |
| **AGT: Approval chains** | 🟡 Medium | Multi-step approvals (user → admin → compliance) |
| **AGT: HMAC evidence signing** | 🟡 Medium | Tamper-proof audit trail |
| **Tenant virtual keys (LiteLLM)** | 🟡 Medium | Per-tenant spend tracking and rate limits |
| **Langfuse session traces per node** | 🟡 Medium | Deep LangGraph observability |
| **Governance Engine: Policy eval endpoint** | 🟡 Medium | Active pre-action policy checks, not just post-event logging |
| **Grafana Loki** | 🟢 Low | Replace Elastic ECK for log aggregation (lighter) |
| **Alert webhooks** | 🟢 Low | Slack/Teams alerts on critical governance events |

### 🔄 CHANGE (Needs Rework)
| Component | Change | Why |
|---|---|---|
| **orchestrator/main.py** | Split into modules | Unmaintainable at 1771 lines |
| **Governance Engine** | Add active policy evaluation | Currently passive log sink |
| **MCP bridge** | Replace stub with real implementation | Currently `print("MCP Bridge initialized.")` |
| **SPIRE** | Wire to runtime | Present but not enforced — services still use X-headers |
| **LangGraph state** | Add risk_score, approval_chain, audit_hmac | Extend for full AGT alignment |
| **Guardrail string matching** | Semantic similarity check via embeddings | Pattern matching is trivially bypassed |

### ❌ REMOVE
| Component | Reason |
|---|---|
| **NeMo Guardrails** | NVIDIA-specific, heavyweight, requires cloud model default, your fallback logic already works better |
| **Garak** (as runtime) | Great for red-teaming/CI, wrong for runtime path — move to CI/CD pipeline only |
| **Elastic ECK** | Too heavyweight for LAN deployment; replace with Loki + Grafana |

---

## 8. Implementation Roadmap

### Phase 1 — Foundation Hardening (2–3 weeks)
- [x] Break `agent-orchestrator/main.py` into modules
- [ ] Wire SPIRE SVID verification between orchestrator ↔ governance engine ↔ future MCP
- [x] Add `@observe` Langfuse decorators to all LangGraph nodes
- [x] Extend `AgentState` with `action_risk_score`, `approval_chain`, `audit_hmac`
- [x] Add HMAC signing to Governance Engine evidence entries

### Phase 2 — MCP Server (3–4 weeks)
- [x] Build `apps/mcp-server/` with MCP protocol (JSON-RPC 2.0)
- [x] Implement tool registry with risk classification
- [x] Implement: `knowledge_search`, `file_reader`, `file_writer`, `terminal_executor`
- [x] Wire Cerbos ABAC per-tool checks
- [x] Wire MCP client in `agent_reasoning_node` to replace hardcoded `AGENT_TOOLS`

### Phase 3 — Agent Catalog + AGT Enhancement (2–3 weeks)
- [x] Build agent catalog (YAML definitions + API)
- [x] Add risk scoring to `governance_shield_node`
- [x] Add approval chain support (multi-level HITL)
- [x] Add `approval_timeout_at` with auto-reject background job
- [x] Add break-glass override with mandatory audit

### Phase 4 — Guardrails Replacement + Observability (2 weeks)
- [ ] Replace NeMo with Guardrails AI validators
- [ ] Add semantic similarity jailbreak detection via Qdrant
- [ ] Add output validation in `generation_node`
- [ ] Set up Grafana Loki (replace Elastic ECK)
- [ ] Add LiteLLM tenant virtual keys
- [x] Add Governance Engine alert webhooks

### Phase 5 — Production Hardening (ongoing)
- [ ] Move Garak to CI/CD pipeline (run nightly red-team scans)
- [x] Add governance engine active policy evaluation endpoint
- [ ] Load test multi-tenant isolation
- [ ] Add automated compliance report generation (PDF from evidence DB)

---

## Final Verdict

This is a **well-conceived architecture with a weak execution layer**. The design decisions (LangGraph, Cerbos, LiteLLM, Langfuse, SPIRE, Keycloak) are all correct choices for an enterprise-grade, air-gapped AI control plane. The fundamental HITL interrupt pattern and multi-tenant RLS approach are production-ready thinking.

The execution gaps are:
1. **MCP is a stub** — this is the most critical missing piece
2. **The god-class orchestrator** — will block any team from working in parallel
3. **NeMo is the wrong guardrail** for this deployment model
4. **Governance is reactive, not proactive** — it should evaluate before action, not just log after

Fix those four things and you have a genuinely enterprise-grade system.
