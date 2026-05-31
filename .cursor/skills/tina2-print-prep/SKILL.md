---
name: tina2-print-prep
description: >-
  End-to-end WEEFUN Tina 2 prep for user-provided MakersWorld models — combine parts on
  one plate, self-review, Orca slice, publish G-code to GitHub noel-15/tina_2. Use when
  the user names a model, Tina 2, MakersWorld, plate G-code, or wants print prep done for them.
---

# Tina 2 autonomous print prep (agent workflow)

The user provides **preferred models** (MakersWorld link or files in `inbox/<slug>/`).
The agent runs the full pipeline; the user does not slice manually.

## Agent workflow (every model)

1. **Ingest:** User downloads **STL/CAD/3MF** into `inbox/<slug>/` (agent cannot reliably log into MakersWorld).
2. **Combine:** Run `prepare` on the folder (or single file path).
3. **Self-review:** Run `review` on the same folder; fix config/excludes if FAIL.
4. **Show user:** Report paths:
   - **Print folder:** `prints/<prefix>/` (`.gcode` + **`README.md`**)
   - **GitHub:** `https://github.com/noel-15/tina_2/tree/main/prints/<prefix>`
5. **Publish:** Always use `publish_print_folder` (via `prepare` with push enabled).

Never read or commit `GITHUB_TINA_PAT` / `list.txt`.

## Commands

```powershell
cd C:\Users\bugon\Desktop\Tina_2
python scripts/tina2_prep.py prepare inbox/my-kit --prefix my-kit
python scripts/tina2_prep.py review inbox/my-kit --prefix my-kit
python scripts/tina2_prep.py preview inbox/my-kit --prefix my-kit
```

Single STL or **3MF:** `prepare inbox/my-kit/model.3mf --prefix my-kit`

**Optional:** `preview` opens Orca; suggest [gcode.ws](https://gcode.ws/) for toolpath view.

## Limits

- Agent **cannot** truly see a 3D render; self-review is **dimensions, bed fit, file size, slice success**.
- User **visual** check: `preview` command (writes to `.cache/preview/`).

See [config/slicer/README.md](../../config/slicer/README.md).
