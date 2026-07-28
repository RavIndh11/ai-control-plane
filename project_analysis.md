# Enterprise AI Control Plane - Comprehensive Project Analysis

## 1. Project Overview & Objectives
The **Enterprise AI Control Plane** is a self-hosted, multi-tenant AI reference architecture designed to secure, monitor, and audit AI workloads within an enterprise network. It serves as a unified platform to manage AI agents, ensure compliance, and apply robust security guardrails.

### Core Objectives:
1.  **Air-Gapped & Local First**: Operates entirely on local LAN hardware (e.g., using Ollama for LLMs) to prevent proprietary data from leaving the corporate perimeter.
2.  **Deterministic Agent Governance**: Enforces rigid access control using Cerbos (RBAC/ABAC) and implements agentic guardrails through LangGraph security nodes.
3.  **Active Compliance Auditing**: Automatically monitors workflows, intercepts safety breaches (like prompt injection or unauthorized access), and logs them to a tamper-proof Governance Engine to produce GRC (Governance, Risk, and Compliance) evidence.

---

## 2. System Architecture & Components

The repository is structured as a monorepo containing various decoupled microservices and platform infrastructure components.

### Applications (`apps/`)
*   **`agent-orchestrator`**: A FastAPI service that manages LangGraph agent state and workflows. It acts as the primary executor for AI tasks and applies the security pipelines.
*   **`dashboard`**: A React/TypeScript web-based management console UI for users and administrators to interact with agents, view compliance metrics, and manage settings. It includes a Simulated Sandbox Mode for local testing.
*   **`governance-engine`**: A FastAPI backend dedicated to compliance auditing. It collects evidence, logs audit entries (e.g., SQL audit logs), uploads reports to MinIO, and calculates compliance scores.
*   **`integration-adapters`**: Contains bridges for MCP (Model Context Protocol), GRC integrations, OIDC for identity, and OpenTelemetry (OTel) for observability.

### Platform Services (`platform/`)
*   **`datastore/`**: Configurations for local data persistence, including PostgreSQL (with pgvector for embeddings), Redis (for caching/state), MinIO (for object storage/evidence reports), and Qdrant (for vector search).
*   **`gitops/`**: GitOps configuration manifests for continuous delivery, specifically utilizing ArgoCD.
*   **`identity/`**: Identity provider configurations, primarily Keycloak for SSO and SPIRE for workload identity (cryptographically signed SPIFFE IDs).
*   **`policy/`**: Cerbos YAML policies defining attribute-based access control (ABAC) rules.
*   **`runtime/`**: AI runtime configurations, featuring LiteLLM for model routing, NeMo Guardrails for pattern checks, and Garak for vulnerability scanning.

### Infrastructure & Deployment (`infra/` & `k8s/`)
*   **`infra/`**: Infrastructure as Code (IaC) declarations utilizing Terraform.
*   **`k8s/`**: Kubernetes deployment templates for datastores and applications.
*   **`tenants/`**: Configurations for tenant isolation, including Kubernetes namespaces, RBAC rules, and network policies.

---

## 3. Workflows & Data Flows

### A. Guardrail Interception & GRC Logging Flow
This flow details how user requests are intercepted, validated, and logged before they reach the language model.

1.  **User Input**: User submits a query or prompt.
2.  **Agent Orchestrator**: Receives the input and initiates the LangGraph workflow.
3.  **Security Node (`guardrail_check`)**: Evaluates the prompt for safety.
    *   **If Input is Unsafe (e.g., SQL injection, bypass attempt)**:
        *   The LLM generation is bypassed.
        *   An HTTP Webhook POST is sent to the **Governance Engine**.
        *   The Governance Engine writes a SQL audit entry, uploads a JSON incident report to MinIO, and updates the tenant's Compliance Score.
    *   **If Input is Safe**:
        *   The request proceeds to the **Generation Node**.
4.  **LLM Generation**: 
    *   Queries LiteLLM, which routes the validated request to an external local Ollama instance for processing.

### B. Access Control & Isolation Flow (Cerbos & RLS)
*   **Authentication**: Handled via Keycloak JWT claims.
*   **Authorization**: FastAPI services verify permissions against the Cerbos engine using `X-User-Role` headers:
    *   `tenant-user`: Can interact with AI threads but is restricted from viewing GRC metrics (`403 Forbidden`).
    *   `tenant-admin` & `compliance-auditor`: Have read access to compliance scores and audit logs.
*   **Data Tier Isolation**: Uses PostgreSQL **Row-Level Security (RLS)**. Database queries are executed within transactions scoped by setting the local tenant ID (`SET LOCAL app.current_tenant_id = '<id>';`), ensuring strict multi-tenant data separation.

---

## 4. Configuration Management
The entire stack is configured via a central `.env` file at the root. Key configurations include:
*   **Kubernetes & Registry**: Target namespace, registry URL, and container image tags.
*   **Datastores**: Credentials for Postgres, Redis, MinIO, etc.
*   **External AI Services**: IP and model name for the local Ollama instance.
*   **Security & Gateways**: Keycloak endpoints, NeMo Guardrails URLs, and Qdrant mappings.
*   **Observability**: OpenTelemetry OTLP endpoint and Langfuse credentials.

*(Note: For local development, missing variables fallback to secure simulated local rules like header-based auth and local guardrails.)*

---

## 5. Development & Deployment Execution

### Local Sandbox Development
Allows testing backend integration using local SQLite databases without Docker or Kubernetes.
*   **Start Backend & Tests**: Running `./run_local.sh` sets up a Python virtual environment, installs dependencies, launches the Governance and Orchestrator APIs (ports `8000` & `8001`), and executes integration tests (`test_flow.py`).
*   **Start Dashboard**: Navigate to `apps/dashboard`, run `npm install`, and `npm run start`. It will run in simulated mode if the backends are offline.

### Production VM Cluster Deployment (K8s)
Targeted for a 1 Master, 2 Worker VM architecture.
1.  **Configure `.env`**: Set `REGISTRY` (e.g., `localhost:5000`) and other environment variables.
2.  **Deploy**: Run `./deploy.sh`. This script builds Docker images on the node, pushes them to the local registry, substitutes configuration into K8s manifests, and applies them via `kubectl`.
3.  **Access Services**: Exposed via NodePorts on the VM IP:
    *   Dashboard: `Port 30082`
    *   Governance Engine: `Port 30080`
    *   Agent Orchestrator: `Port 30081`
4.  **Identity Attestation**: SPIRE workloads can be registered explicitly using provided scripts in the `platform/identity/spire/` directory.
