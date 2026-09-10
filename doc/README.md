# Demo documentation

`demo-architecture.png` — what `CFN_Demo/graviton-demo.yaml` provisions for the
x86-vs-Graviton comparison.

## Regenerating

```bash
cd doc
uv run python architecture.py
```

Requires `graphviz` on the host (`brew install graphviz`). Python dependencies
are pinned in `uv.lock`, which is committed so the diagram reproduces exactly.

## Reading the diagram

Flow runs left to right:

1. **CloudFormation** provisions everything (dashed grey — background detail)
2. **Build host** runs one `buildx build --platform linux/amd64,linux/arm64` (green)
3. **ECR** holds one tag containing both architectures
4. **Two application hosts** pull that same tag; Docker selects the matching
   architecture automatically
5. **Audience** hits both over HTTP and compares ops/sec side by side

Orange is the deploy path — Systems Manager Run Command invokes
`deploy-app.sh <tag>` on both hosts. No SSH and no key pairs anywhere in the
stack.

## Known simplification

The build host and the two application hosts share one subnet. The diagram
draws them in separate boxes because the renderer ranks nodes by flow position,
not by network topology. There is one subnet, not two.
