# Fidget Finger Massager 2000

Printer: **WEEFUN Tina 2**
Bed (config): 100 x 120 x 100 mm

## G-code files

- `fidget-finger-massager-2000-ring-plate.gcode`
- `fidget-finger-massager-2000-rods-plate.gcode`
- `fidget-finger-massager-2000-rollers-plate.gcode`

## Print steps

1. Copy the `.gcode` file(s) below to the **root** of a **FAT32** microSD card.
2. Insert the card into the Tina 2 and select the file on the printer menu.
3. Use **PLA** unless a kit note says otherwise; first print: nozzle ~200 C, bed ~60 C.
4. Stay nearby for the first layer; adjust temps in Orca if needed and re-slice.

## Notes

- Assembly: Press rod into roller, then into ring; CA glue on ring side.
- **ring**: Print flat, holes facing up
- **ring** includes `ring.stl` x1
- **rods**: Long axis horizontal on bed
- **rods** includes `rod.stl` x9
- **rollers**: Print vertical (strong axis)
- **rollers** includes `roller_bumps.stl` x9

## Preview

Regenerate a preview STL with: `python scripts/tina2_prep.py preview inbox/<slug> --prefix <slug>`
