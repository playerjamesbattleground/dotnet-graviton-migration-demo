#!/usr/bin/env python3
"""Show what the two architectures of a multi-architecture image actually share.

    inspect-image.py <repository-name> <tag> [--region R] [--profile P]

Reads the image index and both child manifests straight from ECR and compares
their layer sets. The point it makes is measurable rather than asserted: the
application layer has the SAME digest under both architectures, so the registry
stores it once, and only the .NET runtime layers beneath it differ.

That is the whole claim of the demo, stated in bytes.
"""

import argparse
import json
import subprocess
import sys

INDEX_TYPES = [
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
]
MANIFEST_TYPES = [
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
]

# What a reader expects to see, against the OCI platform names the registry uses.
SHOWN = {"amd64": "x86_64", "arm64": "Arm64"}
CHIP = {"amd64": "Intel", "arm64": "Graviton"}


def mib(n):
    return n / 1048576


class Ecr:
    def __init__(self, repository, region, profile=None):
        self.repository = repository
        self.region = region
        # Unused on the build host, where the instance role supplies credentials;
        # needed to run this by hand from a laptop.
        self.profile = profile

    def manifest(self, image_id, media_types):
        result = subprocess.run(
            ["aws", "ecr", "batch-get-image",
             *(["--profile", self.profile] if self.profile else []),
             "--region", self.region,
             "--repository-name", self.repository,
             "--image-ids", image_id,
             "--accepted-media-types", *media_types,
             "--query", "images[0].imageManifest",
             "--output", "text"],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            sys.exit(f"could not read {image_id}: {result.stderr.strip()}")
        return json.loads(result.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repository")
    ap.add_argument("tag")
    ap.add_argument("--region", default="ap-southeast-1")
    ap.add_argument("--profile", default=None)
    args = ap.parse_args()

    ecr = Ecr(args.repository, args.region, args.profile)

    index = ecr.manifest(f"imageTag={args.tag}", INDEX_TYPES)
    children = {
        e["platform"]["architecture"]: e["digest"]
        for e in index.get("manifests", [])
        if e.get("platform", {}).get("architecture") in SHOWN
    }

    if len(children) != 2:
        sys.exit(f"expected 2 architectures in :{args.tag}, found {len(children)}")

    layers = {}
    print(f"  tag              {args.tag}")
    print(f"  index type       {index.get('mediaType')}")
    print()
    print("  The tag resolves to an INDEX, which points at one manifest per")
    print("  architecture. Two manifests, not two images pushed separately.")
    print()

    for arch in sorted(children):
        man = ecr.manifest(f"imageDigest={children[arch]}", MANIFEST_TYPES)
        layers[arch] = [(l["digest"], l["size"]) for l in man["layers"]]
        total = sum(s for _, s in layers[arch])
        print(f"    {SHOWN[arch]:<7} ({CHIP[arch]:<8})  "
              f"{len(layers[arch])} layers  {mib(total):6.1f} MB  "
              f"{children[arch][:23]}...")

    a, b = sorted(layers)
    set_a = {d for d, _ in layers[a]}
    set_b = {d for d, _ in layers[b]}
    shared = set_a & set_b
    size = {d: s for arch in layers for d, s in layers[arch]}

    def total(digests):
        return mib(sum(size[d] for d in digests))

    print()
    print("  Layer by layer, bottom to top:")
    print()
    print(f"    {'#':>2}  {SHOWN[a]:>12}   {SHOWN[b]:>12}   same blob?")
    for i in range(max(len(layers[a]), len(layers[b]))):
        la = layers[a][i] if i < len(layers[a]) else None
        lb = layers[b][i] if i < len(layers[b]) else None
        same = la and lb and la[0] == lb[0]
        print(f"    {i + 1:>2}  {mib(la[1]) if la else 0:9.2f} MB   "
              f"{mib(lb[1]) if lb else 0:9.2f} MB   "
              f"{'YES -- one blob' if same else 'no'}")

    print()
    print(f"    shared by both   {len(shared):>2} layers  {total(shared):6.1f} MB"
          "   <- the application")
    print(f"    only {SHOWN[a]:<11} {len(set_a - set_b):>2} layers  {total(set_a - set_b):6.1f} MB"
          "   <- .NET runtime + OS")
    print(f"    only {SHOWN[b]:<11} {len(set_b - set_a):>2} layers  {total(set_b - set_a):6.1f} MB"
          "   <- .NET runtime + OS")
    print()
    print(f"    stored in the registry   {total(set_a | set_b):6.1f} MB")
    print(f"    two images added up      {total(set_a) + total(set_b):6.1f} MB")
    print(f"    deduplicated             {total(set_a) + total(set_b) - total(set_a | set_b):6.1f} MB")
    print()
    print("  The application layer carries the SAME digest under both")
    print("  architectures, because dotnet publish emitted architecture-neutral")
    print("  IL -- byte-identical output, so identical digest, so the registry")
    print("  keeps one copy. Only the runtime beneath it is built per processor.")


if __name__ == "__main__":
    main()
