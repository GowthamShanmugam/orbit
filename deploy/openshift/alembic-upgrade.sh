#!/usr/bin/env bash
# Apply database migrations inside a running orbit-backend pod.
# Run when you see errors like: column projects.runtime_overrides does not exist,
# column projects.visibility does not exist, or startup logs: "run migrations first".
#
#   oc login ... && oc project <namespace>
#   ./deploy/openshift/alembic-upgrade.sh
#
# Or: ORBIT_DEPLOY_NAMESPACE=orbit ./deploy/openshift/alembic-upgrade.sh
#
# If exec fails with "container not found", set the API container name, e.g.:
#   ORBIT_BACKEND_CONTAINER=backend ./deploy/openshift/alembic-upgrade.sh
set -euo pipefail

if [[ -n "${ORBIT_DEPLOY_NAMESPACE:-}" ]]; then
  NS="$ORBIT_DEPLOY_NAMESPACE"
  oc project "$NS" >/dev/null
else
  NS="$(oc project -q 2>/dev/null)" || true
fi
if [[ -z "${NS:-}" ]]; then
  echo "error: no OpenShift project. Run: oc login ... && oc project <namespace>" >&2
  exit 1
fi

echo "Running: alembic upgrade head (namespace: $NS)"
EXEC=(oc exec -n "$NS" "deployment/orbit-backend")
if [[ -n "${ORBIT_BACKEND_CONTAINER:-}" ]]; then
  EXEC+=(-c "$ORBIT_BACKEND_CONTAINER")
fi
EXEC+=(-- sh -c 'cd /app && alembic upgrade head')
"${EXEC[@]}"
echo "Done."
