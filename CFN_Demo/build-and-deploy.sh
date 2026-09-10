#!/usr/bin/env bash
#
# Build the GadgetsOnline image for both processor architectures, verify the
# result, and deploy it to both demo hosts.
#
# Runs on the build host provisioned by CFN_Demo/graviton-demo.yaml, which wrote
# the stack's facts to /etc/graviton-demo.env. Stage boundaries are deliberate:
# each one is a pipeline step, so this can be lifted into a CI tool unchanged.
#
#   ./build-and-deploy.sh              build a tag from the git short SHA
#   ./build-and-deploy.sh v3           build an explicit tag
#   SKIP_DEPLOY=1 ./build-and-deploy.sh   build and verify only
#
set -euo pipefail

# --- configuration ----------------------------------------------------------

ENV_FILE=/etc/graviton-demo.env
if [[ -f "$ENV_FILE" ]]; then
  set -a; . "$ENV_FILE"; set +a
fi

: "${ECR_REPO:?ECR_REPO is not set. Expected $ENV_FILE, written by the CloudFormation stack.}"
: "${ECR_REGISTRY:?ECR_REGISTRY is not set.}"
: "${DEMO_REGION:?DEMO_REGION is not set.}"
: "${X86_INSTANCE_ID:?X86_INSTANCE_ID is not set.}"
: "${ARM_INSTANCE_ID:?ARM_INSTANCE_ID is not set.}"

TAG="${1:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
IMAGE="$ECR_REPO:$TAG"
PLATFORMS="linux/amd64,linux/arm64"
DOCKERFILE=Dotnet_App/GadgetsOnline/Dockerfile

step() { printf '\n\033[1;32m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[1;31mFAILED: %s\033[0m\n' "$1" >&2; exit 1; }

# --- stage 1: authenticate --------------------------------------------------

step "Stage 1/5  Authenticate to ECR"
aws ecr get-login-password --region "$DEMO_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"

# --- stage 2: build both architectures --------------------------------------

step "Stage 2/5  Build $PLATFORMS -> $IMAGE"
# One invocation, two architectures, one manifest list. The compile stage runs
# natively (see --platform=$BUILDPLATFORM in the Dockerfile), so no emulation
# layer is involved and no second build agent is required.
#
# Attestations off. BuildKit otherwise attaches a provenance and an SBOM
# manifest to the index, which ECR lists as two extra 1.3 KB untagged records
# with no platform. The index should contain exactly the two architectures
# being demonstrated and nothing else.
docker buildx build \
  --platform "$PLATFORMS" \
  --provenance=false \
  --sbom=false \
  --tag "$IMAGE" \
  --file "$DOCKERFILE" \
  --push \
  .

step "Stage 2b/5  Tag each architecture so ECR names them"
# The two child manifests are untagged by default, so the registry shows them as
# anonymous digests. Applying a tag to an existing manifest adds a name without
# creating another image record -- which `imagetools create` would, by wrapping
# the child in a fresh single-platform index.
for ARCH in amd64 arm64; do
  CHILD_DIGEST=$(docker buildx imagetools inspect "$IMAGE" --raw \
    | jq -r --arg a "$ARCH" '.manifests[] | select(.platform.architecture == $a) | .digest')

  [[ -n "$CHILD_DIGEST" && "$CHILD_DIGEST" != "null" ]] || fail "no $ARCH manifest in the index"

  CHILD_MANIFEST=$(aws ecr batch-get-image \
    --region "$DEMO_REGION" \
    --repository-name "${ECR_REPO##*/}" \
    --image-ids "imageDigest=$CHILD_DIGEST" \
    --query 'images[0].imageManifest' --output text)

  aws ecr put-image \
    --region "$DEMO_REGION" \
    --repository-name "${ECR_REPO##*/}" \
    --image-tag "$TAG-$ARCH" \
    --image-manifest "$CHILD_MANIFEST" \
    --query 'image.imageId.imageTag' --output text 2>/dev/null \
    || echo "  $TAG-$ARCH already tagged"

  echo "  $ARCH -> $TAG-$ARCH  ${CHILD_DIGEST:0:20}..."
done

# --- stage 3: verify the manifest -------------------------------------------

step "Stage 3/5  Verify the image is multi-architecture"
MANIFEST=$(docker buildx imagetools inspect "$IMAGE" --raw)
FOUND=$(echo "$MANIFEST" | jq -r '[.manifests[].platform.architecture] | sort | unique | join(",")')
echo "architectures present: $FOUND"

echo "$FOUND" | grep -q amd64 || fail "amd64 missing from the manifest"
echo "$FOUND" | grep -q arm64 || fail "arm64 missing from the manifest"
echo "PASS: one tag serves both architectures."

# Human-readable form, worth showing on screen during the demo.
docker buildx imagetools inspect "$IMAGE"

if [[ -n "${SKIP_DEPLOY:-}" ]]; then
  step "SKIP_DEPLOY set -- stopping after verification"
  exit 0
fi

# --- stage 4: deploy to both hosts ------------------------------------------

step "Stage 4/5  Deploy $TAG to both hosts via Systems Manager"
COMMAND_ID=$(aws ssm send-command \
  --region "$DEMO_REGION" \
  --instance-ids "$X86_INSTANCE_ID" "$ARM_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "Deploy GadgetsOnline $TAG" \
  --parameters "commands=['/usr/local/bin/deploy-app.sh $TAG']" \
  --query Command.CommandId --output text)

echo "command id: $COMMAND_ID"

for INSTANCE in "$X86_INSTANCE_ID" "$ARM_INSTANCE_ID"; do
  printf 'waiting for %s ' "$INSTANCE"
  for _ in $(seq 1 60); do
    STATUS=$(aws ssm get-command-invocation \
      --region "$DEMO_REGION" \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE" \
      --query Status --output text 2>/dev/null || echo Pending)
    case "$STATUS" in
      Success) echo " $STATUS"; break ;;
      Failed|Cancelled|TimedOut)
        echo " $STATUS"
        aws ssm get-command-invocation --region "$DEMO_REGION" \
          --command-id "$COMMAND_ID" --instance-id "$INSTANCE" \
          --query StandardErrorContent --output text
        fail "deploy to $INSTANCE ended as $STATUS"
        ;;
      *) printf '.'; sleep 3 ;;
    esac
  done
done

# --- stage 5: smoke test ----------------------------------------------------

step "Stage 5/5  Smoke test both endpoints"
for INSTANCE in "$X86_INSTANCE_ID" "$ARM_INSTANCE_ID"; do
  DNS=$(aws ec2 describe-instances --region "$DEMO_REGION" \
    --instance-ids "$INSTANCE" \
    --query 'Reservations[0].Instances[0].PublicDnsName' --output text)

  printf 'GET http://%s/ ' "$DNS"
  for _ in $(seq 1 20); do
    CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://$DNS/" || echo 000)
    if [[ "$CODE" == "200" ]]; then break; fi
    printf '.'
    sleep 3
  done

  [[ "$CODE" == "200" ]] || fail "$DNS returned HTTP $CODE"
  echo " HTTP 200"
  echo "  -> http://$DNS/"
done

step "Done. Tag $TAG is live on both architectures."
