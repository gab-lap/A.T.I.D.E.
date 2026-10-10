#!/bin/bash
# Runs the A.T.I.D.E. evaluation as a Nebius Serverless AI job. DRAFT, never run.
#
# Default is a DRY RUN: it only prints what it would do. Set EXECUTE=1 to actually do it.
# Run from the repo root (the folder with the Dockerfile and your .env).
#
# Required environment:
#   GH_USER            GitHub user that owns the package (gab-lap)
#   GH_PAT             GitHub token with write:packages (read from the environment, never typed on the CLI)
#   NEBIUS_PROJECT_ID  Nebius project ID (see `cat ~/.nebius/config.yaml`)
#   PRESET             CPU preset for the platform, from: nebius compute platform list --parent-id $NEBIUS_PROJECT_ID
# Optional:
#   PLATFORM (default cpu-e2; docs list cpu-e2 for eu-north1, cpu-d3 appears in other regions)
#   SKIP_PUSH=1 (image already pushed)   SKIP_SECRET=1 (secret already exists)   SECRET_NAME (default atide-eval-keys)
#   SUBNET_ID (needed only if the project has several subnets)   RUNS (default 30)   TAG (default latest)
#
# Secrets: API keys are read from your local .env and stored in a Nebius SecretStash (MysteryBox) secret;
# the job gets them through --env-secret, so no key is ever passed on a command line.

set -euo pipefail

: "${GH_USER:?set GH_USER}"
: "${GH_PAT:?set GH_PAT}"
: "${NEBIUS_PROJECT_ID:?set NEBIUS_PROJECT_ID}"
: "${PRESET:?set PRESET (nebius compute platform list --parent-id \$NEBIUS_PROJECT_ID)}"
PLATFORM=${PLATFORM:-cpu-e2}
RUNS=${RUNS:-30}
TAG=${TAG:-latest}
IMAGE_LOCAL=atide-demo:${TAG}
IMAGE_REMOTE=ghcr.io/${GH_USER}/atide-agent:${TAG}
SECRET_NAME=${SECRET_NAME:-atide-eval-keys}
JOB_NAME=atide-eval-$(date +%m%d-%H%M)
EXECUTE=${EXECUTE:-0}

run() {
  echo "+ $*"
  if [ "$EXECUTE" = "1" ]; then "$@"; fi
}

[ -f .env ] || { echo "no .env here: run from the repo root"; exit 1; }

echo "== 1. build the image =="
run docker build -t "$IMAGE_LOCAL" .

echo "== 2. HARD GATE: the image must not contain .env =="
if docker image inspect "$IMAGE_LOCAL" >/dev/null 2>&1; then
  if docker run --rm --entrypoint ls "$IMAGE_LOCAL" -A /ws/src/A.T.I.D.E. | grep -qx '.env'; then
    echo "ABORT: .env is inside the image. Fix .dockerignore, rebuild, do not push."; exit 1
  fi
  echo "ok: no .env in the image"
else
  echo "(image not built yet in dry-run mode, the gate runs for real when EXECUTE=1)"
fi

if [ "${SKIP_PUSH:-0}" != "1" ]; then
echo "== 3. push to GHCR =="
if [ "$EXECUTE" = "1" ]; then
  echo "$GH_PAT" | docker login ghcr.io -u "$GH_USER" --password-stdin
else
  echo "+ docker login ghcr.io -u $GH_USER --password-stdin   (GH_PAT from the environment)"
fi
run docker tag "$IMAGE_LOCAL" "$IMAGE_REMOTE"
run docker push "$IMAGE_REMOTE"
echo "NOTE: in GitHub -> Packages -> atide-agent -> Package settings, set visibility to Public"
echo "      (a public image needs no registry credentials in the job)."
if [ "$EXECUTE" = "1" ]; then read -r -p "Package is public? [y/N] " ans; [ "$ans" = "y" ] || exit 1; fi
else
  echo "== 3. push skipped (SKIP_PUSH=1) =="
fi

echo "== 4. store the keys from .env in SecretStash =="
# Build the JSON payload from .env without printing any value.
PAYLOAD=$(python3 - <<'PY'
import json
items = []
for line in open(".env"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    items.append({"key": k.strip(), "string_value": v.strip().strip('"').strip("'")})
print(json.dumps(items))
PY
)
KEYS=$(python3 - <<'PY'
import re
print(" ".join(m.group(1) for m in (re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", l) for l in open(".env")) if m))
PY
)
echo "keys that will be stored: $KEYS"
if [ "${SKIP_SECRET:-0}" = "1" ]; then
  echo "secret creation skipped (SKIP_SECRET=1), reusing secret $SECRET_NAME"
elif [ "$EXECUTE" = "1" ]; then
  nebius mysterybox secret create --parent-id "$NEBIUS_PROJECT_ID" --name "$SECRET_NAME" \
    --secret-version-payload "$PAYLOAD"
else
  echo "+ nebius mysterybox secret create --parent-id $NEBIUS_PROJECT_ID --name $SECRET_NAME --secret-version-payload <hidden>"
fi

ENV_SECRET_ARGS=""
for k in $KEYS; do ENV_SECRET_ARGS="${ENV_SECRET_ARGS:+$ENV_SECRET_ARGS,}$k=$SECRET_NAME"; done

echo "== 5. create the job =="
SUBNET_ARG=()
[ -n "${SUBNET_ID:-}" ] && SUBNET_ARG=(--subnet-id "$SUBNET_ID")
run nebius ai job create \
  --parent-id "$NEBIUS_PROJECT_ID" \
  --name "$JOB_NAME" \
  --image "$IMAGE_REMOTE" \
  --container-command bash \
  --args "/ws/src/A.T.I.D.E./docker/eval.sh" \
  --env "RUNS=$RUNS" \
  --env-secret "$ENV_SECRET_ARGS" \
  --platform "$PLATFORM" \
  --preset "$PRESET" \
  --timeout 1h \
  "${SUBNET_ARG[@]}"

echo "== 6. follow the logs =="
if [ "$EXECUTE" = "1" ]; then
  JOB_ID=$(nebius ai job get-by-name --name "$JOB_NAME" --format jsonpath='{.metadata.id}')
  echo "job id: $JOB_ID"
  nebius ai job logs "$JOB_ID" --follow | tee "eval_job.log"
  echo "saved eval_job.log (check it for secrets before committing it)"
else
  echo "+ nebius ai job get-by-name --name $JOB_NAME --format jsonpath='{.metadata.id}'"
  echo "+ nebius ai job logs <job_ID> --follow | tee eval_job.log"
fi

echo "done (dry run: $([ "$EXECUTE" = "1" ] && echo no || echo yes))"
