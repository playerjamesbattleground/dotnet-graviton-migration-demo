#!/usr/bin/env bash
#
# Build the demo Jenkins image, start it, and seed the two pipelines.
#
# Run on the build host, from the extracted source tree:
#   sudo /home/ec2-user/src/CFN_Demo/jenkins/setup-jenkins.sh
#
# Idempotent: re-running rebuilds the image, recreates the container and
# re-seeds both jobs from the current Jenkinsfiles. Build history is kept,
# because it lives in the /var/jenkins_home volume rather than the container.
#
# The Jenkinsfiles in Jenkins_Config/ are the source of truth. This script
# injects them into each job's config.xml, so editing a Jenkinsfile and
# re-running is the whole update path -- there is no second copy to keep in sync.
set -euo pipefail

SRC="${SRC:-/home/ec2-user/src}"
JENKINS_HOME=/var/jenkins_home
IMAGE=gadgetsonline-demo-jenkins:latest

step() { printf '\n\033[1;32m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[1;31mFAILED: %s\033[0m\n' "$1" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "run with sudo -- this writes to $JENKINS_HOME"
[[ -d "$SRC" ]]   || fail "source tree not found at $SRC"

# --- 1. build the image -----------------------------------------------------
#
# No binfmt setup here, deliberately. The pipelines create their buildx builder
# with an explicit --platform list, which declares what the node accepts rather
# than inferring it from registered binfmt handlers. That removes a dependency
# that broke twice: binfmt registrations are lost on every reboot, and since
# Linux 5.19 they are mount-namespace aware, so a registration made inside a
# systemd service or a container never appears on the host at all.
#
# Sound because no cross-architecture code is executed: the compile stage is
# pinned to this host's architecture and the target stage only copies files.

step "1/6  Build the Jenkins image (docker CLI, AWS CLI, jq, python3, plugins)"
docker build -t "$IMAGE" -f "$SRC/CFN_Demo/jenkins/Dockerfile" "$SRC/CFN_Demo/jenkins"

# --- 2. seed the two jobs ---------------------------------------------------

step "2/6  Seed the pipelines from Jenkins_Config/"

# The XML below embeds the pipeline script, so any &, < or > in the Groovy has to
# be escaped or Jenkins will refuse to parse config.xml.
xml_escape() {
  python3 -c "import html,sys; print(html.escape(sys.stdin.read()), end='')" < "$1"
}

# $4, when given, is the OCI architecture and drives three substitutions:
#
#   @@TARGET_ARCH@@   amd64      compared against docker's own output
#   @@ARCH_SHOWN@@    x86_64     what a reader sees
#   @@CHIP@@          Intel      what a stage name says on a projector
#
# That is how one Jenkinsfile becomes two per-architecture pipelines whose STAGE
# NAMES differ -- which matters, because during a demo the stage names are the
# only thing on screen.
write_job() {
  local name="$1" jenkinsfile="$2" description="$3" arch="${4:-}"
  local dir="$JENKINS_HOME/jobs/$name"
  local script="$jenkinsfile"
  local shown chip

  [[ -f "$jenkinsfile" ]] || fail "missing $jenkinsfile"
  mkdir -p "$dir"

  if [[ -n "$arch" ]]; then
    case "$arch" in
      amd64) shown="x86_64"; chip="Intel" ;;
      arm64) shown="Arm64";  chip="Graviton" ;;
      *) fail "unknown architecture '$arch'" ;;
    esac

    script="$(mktemp)"
    sed -e "s/@@TARGET_ARCH@@/$arch/g" \
        -e "s/@@ARCH_SHOWN@@/$shown/g" \
        -e "s/@@CHIP@@/$chip/g" "$jenkinsfile" > "$script"

    # Explicit if rather than `grep && fail`: under set -e the exit status of an
    # && list is easy to get wrong, and a silently unsubstituted placeholder
    # would seed a pipeline that fails at run time instead of here.
    if grep -q '@@[A-Z_]*@@' "$script"; then
      fail "placeholder left unsubstituted in $name"
    fi
  fi

  {
    cat <<XMLHEAD
<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <description>$description</description>
  <keepDependencies>false</keepDependencies>
  <properties/>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition" plugin="workflow-cps">
    <script>
XMLHEAD
    xml_escape "$script"
    cat <<'XMLTAIL'
</script>
    <!-- Sandbox off: the script is shipped in this repository rather than
         written by a job author, and running sandboxed would otherwise require
         approving each Groovy method through the UI mid-demo. -->
    <sandbox>false</sandbox>
  </definition>
  <triggers/>
  <disabled>false</disabled>
</flow-definition>
XMLTAIL
  } > "$dir/config.xml"

  if [[ "$script" != "$jenkinsfile" ]]; then
    rm -f "$script"
  fi
  echo "  seeded $name  <- ${jenkinsfile##*/}${arch:+  ($shown / $chip)}"
}

# Build once, deploy twice, then measure. The two deploy pipelines are one file
# seeded with a different architecture, so they cannot drift apart -- and neither
# of them builds anything.
write_job "01-build-multiarch" \
  "$SRC/Jenkins_Config/Jenkinsfile.build-multiarch" \
  "CI: build ONE image that runs on both processors, and release it as :latest."

# The placeholder value is the OCI platform name, because the pipeline compares
# it against docker's own output. What the pipeline PRINTS is x86_64 / Arm64.
write_job "02-deploy-x86" \
  "$SRC/Jenkins_Config/Jenkinsfile.deploy" \
  "Deploy the image to c6i.xlarge -- x86_64, Intel Xeon 8375C." \
  "amd64"

write_job "03-deploy-arm64" \
  "$SRC/Jenkins_Config/Jenkinsfile.deploy" \
  "Deploy the SAME image to c7g.xlarge -- Arm64, AWS Graviton3." \
  "arm64"

write_job "04-load-test" \
  "$SRC/Jenkins_Config/Jenkinsfile.benchmark" \
  "Load both processors at once and publish the comparison."

# Superseded job names from earlier revisions of this script.
for OLD in 01-build-and-deploy 02-benchmark 01-intel-build-deploy \
           02-graviton-build-deploy 03-benchmark; do
  rm -rf "$JENKINS_HOME/jobs/$OLD"
done

chown -R 1000:1000 "$JENKINS_HOME/jobs"

# --- 3. restart the container ----------------------------------------------

step "3/6  Restart Jenkins on the new image"
docker rm -f jenkins >/dev/null 2>&1 || true

DOCKER_GID="$(getent group docker | cut -d: -f3)"
[[ -n "$DOCKER_GID" ]] || fail "no docker group on this host"

docker run -d --name jenkins --restart unless-stopped \
  -p 8080:8080 \
  -v "$JENKINS_HOME:/var/jenkins_home" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$SRC:/workspace" \
  -v /etc/graviton-demo.env:/etc/graviton-demo.env:ro \
  --group-add "$DOCKER_GID" \
  "$IMAGE"

# --- 4. wait for it to come up ---------------------------------------------

step "4/6  Wait for Jenkins"
for _ in $(seq 1 60); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:8080/login || echo 000)
  if [[ "$CODE" == "200" ]]; then
    echo "  Jenkins is up"
    break
  fi
  printf '.'
  sleep 5
done
[[ "$CODE" == "200" ]] || fail "Jenkins did not answer on :8080 (last code $CODE)"

# --- 5. confirm both jobs loaded -------------------------------------------

step "5/6  Confirm the pipelines loaded"
sleep 5
for JOB in 01-build-multiarch 02-deploy-x86 03-deploy-arm64 04-load-test; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://localhost:8080/job/$JOB/" || echo 000)
  if [[ "$CODE" == "200" ]]; then
    echo "  OK   $JOB"
  else
    echo "  MISS $JOB (HTTP $CODE)"
    docker logs jenkins 2>&1 | tail -20
    fail "$JOB did not load"
  fi
done

step "6/6  Confirm the builder accepts both architectures"
# Same construction the pipelines use, so this fails here rather than mid-run.
docker exec jenkins docker buildx rm verify-platforms >/dev/null 2>&1 || true
docker exec jenkins docker buildx create --name verify-platforms \
  --driver docker-container --platform linux/amd64,linux/arm64 >/dev/null 2>&1 || true
AVAILABLE=$(docker exec jenkins docker buildx inspect --bootstrap verify-platforms 2>/dev/null \
              | sed -n 's/^Platforms:[[:space:]]*//p' | head -1)
docker exec jenkins docker buildx rm verify-platforms >/dev/null 2>&1 || true

echo "  builder platforms: ${AVAILABLE:-<none reported>}"
for WANT in linux/amd64 linux/arm64; do
  case "$AVAILABLE" in
    *"$WANT"*) echo "  OK   $WANT" ;;
    *) fail "$WANT not accepted by the builder" ;;
  esac
done

step "Done"
cat <<'SUMMARY'

  01-build-multiarch   CI. One source tree, one compile, one image carrying
                       x86_64 and Arm64, released as :latest.
  02-deploy-x86        Pull that tag onto c6i.xlarge  (x86_64, Intel).
  03-deploy-arm64      Pull the SAME tag onto c7g.xlarge  (Arm64, Graviton).
                       Identical command; the host resolves its own entry.
  04-load-test         Load both at once, publish the comparison.
                       (parameters: DURATION_SECONDS, ROUNDS)

  Reach Jenkins on port 8080 of the load balancer.
SUMMARY
