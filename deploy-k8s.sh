#!/usr/bin/env bash
# deploy-k8s.sh — Full cluster deployment script for Enterprise AI Control Plane
# Run this from the project root on the MASTER node after:
#   1. All 3 nodes are in "Ready" state (kubectl get nodes)
#   2. Node labels are applied (see Step 0 below)
#   3. .env is updated with actual node IPs and Ollama IP
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# 0. Load environment
# ─────────────────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    echo "❌ .env not found. Run from the project root."
    exit 1
fi

set -a; source .env; set +a

# Validate required variables
: "${NAMESPACE:?Set NAMESPACE in .env}"
: "${REGISTRY:?Set REGISTRY in .env (e.g. <master-ip>:5000)}"
: "${TAG:?Set TAG in .env}"
: "${OLLAMA_HOST_IP:?Set OLLAMA_HOST_IP in .env}"
: "${MASTER_NODE_IP:?Set MASTER_NODE_IP in .env}"
: "${AUDIT_HMAC_SECRET:?Set AUDIT_HMAC_SECRET in .env}"

# Compute base64 basic auth for Langfuse OTel endpoint
LANGFUSE_BASIC_AUTH=$(echo -n "${LANGFUSE_PUBLIC_KEY:-pk-lf-master-secure-public-key}:${LANGFUSE_SECRET_KEY:-sk-lf-master-secure-secret-key}" | base64 | tr -d '\n')
export LANGFUSE_BASIC_AUTH

echo "============================================="
echo "🚀 Enterprise AI Control Plane — K8s Deploy"
echo "============================================="
echo "  Namespace:       $NAMESPACE"
echo "  Registry:        $REGISTRY"
echo "  Tag:             $TAG"
echo "  Master Node IP:  $MASTER_NODE_IP"
echo "  Ollama Host:     $OLLAMA_HOST_IP"
echo "============================================="

# ─────────────────────────────────────────────────────────────────────────────
# 1. Verify node labels (warn if missing, don't fail)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "── Step 1: Verifying node labels ──────────────────────"
for label in "node-role=master" "node-role=ai-gateway" "node-role=datastore"; do
    count=$(kubectl get nodes -l "$label" --no-headers 2>/dev/null | wc -l)
    if [ "$count" -eq 0 ]; then
        echo "⚠️  WARNING: No node has label $label. Run:"
        echo "   kubectl label node <node-name> $label"
    else
        echo "  ✅ $label → $(kubectl get nodes -l $label -o jsonpath='{.items[*].metadata.name}')"
    fi
done

# ─────────────────────────────────────────────────────────────────────────────
# 2. Install local-path-provisioner (provides PVC storage on bare metal)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "── Step 2: local-path-provisioner ─────────────────────"
if kubectl get sc local-path &>/dev/null; then
    echo "  ✅ local-path StorageClass already exists"
else
    echo "  Installing Rancher local-path-provisioner..."
    kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.28/deploy/local-path-storage.yaml
    kubectl patch storageclass local-path -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
    echo "  ✅ local-path StorageClass installed and set as default"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. Start local Docker registry on master (if not running)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "── Step 3: Local Docker registry ──────────────────────"
if docker ps --format '{{.Names}}' | grep -q "^registry$"; then
    echo "  ✅ Registry already running at $REGISTRY"
else
    docker run -d -p 5000:5000 --restart=always --name registry registry:2
    echo "  ✅ Registry started at $REGISTRY"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. Build and push application images
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "── Step 4: Build & push container images ───────────────"
for app in governance-engine agent-orchestrator dashboard mcp-server; do
    echo "  Building $app..."
    docker build -t "$REGISTRY/$app:$TAG" "apps/$app" --quiet
    echo "  Pushing $app..."
    docker push "$REGISTRY/$app:$TAG"
    echo "  ✅ $app pushed"
done

# ─────────────────────────────────────────────────────────────────────────────
# 5. Generate manifests via envsubst and apply
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "── Step 5: Apply Kubernetes manifests ─────────────────"
mkdir -p k8s/build

# Helper: substitute env vars and apply
apply_template() {
    local src="$1"
    local dest="k8s/build/$(basename $src)"
    echo "  Applying $src..."
    python3 -c "import os, sys; print(os.path.expandvars(sys.stdin.read()))" < "$src" > "$dest"
    kubectl apply -f "$dest"
}

# Apply in strict dependency order
apply_template k8s/templates/00-namespace-and-secrets.yaml
echo "  ⏳ Waiting 3s for namespace..."
sleep 3

apply_template k8s/templates/01-datastores.yaml
echo "  ⏳ Waiting for datastores to be ready..."
kubectl rollout status deployment/postgres -n "$NAMESPACE" --timeout=120s
kubectl rollout status deployment/redis    -n "$NAMESPACE" --timeout=60s
kubectl rollout status deployment/minio    -n "$NAMESPACE" --timeout=60s
kubectl rollout status deployment/qdrant   -n "$NAMESPACE" --timeout=60s
echo "  ✅ Datastores ready"

apply_template k8s/templates/02-platform.yaml
echo "  ⏳ Waiting for platform services..."
kubectl rollout status deployment/litellm       -n "$NAMESPACE" --timeout=120s
echo "  ✅ Platform services ready"

apply_template k8s/templates/06-keycloak.yaml
kubectl rollout status deployment/keycloak -n "$NAMESPACE" --timeout=120s
echo "  ✅ Keycloak ready"


apply_template k8s/templates/03-apps.yaml
echo "  ⏳ Rolling restart to pick up new images..."
kubectl rollout restart deployment/governance-engine  -n "$NAMESPACE"
kubectl rollout restart deployment/agent-orchestrator -n "$NAMESPACE"
kubectl rollout restart deployment/dashboard          -n "$NAMESPACE"
kubectl rollout restart deployment/mcp-server         -n "$NAMESPACE" 2>/dev/null || true
echo "  ⏳ Waiting for application pods..."
if ! kubectl rollout status deployment/governance-engine  -n "$NAMESPACE" --timeout=120s; then
    echo "❌ Governance Engine failed to roll out! Diagnostics:"
    kubectl describe pod -l app=governance-engine -n "$NAMESPACE"
    kubectl logs -l app=governance-engine -n "$NAMESPACE" --all-containers
    exit 1
fi
if ! kubectl rollout status deployment/agent-orchestrator -n "$NAMESPACE" --timeout=120s; then
    echo "❌ Agent Orchestrator failed to roll out! Diagnostics:"
    kubectl describe pod -l app=agent-orchestrator -n "$NAMESPACE"
    kubectl logs -l app=agent-orchestrator -n "$NAMESPACE" --all-containers
    exit 1
fi
kubectl rollout status deployment/dashboard          -n "$NAMESPACE" --timeout=60s
kubectl rollout status deployment/mcp-server -n "$NAMESPACE" --timeout=60s
echo "  ✅ Applications ready"

apply_template k8s/templates/04-observability.yaml
echo "  ⏳ Waiting for observability stack..."
kubectl rollout status deployment/loki -n "$NAMESPACE" --timeout=120s
kubectl rollout status daemonset/promtail -n "$NAMESPACE" --timeout=120s
echo "  ✅ Observability stack ready"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Run schema migration on PostgreSQL
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "── Step 6: Database schema migration ───────────────────"
PG_POD=$(kubectl get pod -n "$NAMESPACE" -l app=postgres -o jsonpath='{.items[0].metadata.name}')
kubectl cp platform/datastore/postgres/schema.sql "$NAMESPACE/$PG_POD:/tmp/schema.sql"

# Run schema (idempotent — uses IF NOT EXISTS throughout)
kubectl exec -n "$NAMESPACE" "$PG_POD" -- \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/schema.sql -q
echo "  ✅ Schema applied to $POSTGRES_DB"

# Create the langfuse and keycloak databases if they don't exist
kubectl exec -n "$NAMESPACE" "$PG_POD" -- \
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE langfuse;" 2>/dev/null || true
kubectl exec -n "$NAMESPACE" "$PG_POD" -- \
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE keycloak;" 2>/dev/null || true
echo "  ✅ langfuse and keycloak databases ensured"

# Refresh compliance_rules seed (wipe old text-pattern rules, replace with regex)
echo "  Refreshing compliance rule seed..."
kubectl exec -n "$NAMESPACE" "$PG_POD" -- \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
        TRUNCATE TABLE compliance_rules;
        INSERT INTO compliance_rules (rule_id, pattern, is_active, control_id) VALUES
            (gen_random_uuid()::text, '(?i)\\bSELECT\\b.+\\bFROM\\b',          TRUE, 'SOC2-CC-6.1'),
            (gen_random_uuid()::text, '(?i)\\bDROP\\s+TABLE\\b',               TRUE, 'SOC2-CC-6.1'),
            (gen_random_uuid()::text, '(?i)\\bINSERT\\s+INTO\\b',              TRUE, 'SOC2-CC-6.1'),
            (gen_random_uuid()::text, '(?i)\\bDELETE\\s+FROM\\b',              TRUE, 'SOC2-CC-6.1'),
            (gen_random_uuid()::text, '(?i)\\bUNION\\s+SELECT\\b',             TRUE, 'SOC2-CC-6.1'),
            (gen_random_uuid()::text, ';\\s*rm\\s+-rf',                         TRUE, 'GDPR-Art-32'),
            (gen_random_uuid()::text, '&&\\s*rm\\s+-rf',                        TRUE, 'GDPR-Art-32'),
            (gen_random_uuid()::text, '\\|\\s*bash',                            TRUE, 'GDPR-Art-32'),
            (gen_random_uuid()::text, '(?i)\\bexec\\s*\\(',                     TRUE, 'GDPR-Art-32'),
            (gen_random_uuid()::text, '(?i)BEGIN\\s+(RSA\\s+)?PRIVATE\\s+KEY', TRUE, 'GDPR-Art-32');
    " -q 2>/dev/null || echo "  ⚠️  Seed refresh skipped (table may not exist yet)."
echo "  ✅ Compliance rule seed refreshed"

# Create the MinIO evidence bucket
echo "  Creating MinIO bucket manifold-evidence..."
MINIO_POD=$(kubectl get pod -n "$NAMESPACE" -l app=minio -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n "$NAMESPACE" "$MINIO_POD" -- \
    sh -c "mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD 2>/dev/null; \
           mc mb local/manifold-evidence 2>/dev/null || true; \
           echo 'Bucket ready'" || echo "  ⚠️  MinIO bucket setup skipped (mc not in image — use web UI at :30090)"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Summary
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "============================================="
echo "✅  Deployment complete!"
echo "============================================="
echo ""
echo "  NodePort Services (use any node IP):"
echo "  ┌─────────────────────────────────────────────────────┐"
echo "  │  Dashboard UI:          http://$MASTER_NODE_IP:30082  │"
echo "  │  Agent Orchestrator:    http://$MASTER_NODE_IP:30081  │"
echo "  │  Governance Engine:     http://$MASTER_NODE_IP:30080  │"
echo "  │  Langfuse Traces:       http://$MASTER_NODE_IP:30083  │"
echo "  │  Grafana UI:            http://$MASTER_NODE_IP:30091  │"
echo "  │  LiteLLM Gateway:       http://$MASTER_NODE_IP:30040  │"
echo "  │  MinIO Console:         http://$MASTER_NODE_IP:30090  │"
echo "  └─────────────────────────────────────────────────────┘"
echo ""
echo "  Monitor pods:"
echo "    kubectl get pods -n $NAMESPACE -w"
echo ""
echo "  Quick health check:"
echo "    curl http://$MASTER_NODE_IP:30080/health   # Governance Engine"
echo "    curl http://$MASTER_NODE_IP:30081/health   # Agent Orchestrator"
echo ""
