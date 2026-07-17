# Enterprise AI Control Plane: System & Architecture Index

This index serves as the developer entry point and system blueprint for the **Enterprise AI Control Plane** monorepo. It details the system architecture, component mappings, runtime flows, and development execution guidelines for both human engineers and AI coding agents.

---

## 🎯 1. System Overview & Objectives
The Enterprise AI Control Plane is a self-hosted, multi-tenant AI reference architecture designed to secure, monitor, and audit AI workloads within an enterprise network.

### Key Goals:
1.  **Air-Gapped & Local First**: Designed to run entirely on local LAN hardware (using external LLM runners like Ollama) without leaking proprietary data outside the perimeter.
2.  **Deterministic Agent Governance**: Enforces security policies at the user level (via Cerbos RBAC/ABAC) and agentic guardrails (via LangGraph security nodes).
3.  **Active Compliance Auditing**: Automatically intercepts safety breaches and logs them to a central, tamper-proof Governance Engine to generate GRC compliance evidence.

---

## 🏗️ 2. Core Components & Folder Structure

```
enterprise-ai-control-plane/
├── apps/
│   ├── dashboard/            # React/TypeScript management console UI (Port 30082)
│   ├── agent-orchestrator/   # LangGraph agent state/workflow backends (Port 30081)
│   ├── governance-engine/    # FastAPI compliance auditing engine (Port 30080)
│   └── integration-adapters/ # MCP, GRC, and OTel collectors
├── platform/
│   ├── datastore/            # Database value configs (Redis, Postgres, MinIO, Qdrant)
│   ├── identity/             # Keycloak SSO configs and SPIRE server/agent specs
│   ├── policy/               # Cerbos ABAC authorization YAML policies
│   └── runtime/              # LiteLLM routing, NeMo Guardrails, and Garak scanners
├── k8s/                      # Kubernetes deployment templates (datastores, apps)
├── deploy.sh                 # Master VM deployment orchestrator
├── run_local.sh              # Local development launcher
├── test_flow.py              # Integration test executor
└── hardware_requirements.md  # Recommended hardware and VM resource mappings
```

---

## 🚦 3. System Workflows & Data Flows

### A. Guardrail Interception & GRC Logging Flow
When a user executes a query, the system runs through a multi-tiered security pipeline before contacting the model:

```
[User Input] 
     |
     v
[Agent Orchestrator] 
     |-- Runs LangGraph Workflow 
     |-- Node 1: "guardrail_check" (evaluates prompt input)
     |
     +---> (If Input Unsafe / restricted SQL/Bypass patterns detected)
     |          |
     |          +--- [Bypasses LLM Generation] 
     |          +--- [Sends HTTP Webhook POST] ---> [Governance Engine] (Port 8000)
     |                                                    |
     |                                                    +--- Writes SQL audit entry
     |                                                    +--- Uploads JSON report to MinIO
     |                                                    +--- Recalculates Compliance Score
     v
[Node 2: "generation"] (Only reached if prompt passes guardrail)
     |-- Queries LiteLLM (Port 4000)
     |-- LiteLLM routes to External Ollama LAN IP (Port 11434)
```

### B. Access Control Isolation Flow (Cerbos & RLS)
*   **User Authentication**: Handled via Keycloak JWT claims.
*   **Authorization Checking**: FastAPI services query the Cerbos engine to verify permissions using `X-User-Role` headers:
    *   `tenant-user` can interact with chat threads but is blocked (`403 Forbidden`) from viewing GRC metrics.
    *   `tenant-admin` and `compliance-auditor` can read compliance scores.
*   **Data Tier Isolation**: PostgreSQL tables enforce **Row-Level Security (RLS)**. Queries run inside transactions scoped by `SET LOCAL app.current_tenant_id = '<id>';`, ensuring tenants never read or write to other tenant namespaces.

---

## 🛠️ 4. Development & Running Guides

### A. Local Sandbox Mode (No K8s / No Docker needed)
To test and verify the entire backend integration locally using SQLite databases:
```bash
./run_local.sh
```
This script sets up a python virtualenv, installs dependencies, launches the backends in the background, and runs [test_flow.py](file:///home/aravindh/Projects/enterprise-ai-control-plane/test_flow.py) to confirm SQL persistence and Cerbos checks.

To run the React console:
```bash
cd apps/dashboard
npm install
npm run start
```
*Note: If local backend ports 8000/8001 are offline, the dashboard automatically enters an interactive simulated sandbox mode matching the backend logic.*

### B. Production VM Cluster Deployment
To launch the stack onto a 3-node Kubernetes VM cluster:
1.  Configure LAN IPs, registries, and passwords in the central [`.env`](file:///home/aravindh/Projects/enterprise-ai-control-plane/.env) file.
2.  Run the installer:
    ```bash
    ./deploy.sh
    ```
3.  Expose SPIRE attestation:
    ```bash
    kubectl apply -f platform/identity/spire/spire-bundle.yaml
    ./platform/identity/spire/register-workloads.sh
    ```
