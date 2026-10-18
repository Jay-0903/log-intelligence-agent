# Project Overview — slide-by-slide outline

**Deliverable:** `docs/project-overview.pptx` (editable, 16:9, 9 slides, speaker
notes on every slide).
**Build script:** `docs/build_pptx.py` (regenerates the .pptx; no third-party
libraries — stdlib only).

Audience: hackathon jury (assume they know the *challenge* deeply, but **not**
what we specifically built). Target talk length: ≤ 5 minutes (~30–35 s/slide).
Design is inspired by the reference CVPR deck's visual style (clean near-white
background, large dark titles, one message per slide, diagrams over paragraphs),
**not** its content.

Every figure on the slides is drawn from this repo (`README.md`,
`docs/INVESTIGATION.md`, the code) — no invented facts.

| # | Slide | One main message | Visual |
|---|-------|------------------|--------|
| 1 | **Title** | We turn millions of log lines into the right answer for three roles | Accent band, role line |
| 2 | **The problem** | Same logs, three audiences — and the logs don't fit in a prompt | 3 role cards |
| 3 | **Our idea** | Don't send logs to the AI; give it tools that fetch just the evidence | 4-box pipeline w/ arrows |
| 4 | **How it works** | 16 small tools grouped by role; plain-language terms explained | 2 explainer cards (full-text, MCP) |
| 5 | **The insight** | Loud ≠ recurring: rank by spread over time, not raw volume | Red "burst" vs green "recurring" compare |
| 6 | **Evidence** | One real failure traced in ~20 s: cache error → panic → link loss | Monospace log-cascade panel |
| 7 | **Results & scale** | Full corpus works; optional 1B-row remote query, zero download | Figures + stretch card |
| 8 | **Limitations** | Honest by design: counts ≠ incidents, causes are hypotheses | Two columns: honest / known limits |
| 9 | **Conclusion** | The win isn't a bigger model — it's the right, checkable evidence | Big takeaway line |

## Plain-language terms, introduced on first use
- **Tool** (slide 3): a pre-written database query the AI can call.
- **Full-text search** (slide 4): a smart "Ctrl-F" over millions of lines that
  ranks the best matches first.
- **MCP** (slide 4): an open standard that lets an assistant like Claude
  discover and call our tools directly.
- **Spread / days present** (slide 5): on how many separate days an alert
  appears — our measure of "recurring" vs. a one-day "burst".
- **BM25 score** (slide 6): a relevance score for a full-text match (higher = a
  better textual match), not a confidence in the root cause.

## Key numbers (all from the repo, verified against the live database)
- Corpus: **BGL 4,747,963** lines, **OpenStack 207,820** lines.
- KERNDTLB **152,734** lines, **99.6%** on one day → a burst.
- KERNMC present **144** days, KERNRTSP **126** days → the recurring faults.
- Engineer trace: node **R27-M0-NA-C:J11-U11**, BM25 score **8.382**.
- Optional stretch: **1,000,000,000** rows queried in place, zero download.

## How to render / export
- Open `project-overview.pptx` directly in **PowerPoint, Keynote, or Google
  Slides** — it is a standard OOXML file.
- To export a PDF: open it and *File → Export/Download → PDF*, or run
  `soffice --headless --convert-to pdf docs/project-overview.pptx` on a machine
  that has LibreOffice.

> **Environment note:** the deck was generated and validated in a sandbox with
> **no PowerPoint, LibreOffice, or browser renderer and no internet**. The .pptx
> is verified structurally (valid OOXML ZIP, well-formed XML in all 49 parts) and
> with a layout linter (no shapes out of the 16:9 canvas, no overlapping text
> boxes). It could **not** be rendered to page images here, so please do a quick
> visual pass on first open. `docs/presentation.html` mirrors the same content as
> a browser-renderable fallback.
