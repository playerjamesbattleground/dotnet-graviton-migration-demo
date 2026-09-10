#!/usr/bin/env python3
"""Build the one-slide architecture flow for a non-technical audience.

    uv run python make-slide.py

Produces two files from one set of coordinates:

    graviton-flow-v1.pptx   the deliverable, editable in PowerPoint
    graviton-flow-v1.html   a preview, screenshot-able without PowerPoint

Both are generated from the LAYOUT and PALETTE constants below, so the preview
cannot drift from the slide. That matters because there is no LibreOffice on this
machine to render the pptx directly.

Style is lifted from Risks_Slide_Only.pptx: Arial throughout, AWS Squid Ink and
Orange, a full-height accent bar on the left, 0.60in margins, and the same
kicker/title/subtitle stack.
"""

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).resolve().parent
ICONS = Path(
    "/Users/jjiangl/workspace/ws_amazon/sa2026/"
    "Icon-package_07312026.5846e92413caa21490223536cc97f1269e44fa92"
)

ARCH = ICONS / "Architecture-Service-Icons_07312026"
RES = ICONS / "Resource-Icons_07312026"

ICON = {
    "source": RES / "Res_General-Icons/Res_48_Light/Res_Source-Code_48_Light.png",
    "image": ARCH / "Arch_Containers/64/Arch_Amazon-Elastic-Container-Registry_64.png",
    "compute": ARCH / "Arch_Compute/64/Arch_Amazon-EC2_64.png",
    "cost": ARCH / "Arch_Cloud-Financial-Management/64/Arch_AWS-Cost-Explorer_64.png",
}

# --- palette, read out of the template slide --------------------------------
INK = "232F3E"      # AWS Squid Ink -- headings and primary text
ORANGE = "FF9900"   # AWS Orange -- the Graviton lane and every win
PANEL = "F5F7FA"    # node fill
BORDER = "E5E7EB"   # node stroke
BODY = "555555"     # body copy
MUTED = "888888"    # kicker, footnotes
BLUE = "0073BB"     # AWS link blue -- the Intel lane
WHITE = "FFFFFF"

# --- layout, in inches ------------------------------------------------------
L = {
    "slide_w": 13.333,
    "slide_h": 7.5,
    "bar_w": 0.18,
    "margin": 0.60,
    "kicker_y": 0.42,
    "title_y": 0.72,
    "subtitle_y": 1.42,
    # Three node columns. A build step was folded into the image column: for this
    # audience "the code becomes two images" is one idea, not two.
    "col_x": [0.85, 4.55, 8.25],
    "node_w": 2.45,
    "node_h": 1.15,
    # Two lanes; the shared source sits on the centre line between them.
    "lane_y": [2.45, 4.35],
    "source_y": 3.40,
    "badge": (3.42, 3.46, 1.05, 0.42),
    "result_x": 11.05,
    "footer_y": 6.62,
}

TITLE = "One codebase. Two processors."
SUBTITLE = "Two lines of configuration decide which chip runs it — nothing else changes"
KICKER = "GADGETSONLINE  ·  AWS GRAVITON BUSINESS CASE"
FOOTER = (
    "Measured on this application: 4 vCPU each, same availability zone, median of 3 rounds. "
    "Prices are published on-demand Linux rates."
)

LANES = [
    {
        "colour": BLUE,
        "image": ("Container image", "built for x86_64"),
        "compute": ("Amazon EC2  ·  c6i.xlarge", "Intel Xeon, 4 vCPU"),
    },
    {
        "colour": ORANGE,
        "image": ("Container image", "built for arm64"),
        "compute": ("Amazon EC2  ·  c7g.xlarge", "AWS Graviton3, 4 vCPU"),
    },
]

RESULTS = [("30%", "FASTER"), ("35%", "LOWER COST")]


def rgb(h):
    return RGBColor.from_string(h)


# ---------------------------------------------------------------------------
# PowerPoint
# ---------------------------------------------------------------------------

def text_box(slide, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
             spacing=None):
    """runs: list of (text, size_pt, bold, colour_hex, space_before_pt)."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0

    for i, (text, size, bold, colour, before) in enumerate(runs):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        if before:
            para.space_before = Pt(before)
        run = para.add_run()
        run.text = text
        run.font.name = "Arial"
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = rgb(colour)
        if spacing:
            # Letter spacing is not in python-pptx's API; set it on the run's rPr.
            run.font._rPr.set("spc", str(int(spacing * 100)))
    return box


def rounded(slide, x, y, w, h, fill, line=None, radius=0.06):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h)
    )
    shape.adjustments[0] = radius
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    if line:
        shape.line.color.rgb = rgb(line)
        shape.line.width = Pt(1)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    shape.text_frame.text = ""
    return shape


def rect(slide, x, y, w, h, fill):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def arrow(slide, x1, y1, x2, y2, colour):
    """A thin connector with an arrow head, drawn as a rotated rectangle would be
    fragile, so this uses a straight connector with a triangle at the end."""
    from pptx.enum.shapes import MSO_CONNECTOR

    conn = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2)
    )
    conn.line.color.rgb = rgb(colour)
    conn.line.width = Pt(1.75)
    # Arrow head. python-pptx has no property for it, so set the line element.
    ln = conn.line._get_or_add_ln()
    from pptx.oxml.ns import qn
    from lxml import etree

    tail = etree.SubElement(ln, qn("a:tailEnd"))
    tail.set("type", "triangle")
    tail.set("w", "med")
    tail.set("len", "med")
    return conn


def node(slide, x, y, lane_colour, icon_path, heading, sub):
    """A flow node: panel, lane-colour chip on the left edge, icon, two text lines."""
    rounded(slide, x, y, L["node_w"], L["node_h"], PANEL, BORDER)
    # The 0.08in chip is the template's own idiom for marking a row.
    rect(slide, x, y + 0.10, 0.08, L["node_h"] - 0.20, lane_colour)

    slide.shapes.add_picture(
        str(icon_path), Inches(x + 0.26), Inches(y + (L["node_h"] - 0.52) / 2),
        Inches(0.52), Inches(0.52),
    )
    text_box(
        slide, x + 0.92, y + 0.30, L["node_w"] - 1.05, 0.60,
        [
            (heading, 11.5, True, INK, 0),
            (sub, 9.5, False, BODY, 2),
        ],
    )


def build_pptx(path):
    prs = Presentation()
    prs.slide_width = Inches(L["slide_w"])
    prs.slide_height = Inches(L["slide_h"])
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

    # Full-height accent bar, as on the template slide.
    rect(slide, 0, 0, L["bar_w"], L["slide_h"], ORANGE)

    text_box(slide, L["margin"], L["kicker_y"], 11.0, 0.30,
             [(KICKER, 10, True, MUTED, 0)], spacing=1.2)
    text_box(slide, L["margin"] - 0.02, L["title_y"], 12.20, 0.70,
             [(TITLE, 26, True, INK, 0)])
    text_box(slide, L["margin"], L["subtitle_y"], 12.20, 0.35,
             [(SUBTITLE, 13.5, False, BODY, 0)])

    cx = L["col_x"]
    nw, nh = L["node_w"], L["node_h"]

    # Column 1: one source tree, on the centre line.
    node(slide, cx[0], L["source_y"], INK, ICON["source"],
         "Application source", "one repository, one commit")

    # Columns 2 and 3, one row per lane.
    for lane, spec in zip(L["lane_y"], LANES):
        node(slide, cx[1], lane, spec["colour"], ICON["image"], *spec["image"])
        node(slide, cx[2], lane, spec["colour"], ICON["compute"], *spec["compute"])

        # image -> compute
        arrow(slide, cx[1] + nw, lane + nh / 2, cx[2], lane + nh / 2, spec["colour"])
        # source -> image, angled out of the shared source node
        arrow(slide, cx[0] + nw, L["source_y"] + nh / 2, cx[1], lane + nh / 2,
              spec["colour"])

    # The point of the whole slide, sat on the fork.
    bx, by, bw, bh = L["badge"]
    rounded(slide, bx, by, bw, bh, ORANGE, radius=0.5)
    text_box(slide, bx, by + 0.06, bw, bh,
             [("2 lines", 11, True, WHITE, 0), ("changed", 8.5, True, WHITE, 0)],
             align=PP_ALIGN.CENTER)

    # Results, on the Graviton lane only.
    rx = L["result_x"]
    rounded(slide, rx, L["lane_y"][1] - 0.06, L["slide_w"] - L["margin"] - rx,
            nh + 0.12, "FFF4EC", ORANGE)
    slide.shapes.add_picture(
        str(ICON["cost"]), Inches(rx + 0.18), Inches(L["lane_y"][1] + 0.30),
        Inches(0.46), Inches(0.46),
    )
    for i, (value, label) in enumerate(RESULTS):
        text_box(
            slide, rx + 0.75 + i * 0.82, L["lane_y"][1] + 0.16, 0.80, 0.85,
            [(value, 26, True, ORANGE, 0), (label, 7.5, True, BODY, 1)],
            align=PP_ALIGN.LEFT,
        )

    text_box(slide, L["margin"], L["footer_y"], 12.13, 0.50,
             [(FOOTER, 9.5, False, MUTED, 0)])

    prs.save(str(path))
    return path


# ---------------------------------------------------------------------------
# HTML preview, from the same constants
# ---------------------------------------------------------------------------

PX = 96  # 1in at 96dpi


def build_html(path):
    def p(v):
        return f"{v * PX:.1f}px"

    cx, nw, nh = L["col_x"], L["node_w"], L["node_h"]

    def node_html(x, y, colour, icon, heading, sub):
        return f"""
<div class="node" style="left:{p(x)};top:{p(y)};width:{p(nw)};height:{p(nh)}">
  <span class="chip" style="background:#{colour}"></span>
  <img src="file://{icon}" class="ico">
  <div class="ntext"><b>{heading}</b><span>{sub}</span></div>
</div>"""

    nodes = node_html(cx[0], L["source_y"], INK, ICON["source"],
                      "Application source", "one repository, one commit")
    arrows = ""
    for lane, spec in zip(L["lane_y"], LANES):
        nodes += node_html(cx[1], lane, spec["colour"], ICON["image"], *spec["image"])
        nodes += node_html(cx[2], lane, spec["colour"], ICON["compute"], *spec["compute"])
        arrows += (
            f'<line x1="{(cx[1]+nw)*PX}" y1="{(lane+nh/2)*PX}" '
            f'x2="{cx[2]*PX}" y2="{(lane+nh/2)*PX}" stroke="#{spec["colour"]}"/>'
            f'<line x1="{(cx[0]+nw)*PX}" y1="{(L["source_y"]+nh/2)*PX}" '
            f'x2="{cx[1]*PX}" y2="{(lane+nh/2)*PX}" stroke="#{spec["colour"]}"/>'
        )

    bx, by, bw, bh = L["badge"]
    rx = L["result_x"]
    rw = L["slide_w"] - L["margin"] - rx

    results = "".join(
        f'<div class="stat" style="left:{p(rx+0.75+i*0.82)};top:{p(L["lane_y"][1]+0.16)}">'
        f'<b>{v}</b><span>{lbl}</span></div>'
        for i, (v, lbl) in enumerate(RESULTS)
    )

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; box-sizing:border-box; }}
body {{ width:{p(L["slide_w"])}; height:{p(L["slide_h"])}; position:relative;
        background:#fff; font-family:Arial, Helvetica, sans-serif; overflow:hidden; }}
.bar {{ position:absolute; left:0; top:0; width:{p(L["bar_w"])};
        height:{p(L["slide_h"])}; background:#{ORANGE}; }}
.kicker {{ position:absolute; left:{p(L["margin"])}; top:{p(L["kicker_y"])};
           font-size:13.3px; font-weight:700; color:#{MUTED}; letter-spacing:1.2px; }}
.title {{ position:absolute; left:{p(L["margin"]-0.02)}; top:{p(L["title_y"])};
          font-size:34.6px; font-weight:700; color:#{INK}; }}
.subtitle {{ position:absolute; left:{p(L["margin"])}; top:{p(L["subtitle_y"])};
             font-size:18px; color:#{BODY}; }}
svg {{ position:absolute; left:0; top:0; width:100%; height:100%; }}
svg line {{ stroke-width:2.3; marker-end:url(#a); }}
.node {{ position:absolute; background:#{PANEL}; border:1px solid #{BORDER};
         border-radius:7px; display:flex; align-items:center; }}
.chip {{ position:absolute; left:0; top:9px; bottom:9px; width:5px;
         border-radius:2px 0 0 2px; }}
.ico {{ margin-left:25px; width:50px; height:50px; }}
.ntext {{ margin-left:14px; display:flex; flex-direction:column; }}
.ntext b {{ font-size:15.3px; color:#{INK}; }}
.ntext span {{ font-size:12.6px; color:#{BODY}; margin-top:3px; }}
.badge {{ position:absolute; left:{p(bx)}; top:{p(by)}; width:{p(bw)}; height:{p(bh)};
          background:#{ORANGE}; border-radius:21px; color:#fff; text-align:center;
          display:flex; flex-direction:column; justify-content:center; }}
.badge b {{ font-size:14.6px; }}
.badge span {{ font-size:11.3px; font-weight:700; }}
.results {{ position:absolute; left:{p(rx)}; top:{p(L["lane_y"][1]-0.06)};
            width:{p(rw)}; height:{p(nh+0.12)}; background:#FFF4EC;
            border:1px solid #{ORANGE}; border-radius:7px; }}
.results img {{ position:absolute; left:17px; top:29px; width:44px; height:44px; }}
.stat {{ position:absolute; display:flex; flex-direction:column; }}
.stat b {{ font-size:34.6px; font-weight:700; color:#{ORANGE}; line-height:1; }}
.stat span {{ font-size:10px; font-weight:700; color:#{BODY}; margin-top:3px; }}
.footer {{ position:absolute; left:{p(L["margin"])}; top:{p(L["footer_y"])};
           width:{p(12.13)}; font-size:12.6px; color:#{MUTED}; }}
</style></head><body>
<div class="bar"></div>
<div class="kicker">{KICKER}</div>
<div class="title">{TITLE}</div>
<div class="subtitle">{SUBTITLE}</div>
<svg><defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5"
  markerHeight="5" orient="auto-start-reverse">
  <path d="M0,1 L9,5 L0,9 z" fill="context-stroke"/></marker></defs>{arrows}</svg>
{nodes}
<div class="badge"><b>2 lines</b><span>changed</span></div>
<div class="results"><img src="file://{ICON["cost"]}"></div>
{results}
<div class="footer">{FOOTER}</div>
</body></html>"""

    path.write_text(html)
    return path


if __name__ == "__main__":
    missing = [k for k, v in ICON.items() if not v.exists()]
    if missing:
        raise SystemExit(f"missing icons: {missing}")

    print("pptx:", build_pptx(HERE / "graviton-flow-v1.pptx"))
    print("html:", build_html(HERE / "graviton-flow-v1.html"))
