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
python scripts/tina2_prep.py info models/inbox/model.stl
python scripts/tina2_prep.py prepare models/inbox/model.stl
python scripts/tina2_prep.py prepare "Fidget+Finger+Massager+2000!" --prefix fidget-finger-massager-2000
python scripts/tina2_prep.py prepare models/inbox/model.stl --fit-bed --deploy
```

**Scaling:** Finger-sized MakersWorld models are usually correct at 100% — do **not** use `--fit-bed` unless you intentionally want “as large as the bed.”

## `prepare` pipeline

convert → scale (`--fit-bed`, `--scale`, or `--target-mm`) → slice → copy to `gcode/` → **git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" + push** (unless `--no-push`) → optional `--deploy` to `sd.drive`.

## GitHub

- Remote: https://github.com/noel-15/tina_2
- Token key: `GITHUB_TINA_PAT` in `github.token_file` (default `C:/Users/bugon/.config/list.txt`).
- Only publish under `gcode/`; do not commit inbox STLs or credentials.

## Slicer setup

See [config/slicer/README.md](../../config/slicer/README.md).

## Failures

- Slicer missing: set `slicer.executable` after installing Orca.
- Push fails: verify PAT has `repo` scope and key name `GITHUB_TINA_PAT`.
- Too large: use `--fit-bed` or lower `--scale`.
