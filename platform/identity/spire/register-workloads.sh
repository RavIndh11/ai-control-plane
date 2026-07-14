#!/usr/bin/env bash
# File: platform/identity/spire/register-workloads.sh
# Script to register Agent Orchestrator and Governance Engine workloads in SPIRE Server.
set -e

# Configurable parameters
NAMESPACE=${NAMESPACE:-"control-plane"}
SPIRE_NAMESPACE=${SPIRE_NAMESPACE:-"spire"}
TRUST_DOMAIN=${TRUST_DOMAIN:-"control-plane.local"}

echo "============================================="
echo "🔒 Registering Workload Identities in SPIRE"
echo "============================================="

# Helper function to execute spire-server commands inside the server pod
run_spire_cmd() {
    local server_pod
    server_pod=$(kubectl get pods -n "$SPIRE_NAMESPACE" -l app=spire-server -o jsonpath='{.items[0].metadata.name}')
    
    echo "Running SPIRE server command inside pod: $server_pod"
    kubectl exec -n "$SPIRE_NAMESPACE" "$server_pod" -c spire-server -- /opt/spire/bin/spire-server "$@"
}

# 1. Register the SPIRE Agent (Node Attestation Parent Entry)
echo "Registering SPIRE Agent Node Attestor..."
run_spire_cmd entry create \
    -spiffeID "spiffe://$TRUST_DOMAIN/ns/$SPIRE_NAMESPACE/sa/spire-agent-sa" \
    -node \
    -selector "k8s_psat:cluster:demo-cluster" \
    || echo "⚠️ SPIRE Agent entry already exists or registration skipped."

# 2. Register the Agent Orchestrator Workload
echo "Registering Agent Orchestrator Workload ID..."
run_spire_cmd entry create \
    -parentID "spiffe://$TRUST_DOMAIN/ns/$SPIRE_NAMESPACE/sa/spire-agent-sa" \
    -spiffeID "spiffe://$TRUST_DOMAIN/ns/$NAMESPACE/sa/agent-orchestrator-sa/app/agent-orchestrator" \
    -selector "k8s:ns:$NAMESPACE" \
    -selector "k8s:sa:agent-orchestrator-sa" \
    -selector "k8s:pod-label:app:agent-orchestrator" \
    || echo "⚠️ Agent Orchestrator entry already exists."

# 3. Register the Governance Engine Workload
echo "Registering Governance Engine Workload ID..."
run_spire_cmd entry create \
    -parentID "spiffe://$TRUST_DOMAIN/ns/$SPIRE_NAMESPACE/sa/spire-agent-sa" \
    -spiffeID "spiffe://$TRUST_DOMAIN/ns/$NAMESPACE/sa/governance-engine-sa/app/governance-engine" \
    -selector "k8s:ns:$NAMESPACE" \
    -selector "k8s:sa:governance-engine-sa" \
    -selector "k8s:pod-label:app:governance-engine" \
    || echo "⚠️ Governance Engine entry already exists."

echo "============================================="
echo "🎉 SPIFFE Workload Identities Registered Successfully!"
echo "============================================="
