# Orca Slicer profile for WEEFUN Tina 2

1. Install [Orca Slicer](https://github.com/SoftFever/OrcaSlicer/releases) on Windows.
2. **Printer setup:** Add a custom FFF printer:
   - Bed: 100 x 120 x 100 mm (confirm on your manual)
   - Nozzle: 0.4 mm
   - G-code flavor: Marlin (if prints fail, try other flavors in advanced settings)
3. **Filament:** Generic PLA — start 200 C nozzle, 60 C bed; tune after first print.
4. **Export settings for CLI:** In Orca, export or note paths to your machine / process / filament JSON files.
5. Edit `config/tina2.yaml`:
   - `slicer.executable` — usually `C:/Program Files/OrcaSlicer/orca-slicer.exe`
   - `slicer.settings` — list of JSON paths, e.g.:
     ```yaml
     settings:
       - "C:/Users/you/AppData/Roaming/OrcaSlicer/system/..."
     ```
6. Test slice from GUI once, then:
   ```powershell
   python scripts/tina2_prep.py slice .cache/work/your-model.stl
   ```

Wiibuilder/WEEFUN app can still be used manually; this project uses Orca for scripted G-code.
