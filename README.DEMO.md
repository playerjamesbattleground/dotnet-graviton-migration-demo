# Graviton demo — x86_64 vs Arm64, one image

A live demo showing that this ASP.NET 6 application moves from Intel to AWS
Graviton for the cost of **one keyword in the Dockerfile and one flag on the
build command**, and measuring what that buys.

Everything here is additive. The original EKS and Jenkins templates under
`CFN_Yaml/` and `K8s_Yaml/` are untouched and unused by this demo.

---

## What it demonstrates

1. **One image, two processors.** A single tag whose manifest lists both
   architectures. The host picks its own entry at pull time — the deploy command
   names no architecture.
2. **The change is two lines.** `--platform=$BUILDPLATFORM` in the Dockerfile,
   `--platform linux/amd64,linux/arm64` on the build. Application source, project
   file and NuGet packages are untouched.
3. **The application layer is literally the same bytes.** `dotnet publish` emits
   architecture-neutral IL, so the app layer has the same digest under both
   architectures and the registry stores it once. Only the .NET runtime layers
   below it differ. Measured, not asserted — see `04-load-test` and the
   `Verify one image, both arches` stage.
4. **What that costs and saves.** Throughput, on-demand price, and the monthly
   cost to sustain a fixed request rate on each processor.

---

## Layout

| Path | What it is |
|---|---|
| `CFN_Demo/graviton-demo.yaml` | The whole demo stack: ECR, IAM, security groups, ALB, build host, two application hosts |
| `CFN_Demo/jenkins/Dockerfile` | Jenkins image with docker CLI, AWS CLI, jq, python3 and the four plugins the pipelines need |
| `CFN_Demo/jenkins/setup-jenkins.sh` | Builds that image, seeds the four pipelines, restarts Jenkins |
| `CFN_Demo/jenkins/refresh-source.sh` | Updates the source tree the pipelines build from, without breaking the bind mount |
| `CFN_Demo/jenkins/render-report.py` | Renders the benchmark comparison as text and as a projector-sized HTML page |
| `CFN_Demo/jenkins/inspect-image.py` | Compares the layer sets of the two architectures, straight from ECR |
| `Jenkins_Config/Jenkinsfile.build-multiarch` | CI: build one image for both architectures |
| `Jenkins_Config/Jenkinsfile.deploy` | Deploy to one host. Seeded twice with a different architecture |
| `Jenkins_Config/Jenkinsfile.benchmark` | Load both hosts and publish the comparison |
| `Dotnet_App/GadgetsOnline/Services/RecommendationEngine.cs` | The measured workload |
| `Dotnet_App/GadgetsOnline/Services/Platform.cs` | Instance metadata (IMDSv2), architecture, memory |
| `doc/make-slide.py` | The one-slide architecture flow, as .pptx |

Superseded, kept only for reference: `CFN_Yaml/`, `K8s_Yaml/`,
`Jenkins_Config/Jenkinsfile`, `Jenkinsfile_x86`, `JenkinsCasC.yaml`.

---

## Prerequisites

- An AWS account with a default VPC in the target region, and credentials on the
  standard chain. This was built against `ap-southeast-1`.
- `aws` CLI v2, and the Session Manager plugin for shell access
  (`brew install --cask session-manager-plugin`).
- An S3 bucket to hand the source to the build host. Nothing else needs it.
- No Docker, no .NET SDK and no `kubectl` locally. Everything builds on the build
  host.

---

## 1. Deploy the stack

```bash
REGION=ap-southeast-1
PROFILE=your-profile

VPC=$(aws ec2 describe-vpcs --profile $PROFILE --region $REGION \
        --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)

# Two subnets in DIFFERENT availability zones: an ALB must span two. Only the
# first one holds instances, so the comparison shares an AZ.
read -r SUBNET1 SUBNET2 <<<"$(aws ec2 describe-subnets --profile $PROFILE --region $REGION \
        --filters Name=default-for-az,Values=true \
        --query 'Subnets[0:2].SubnetId' --output text)"

aws cloudformation create-stack \
  --profile $PROFILE --region $REGION \
  --stack-name gadgetsonline-graviton-demo \
  --template-body file://CFN_Demo/graviton-demo.yaml \
  --capabilities CAPABILITY_IAM \
  --parameters \
    ParameterKey=VpcId,ParameterValue=$VPC \
    ParameterKey=SubnetId,ParameterValue=$SUBNET1 \
    ParameterKey=SecondSubnetId,ParameterValue=$SUBNET2

aws cloudformation wait stack-create-complete \
  --profile $PROFILE --region $REGION --stack-name gadgetsonline-graviton-demo

aws cloudformation describe-stacks --profile $PROFILE --region $REGION \
  --stack-name gadgetsonline-graviton-demo \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
```

Takes about 5 minutes. The application hosts come up running an nginx
placeholder, so the network path can be checked before any image exists.

### What it creates

| Resource | Detail |
|---|---|
| ECR repository | `gadgetsonline-graviton-demo`, `DeletionPolicy: Retain` so a stack delete cannot destroy pushed images |
| Build host | `c7g.large`, 20 GiB, Docker + buildx + Jenkins |
| Intel host | `c6i.xlarge`, 20 GiB — Xeon 8375C, 4 vCPU |
| Graviton host | `c7g.xlarge`, 20 GiB — Graviton3, 4 vCPU |
| Load balancer | `:8081` Intel, `:8082` Graviton, `:8080` Jenkins |
| IAM | Two roles: push for the build host, pull for the application hosts, each scoped to that one repository |
| Access | Session Manager only. No inbound SSH, no key pairs |

### Exposure

`AdminCidr` defaults to **empty**, which creates **no inbound rule at all**. The
load balancer resolves but refuses every connection. That is deliberate: an open
inbound rule on a public load balancer is what detective controls look for.

To open it, set `AdminCidr` to your own address or corporate range — never
`0.0.0.0/0`:

```bash
aws cloudformation update-stack \
  --profile $PROFILE --region $REGION \
  --stack-name gadgetsonline-graviton-demo \
  --use-previous-template --capabilities CAPABILITY_IAM \
  --parameters \
    ParameterKey=AdminCidr,ParameterValue=203.0.113.4/32 \
    $(for P in VpcId SubnetId SecondSubnetId X86InstanceType ArmInstanceType \
               BuildInstanceType X86AmiId ArmAmiId; do
        printf 'ParameterKey=%s,UsePreviousValue=true ' $P; done)
```

With `AdminCidr` empty, reach the hosts over port forwarding instead — the stack
outputs the two commands ready to run.

---

## 2. Hand the source to the build host

The pipelines build from `/home/ec2-user/src`, bind-mounted into the Jenkins
container as `/workspace`. Get the source there via S3.

```bash
BUCKET=your-bucket

# COPYFILE_DISABLE stops macOS tar writing ._<name> sidecars. Extracted on Linux
# those become real files, and ._Startup.cs enters the compiler's source list.
COPYFILE_DISABLE=1 tar czf /tmp/src.tar.gz \
  --exclude='.git' --exclude='doc/.venv' --exclude='._*' --exclude='.DS_Store' \
  --exclude='*/obj' --exclude='*/bin' \
  -C . .dockerignore CFN_Demo Jenkins_Config Dotnet_App CFN_Yaml K8s_Yaml doc \
        README.md README.DEMO.md LICENSE.txt

aws s3 cp /tmp/src.tar.gz s3://$BUCKET/src.tar.gz --profile $PROFILE --region $REGION
```

Then, on the build host:

```bash
BUILD_HOST=$(aws cloudformation describe-stacks --profile $PROFILE --region $REGION \
  --stack-name gadgetsonline-graviton-demo \
  --query 'Stacks[0].Outputs[?OutputKey==`BuildHostId`].OutputValue' --output text)

URL=$(aws s3 presign s3://$BUCKET/src.tar.gz --profile $PROFILE --region $REGION --expires-in 3600)

aws ssm start-session --profile $PROFILE --region $REGION --target $BUILD_HOST
```

```bash
# inside the session
sudo -i
curl -fsSL '<the presigned URL>' -o /tmp/src.tar.gz
mkdir -p /home/ec2-user/src
tar xzf /tmp/src.tar.gz -C /home/ec2-user/src
chown -R ec2-user:ec2-user /home/ec2-user/src
```

---

## 3. Set up Jenkins

```bash
sudo bash /home/ec2-user/src/CFN_Demo/jenkins/setup-jenkins.sh
```

Builds the Jenkins image, seeds the four pipelines from `Jenkins_Config/`, and
restarts the container. Idempotent — build history survives, because it lives in
the `/var/jenkins_home` volume rather than the container.

Jenkins has no security realm. Acceptable because the only route to it is the
load balancer, whose security group admits one CIDR.

---

## 4. Run the demo

Open Jenkins on port 8080 of the load balancer, and click through in order.

### `01-build-multiarch`  ·  ~40s

| Stage | What happens |
|---|---|
| Build image for x86_64 + Arm64 | One `buildx build --platform linux/amd64,linux/arm64`. Signing in and creating the builder are folded in |
| Verify one image, both arches | Asserts the index carries exactly two architectures, then prints the layer comparison |
| Release as :latest | Names each entry `bN-amd64` / `bN-arm64`, and points `:latest` at this build |

**Talking point:** *"Compared to your existing build, you add one platform flag."*

### `02-deploy-x86` and `03-deploy-arm64`  ·  ~15s each

| Stage | What happens |
|---|---|
| Pull :latest onto Intel / Graviton | Systems Manager runs `deploy-app.sh latest` on that host |
| Confirm it received x86_64 / Arm64 | Reads what the host recorded on pull |

**Talking point:** *"Deployment does not change at all. Same command, same tag —
the platform decides which entry it takes."*

Both pipelines print the same command. Put the two logs side by side.

### `04-load-test`  ·  ~40s

Parameters: `DURATION_SECONDS` (default 8), `ROUNDS` (default 3).

Both hosts are started together, so neither gets a quieter moment. Load is
generated **inside the application** on each host, so neither the network nor
Jenkins is in the measurement path. The median of the rounds is reported.

Output lands in three places:

- **Benchmark Report** in the build's sidebar — the projector-sized HTML page
- Console log — the same figures as text
- Artifacts — `benchmark-report.html`, `benchmark-report.txt`,
  `benchmark-raw.json` (per-round raw data)

Prices come from the Price List API, falling back to committed
`ap-southeast-1` values if the build host's role lacks `pricing:GetProducts`.

---

## The application changes

| File | Change |
|---|---|
| `Services/RecommendationEngine.cs` | **New.** Saturates every vCPU for a fixed window and reports operations per second. Mixed floating point, a sort and a periodic hash, so the result is not an artefact of one processor extension. Dedicated threads rather than the thread pool, so saturating the cores cannot starve the pool serving the status polls |
| `Services/Platform.cs` | **New.** IMDSv2 metadata, architecture, and memory from `/proc/meminfo` — not `GC.GetGCMemoryInfo`, which reports the cgroup limit inside a container rather than the instance specification |
| `Controllers/RecommendationsController.cs` | **New.** `POST /Recommendations/Start?seconds=N`, `GET /Recommendations/Status` |
| `Views/Home/Index.cshtml` | A "Find My Perfect Gadget" button, using the storefront's own `.button` class |
| `Views/Shared/_Layout.cshtml` | Corner readout: architecture, instance type and id, cores and memory. Server-rendered, since none of it changes for the life of the process |
| `Startup.cs` | Registers the engine as a singleton; applies HTTPS redirection only when an HTTPS port is configured |
| `appsettings.json` | Removed a hardcoded RDS credential. The demo path defaults to local SQLite, so nothing consumed it |
| `Dockerfile` | **One keyword:** `FROM --platform=$BUILDPLATFORM ...sdk:6.0` |
| `.dockerignore` | **New.** Excludes macOS `._*` sidecars, build output, and everything not needed to compile |

Drive the benchmark by hand if you want:

```bash
curl -X POST "http://<host>/Recommendations/Start?seconds=10"
curl "http://<host>/Recommendations/Status"
```

---

## Updating code after a change

```bash
# 1. Repackage and upload (same command as step 2)
# 2. Refresh the source tree on the build host
sudo bash /home/ec2-user/src/CFN_Demo/jenkins/refresh-source.sh '<presigned URL>'
```

Use `refresh-source.sh` for an application or Jenkinsfile change. Use
`setup-jenkins.sh` when the Jenkins image, its plugins or the job definitions
change, since that rebuilds the image and re-seeds the jobs.

Changing a Razor view or any C# requires a rebuild — views are compiled into the
image, so run `01` then `02` and `03`. A change to `render-report.py` alone takes
effect on the next `04` with no rebuild, because the script is read from the
mounted tree at run time.

---

## Gotchas

Every one of these cost real time. Documented so it costs none the next time.

**macOS `tar` writes AppleDouble sidecars.** Any file with extended attributes
gets a `._<name>` companion. On Linux those extract as real files, and
`._Startup.cs` enters the compiler's source list — 21 instances of
`error CS2015: is a binary file instead of a text file` from a build that is
otherwise fine. Fixed by `.dockerignore` and `COPYFILE_DISABLE=1`.

**8 GiB root volume is not enough for the build host.** Jenkins image and home
volume, a BuildKit worker, the .NET SDK layer and a runtime layer per
architecture. It fails with `MSB3021: No space left on device` several minutes
into an apparently healthy build. The template now allocates 20 GiB.

**Do not rely on binfmt for cross-architecture builds.** Registrations are lost
on every reboot, and since Linux 5.19 they are mount-namespace aware, so one made
inside a container or a systemd service never appears on the host. The pipelines
instead **declare** the platforms on the builder:
`docker buildx create --platform linux/amd64,linux/arm64`. Sound here because no
cross-architecture code is ever executed — the compile stage is pinned to the
host's own architecture and the target stage only copies files. Add a `RUN` to
the target stage and this breaks loudly rather than silently emulating.

**A security group's description is immutable.** Editing it forces
CloudFormation to replace the group, which cycles every instance attached to it.
A change set showed it taking both application hosts down.

**EC2 rejects some characters in a security group description.** A YAML folded
block (`>`) appends a trailing newline, and an apostrophe is outside the allowed
set. Either one rolls back the whole stack update. Keep them single-line and
plain.

**Jenkins does not apply a parameter's `defaultValue` on a job's first build.**
The definitions are only registered once a run has completed, so `params.X` is
null until then. Resolve defaults in the pipeline.

**`set -u` and a bare `$1`.** Aborts on "unbound variable" before the guard below
it can print anything useful. Use `${1:-}`.

**A bind mount follows the directory's inode.** `rm -rf /home/ec2-user/src`
followed by a fresh extract leaves the container's `/workspace` pointing at the
deleted inode: Jenkins reports "no such file or directory" for a path that
plainly exists on the host. `refresh-source.sh` clears the directory's *contents*
and keeps the directory.

**Jenkins runs `sh` with `-x`.** Every command echoes and buries intentional
output. Start each `sh` block with `set +x`.

**Jenkins blocks styling in published HTML.** Workspace files are served under
`sandbox allow-scripts; default-src 'none'`, which silently strips inline CSS and
leaves a report looking like plain text. The Jenkins image sets
`-Dhudson.model.DirectoryBrowserSupport.CSP=`.

**Do not size a published report against `100vh`.** Jenkins frames it at a height
it does not disclose; fixed sizes plus `min-height:100vh` and `space-between`
overflow that frame and overlap. `render-report.py` clamps every size against
viewport height instead.

**Pre-existing, not fixed:** `_Layout.cshtml` references
`Scripts/jquery-1.4.4.min.js`, which is not in the repository — it ships jQuery
3.6.0. That 404 kills every script on the page, including the benchmark button.
The corner readout is unaffected because it is server-rendered, and the benchmark
still runs from the pipeline. Point the reference at
`Scripts/jquery-3.6.0.min.js` to make the button work.

---

## Cost

Roughly **$0.75/hour** for the three instances plus the load balancer, in
`ap-southeast-1` on-demand:

| | $/hour |
|---|---|
| `c6i.xlarge` | 0.1960 |
| `c7g.xlarge` | 0.1666 |
| `c7g.large` (build) | 0.0833 |
| Application Load Balancer | ~0.0225 + LCU |

Stop the two application hosts between rehearsals; the build host holds the
Docker layer cache, so stopping it costs a slow first build afterwards.

---

## Teardown

```bash
aws cloudformation delete-stack --profile $PROFILE --region $REGION \
  --stack-name gadgetsonline-graviton-demo
```

The ECR repository is **retained on purpose**, so a mistimed delete cannot
destroy pushed images mid-demo. Remove it separately when finished:

```bash
aws ecr delete-repository --profile $PROFILE --region $REGION \
  --repository-name gadgetsonline-graviton-demo --force
```

Also remove the S3 object used to hand over the source, and — if you ran
`gh auth login` on the build host — `gh auth logout` before the instance is
destroyed.

