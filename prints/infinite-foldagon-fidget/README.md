# Infinite Foldagon Fidget

Printer: **WEEFUN Tina 2**
Bed (config): 100 x 120 x 100 mm

## G-code files

- `infinite-foldagon-fidget-plate.gcode`

## Print steps

1. Copy the `.gcode` file(s) below to the **root** of a **FAT32** microSD card.
2. Insert the card into the Tina 2 and select the file on the printer menu.
3. Use **PLA** unless a kit note says otherwise; first print: nozzle ~200 C, bed ~60 C.
4. Stay nearby for the first layer; adjust temps in Orca if needed and re-slice.

## Notes

- Source file: `6don_proj_M+-+SingleColor.3mf`
- MakersWorld: https://makerworld.com/en/models/1263152-infinite-foldagon-fidget
- Single-color plate: pre-assembled layout (3 linked segments). ~80x70 mm footprint, ~35 mm tall.
- After printing, fold along hinges per model page; no glue required for basic fidget.

## Preview

Regenerate a preview STL with: `python scripts/tina2_prep.py preview inbox/infinite-foldagon-fidget --prefix infinite-foldagon-fidget`
