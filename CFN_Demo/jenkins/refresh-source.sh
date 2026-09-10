#!/usr/bin/env bash
#
# Refresh the source tree the Jenkins pipelines build from.
#
# Run on the build host:
#   sudo /home/ec2-user/src/CFN_Demo/jenkins/refresh-source.sh '<presigned S3 URL>'
#
# Use this for an application or Jenkinsfile change. Use setup-jenkins.sh instead
# when the Jenkins image, its plugins, or the job definitions change, since that
# rebuilds the image and re-seeds the jobs.
#
# WHY THIS SCRIPT EXISTS
#
# The obvious refresh -- `rm -rf /home/ec2-user/src` then untar -- silently breaks
# Jenkins. A bind mount follows the INODE of the directory it was created against,
# so deleting and recreating that directory leaves the container's /workspace
# pointing at the old, now-deleted inode: the pipelines see an empty workspace and
# fail with "no such file or directory" on a path that plainly exists on the host.
#
# It went unnoticed for a while because setup-jenkins.sh recreates the container
# afterwards, which re-establishes the mount. Skip that step to save time and the
# breakage appears.
#
# This script clears the directory's CONTENTS and keeps the directory itself, so
# the inode -- and the mount -- survive. No container restart needed.
set -euo pipefail

SRC="${SRC:-/home/ec2-user/src}"
URL="${1:-}"

step() { printf '\n\033[1;32m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[1;31mFAILED: %s\033[0m\n' "$1" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "run with sudo"
[[ -n "$URL" ]]   || fail "usage: refresh-source.sh '<presigned S3 URL>'"

step "1/4  Download"
curl -fsSL "$URL" -o /tmp/src.tar.gz
echo "  $(stat -c %s /tmp/src.tar.gz) bytes"

step "2/4  Replace the contents, keeping the directory inode"
mkdir -p "$SRC"
# Dotglob so hidden entries such as .dockerignore are cleared too. The directory
# itself is never removed -- see the note at the top of this file.
find "$SRC" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
tar xzf /tmp/src.tar.gz -C "$SRC"

# macOS tar emits a ._<name> sidecar for any file carrying extended attributes;
# on Linux those become real files, and ._Startup.cs would enter the compiler's
# source list. .dockerignore also excludes them, so this is belt and braces.
find "$SRC" -name '._*' -delete 2>/dev/null || true

chown -R ec2-user:ec2-user "$SRC"

step "3/4  Confirm the host tree"
[[ -f "$SRC/Dotnet_App/GadgetsOnline/GadgetsOnline.csproj" ]] || fail "application sources missing"
[[ -f "$SRC/.dockerignore" ]] || fail ".dockerignore missing -- the build would pick up macOS sidecars"
echo "  $(find "$SRC" -type f | wc -l) files"

step "4/4  Confirm Jenkins sees the same tree"
# The check that would have caught the inode problem immediately.
if ! docker exec jenkins test -f /workspace/Dotnet_App/GadgetsOnline/GadgetsOnline.csproj; then
  echo "  Jenkins cannot see /workspace -- the bind mount is stale."
  echo "  Restarting the container to re-establish it."
  docker restart jenkins >/dev/null
  for _ in $(seq 1 24); do
    if [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:8080/login || echo 000)" == "200" ]]; then
      break
    fi
    sleep 5
  done
  docker exec jenkins test -f /workspace/Dotnet_App/GadgetsOnline/GadgetsOnline.csproj \
    || fail "Jenkins still cannot see the source tree"
fi
echo "  workspace visible in the container"

step "Done -- run 01-intel-build-deploy and 02-graviton-build-deploy"
