#!/usr/bin/env bash
# File: deploy.sh
set -e

# 1. Load Configurations
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found. Copy it from the repository root."
    exit 1
fi

echo "============================================="
echo "⚙️  1. Loading Environment Configurations"
echo "============================================="
# Export all variables from .env
set -a
source .env
set +a

echo "Namespace:   $NAMESPACE"
echo "Registry:    $REGISTRY"
echo "Image Tag:   $TAG"
echo "LLM Gateway: $LLM_GATEWAY_URL"
echo "LLM Model:   $LLM_MODEL"
echo "Ollama Host: $OLLAMA_HOST_IP"
echo "============================================="

# 2. Build Container Images
echo "============================================="
echo "📦 2. Building Application Container Images"
echo "============================================="
echo "Building dashboard..."
docker build -t "$REGISTRY/dashboard:$TAG" apps/dashboard

echo "Building governance-engine..."
docker build -t "$REGISTRY/governance-engine:$TAG" apps/governance-engine

echo "Building agent-orchestrator..."
docker build -t "$REGISTRY/agent-orchestrator:$TAG" apps/agent-orchestrator

# 3. Push Container Images
echo "============================================="
echo "🚀 3. Pushing Images to Registry ($REGISTRY)"
echo "============================================="
echo "Pushing dashboard..."
docker push "$REGISTRY/dashboard:$TAG" || echo "⚠️ Warning: Failed to push dashboard. Ensure registry is running."

echo "Pushing governance-engine..."
docker push "$REGISTRY/governance-engine:$TAG" || echo "⚠️ Warning: Failed to push governance-engine."

echo "Pushing agent-orchestrator..."
docker push "$REGISTRY/agent-orchestrator:$TAG" || echo "⚠️ Warning: Failed to push agent-orchestrator."

# 4. Generate K8s Manifests (Variable Substitution)
echo "============================================="
echo "🔧 4. Generating Templated K8s Manifests"
echo "============================================="
mkdir -p k8s/build

# Python snippet to perform env variable substitution on templates
substitute_vars() {
    local src=$1
    local dest=$2
    python3 -c "import os, sys; print(os.path.expandvars(sys.stdin.read()))" < "$src" > "$dest"
}

substitute_vars k8s/templates/datastores.yaml k8s/build/datastores.yaml
substitute_vars k8s/templates/apps.yaml k8s/build/apps.yaml

echo "Manifests compiled in k8s/build/ directory."

# 5. Deploy to Kubernetes
echo "============================================="
echo "☸️  5. Deploying to Kubernetes Cluster"
echo "============================================="
kubectl apply -f k8s/build/

echo "============================================="
echo "🎉 Deployment Orchestrated Successfully!"
echo "============================================="
echo "Stack deployed in namespace: $NAMESPACE"
echo ""
echo "Access URLs (Use your Master/Worker Node IP):"
echo "--------------------------------------------------------"
echo "📊 React Dashboard Frontend: http://<NODE-IP>:30082"
echo "🚦 Governance Engine API:   http://<NODE-IP>:30080"
echo "🤖 Agent Orchestrator API:   http://<NODE-IP>:30081"
echo "--------------------------------------------------------"
echo "Verify status using: kubectl get pods -n $NAMESPACE"
echo "============================================="
