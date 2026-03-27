#!/usr/bin/env bash
# Build images on the cluster (binary Docker strategy) and roll out Orbit.
# Prereqs: oc login, cluster egress for npm/pip.
# Target namespace: set ORBIT_DEPLOY_NAMESPACE (e.g. orbit or orbit-operator) or run: oc project <ns>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ -n "${ORBIT_DEPLOY_NAMESPACE:-}" ]]; then
  NS="$ORBIT_DEPLOY_NAMESPACE"
  oc project "$NS" >/dev/null
else
  NS="$(oc project -q 2>/dev/null)" || true
fi
if [[ -z "${NS:-}" ]]; then
  echo "error: no OpenShift project. Run: oc login ... && oc project <namespace> or export ORBIT_DEPLOY_NAMESPACE=<namespace>" >&2
  exit 1
fi

echo "Using namespace: $NS"

apply_yaml() {
  oc apply -n "$NS" -f "$1"
}

echo "Applying ImageStreams and BuildConfigs..."
apply_yaml "$ROOT/deploy/openshift/01-imagestreams.yaml"
apply_yaml "$ROOT/deploy/openshift/02-buildconfigs.yaml"

echo "Building orbit-backend (uploads $(basename "$ROOT")/backend as context; respects backend/.dockerignore)..."
oc start-build orbit-backend -n "$NS" --from-dir="$ROOT/backend" --follow --wait

echo "Building orbit-frontend..."
oc start-build orbit-frontend -n "$NS" --from-dir="$ROOT/frontend" --follow --wait

echo "Applying Postgres + Redis..."
apply_yaml "$ROOT/deploy/openshift/03-infra.yaml"
oc wait -n "$NS" --for=condition=available deployment/orbit-postgres --timeout=180s
oc wait -n "$NS" --for=condition=available deployment/orbit-redis --timeout=120s

SECRET_KEY_VALUE="${ORBIT_SECRET_KEY:-$(openssl rand -hex 32)}"
VAULT_KEY_VALUE="${ORBIT_VAULT_MASTER_KEY:-$(openssl rand -hex 32)}"

echo "Creating backend secret orbit-backend-config-env (replacing if present)..."
oc delete secret orbit-backend-config-env -n "$NS" --ignore-not-found
oc create secret generic orbit-backend-config-env -n "$NS" \
  --from-literal=DATABASE_URL="postgresql+asyncpg://orbit:orbit@orbit-postgres:5432/orbit" \
  --from-literal=REDIS_URL="redis://orbit-redis:6379/0" \
  --from-literal=SECRET_KEY="$SECRET_KEY_VALUE" \
  --from-literal=VAULT_MASTER_KEY="$VAULT_KEY_VALUE" \
  --from-literal=ENVIRONMENT=production \
  --from-literal=CLAUDE_PROVIDER="${CLAUDE_PROVIDER:-vertex}" \
  --from-literal=GCP_PROJECT_ID="${GCP_PROJECT_ID:-}" \
  --from-literal=GCP_REGION="${GCP_REGION:-us-east5}" \
  $( [[ -n "${ANTHROPIC_API_KEY:-}" ]] && echo --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" )

echo "Applying API + frontend..."
apply_yaml "$ROOT/deploy/openshift/04-app.yaml"

if ! oc get route orbit-web -n "$NS" &>/dev/null; then
  oc expose service orbit-frontend -n "$NS" --name=orbit-web --port=8080
fi

ROUTE_HOST="$(oc get route orbit-web -n "$NS" -o jsonpath='{.spec.host}')"
echo "Public URL: https://${ROUTE_HOST}"

echo "Setting CORS for backend to match Route..."
oc set env deployment/orbit-backend -n "$NS" "CORS_ORIGINS=https://${ROUTE_HOST}"

echo "Waiting for rollouts..."
oc rollout status deployment/orbit-backend -n "$NS" --timeout=300s
oc rollout status deployment/orbit-frontend -n "$NS" --timeout=300s

echo "Done. Open: https://${ROUTE_HOST}"
echo ""
echo "Note: Vertex AI needs GCP credentials in-cluster (e.g. Workload Identity, mounted SA JSON + GOOGLE_APPLICATION_CREDENTIALS, or switch to Anthropic: oc set env deployment/orbit-backend CLAUDE_PROVIDER=anthropic ANTHROPIC_API_KEY=... )."
