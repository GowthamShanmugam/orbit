#!/usr/bin/env bash
# Restart Orbit API + web pods so they pull fresh images (imagePullPolicy: Always).
#
#   oc login ... && oc project <namespace>
#   ./deploy/openshift/rollout.sh
#
# Or: ORBIT_DEPLOY_NAMESPACE=orbit ./deploy/openshift/rollout.sh
set -euo pipefail

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

echo "Namespace: $NS"

# Ensure APP_BASE_URL is set in orbit-config so OAuth callbacks point to the cluster.
ROUTE_HOST="$(oc get route orbit -n "$NS" -o jsonpath='{.spec.host}' 2>/dev/null)" || true
if [[ -n "$ROUTE_HOST" ]]; then
  APP_BASE_URL="https://${ROUTE_HOST}/api"
  echo "Setting APP_BASE_URL=${APP_BASE_URL}"
  oc set env deployment/orbit-backend -n "$NS" APP_BASE_URL="$APP_BASE_URL"
else
  echo "warning: could not detect route host; APP_BASE_URL not updated" >&2
fi

echo "Restarting deployments orbit-backend, orbit-frontend..."

oc rollout restart deployment/orbit-backend -n "$NS"
oc rollout restart deployment/orbit-frontend -n "$NS"

echo "Waiting for rollouts..."
oc rollout status deployment/orbit-backend -n "$NS" --timeout=300s
oc rollout status deployment/orbit-frontend -n "$NS" --timeout=300s

echo "Done."
