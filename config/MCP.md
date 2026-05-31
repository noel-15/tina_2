# MCP and Orca

There is **no official OrcaSlicer MCP** from the Orca project. This repo uses **[mcp-3d-printer-server](https://www.npmjs.com/package/mcp-3d-printer-server)** (npm), which can drive **Orca’s CLI** for tools like `slice_stl` and STL manipulation.

## Installed config

Project MCP: [`.cursor/mcp.json`](../.cursor/mcp.json)

After editing, **reload Cursor** (or restart) so MCP servers connect.

## Tina 2 limits

- WEEFUN Tina 2 prints from **microSD**, not OctoPrint/Klipper/Bambu MQTT.
- MCP **printer control** tools (upload, start job, temperatures) will **not** work until you add a host (OctoPrint, etc.). That is expected for SD-only printers.
- For Tina 2 + GitHub + combined plate G-code, keep using **`python scripts/tina2_prep.py prepare …`** — it uses your `config/slicer/tina2_*.json` profiles.

## Orca path

If Orca is installed elsewhere, update `SLICER_PATH` in `.cursor/mcp.json`.

## Optional: orca-mcp on GitHub

[github.com/mucahid40/orca-mcp](https://github.com/mucahid40/orca-mcp) is listed as an Orca-focused MCP; verify the repo before relying on it. The npm server above is what this project configures today.
