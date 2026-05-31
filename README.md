# Tina 2 print prep

Pipeline for **WEEFUN Tina 2**: slice with Orca (Marlin profiles in `config/slicer/`), publish ready-to-print G-code to GitHub.

## Folders

| Path | Purpose |
|------|---------|
| **`inbox/`** | Drop MakersWorld downloads here — one subfolder per model (`inbox/my-kit/`). Not committed to git. |
| **`prints/`** | Published projects: each subfolder has `.gcode` file(s) + **`README.md`** (SD card steps). This is what you copy to the microSD. |
| **`.cache/`** | Temporary work files from slicing (safe to delete). |
| **`scripts/`** | `tina2_prep.py` CLI |
| **`config/`** | `tina2.yaml`, slicer profiles, optional kit YAML under `config/kits/` |

## Setup

```powershell
cd C:\Users\bugon\Desktop\Tina_2
pip install -r requirements.txt
```

Set `GITHUB_TINA_PAT` (or token in the path configured in `config/tina2.yaml`) before publish.

## Typical workflow

```powershell
python scripts/tina2_prep.py prepare inbox/my-kit --prefix my-kit
python scripts/tina2_prep.py review inbox/my-kit --prefix my-kit
```

Single `.3mf` in a folder is supported. Output lands in `prints/my-kit/` and is pushed to [noel-15/tina_2](https://github.com/noel-15/tina_2) when push is enabled.
