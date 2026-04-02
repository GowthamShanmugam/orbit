# Kubernetes Clusters — Project Overview

Generated for: Gowtham Shanmugasundaram  
Project: Open Data Hub / RHOAI (opendatahub-operator, kube-auth-proxy, architecture-context)

---

## Cluster Summary

| Cluster Name | Role | Status | API Server |
|---|---|---|---|
| `gowtham-oauth-test` | **test** (read-write) | Connected | `api.p2r4t4z7a2o1m8i.c8l6.p3.openshiftapps.com:443` |
| `gowtham-oidc-context` | **context** (read-only) | Connected | `api.p2r4t4z7a2o1m8i.c8l6.p3.openshiftapps.com:443` |

> Both clusters share the same API server URL — they are the same underlying OpenShift (ROSA) cluster, exposed with two different access roles in this project.

---

## Cluster 1: `gowtham-oauth-test`

### Role & Access
- **Role:** test (read-write)
- **Capabilities:** Read, write, apply manifests, run commands, delete resources, execute Jobs

### Platform
- OpenShift (ROSA — Red Hat OpenShift Service on AWS)
- API: `https://api.p2r4t4z7a2o1m8i.c8l6.p3.openshiftapps.com:443`

### Purpose
Primary test cluster for validating changes to `kube-auth-proxy` and `opendatahub-operator`. Used to:
- Deploy the ODH operator image and validate component reconciliation
- Test BYOIDC and OAuth authentication flows via `kube-auth-proxy`
- Run E2E tests against live operator deployments

### Key Namespaces Observed

| Namespace | Description |
|---|---|
| `rhods-operator` | ODH/RHOAI operator pods (controller-manager) |
| `opendatahub` | Platform components (Dashboard, KServe, TrustyAI, etc.) |
| `redhat-ods-applications` | RHOAI application components |
| `test123` | Test namespace created during this session |
| `default` | Default Kubernetes namespace |

### Operator Image in Use
```
quay.io/gshanmug-quay/opendatahub-operator:RHOAIENG-54751
```

### Component Health (last observed)

| Deployment | Namespace | Ready | Notes |
|---|---|---|---|
| `odh-dashboard` | `redhat-ods-applications` | 2/2 | Healthy |
| `kserve-controller-manager` | `redhat-ods-applications` | 1/1 | Healthy |
| `kuberay-operator` | `redhat-ods-applications` | 1/1 | Healthy |
| `mlflow-operator-controller-manager` | `redhat-ods-applications` | 1/1 | Healthy |
| `feast-operator-controller-manager` | `redhat-ods-applications` | 1/1 | Healthy |
| `trustyai-service-operator-controller-manager` | `redhat-ods-applications` | 1/1 | Healthy |
| `odh-model-controller` | `redhat-ods-applications` | 0/1 | **Not Ready — investigate** |

### Known Issues

#### Operator RBAC Errors (observed in `rhods-operator`)
The service account `opendatahub-operator-controller-manager` has missing ClusterRole permissions:

```
clusterserviceversions.operators.coreos.com is forbidden
leases.coordination.k8s.io is forbidden
```

One of the 3 operator pods is in `CrashLoopBackOff` (194+ restarts) due to these permission gaps. The operator cannot fully reconcile until RBAC is corrected.

#### `odh-model-controller` Not Ready (0/1)
Root cause not yet diagnosed. Likely related to the RBAC issue above or a missing dependency from the incomplete operator reconciliation.

### E2E Test Status
E2E tests were attempted but could not complete due to the RBAC/CRD issues above. The `DataScienceCluster` and `DSCInitialization` CRDs were not fully registered when the tests ran.

---

## Cluster 2: `gowtham-oidc-context`

### Role & Access
- **Role:** context (read-only)
- **Capabilities:** Read resources, get logs, query events — no write operations

### Platform
- OpenShift (ROSA — same underlying cluster as `gowtham-oauth-test`)
- API: `https://api.p2r4t4z7a2o1m8i.c8l6.p3.openshiftapps.com:443`

### Purpose
Read-only reference view of the same cluster. Used to:
- Inspect running state without risk of accidental writes
- Audit component configurations, logs, and events
- Provide a safe context for architecture review and diagnostics

---

## Access Model

```
gowtham-oauth-test  (test role)
│
├── Create / Update / Delete resources     ✓
├── Apply manifests                        ✓
├── Run ephemeral Jobs (k8s_run_command)   ✓
├── Read resources & logs                  ✓
└── Same physical cluster as oidc-context ─┐
                                           │
gowtham-oidc-context  (context role)       │
│                                          │
├── Read resources & logs                  ✓
├── Query events                           ✓
├── Create / Update / Delete resources     ✗
├── Apply manifests                        ✗
└── Run commands                           ✗
```

---

## Recommended Actions

| Priority | Action | Target Cluster |
|---|---|---|
| High | Fix RBAC for `opendatahub-operator-controller-manager` SA — add missing ClusterRoles for `clusterserviceversions` and `leases` | `gowtham-oauth-test` |
| High | Diagnose `odh-model-controller` 0/1 ready — check pod logs and events | `gowtham-oauth-test` |
| Medium | Re-run E2E tests once operator RBAC and CRDs are healthy | `gowtham-oauth-test` |
| Low | Confirm `test123` namespace is cleaned up when no longer needed | `gowtham-oauth-test` |

---

## Notes

- Cluster credentials rotate periodically. If you see 401 Unauthorized errors, refresh your kubeconfig with `oc login` or via the ROSA console.
- The E2E test suite (`make e2e-test`) must be run from a machine with the Go toolchain installed. The operator image (`quay.io/gshanmug-quay/opendatahub-operator:RHOAIENG-54751`) is the operator binary, not a test runner image.
- For BYOIDC/Entra ID testing (RHOAIENG-54751), a cluster configured with `--oidc-issuer-url` pointing to Entra ID is required in addition to this cluster.
