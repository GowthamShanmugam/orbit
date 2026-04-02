#!/usr/bin/env bash
# Build backend + frontend images and push to Quay.
#
#   podman login quay.io
#   ./deploy/quay-build-push.sh
#
# Override repo: QUAY_PREFIX=quay.io/other-org ./deploy/quay-build-push.sh
# Browser URLs like https://quay.io/repository/org/... are normalized automatically.
# Optional: IMAGE_TAG=v1.0.0  CONTAINER_ENGINE=docker
# Default platform is linux/amd64 (typical for Quay → OpenShift/x86). Override: IMAGE_PLATFORM=linux/arm64
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Default Quay namespace (edit if your org on Quay changes).
DEFAULT_QUAY_PREFIX="quay.io/gshanmug-quay"
QUAY_PREFIX="${QUAY_PREFIX:-$DEFAULT_QUAY_PREFIX}"

# Image refs must be host/path:tag — not https:// and not .../repository/... (Quay UI URLs).
normalize_quay_prefix() {
  local p="${1%/}"
  p="${p#https://}"
  p="${p#http://}"
  if [[ "$p" == quay.io/repository/* ]]; then
    p="quay.io/${p#quay.io/repository/}"
  fi
  printf '%s' "$p"
}

QUAY_PREFIX="$(normalize_quay_prefix "$QUAY_PREFIX")"

ENGINE="${CONTAINER_ENGINE:-podman}"
if ! command -v "$ENGINE" &>/dev/null; then
  ENGINE=docker
fi
if ! command -v "$ENGINE" &>/dev/null; then
  echo "error: install podman or docker" >&2
  exit 1
fi

TAG="${IMAGE_TAG:-latest}"

if [[ -n "${BACKEND_IMAGE:-}" ]]; then
  BACKEND_IMG="$BACKEND_IMAGE"
elif [[ "$QUAY_PREFIX" == */orbit-backend ]]; then
  BACKEND_IMG="${QUAY_PREFIX}:${TAG}"
elif [[ "$QUAY_PREFIX" == */orbit-frontend ]]; then
  echo "error: QUAY_PREFIX ends with orbit-frontend; use org only (e.g. quay.io/gshanmug-quay) or set BACKEND_IMAGE / FRONTEND_IMAGE" >&2
  exit 1
else
  BACKEND_IMG="${QUAY_PREFIX}/orbit-backend:${TAG}"
fi

if [[ -n "${FRONTEND_IMAGE:-}" ]]; then
  FRONTEND_IMG="$FRONTEND_IMAGE"
elif [[ "$QUAY_PREFIX" == */orbit-backend ]]; then
  FRONTEND_IMG="${QUAY_PREFIX%/orbit-backend}/orbit-frontend:${TAG}"
elif [[ "$QUAY_PREFIX" == */orbit-frontend ]]; then
  FRONTEND_IMG="${QUAY_PREFIX}:${TAG}"
else
  FRONTEND_IMG="${QUAY_PREFIX}/orbit-frontend:${TAG}"
fi

IMAGE_PLATFORM="${IMAGE_PLATFORM:-linux/amd64}"

# Frontend: Vite/esbuild must run on native CPU when producing linux/amd64 images on Apple Silicon (qemu → EPIPE).
if [[ -z "${FRONTEND_BUILDPLATFORM:-}" ]]; then
  case "$(uname -m)" in
    arm64|aarch64) FRONTEND_BUILDPLATFORM=linux/arm64 ;;
    x86_64|amd64) FRONTEND_BUILDPLATFORM=linux/amd64 ;;
    *) FRONTEND_BUILDPLATFORM=linux/amd64 ;;
  esac
fi

echo "Using engine: $ENGINE"
echo "Platform (runtime images): $IMAGE_PLATFORM"
echo "Frontend build stage (native tooling): $FRONTEND_BUILDPLATFORM"
echo "Backend:  $BACKEND_IMG"
echo "Frontend: $FRONTEND_IMG"

BUILD_OPT=(--platform "$IMAGE_PLATFORM" --build-arg "ORBIT_PLATFORM=$IMAGE_PLATFORM")
"$ENGINE" build "${BUILD_OPT[@]}" -f "$ROOT/backend/Containerfile" -t "$BACKEND_IMG" "$ROOT/backend"
"$ENGINE" build \
  --platform "$IMAGE_PLATFORM" \
  --build-arg "ORBIT_PLATFORM=$IMAGE_PLATFORM" \
  --build-arg "NODE_BUILD_PLATFORM=$FRONTEND_BUILDPLATFORM" \
  -f "$ROOT/frontend/Containerfile" \
  -t "$FRONTEND_IMG" \
  "$ROOT/frontend"

"$ENGINE" push "$BACKEND_IMG"
"$ENGINE" push "$FRONTEND_IMG"

echo "Pushed: $BACKEND_IMG and $FRONTEND_IMG"
