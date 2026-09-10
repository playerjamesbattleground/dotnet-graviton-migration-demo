#!/usr/bin/env python3
"""Render the benchmark comparison as plain text and as a self-contained HTML page.

    render-report.py <raw.json> <x86_price> <arm_price> [--html <path>]

Text goes to stdout, so the pipeline can `tee` it into the console log and an
artefact at once. HTML is written to --html (default benchmark-report.html) and
published in the Jenkins sidebar.

Lives in its own file rather than inline in the Jenkinsfile: it would otherwise
sit inside a Groovy string inside a shell heredoc, three levels of quoting deep,
where the HTML's own braces and quotes are very easy to break. Here it can also
be run by hand against a saved raw.json.
"""

import argparse
import html
import json
import statistics
import sys

# Column swatches. Muted blue for Intel, warm orange for Graviton, so the two are
# distinguishable in print and for the most common colour-vision deficiencies.
INTEL = "#6b7fa8"
GRAV = "#e8834a"

# 730 hours: the 365-day average month AWS itself uses for monthly estimates.
HOURS_PER_MONTH = 730

# Throughput the monthly cost is quoted against. Its value cancels out of every
# percentage; it only sets the scale of the two dollar figures, and 100k puts
# them in the readable hundreds rather than fractions of a cent.
REFERENCE_RATE = 100_000


def compute(rounds, x86_price, arm_price):
    x86_runs = [r["x86"]["operationsPerSecond"] for r in rounds]
    arm_runs = [r["arm"]["operationsPerSecond"] for r in rounds]

    x86 = int(statistics.median(x86_runs))
    arm = int(statistics.median(arm_runs))

    first = rounds[0]
    return {
        "rounds": len(rounds),
        "threads": first["x86"]["threads"],
        "x86": x86,
        "arm": arm,
        "x86_price": x86_price,
        "arm_price": arm_price,
        "x86_label": f'{first["x86"]["instanceType"]} ({first["x86"]["architecture"]})',
        "arm_label": f'{first["arm"]["instanceType"]} ({first["arm"]["architecture"]})',
        "x86_type": first["x86"]["instanceType"],
        "arm_type": first["arm"]["instanceType"],
        "faster": (arm / x86 - 1) * 100,
        "cheaper": (1 - arm_price / x86_price) * 100,
        "price_perf": ((arm / arm_price) / (x86 / x86_price) - 1) * 100,
        # Monthly cost to sustain a fixed rate, which folds throughput and price
        # into one figure an audience reads without arithmetic. "Cost per billion
        # operations" was the same maths, but a billion of anything is abstract
        # and the number came out in fractions of a cent.
        #
        #   share of an instance needed = REFERENCE_RATE / throughput
        #   monthly cost = that share * hourly price * hours in a month
        #
        # Fractional instances on purpose: rounding up to whole ones would make
        # the answer depend on the reference rate chosen rather than on the
        # processors being compared.
        "reference_rate": REFERENCE_RATE,
        "x86_monthly": (REFERENCE_RATE / x86) * x86_price * HOURS_PER_MONTH,
        "arm_monthly": (REFERENCE_RATE / arm) * arm_price * HOURS_PER_MONTH,
    }


def render_text(m):
    m["work_saving"] = (1 - m["arm_monthly"] / m["x86_monthly"]) * 100
    W = 66
    out = []
    add = out.append

    add("")
    add("=" * W)
    add(" GadgetsOnline CPU benchmark")
    add(f' {m["rounds"]} round(s), median reported, {m["threads"]} vCPU each, same AZ')
    add("=" * W)
    add("")
    add(f'  {"":<24} {"Intel":>16} {"Graviton":>16}')
    add(f'  {"instance":<24} {m["x86_label"]:>16} {m["arm_label"]:>16}')
    add(f'  {"throughput (ops/sec)":<24} {m["x86"]:>16,} {m["arm"]:>16,}')
    add(f'  {"on-demand ($/hr)":<24} {m["x86_price"]:>16.4f} {m["arm_price"]:>16.4f}')
    add(f'  {"$/month @ 100k ops/s":<24} {m["x86_monthly"]:>16,.2f} {m["arm_monthly"]:>16,.2f}')
    add("")
    add("-" * W)
    add(f'  Graviton faster by                          {m["faster"]:6.1f} %')
    add(f'  Graviton cheaper by                         {m["cheaper"]:6.1f} %')
    add(f'  Same work costs                             {m["work_saving"]:6.1f} % less')
    add("-" * W)
    add("")
    add("=" * W)
    return "\n".join(out)


def render_html(m):
    """A single page sized for a projector.

    Everything is scaled for someone reading it from the back of a room: three
    figures, three measurements. Type sizes are clamped against viewport HEIGHT
    rather than fixed, because Jenkins serves a published report inside a frame
    whose height it does not disclose -- fixed sizes plus min-height:100vh and
    space-between overflowed that frame and made the sections overlap.
    """
    bar_max = max(m["x86"], m["arm"])

    def bar(value, colour):
        pct = value / bar_max * 100
        return (
            '<div class="track"><div class="fill" '
            f'style="width:{pct:.1f}%;background:{colour}"></div></div>'
        )

    def tile(label, value, win):
        tone = " win" if win else ""
        return (
            f'<div class="tile{tone}"><div class="tile-value">{value}</div>'
            f'<div class="tile-label">{html.escape(label)}</div></div>'
        )

    # Three tiles, three independent sources: throughput, the AWS price list, and
    # the two combined. Nothing here restates another tile.
    tiles = "".join([
        tile("Faster", f'{m["faster"]:.0f}%', True),
        tile("Cheaper per hour", f'{m["cheaper"]:.0f}%', False),
        tile("Lower cost, same work", f'{m["work_saving"]:.0f}%', True),
    ])

    css = """
/* Sizes scale with the viewport HEIGHT rather than assuming 1080px. Jenkins
   serves a published report inside a frame whose height it does not disclose;
   the previous fixed sizes plus min-height:100vh and space-between meant the
   content overflowed that frame and the sections overlapped.
   Natural document flow here, so nothing can be clipped by a short container. */
* { box-sizing: border-box; margin: 0; }
body {
  padding: clamp(18px, 3.4vh, 46px) clamp(20px, 3vw, 58px);
  background: #f7f7f5; color: #17171a;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

h1 { font-size: clamp(26px, 5.4vh, 58px); font-weight: 700;
     letter-spacing: -0.03em; line-height: 1.04; }
.sub { margin-top: clamp(6px, 1.2vh, 14px); font-size: clamp(13px, 2.1vh, 23px);
       color: #6f6f72; line-height: 1.35; }
.sub b { color: #17171a; font-weight: 600; }

.tiles { display: flex; gap: clamp(10px, 1.6vw, 24px);
         margin: clamp(14px, 3vh, 34px) 0 clamp(12px, 2.4vh, 28px); }
.tile { flex: 1 1 0; min-width: 0;
        padding: clamp(12px, 2.4vh, 32px) clamp(12px, 1.6vw, 32px);
        border-radius: 14px; background: #fff; border: 2px solid #e4e4df; }
.tile.win { background: #fff4ec; border-color: #eeb894; }
.tile-value { font-size: clamp(38px, 9.4vh, 104px); font-weight: 800;
              letter-spacing: -0.05em; line-height: 0.9; }
.tile.win .tile-value { color: #cf5f16; }
.tile-label { margin-top: clamp(6px, 1.4vh, 17px);
              font-size: clamp(11px, 2.1vh, 23px); color: #6f6f72; font-weight: 500; }

.rows { background: #fff; border: 2px solid #e4e4df; border-radius: 14px; }
.row { display: grid; grid-template-columns: 1fr 1.15fr 1.15fr; align-items: center;
       padding: clamp(10px, 2.2vh, 25px) clamp(14px, 1.8vw, 32px);
       border-bottom: 2px solid #f0f0ec; }
.row:first-child { border-radius: 12px 12px 0 0; }
.row:last-child { border-bottom: none; border-radius: 0 0 12px 12px; }
.row-label { font-size: clamp(11px, 2.1vh, 23px); color: #6f6f72; font-weight: 500;
             line-height: 1.3; }
.val { text-align: right; font-size: clamp(22px, 4.7vh, 50px); font-weight: 700;
       letter-spacing: -0.04em; font-variant-numeric: tabular-nums; line-height: 1.05; }
.val.accent { color: #cf5f16; }

.head { display: grid; grid-template-columns: 1fr 1.15fr 1.15fr;
        padding: clamp(8px, 1.7vh, 19px) clamp(14px, 1.8vw, 32px);
        background: #fafaf7; border-bottom: 2px solid #e4e4df; border-radius: 12px 12px 0 0; }
.head div { text-align: right; font-size: clamp(11px, 2vh, 21px); font-weight: 700; }
.head div:first-child { text-align: left; font-size: clamp(10px, 1.7vh, 18px);
                        color: #8c8c8f; font-weight: 500;
                        text-transform: uppercase; letter-spacing: 0.09em; }
.chip { display: inline-block; width: 0.62em; height: 0.62em; border-radius: 3px;
        margin-right: 0.5em; }

.track { height: clamp(8px, 2vh, 21px); background: #eeeeea; border-radius: 999px;
         margin-top: clamp(5px, 1.3vh, 14px); overflow: hidden; }
.fill { height: 100%; border-radius: 999px; }

footer { margin-top: clamp(12px, 2.6vh, 30px);
         font-size: clamp(9px, 1.6vh, 17px); color: #8c8c8f; line-height: 1.55; }
footer b { color: #6f6f72; font-weight: 600; }
"""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GadgetsOnline &mdash; Graviton vs x86</title>
<style>{css}</style></head><body>

<header>
  <h1>Same application. Two processors.</h1>
  <div class="sub">
    <b>{html.escape(m["x86_label"])}</b> versus <b>{html.escape(m["arm_label"])}</b>
    &nbsp;&middot;&nbsp; {m["threads"]} vCPU each, same availability zone
    &nbsp;&middot;&nbsp; median of {m["rounds"]} rounds
  </div>
</header>

<section class="tiles">{tiles}</section>

<section class="rows">
  <div class="head">
    <div>Measurement</div>
    <div><span class="chip" style="background:{INTEL}"></span>Intel</div>
    <div><span class="chip" style="background:{GRAV}"></span>Graviton</div>
  </div>
  <div class="row">
    <div class="row-label">Throughput<br>operations / second</div>
    <div class="val">{m["x86"]:,}{bar(m["x86"], INTEL)}</div>
    <div class="val accent">{m["arm"]:,}{bar(m["arm"], GRAV)}</div>
  </div>
  <div class="row">
    <div class="row-label">On-demand price<br>per hour</div>
    <div class="val">${m["x86_price"]:.4f}</div>
    <div class="val">${m["arm_price"]:.4f}</div>
  </div>
  <div class="row">
    <div class="row-label">Monthly cost<br>to sustain {m["reference_rate"]:,} ops/sec</div>
    <div class="val">${m["x86_monthly"]:,.0f}</div>
    <div class="val accent">${m["arm_monthly"]:,.0f}</div>
  </div>
</section>

<footer>
  <b>Workload</b> floating-point scoring, a sort and a periodic hash across every
  vCPU for a fixed window &mdash; mixed, so the result is not an artefact of one
  processor extension. Generated inside the application on each host, so neither
  the network nor the CI system is in the measurement path; both hosts start together.<br>
  <b>Costs</b> published on-demand Linux rates, {HOURS_PER_MONTH} hours per month,
  at the capacity each processor needs to hold {m["reference_rate"]:,} ops/sec.
  The reference rate cancels out of every percentage above.<br>
  <b>Names</b> architectures are as the .NET runtime reports them. <b>X64</b> is the
  64-bit x86 instruction set &mdash; AMD designed it, Intel adopted it, and this host
  is Intel. <b>Arm64</b> is the 64-bit Arm instruction set, which AWS Graviton
  implements.
</footer>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw_json")
    ap.add_argument("x86_price", type=float)
    ap.add_argument("arm_price", type=float)
    ap.add_argument("--html", default="benchmark-report.html")
    args = ap.parse_args()

    with open(args.raw_json) as fh:
        rounds = json.load(fh)

    if not rounds:
        sys.exit("no rounds recorded -- nothing to report")

    m = compute(rounds, args.x86_price, args.arm_price)

    print(render_text(m))

    with open(args.html, "w") as fh:
        fh.write(render_html(m))


if __name__ == "__main__":
    main()
