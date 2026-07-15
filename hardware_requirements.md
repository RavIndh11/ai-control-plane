# Hardware Requirements & Node Service Mapping

This document specifies the recommended hardware specifications and workload distribution for the **Enterprise AI Control Plane** 3-node VM cluster and external LLM hardware.

---

## 🖥️ Node 1: Master Control Node (VM)
*   **Purpose**: Kubernetes cluster coordinator, authentication registry, and workload identity server.
*   **Recommended Specifications**:
    *   **CPU**: 2 vCPUs (Minimum required by Kubernetes)
    *   **RAM**: 8 GB RAM (To support Keycloak and SPIRE servers)
    *   **Disk**: 50 GB SSD
*   **Workloads Running**:
    *   Kubernetes Control Plane (`kube-apiserver`, `etcd`, `scheduler`)
    *   **Keycloak** (IAM & SSO Identity Provider)
    *   **SPIRE Server** (Workload identity authority)
    *   **ArgoCD** (GitOps Deployment controller)
    *   **Docker Registry** (Insecure registry on Port 5000)

---

## 🖥️ Node 2: AI Gateway & Cache Worker (VM)
*   **Purpose**: Runs the LLM routing proxy, cache database, and agent safety guardrails.
*   **Recommended Specifications**:
    *   **CPU**: 4 vCPUs
    *   **RAM**: 8 GB RAM
    *   **Disk**: 50 GB SSD
*   **Workloads Running**:
    *   **LiteLLM Gateway** (Model router & spend tracking)
    *   **Redis** (Semantic prompt cache & LangGraph state checkpointing)
    *   **NeMo Guardrails** (Safety policy validations)
    *   **OTel Collector** (Observability traces scraper)
    *   **Ollama Bridge** (K8s `ExternalName` service pointing to the physical LLM node)

---

## 🖥️ Node 3: Custom Applications & Datastores Worker (VM)
*   **Purpose**: Hosts user-facing services, PostgreSQL, object storage, and vector databases.
*   **Recommended Specifications**:
    *   **CPU**: 4 vCPUs
    *   **RAM**: 16 GB RAM (Highly database-intensive node)
    *   **Disk**: 100 GB SSD (For vector indexes and audit objects)
*   **Workloads Running**:
    *   **React Dashboard UI** (Console panel on Port 30082)
    *   **Agent Orchestrator** (LangGraph workflows on Port 30081)
    *   **Governance Engine** (FastAPI compliance logger on Port 30080)
    *   **Qdrant** (Vector Database for RAG)
    *   **PostgreSQL** (Relational metadata store with `pgvector`)
    *   **MinIO** (GRC immutable audit logs storage)

---

## ⚙️ LAN Node: Dedicated LLM Hosting (Physical Machine)
*   **Purpose**: Dedicated bare-metal machine to host and run LLM models without affecting virtualized VM resources.
*   **Recommended Specifications**:
    *   **CPU**: 8 Cores (High CPU processing capability) / Optional NVIDIA GPU (e.g. RTX 3090/4090)
    *   **RAM**: 32 GB RAM
    *   **Disk**: 100 GB SSD
*   **Workloads Running**:
    *   **Ollama (standalone)**: Exposing models (`llama3.1`, `mistral`, `qwen3`) on Port 11434.
