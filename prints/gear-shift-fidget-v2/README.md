# Gear Shift Fidget V2

Printer: **WEEFUN Tina 2**
Bed (config): 100 x 120 x 100 mm

## G-code files

- `gear-shift-fidget-v2-plate.gcode`

## Print steps

1. Copy the `.gcode` file(s) below to the **root** of a **FAT32** microSD card.
2. Insert the card into the Tina 2 and select the file on the printer menu.
3. Use **PLA** unless a kit note says otherwise; first print: nozzle ~200 C, bed ~60 C.
4. Stay nearby for the first layer; adjust temps in Orca if needed and re-slice.

## Notes

- Source file: `Single+Color.3mf`
- MakersWorld: https://makerworld.com/en/models/1548507-gear-shift-fidget-toy-v2-print-in-place
- Print-in-place (Single Color profile). Project was repositioned onto the Tina bed (Bambu plate coordinates).
- After print: break brim/supports if any; work the shifter through all gears.

## Preview

Regenerate a preview STL with: `python scripts/tina2_prep.py preview inbox/<slug> --prefix <slug>`
