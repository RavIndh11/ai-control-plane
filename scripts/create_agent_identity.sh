#!/bin/bash
# ==============================================================================
# scripts/create_agent_identity.sh
# Creates an Agentic Identity (Service Account) in Keycloak for AGT Mapping.
# ==============================================================================

set -e

KEYCLOAK_URL="http://localhost:30084"
REALM="master"
ADMIN_USER="admin"
ADMIN_PASS="admin"
AGENT_CLIENT_ID="support-agent-v1"

echo "1. Authenticating with Keycloak Admin CLI..."
/opt/keycloak/bin/kcadm.sh config credentials --server $KEYCLOAK_URL --realm master --user $ADMIN_USER --password $ADMIN_PASS

echo "2. Creating Agent Client (Service Account / Client Credentials Flow)..."
/opt/keycloak/bin/kcadm.sh create clients -r $REALM -s clientId=$AGENT_CLIENT_ID -s enabled=true \
  -s serviceAccountsEnabled=true \
  -s standardFlowEnabled=false \
  -s publicClient=false

echo "3. Assigning Agentic Roles (mapped later by AGT)..."
# Create role
/opt/keycloak/bin/kcadm.sh create roles -r $REALM -s name="autonomous-agent"
# Map role to the service account
USER_ID=$(/opt/keycloak/bin/kcadm.sh get users -r $REALM -q username=service-account-$AGENT_CLIENT_ID | jq -r '.[0].id')
/opt/keycloak/bin/kcadm.sh add-roles -r $REALM --uusername service-account-$AGENT_CLIENT_ID --rolename "autonomous-agent"

echo "4. Retrieving Agent Client Secret..."
SECRET=$(/opt/keycloak/bin/kcadm.sh get clients -r $REALM -q clientId=$AGENT_CLIENT_ID | jq -r '.[0].id' | xargs -I {} /opt/keycloak/bin/kcadm.sh get clients/{}/client-secret -r $REALM | jq -r '.value')

echo "============================================================"
echo "Identity created successfully."
echo "Agent Client ID : $AGENT_CLIENT_ID"
echo "Agent Secret    : $SECRET"
echo "Roles           : autonomous-agent"
echo "Use these to fetch a JWT for the agent before hitting the Orchestrator API."
echo "============================================================"
