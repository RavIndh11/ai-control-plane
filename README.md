# Enterprise AI Control Plane

This monorepo contains the core architecture, security policies, and application templates for the **Enterprise AI Control Plane**—a multi-tenant system designed to secure, monitor, and orchestrate enterprise AI agent workflows.

---

## 🏗️ Repository Architecture

```
enterprise-ai-control-plane/
├── apps/
│   ├── agent-orchestrator/   # LangGraph agent state workflows (FastAPI)
│   ├── dashboard/            # React/TypeScript management console UI
│   ├── governance-engine/    # FastAPI GRC audit & evidence collector
│   └── integration-adapters/ # MCP, GRC, OIDC, and OTel bridges
├── platform/
│   ├── datastore/            # Local configs for Redis, pgvector, and MinIO
│   ├── gitops/               # GitOps config manifests (ArgoCD)
│   ├── identity/             # Identity providers (Keycloak, SPIRE)
│   ├── policy/               # ABAC authorization policies (Cerbos)
│   └── runtime/              # LLM gateways & validation (LiteLLM, Guardrails, Garak)
├── infra/                    # IaC declarations (Terraform)
├── tenants/                  # Tenant isolation namespaces, RBAC, and network policies
├── k8s/                      # Kubernetes templates for deployment
├── deploy.sh                 # Master deployment script
└── run_local.sh              # Local development setup and integration test runner
```

---

## ⚙️ Configuration & Environment Settings

All deployment parameters are controlled centrally from a single environment file at the root:
*   **`.env`**: Edit this file to configure:
    *   **Kubernetes & Registry**: Namespace, registry URL, and image tag.
    *   **Datastores**: Postgres, Redis, and MinIO credentials.
    *   **External AI Services**: Ollama host IP and model name.
    *   **Security & Gateways**: Keycloak JWKS endpoint (JWT verification), NeMo Guardrails URL, and Qdrant collection mappings.
    *   **Observability**: OpenTelemetry OTLP endpoint and Langfuse credentials.

*Note: For local development, leaving Keycloak, NeMo, and MinIO environment variables blank will automatically fall back to secure, simulated local rules (header-based auth, local pattern guardrails, and DB-only evidence storage).*


---

## 💻 Local Development & Integration Testing

To run the backends locally and test the integration flow (where the LangGraph agent intercepts sql injection attempts and automatically logs them as evidence with the Governance Engine):

1.  **Run the Local Integration Flow**:
    ```bash
    chmod +x run_local.sh
    ./run_local.sh
    ```
    This script initializes a Python virtual environment, installs dependencies, launches the backends on ports `8000` (Governance) and `8001` (Orchestrator), executes the integration tests in `test_flow.py`, and shuts down cleanly.

2.  **Run the Dashboard UI**:
    Navigate to the dashboard directory, install packages, and start the development server:
    ```bash
    cd apps/dashboard
    npm install
    npm run start
    ```
    *If local backend servers are offline, the dashboard automatically enters an interactive **Simulated Sandbox Mode** where you can test agent runs and compliance events directly.*

---

## ☸️ VM Cluster Deployment (1 Master, 2 Workers)

To deploy the entire stack to your production/testing VM cluster, follow these steps on your master node:

1.  **Configure Registry and Tag**:
    Open the central `.env` file and set `REGISTRY` to your shared container registry (e.g., a local registry running on your master node on port 5000: `localhost:5000`).
    ```ini
    REGISTRY=your-registry-ip:5000
    TAG=latest
    ```

2.  **Deploy Stack**:
    Execute the deployment script:
    ```bash
    ./deploy.sh
    ```
    This script automatically:
    *   Builds Docker containers for the `dashboard`, `governance-engine`, and `agent-orchestrator` directly on the node.
    *   Pushes the built images to the registry.
    *   Substitutes configuration credentials and image paths into the Kubernetes templates.
    *   Applies the manifests using `kubectl`.

3.  **Access the Ports**:
    The services are exposed via NodePorts on your VM node IPs:
    *   **React Dashboard**: `http://<NODE-IP>:30082`
    *   **Governance Engine API**: `http://<NODE-IP>:30080`
    *   **Agent Orchestrator API**: `http://<NODE-IP>:30081`

---

## 🛡️ Security & Multi-Tenancy Design
*   **Data Partitioning**: Isolated per tenant using PostgreSQL **Row-Level Security (RLS)**.
*   **Fine-Grained Authorization**: Implemented via [Cerbos](https://cerbos.dev) attribute-based access control (ABAC).
*   **Workload Identity**: Cryptographically signed SPIFFE IDs managed by **SPIRE** sidecars inside the cluster namespace.
