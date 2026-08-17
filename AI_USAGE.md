# AI usage

Honest note for reviewers. Heavy AI use was expected for this take-home.

## Tools used

| Tool | Where it helped |
|------|-----------------|
| **Cursor Agent (Composer)** | Scaffolding Expo + Django, spine detector, Gemini OCR client, scan pipeline, review/library APIs and UI, tests, README/catalog scripts |
| **Google Gemini** (product dependency) | Hosted VLM for reading title/author off spine crops at runtime (`gemini-2.5-flash`) |
| **LLM-assisted catalog drafting** | Seeded the messy 125-row `catalog.csv` via `scripts/generate_catalog.py` (ambiguity cases chosen deliberately, not dumped blindly) |

## What AI did *not* replace

- Architecture choices (local YOLO/OpenCV vs hosted Gemini; confidence bands; human review as product)
- Running and fixing tests (`pytest` — 33 tests at wrap-up)
- Measuring local detect latency on the committed `photos/`
- Owning tradeoffs called out in the README (Torch install failure → YOLOv4-tiny/OpenCV path)

## How to treat the code

Assume any line may be questioned in the live session. Prefer asking “why this routing / threshold / fallback?” over “did a human type every character?”
