---
name: tina2-print-prep
description: >-
  Prepare MakersWorld STLs for WEEFUN Tina 2 — scale to bed, slice with Orca/Prusa CLI,
  publish G-code to GitHub noel-15/tina_2, optional microSD deploy. Use for Tina 2,
  MakersWorld, G-code, scaling, slicing, or tina_2 repo.
---

# Tina 2 print prep

## Before running

1. Read [config/tina2.yaml](../../config/tina2.yaml).
2. Never read, log, or commit `list.txt` or `GITHUB_TINA_PAT`.
3. MakersWorld: download **STL/CAD** to `models/inbox/` (not Bambu-only G-code).

## Commands (from repo root)

```powershell
pip install -r requirements.txt
python scripts/tina2_prep.py preview "Fidget+Finger+Massager+2000!"
python scripts/tina2_prep.py prepare "Fidget+Finger+Massager+2000!" --prefix fidget-finger-massager-2000
python scripts/tina2_prep.py prepare models/inbox/single-part.stl
```

**Folders:** `prepare` on a folder always produces **one combined** `-plate.gcode` (see `plate.exclude_by_default` in config). Use `--separate` only if you need one file per STL.

**Preview:** `preview` opens **Orca Slicer** with the same STLs that would go on the plate — use Prepare / slice preview there. GitHub only stores G-code text, not a 3D view.

## GitHub

- Remote: https://github.com/noel-15/tina_2
- Publish only under `gcode/` (prefer single `*-plate.gcode` per model kit).

## Slicer setup

See [config/slicer/README.md](../../config/slicer/README.md).
