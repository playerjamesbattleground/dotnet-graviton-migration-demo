"""Render the demo setup architecture diagram.

Emits demo-architecture.png into this folder, describing what
CFN_Demo/graviton-demo.yaml provisions.

Run with:  uv run python architecture.py
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import EC2, ECR
from diagrams.aws.management import Cloudformation, SystemsManager
from diagrams.aws.security import IAM
from diagrams.onprem.client import Users

GRAPH_ATTR = {
    "fontsize": "20",
    "bgcolor": "white",
    "pad": "0.6",
    "splines": "spline",
    "nodesep": "0.9",
    "ranksep": "1.6",
}

# Dashed grey for provisioning, so it reads as background rather than flow.
PROVISION = Edge(color="grey40", style="dashed")


def demo_setup() -> None:
    """Nodes are declared in flow order so graphviz ranks them left to right."""
    with Diagram(
        "Demo setup — one image, two processors",
        filename="demo-architecture",
        show=False,
        direction="LR",
        graph_attr=GRAPH_ATTR,
    ):
        # --- what provisions it all ---------------------------------------
        cfn = Cloudformation("CFN_Demo/\ngraviton-demo.yaml\none stack")

        # --- the build host -----------------------------------------------
        with Cluster("Default VPC · public subnet"):
            builder = EC2("Build host\nc7g.large\ndocker + buildx")

        # --- the registry -------------------------------------------------
        ecr = ECR("ECR\none tag,\ntwo architectures")

        # --- the two application hosts ------------------------------------
        with Cluster("Application hosts — identical image, matched vCPU"):
            x86 = EC2("c6i.xlarge\nIntel · 4 vCPU")
            arm = EC2("c7g.xlarge\nGraviton3 · 4 vCPU")

        # --- the audience -------------------------------------------------
        users = Users("Demo audience\nside-by-side\nops/sec")

        # --- supporting services, deliberately off the main flow ----------
        with Cluster("Control plane (no SSH, no key pairs)"):
            ssm = SystemsManager("Systems Manager\nRun Command")
            iam = IAM("2 IAM roles\npush / pull")

        cfn >> PROVISION >> builder
        cfn >> PROVISION >> ecr
        cfn >> PROVISION >> iam

        # The build path: one command, both architectures, no emulation.
        builder >> Edge(
            label="buildx build --platform\nlinux/amd64,linux/arm64",
            color="darkgreen",
            penwidth="2",
        ) >> ecr

        ecr >> Edge(
            label="docker pull — architecture\nselected automatically",
            color="darkgreen",
            penwidth="2",
        ) >> x86
        ecr >> Edge(color="darkgreen", penwidth="2") >> arm

        # The deploy path.
        builder >> Edge(label="send-command", color="darkorange") >> ssm
        ssm >> Edge(label="deploy-app.sh <tag>", color="darkorange") >> x86
        ssm >> Edge(color="darkorange") >> arm

        # The demo itself.
        x86 >> Edge(label="HTTP :80", color="grey30") >> users
        arm >> Edge(color="grey30") >> users


if __name__ == "__main__":
    demo_setup()
    print("wrote demo-architecture.png")
