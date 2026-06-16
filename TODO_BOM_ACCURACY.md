# BOM Converter — Accuracy TODO & Test Log

Goal: maximize data-reading / data-transfer accuracy of the PDF→BOM converter
(`api/pdf_tool.py`, `api/layout_parse.py`, `api/bom_verify.py`) across the 19
sample BOM PDFs. Test thoroughly after every change (no regressions).

Test corpus (19 PDFs): the 18 in the Tool Suite root + `api/samples/sample_BOM.pdf`.
Run all: copy to container `/tmp/corpus`, then `python /tmp/audit.py`.
Regression baseline: `/tmp/orig.json` (pre-session). Last full run: **no row-count
regressions** (only ThermoFisher 16→15, intentional junk-row drop).

Legend: [x] done · [ ] todo · [~] partial · [!] needs parser rework or GPU AI

---

## DONE (shipped & regression-tested this session)
- [x] Mfg P/N = real Manufacturer P/N, not customer/house P/N (disambiguation) — fixed ThermoFisher, Jorge
- [x] Drawing-callout noise scrub (`8 10`, brackets, `(NN AWG)`, doubled-OCR); drop junk rows
- [x] Stop fabricating SMT/TH (emit only on explicit package signal)
- [x] Preserve alternate MPNs in one cell; keep real `.025"` dims in descriptions
- [x] Split glued maker+P/N cell (`HIROSE MDF6-14DS-3.5C` → `HIROSE` + `MDF6-14DS-3.5C`)
- [x] Drop stray wire-colour leader (`BK`) from a cable row's maker
- [x] Collapse wrapped/multi-line refdes & cells to one line (Jorge)
- [x] [~] Recover a Qty merged into the refdes column (safe; helps only when qty rides the refdes tail)
- [x] On-prem AI verify/repair layer built (`bom_verify.py`); OFF by default (CPU too slow; GPU-ready)

## NEEDS PARSER REWORK or GPU AI (deep coordinate-parser limits — high regression risk to fix blindly)
- [!] **Qty column dropped** when the parser MERGES `Reference Designator … Qty`
      into one column — IBML #6411 (all qty blank), IBML #7036 (mostly blank),
      Witricity 305 (blank). Root cause: `parse_columnar_coords` column-edge
      detection merges sparse adjacent columns. Proper fix = split a merged column
      whose header carries 2+ BOM keywords. Risky for the 78-/371-row files.
- [!] **Manufacturer multi-line fragmentation** — Witricity 305: long makers that
      wrap to a 2nd line get mis-attributed to the next row
      (`Samsung Electro` + `Mechanics America, Inc`, bare `Inc.` / `Co.`,
      `United Chemi-Con 18mmx25mm (DxL)`). Needs multi-line maker reassembly in
      coordinate space — exactly what the VLM verify pass handles well.
- [!] **Tread Camera Unit** — columns mis-assigned (descriptions land in Mfg P/N),
      rows 15–17 are title-block text; parser over-confident (conf 1.0).
- [!] **Elliot Electric 10-Pin Comms Cable** — harness parser captured NOTES text
      instead of parts.
- [!] **DEHN #8797** — OCR-scanned; 2 rows, header text captured as description.
- [!] **Manufacturer carries category words** — DR Wildcard:
      `SEMICONDUCTOR OPTL INFINEON`→`INFINEON`, `LINEAR VOLTAGE MONITOR TECHNOLOGY`→
      `LINEAR TECHNOLOGY`. Post-processing is ambiguous (which token is the maker);
      safer with the AI pass.
- [!] **Description run-on with next-row / PWB sub-assembly** — IBML #7036 row1,
      #6411 row7 (`…Through Hol PWB, High Current Stepper Motor Dri`).

The [!] items are why the GPU is the real unlock: the data is visually present on
the drawing but the deterministic geometry can't recover it without risking the
files that already extract cleanly. The AI verify/repair layer (`bom_verify.py`)
re-reads only the suspect cells and reconciles — turn it on with `BOM_AI_VERIFY=true`
once a 24 GB GPU is installed.

---

## PER-FILE AUDIT (19) — current accuracy
| # | File | Method | Rows | Verdict |
|---|------|--------|------|---------|
| 1 | 023-0899 Tread Camera | layout-columns | 17 | ❌ columns mis-assigned, title-block rows |
| 2 | ACX064 | harness-callouts | 8 | ✅ good (Molex + wires) |
| 3 | DEHN #8797 | ocr-scanned | 2 | ❌ OCR, header-as-row |
| 4 | DR CML Wildcard | layout-columns | 78 | ✅ excellent; minor Mfg category words |
| 5 | Electroswitch #7183 | layout-coords | 9 | ✅ good; alt MPNs kept; desc slightly truncated |
| 6 | Elliot Electric | harness-callouts | 9 | ❌ captured notes, not parts |
| 7 | IBML #6411 | layout-coords | 15 | ⚠ good; Qty merged-into-refdes (mostly lost) |
| 8 | IBML #7036 | layout-coords | 34 | ⚠ good; Qty lost; one desc run-on |
| 9 | Jorge #5518 | tables | 24 | ✅ excellent (newlines now collapsed) |
| 10 | Martek #8527 | component-matrix | 4 | ✅ good (LEDs + resistor) |
| 11 | Parata #8766 | layout-columns | 4 | ⚠ no real MPN column in source; junk PNs blanked |
| 12 | Part# 3031406 500-0153 | harness-callouts | 6 | ✅ good (Molex/Carol + materials) |
| 13 | RX Medic #7044 | tables | 4 | ✅ good (Digikey PNs) |
| 14 | Thermofisher #7550 | layout-columns | 15 | ✅ fixed this session (HIROSE split, etc.) |
| 15 | Witricity 305-001697 | layout-columns | 371 | ⚠ mostly excellent; some maker fragments; Qty blank |
| 16 | Witricity 501-000107 | (varies) | 10 | ✅ ok |
| 17 | Zoetis #8530 | (varies) | 4 | ⚠ source overlapping-glyph defects in MPN |
| 18 | Zoetis #8530L-2 | layout-coords | 31 | ⚠ all 4 pages now captured (was page 1 only=11); qty recovered; residual MPN/desc glyph-overlap from source |
| 19 | sample_BOM | (varies) | — | ✅ ok |

Summary: ~12/19 extract cleanly; ~4 have a specific recoverable gap (qty/maker
fragments); ~3 are hard drawings (OCR / mis-columned) that need the AI pass.
