#!/usr/bin/env python3
"""
Build project-overview.pptx — a real, editable 16:9 PowerPoint — with NO
third-party libraries (stdlib zipfile + hand-written OOXML only).

Why hand-written OOXML: this sandbox has no internet (can't pip install
python-pptx) and no LibreOffice, but a .pptx is just a ZIP of XML parts, which
the standard library can produce. The result opens and edits in PowerPoint,
Keynote and Google Slides.

Run:   python docs/build_pptx.py
Out:   docs/project-overview.pptx

Design (inspired by the reference CVPR deck, adapted for readability):
  - 16:9, clean near-white background, one big message per slide
  - large dark title, generous whitespace, sparse text, accent colour for key terms
  - every slide carries speaker notes (plain-language explanation + transition)

Content source of truth: this repo (README.md, docs/INVESTIGATION.md, the code)
and the SchubKI "Making Sense of Logs" brief. No invented facts.
"""
import zipfile
from xml.sax.saxutils import escape

# ----- geometry (EMUs: 914400 per inch); 16:9 = 13.333in x 7.5in -----
EMU = 914400
W = int(13.333 * EMU)
H = int(7.5 * EMU)

# ----- palette -----
INK   = "1A1A1A"   # near-black title/body
MUT   = "6E7781"   # muted grey subtitle
ACC   = "1F6FEB"   # accent blue (key terms)
GOOD  = "2DA44E"
WARN  = "BF8700"
BAD   = "CF222E"
BG    = "FBFCFD"   # near-white
PANEL = "F0F3F6"   # light card
LINE  = "D0D7DE"
FONT  = "Segoe UI"

def _rgb(c): return c

# ---------- low-level shape helpers (return <p:sp> XML) ----------
def _run(text, sz, color=INK, bold=False, italic=False):
    b = ' b="1"' if bold else ''
    i = ' i="1"' if italic else ''
    return (f'<a:r><a:rPr lang="en-US" sz="{sz}"{b}{i} dirty="0">'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f'<a:latin typeface="{FONT}"/></a:rPr>'
            f'<a:t xml:space="preserve">{escape(text)}</a:t></a:r>')

def _para(runs, align="l", bullet=False, lvl=0, space_after=600, line=None):
    al = {"l":"l","c":"ctr","r":"r"}[align]
    bu = ('<a:buFont typeface="Arial"/><a:buChar char="&#8226;"/>'
          if bullet else '<a:buNone/>')
    spc = f'<a:spcAft><a:spcPts val="{space_after}"/></a:spcAft>'
    ln = f'<a:lnSpc><a:spcPct val="{line}"/></a:lnSpc>' if line else ''
    indent = f' lvl="{lvl}"' if lvl else ''
    marL = f' marL="{(lvl+1)*274320}" indent="-274320"' if bullet else ''
    return (f'<a:p><a:pPr algn="{al}"{indent}{marL}>{ln}{spc}{bu}</a:pPr>'
            f'{"".join(runs)}</a:p>')

_sid = [1]
def _nid():
    _sid[0] += 1
    return _sid[0]

def _txbox(x, y, w, h, paras, anchor="t", wrap=True):
    an = {"t":"t","ctr":"ctr","b":"b"}[anchor]
    wr = 'wrap="square"' if wrap else 'wrap="none"'
    nid = _nid()
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{nid}" name="tx{nid}"/>'
            f'<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            f'<p:txBody><a:bodyPr {wr} anchor="{an}" lIns="0" rIns="0" tIns="0" bIns="0"/>'
            f'<a:lstStyle/>{"".join(paras)}</p:txBody></p:sp>')

def _rect(x, y, w, h, fill, line=None, rad=False):
    nid = _nid()
    geom = 'roundRect' if rad else 'rect'
    ln = (f'<a:ln w="12700"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>'
          if line else '<a:ln><a:noFill/></a:ln>')
    f = (f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>'
         if fill else '<a:noFill/>')
    av = '<a:avLst><a:gd name="adj" fmla="val 6000"/></a:avLst>' if rad else '<a:avLst/>'
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{nid}" name="r{nid}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
            f'<a:prstGeom prst="{geom}">{av}</a:prstGeom>{f}{ln}</p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>')

def _line(x, y, w, color=LINE, weight=19050):
    nid = _nid()
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{nid}" name="ln{nid}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="0"/></a:xfrm>'
            f'<a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
            f'<a:ln w="{weight}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:ln>'
            f'</p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>')

# card with a title + body lines, used for the little coloured role boxes
def _card(x, y, w, h, title, body, accent=ACC):
    bar = _rect(x, y, w, h, PANEL, line=LINE, rad=True)
    tb = _txbox(x+200000, y+150000, w-400000, h-300000, [
        _para([_run(title, 1300, accent, bold=True)], space_after=400),
        _para([_run(body, 1150, INK)], line="100000"),
    ])
    return bar + tb

MARGIN = int(0.9 * EMU)
TITLE_Y = int(0.55 * EMU)
BODY_Y = int(1.95 * EMU)

def title_block(title, accentword=None):
    """Big title + thin accent rule, reference-deck style."""
    runs = [_run(title, 3200, INK, bold=True)]
    sp = _txbox(MARGIN, TITLE_Y, W-2*MARGIN, int(1.1*EMU), [_para(runs)])
    rule = _line(MARGIN, int(1.72*EMU), int(2.2*EMU), ACC, 38100)
    return sp + rule

def footer(n, label):
    return (_line(MARGIN, H-int(0.72*EMU), W-2*MARGIN, LINE, 9525) +
            _txbox(MARGIN, H-int(0.6*EMU), W-2*MARGIN, int(0.4*EMU), [
                _para([_run(f"{label}", 900, MUT),
                       _run(f"   \u00b7   slide {n} of 9", 900, LINE)], align="l")]))

# =====================================================================
#  SLIDES — each returns (shapes_xml, notes_text)
# =====================================================================
def slide_title():
    shapes = (
        _rect(0, 0, W, int(0.22*EMU), ACC) +
        _txbox(MARGIN, int(2.4*EMU), W-2*MARGIN, int(2.0*EMU), [
            _para([_run("Log Intelligence Agent", 4400, INK, bold=True)], space_after=200),
            _para([_run("Turning millions of log lines into the right answer for the right person",
                        1600, MUT)], space_after=200),
        ]) +
        _txbox(MARGIN, int(5.1*EMU), W-2*MARGIN, int(1.3*EMU), [
            _para([_run("SchubKI National AI Hackathon 2026", 1300, INK, bold=True),
                   _run("   ·   SereneDB — \u201cMaking Sense of Logs\u201d", 1300, MUT)],
                  space_after=250),
            _para([_run("Engineer   ·   Team Lead   ·   Manager", 1300, ACC, bold=True)]),
        ])
    )
    notes = ("Hello — our project is the Log Intelligence Agent. In one line: it "
             "turns millions of raw log lines into a clear, trustworthy answer for "
             "three different people — an engineer, a team lead, and a manager. "
             "Over the next five minutes I'll show the problem, our idea, how it "
             "works, and the evidence it produces. Transition: let's start with why "
             "this is hard.")
    return shapes, notes

def slide_problem():
    shapes = (
        title_block("The problem") +
        _txbox(MARGIN, BODY_Y, int(6.6*EMU), int(4.4*EMU), [
            _para([_run("Modern systems emit ", 1500, INK),
                   _run("millions of log lines", 1500, ACC, bold=True),
                   _run(" a day.", 1500, INK)], bullet=True, space_after=500),
            _para([_run("An AI can ", 1500, INK), _run("explain", 1500, INK, italic=True),
                   _run(" a failure — but the logs ", 1500, INK),
                   _run("don\u2019t fit in a prompt.", 1500, ACC, bold=True)],
                  bullet=True, space_after=500),
            _para([_run("Three people ask about the ", 1500, INK),
                   _run("same logs", 1500, INK, bold=True),
                   _run(" but need different answers.", 1500, INK)],
                  bullet=True, space_after=500),
        ]) +
        _card(int(7.7*EMU), int(2.0*EMU), int(4.7*EMU), int(1.25*EMU),
              "Engineer", "What failed, where, and what happened right before & after?") +
        _card(int(7.7*EMU), int(3.45*EMU), int(4.7*EMU), int(1.25*EMU),
              "Team Lead", "Which problems keep coming back, and who owns them?") +
        _card(int(7.7*EMU), int(4.9*EMU), int(4.7*EMU), int(1.25*EMU),
              "Manager", "What should we fix first \u2014 and why?") +
        footer(2, "The problem")
    )
    notes = ("A busy system writes millions of log lines every day. A language "
             "model is great at explaining a failure, but you physically cannot "
             "paste millions of lines into it. And it's not one audience: the same "
             "logs are read by an engineer debugging an incident, a team lead "
             "looking for recurring issues, and a manager deciding priorities. "
             "Each needs different evidence. Transition: here's our idea for serving "
             "all three without drowning the model in data.")
    return shapes, notes

def slide_idea():
    shapes = (
        title_block("Our idea") +
        _txbox(MARGIN, int(1.9*EMU), W-2*MARGIN, int(1.05*EMU), [
            _para([_run("Don\u2019t send the logs to the AI. Give it ", 1500, INK),
                   _run("tools", 1500, ACC, bold=True),
                   _run(" that fetch just the evidence it needs.", 1500, INK)], space_after=150),
            _para([_run("A tool = a pre-written database query the AI can call "
                        "(e.g. \u201csearch logs\u201d, \u201ccount by team\u201d).",
                        1100, MUT, italic=True)]),
        ]) +
        # simple left-to-right pipeline of 4 boxes with arrows
        _pipeline(int(3.15*EMU)) +
        _txbox(MARGIN, int(5.35*EMU), W-2*MARGIN, int(1.1*EMU), [
            _para([_run("The database does the heavy lifting (search + counting); "
                        "the AI only sees a small, relevant slice and ", 1300, INK),
                   _run("explains it.", 1300, ACC, bold=True)], space_after=200),
            _para([_run("Every answer carries the exact query behind it \u2014 so every "
                        "number is checkable.", 1200, MUT)]),
        ]) +
        footer(3, "Our idea")
    )
    notes = ("Our key idea is a flip. Instead of pushing logs into the model, we "
             "give the model a small set of tools — think of each tool as a "
             "pre-written database query it can call, like 'search the logs' or "
             "'count alerts by team'. The database (SereneDB) does the heavy "
             "lifting of searching and counting; the AI only ever receives a small, "
             "relevant slice plus a summary, which it turns into a plain-language "
             "answer. And crucially, every answer carries the exact query behind it, "
             "so a reviewer can check every number. Transition: let me show how the "
             "pieces fit together.")
    return shapes, notes

def _pipeline(y):
    labels = [("Question", "from a role"), ("AI picks a tool", "no free-form SQL"),
              ("SereneDB runs it", "search / count"), ("Answer + evidence", "with the query")]
    accs = [MUT, ACC, ACC, GOOD]
    boxw = int(2.7*EMU); gap = int(0.42*EMU); x = MARGIN; h = int(1.5*EMU)
    out = ""
    for i,(t,s) in enumerate(labels):
        out += _rect(x, y, boxw, h, PANEL, line=LINE, rad=True)
        out += _txbox(x+120000, y+300000, boxw-240000, h-500000, [
            _para([_run(t, 1300, accs[i], bold=True)], align="c", space_after=300),
            _para([_run(s, 1050, MUT)], align="c")])
        if i < 3:
            ax = x + boxw + int(0.05*EMU)
            out += _txbox(ax, y, gap, h, [_para([_run("\u2192", 2000, LINE, bold=True)],
                                                align="c")], anchor="ctr")
        x += boxw + gap
    return out

def slide_how():
    shapes = (
        title_block("How it works") +
        _txbox(MARGIN, BODY_Y, int(6.7*EMU), int(4.5*EMU), [
            _para([_run("16 small tools", 1500, ACC, bold=True),
                   _run(", grouped by who asks:", 1500, INK)], space_after=450),
            _para([_run("Engineer", 1350, INK, bold=True),
                   _run(" \u2014 full-text search, nearby events, trace one request",
                        1250, INK)], bullet=True, space_after=350),
            _para([_run("Team Lead", 1350, INK, bold=True),
                   _run(" \u2014 counts per alert, per team, trends over time",
                        1250, INK)], bullet=True, space_after=350),
            _para([_run("Manager", 1350, INK, bold=True),
                   _run(" \u2014 what\u2019s widespread vs. a one-off, with owners",
                        1250, INK)], bullet=True, space_after=350),
            _para([_run("Shared", 1350, INK, bold=True),
                   _run(" \u2014 data scope, team ownership, remote data at scale",
                        1250, INK)], bullet=True, space_after=350),
        ]) +
        _card(int(7.9*EMU), int(2.0*EMU), int(4.5*EMU), int(2.0*EMU),
              "Full-text search, in plain terms",
              "Like a smart \u201cCtrl-F\u201d over 4.7 million lines that ranks the "
              "best matches first \u2014 built into SereneDB, so it is fast.", ACC) +
        _card(int(7.9*EMU), int(4.2*EMU), int(4.5*EMU), int(2.0*EMU),
              "Standard, open interface (MCP)",
              "The tools are exposed over MCP, so an assistant like Claude can "
              "discover and call them directly \u2014 no custom app needed.", GOOD) +
        footer(4, "How it works")
    )
    notes = ("Concretely, we built 16 tools, grouped by who asks. The engineer gets "
             "full-text search, 'what happened nearby in time', and the ability to "
             "trace a single request. The team lead gets counts — per alert type, "
             "per owning team, and trends over time. The manager gets a view of "
             "what's widespread versus a one-off, each routed to the team that owns "
             "it. Two plain-language notes: 'full-text search' is basically a smart "
             "Ctrl-F over 4.7 million lines that ranks the best matches first; and "
             "we expose everything over MCP, an open standard, so an assistant like "
             "Claude can call the tools directly. Transition: the best way to see "
             "the value is a real investigation — one story, three roles.")
    return shapes, notes

def slide_insight():
    # the headline analytic insight, as a visual comparison
    shapes = (
        title_block("The insight: loud \u2260 recurring") +
        _txbox(MARGIN, BODY_Y, W-2*MARGIN, int(0.9*EMU), [
            _para([_run("The noisiest alert looks like the top priority \u2014 until you "
                        "measure how it is ", 1450, INK),
                   _run("spread over time.", 1450, ACC, bold=True)])]) +
        # two comparison cards
        _rect(MARGIN, int(2.9*EMU), int(5.5*EMU), int(2.9*EMU), PANEL, line=BAD, rad=True) +
        _txbox(MARGIN+220000, int(3.1*EMU), int(5.1*EMU), int(2.6*EMU), [
            _para([_run("KERNDTLB \u2014 a BURST", 1500, BAD, bold=True)], space_after=350),
            _para([_run("152,734", 2600, INK, bold=True),
                   _run("  lines (loudest)", 1250, MUT)], space_after=250),
            _para([_run("but 99.6% fell on a SINGLE day", 1300, INK)], space_after=200),
            _para([_run("\u2192 one incident, not an ongoing problem", 1200, BAD, italic=True)]),
        ]) +
        _rect(int(6.85*EMU), int(2.9*EMU), int(5.5*EMU), int(2.9*EMU), PANEL, line=GOOD, rad=True) +
        _txbox(int(6.85*EMU)+220000, int(3.1*EMU), int(5.1*EMU), int(2.6*EMU), [
            _para([_run("KERNMC / KERNRTSP \u2014 RECURRING", 1500, GOOD, bold=True)], space_after=350),
            _para([_run("342 / 3,983", 2600, INK, bold=True),
                   _run("  lines (quieter)", 1250, MUT)], space_after=250),
            _para([_run("present on 144 / 126 separate days", 1300, INK)], space_after=200),
            _para([_run("\u2192 the real standing problems to fix", 1200, GOOD, italic=True)]),
        ]) +
        _txbox(MARGIN, int(6.0*EMU), W-2*MARGIN, int(0.7*EMU), [
            _para([_run("We rank by ", 1250, INK), _run("spread (days present)", 1250, ACC, bold=True),
                   _run(", not raw volume \u2014 so a one-day storm never hides the chronic faults.",
                        1250, INK)], align="c")]) +
        footer(5, "The insight")
    )
    notes = ("Here's the insight that makes the whole thing worth it. If you rank "
             "alerts by raw volume, KERNDTLB wins with 152,734 lines — it looks like "
             "the top priority. But measure how it's spread over time and 99.6% of "
             "it landed on a single day: it's one incident, not an ongoing problem. "
             "Meanwhile two much quieter alerts, KERNMC and KERNRTSP, show up on 144 "
             "and 126 separate days — those are the real standing faults. So we rank "
             "by spread, by how many distinct days an alert appears, not by volume. "
             "That's the kind of judgment a human analyst makes, and our tools make "
             "it automatic. Transition: now watch the engineer drill into one of "
             "those recurring faults.")
    return shapes, notes

def slide_evidence():
    shapes = (
        title_block("Evidence: one failure, traced") +
        _txbox(MARGIN, BODY_Y, W-2*MARGIN, int(0.8*EMU), [
            _para([_run("Engineer asks about ", 1400, INK),
                   _run("\u201crts panic\u201d", 1400, ACC, bold=True),
                   _run("; the agent reconstructs a ~20-second hardware cascade on one node.",
                        1400, INK)])]) +
        _rect(MARGIN, int(2.85*EMU), W-2*MARGIN, int(2.75*EMU), "0B1626", rad=True) +
        _txbox(MARGIN+260000, int(3.05*EMU), W-2*MARGIN-520000, int(2.4*EMU), [
            _code("node R27-M0-NA-C:J11-U11   (2006-01-03, UTC-8 clock shown)"),
            _code("03:24:46  KERNMC   L2 d-cache parity machine check  (bit=0x1d)"),
            _code("          \u2026 ~19 s of register dump \u2026"),
            _code("03:25:05  KERNRTSP rts panic! - stopping execution   (BM25 score 8.382)"),
            _code("03:25:06+ APPSEV   \u201cLink has been severed\u201d \u2192 I/O nodes, racks R20\u2013R27"),
        ]) +
        _txbox(MARGIN, int(5.85*EMU), W-2*MARGIN, int(0.9*EMU), [
            _para([_run("Hypothesis (not fact): a cache fault ", 1250, INK),
                   _run("likely", 1250, ACC, bold=True),
                   _run(" took down a multi-rack job \u2014 the logs show the sequence, "
                        "not proof of cause.", 1250, INK)])]) +
        footer(6, "Evidence \u00b7 engineer")
    )
    notes = ("This is a real trace from the full dataset. The engineer searches for "
             "'rts panic'. The agent finds the panic on one node and pulls what "
             "happened right around it, and a clear ~20-second story appears: first "
             "a hardware cache error, the KERNMC machine check; then about 19 "
             "seconds of the kernel dumping its state; then the rts panic itself; "
             "then, within a second, application nodes across several racks lose "
             "their link. Notice the language: we say the cache fault 'likely' "
             "caused it — the logs prove the sequence and timing, not causation, and "
             "we're careful to label that. Transition: and this works at the scale "
             "the challenge cares about.")
    return shapes, notes

def _code(text):
    return _para([_run(text, 1150, "C9D1D9")], space_after=250, line="110000")

def slide_results():
    shapes = (
        title_block("It works \u2014 and at scale") +
        _txbox(MARGIN, BODY_Y, int(6.6*EMU), int(4.3*EMU), [
            _para([_run("Full base corpus, in SereneDB:", 1400, INK, bold=True)], space_after=400),
            _para([_run("BGL  \u2014  4,747,963 log lines", 1300, INK)], bullet=True, space_after=300),
            _para([_run("OpenStack  \u2014  207,820 log lines", 1300, INK)], bullet=True, space_after=300),
            _para([_run("Both searched and aggregated; every answer cites its query",
                        1300, INK)], bullet=True, space_after=300),
            _para([_run("Real full-text match verified (BM25 score 8.382)", 1300, INK)],
                  bullet=True, space_after=300),
        ]) +
        _rect(int(7.7*EMU), int(2.0*EMU), int(4.7*EMU), int(4.1*EMU), PANEL, line=LINE, rad=True) +
        _txbox(int(7.7*EMU)+240000, int(2.25*EMU), int(4.7*EMU)-480000, int(3.7*EMU), [
            _para([_run("Optional: huge-data stretch", 1400, ACC, bold=True)], space_after=400),
            _para([_run("1,000,000,000", 2400, INK, bold=True)], space_after=150),
            _para([_run("rows of remote data queried", 1250, MUT)], space_after=400),
            _para([_run("in place \u2014 zero download", 1300, GOOD, bold=True)], space_after=350),
            _para([_run("count in ~0.1 s; group-by in ~12\u201315 s", 1200, INK)], space_after=300),
            _para([_run("Honest limit: a full-text index on 1B rows needs more memory "
                        "than we had.", 1150, MUT, italic=True)]),
        ]) +
        footer(7, "Results & scale")
    )
    notes = ("The workflow runs on the full challenge corpus inside SereneDB: 4.7 "
             "million BGL lines and about 208 thousand OpenStack lines, both "
             "searched and aggregated, with every answer citing the query behind it, "
             "and real full-text matching verified. As an optional stretch, we also "
             "pointed the same approach at a billion rows of remote data and queried "
             "it in place with zero download — a count comes back in a tenth of a "
             "second, a group-by in around twelve to fifteen seconds. And we're "
             "honest about the limit we hit: building a full-text index over a "
             "billion rows needs more memory than our machine had. Transition: so "
             "what should you take away, and where are the edges?")
    return shapes, notes

def slide_limits():
    shapes = (
        title_block("What it does \u2014 and doesn\u2019t \u2014 claim") +
        _txbox(MARGIN, BODY_Y, int(5.9*EMU), int(4.4*EMU), [
            _para([_run("Honest by design", 1500, GOOD, bold=True)], space_after=400),
            _para([_run("Counts are matching log lines, not confirmed incidents",
                        1250, INK)], bullet=True, space_after=350),
            _para([_run("Causes are hypotheses \u2014 phrased \u201clikely\u201d / "
                        "\u201cconsistent with\u201d", 1250, INK)], bullet=True, space_after=350),
            _para([_run("No invented downtime, cost, or customer impact",
                        1250, INK)], bullet=True, space_after=350),
        ]) +
        _txbox(int(6.9*EMU), BODY_Y, int(5.5*EMU), int(4.4*EMU), [
            _para([_run("Known limits (stated)", 1500, WARN, bold=True)], space_after=400),
            _para([_run("Dates are UTC; clock times in log lines are local (UTC-8)",
                        1250, INK)], bullet=True, space_after=350),
            _para([_run("OpenStack \u201cerror\u201d = error keywords, not the labelled "
                        "ground-truth anomalies", 1250, INK)], bullet=True, space_after=350),
            _para([_run("Full-text index on 1B remote rows: memory-bound",
                        1250, INK)], bullet=True, space_after=350),
        ]) +
        footer(8, "Limitations")
    )
    notes = ("We were deliberate about honesty, because that's what makes the "
             "answers trustworthy. We never treat a count of log lines as a count of "
             "confirmed incidents. Any cause is phrased as a hypothesis — 'likely', "
             "'consistent with' — never stated as fact. We never invent business "
             "impact like downtime or cost. And we state our known limits plainly: "
             "day-buckets are in UTC while the clock times printed in log lines are "
             "local; our OpenStack 'error' rate is a keyword match, not the "
             "dataset's official anomaly labels; and the billion-row full-text index "
             "is memory-bound. Transition: to wrap up.")
    return shapes, notes

def slide_conclusion():
    shapes = (
        _rect(0, 0, W, int(0.22*EMU), ACC) +
        title_block("Conclusion") +
        _txbox(MARGIN, BODY_Y, W-2*MARGIN, int(3.4*EMU), [
            _para([_run("Question \u2192 evidence \u2192 recommendation", 2200, INK, bold=True)],
                  space_after=500),
            _para([_run("Three roles, one corpus, distinct evidence \u2014 the database "
                        "proves every number, the AI explains it.", 1500, INK)],
                  space_after=450),
            _para([_run("The win isn\u2019t a bigger model; it\u2019s giving the model the "
                        "right, checkable evidence.", 1500, ACC, bold=True)]),
        ]) +
        _txbox(MARGIN, int(5.7*EMU), W-2*MARGIN, int(0.8*EMU), [
            _para([_run("Runs from a clean checkout: Docker SereneDB \u2192 loader \u2192 "
                        "agent / MCP server.  Thank you.", 1250, MUT)])]) +
        footer(9, "Conclusion")
    )
    notes = ("To conclude: the whole system is one loop — question, to evidence, to "
             "recommendation — served three ways for three roles from a single "
             "corpus, where the database proves every number and the AI explains it "
             "in plain language. The takeaway is that the win here isn't a bigger "
             "model; it's giving the model the right, checkable evidence to reason "
             "over. It runs end to end from a clean checkout. Thank you — happy to "
             "take questions.")
    return shapes, notes

SLIDES = [slide_title, slide_problem, slide_idea, slide_how, slide_insight,
          slide_evidence, slide_results, slide_limits, slide_conclusion]

# =====================================================================
#  OOXML packaging
# =====================================================================
def slide_xml(shapes):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="'+BG+'"/></a:solidFill>'
            '<a:effectLst/></p:bgPr></p:bg>'
            '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            + shapes +
            '</p:spTree></p:cSld><p:clrMapOvr><a:overrideClrMapping '
            'bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
            'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" '
            'hlink="hlink" folHlink="folHlink"/></p:clrMapOvr></p:sld>')

def notes_xml(text):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
            '</p:nvGrpSpPr><p:grpSpPr/>'
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes"/><p:cNvSpPr><a:spLocks noGrp="1"/>'
            '</p:cNvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/>'
            '<p:txBody><a:bodyPr/><a:lstStyle/>'
            f'<a:p><a:r><a:rPr lang="en-US" dirty="0"/><a:t>{escape(text)}</a:t></a:r></a:p>'
            '</p:txBody></p:sp></p:spTree></p:cSld></p:notes>')

def build(path):
    n = len(SLIDES)
    z = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED)

    # [Content_Types].xml
    overrides = [
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>',
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>',
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>',
        '<Override PartName="/ppt/notesMasters/notesMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"/>',
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    for i in range(1, n+1):
        overrides.append(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
        overrides.append(f'<Override PartName="/ppt/notesSlides/notesSlide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>')
    z.writestr('[Content_Types].xml',
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        + "".join(overrides) + '</Types>')

    # root rels
    z.writestr('_rels/.rels',
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        '</Relationships>')

    # docProps
    z.writestr('docProps/core.xml',
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>Log Intelligence Agent \u2014 Project Overview</dc:title>'
        '<dc:creator>Log Intelligence Agent team</dc:creator></cp:coreProperties>')
    z.writestr('docProps/app.xml',
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        f'<Slides>{n}</Slides><Application>build_pptx.py</Application></Properties>')

    # presentation.xml + rels (slide size 16:9)
    sldIds = "".join(f'<p:sldId id="{255+i}" r:id="rId{i}"/>' for i in range(1, n+1))
    z.writestr('ppt/presentation.xml',
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" saveSubsetFonts="1">'
        f'<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId{n+1}"/></p:sldMasterIdLst>'
        f'<p:notesMasterIdLst><p:notesMasterId r:id="rId{n+2}"/></p:notesMasterIdLst>'
        f'<p:sldIdLst>{sldIds}</p:sldIdLst>'
        f'<p:sldSz cx="{W}" cy="{H}" type="screen16x9"/>'
        f'<p:notesSz cx="{H}" cy="{W}"/></p:presentation>')
    presRels = ["".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>'
        for i in range(1, n+1))]
    presRels.append(f'<Relationship Id="rId{n+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>')
    presRels.append(f'<Relationship Id="rId{n+2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster" Target="notesMasters/notesMaster1.xml"/>')
    presRels.append(f'<Relationship Id="rId{n+3}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>')
    z.writestr('ppt/_rels/presentation.xml.rels',
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(presRels) + '</Relationships>')

    # theme (minimal but complete clrScheme/fontScheme/fmtScheme)
    z.writestr('ppt/theme/theme1.xml', THEME)

    # slide master + layout
    z.writestr('ppt/slideMasters/slideMaster1.xml', SLIDE_MASTER)
    z.writestr('ppt/slideMasters/_rels/slideMaster1.xml.rels',
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
        '</Relationships>')
    z.writestr('ppt/slideLayouts/slideLayout1.xml', SLIDE_LAYOUT)
    z.writestr('ppt/slideLayouts/_rels/slideLayout1.xml.rels',
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
        '</Relationships>')

    # notes master
    z.writestr('ppt/notesMasters/notesMaster1.xml', NOTES_MASTER)
    z.writestr('ppt/notesMasters/_rels/notesMaster1.xml.rels',
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
        '</Relationships>')

    # slides + notes
    for i, fn in enumerate(SLIDES, start=1):
        _sid[0] = 1
        shapes, notes = fn()
        z.writestr(f'ppt/slides/slide{i}.xml', slide_xml(shapes))
        z.writestr(f'ppt/slides/_rels/slide{i}.xml.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            f'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide{i}.xml"/>'
            '</Relationships>')
        z.writestr(f'ppt/notesSlides/notesSlide{i}.xml', notes_xml(notes))
        z.writestr(f'ppt/notesSlides/_rels/notesSlide{i}.xml.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="../slides/slide{i}.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster" Target="../notesMasters/notesMaster1.xml"/>'
            '</Relationships>')
    z.close()
    return n

# ---- static OOXML parts (theme / master / layout / notes master) ----
THEME = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
 '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="LIA">'
 '<a:themeElements><a:clrScheme name="LIA">'
 '<a:dk1><a:srgbClr val="1A1A1A"/></a:dk1><a:lt1><a:srgbClr val="FBFCFD"/></a:lt1>'
 '<a:dk2><a:srgbClr val="6E7781"/></a:dk2><a:lt2><a:srgbClr val="F0F3F6"/></a:lt2>'
 '<a:accent1><a:srgbClr val="1F6FEB"/></a:accent1><a:accent2><a:srgbClr val="2DA44E"/></a:accent2>'
 '<a:accent3><a:srgbClr val="BF8700"/></a:accent3><a:accent4><a:srgbClr val="CF222E"/></a:accent4>'
 '<a:accent5><a:srgbClr val="8250DF"/></a:accent5><a:accent6><a:srgbClr val="0969DA"/></a:accent6>'
 '<a:hlink><a:srgbClr val="1F6FEB"/></a:hlink><a:folHlink><a:srgbClr val="8250DF"/></a:folHlink>'
 '</a:clrScheme>'
 '<a:fontScheme name="LIA"><a:majorFont><a:latin typeface="Segoe UI"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
 '<a:minorFont><a:latin typeface="Segoe UI"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
 '<a:fmtScheme name="LIA">'
 '<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
 '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
 '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
 '<a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
 '<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
 '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle>'
 '<a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
 '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
 '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>'
 '</a:fmtScheme></a:themeElements></a:theme>')

SLIDE_MASTER = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
 '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
 '<p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FBFCFD"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
 '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
 '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
 '</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
 'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" '
 'hlink="hlink" folHlink="folHlink"/>'
 '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
 '<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="3200"><a:solidFill><a:srgbClr val="1A1A1A"/></a:solidFill>'
 '<a:latin typeface="Segoe UI"/></a:defRPr></a:lvl1pPr></p:titleStyle>'
 '<p:bodyStyle><a:lvl1pPr><a:defRPr sz="1500"><a:solidFill><a:srgbClr val="1A1A1A"/></a:solidFill>'
 '<a:latin typeface="Segoe UI"/></a:defRPr></a:lvl1pPr></p:bodyStyle>'
 '<p:otherStyle/></p:txStyles></p:sldMaster>')

SLIDE_LAYOUT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
 '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">'
 '<p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
 '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
 '</p:spTree></p:cSld><p:clrMapOvr><a:overrideClrMapping bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" '
 'accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
 'accent6="accent6" hlink="hlink" folHlink="folHlink"/></p:clrMapOvr></p:sldLayout>')

NOTES_MASTER = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
 '<p:notesMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
 '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
 '<p:grpSpPr/></p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" '
 'accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
 'accent6="accent6" hlink="hlink" folHlink="folHlink"/></p:notesMaster>')

if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(__file__), "project-overview.pptx")
    count = build(out)
    size = os.path.getsize(out)
    print(f"[ok] wrote {out} ({count} slides, {size:,} bytes)")
