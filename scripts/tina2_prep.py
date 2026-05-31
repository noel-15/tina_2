#!/usr/bin/env python3
"""Prepare MakersWorld STLs for WEEFUN Tina 2: scale, slice, publish gcode, optional SD deploy."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import trimesh
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "tina2.yaml"


def load_config(path: Path | None = None) -> dict:
    cfg_path = path or DEFAULT_CONFIG
    with cfg_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_path(cfg: dict, key: str) -> Path:
    return (ROOT / cfg["paths"][key]).resolve()


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-").lower()
    return s or "model"


def load_mesh(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(path, force="mesh")
    if isinstance(loaded, trimesh.Scene):
        meshes = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not meshes:
            raise SystemExit(f"No mesh geometry in {path}")
        loaded = trimesh.util.concatenate(meshes)
    if not isinstance(loaded, trimesh.Trimesh):
        raise SystemExit(f"Unsupported mesh type from {path}")
    return loaded


def mesh_info(path: Path) -> None:
    mesh = load_mesh(path)
    b = mesh.bounds
    ext = b[1] - b[0]
    print(f"file: {path}")
    print(f"bounds_mm: min={b[0].tolist()} max={b[1].tolist()}")
    print(f"size_mm: x={ext[0]:.3f} y={ext[1]:.3f} z={ext[2]:.3f}")


def scale_mesh(mesh: trimesh.Trimesh, factor: float) -> trimesh.Trimesh:
    if factor <= 0:
        raise SystemExit("Scale factor must be positive")
    out = mesh.copy()
    out.apply_scale(factor)
    return out


def fit_factor(mesh: trimesh.Trimesh, cfg: dict) -> float:
    p = cfg["printer"]
    margin = float(p.get("fit_margin", 0.95))
    ext = mesh.bounds[1] - mesh.bounds[0]
    sx = (p["bed_x_mm"] * margin) / ext[0] if ext[0] > 0 else 1.0
    sy = (p["bed_y_mm"] * margin) / ext[1] if ext[1] > 0 else 1.0
    sz = (p["bed_z_mm"] * margin) / ext[2] if ext[2] > 0 else 1.0
    return min(sx, sy, sz)


def target_factor(mesh: trimesh.Trimesh, target_mm: float) -> float:
    ext = mesh.bounds[1] - mesh.bounds[0]
    longest = float(max(ext))
    if longest <= 0:
        raise SystemExit("Cannot scale mesh with zero extent")
    return target_mm / longest


def write_stl(mesh: trimesh.Trimesh, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)


def convert_3mf_via_orca(cfg: dict, src: Path, dest: Path) -> Path:
    slicer = cfg["slicer"]
    exe = Path(slicer["executable"])
    if not exe.is_file():
        raise SystemExit(f"Slicer not found for 3MF conversion: {exe}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    with tempfile.TemporaryDirectory(prefix="tina2-3mf-") as tmp:
        out_dir = Path(tmp)
        cmd = [str(exe), str(src.resolve()), "--export-stl", str(dest.resolve()), "--outputdir", str(out_dir)]
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        if dest.is_file():
            return dest
        candidates = sorted(out_dir.glob("*.stl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            shutil.copy2(candidates[0], dest)
            return dest
        if proc.returncode != 0:
            raise SystemExit(f"3MF to STL conversion failed ({proc.returncode})")
    raise SystemExit(f"No STL produced from 3MF: {src}")


def convert_to_stl(src: Path, dest: Path, cfg: dict | None = None) -> Path:
    if src.suffix.lower() == ".stl":
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return dest
    if src.suffix.lower() == ".3mf":
        return convert_3mf_via_orca(cfg or load_config(), src, dest)
    mesh = load_mesh(src)
    write_stl(mesh, dest)
    return dest


def default_orca_settings(cfg: dict) -> list[Path]:
    slicer = cfg["slicer"]
    settings = slicer.get("settings") or []
    if settings:
        return [(ROOT / p).resolve() if not Path(p).is_absolute() else Path(p) for p in settings]
    return [
        ROOT / "config/slicer/tina2_machine.json",
        ROOT / "config/slicer/tina2_process.json",
        ROOT / "config/slicer/tina2_pla.json",
    ]


def run_slice(
    cfg: dict,
    stl_paths: Path | list[Path],
    out_dir: Path,
    gcode_name: str | None = None,
) -> Path:
    paths = [stl_paths] if isinstance(stl_paths, Path) else list(stl_paths)
    if not paths:
        raise SystemExit("No STL paths to slice")
    out_dir.mkdir(parents=True, exist_ok=True)
    slicer = cfg["slicer"]
    exe = Path(slicer["executable"])
    if not exe.is_file():
        raise SystemExit(
            f"Slicer not found: {exe}\nInstall Orca Slicer and set slicer.executable in config/tina2.yaml"
        )
    stype = slicer.get("type", "orca").lower()
    final_name = gcode_name or (
        f"{paths[0].stem}.gcode" if len(paths) == 1 else f"{slugify(paths[0].parent.name)}-plate.gcode"
    )
    gcode_path = out_dir / final_name
    for old in out_dir.glob("plate_*.gcode"):
        old.unlink(missing_ok=True)
    if gcode_path.is_file():
        gcode_path.unlink()

    cmd: list[str] = [str(exe)]
    if stype == "orca":
        datadir = slicer.get("datadir") or str(
            Path.home() / "AppData/Roaming/OrcaSlicer/system"
        )
        cmd.extend(["--datadir", str(Path(datadir))])
        setting_paths = default_orca_settings(cfg)
        missing = [p for p in setting_paths if not p.is_file()]
        if missing:
            raise SystemExit("Missing slicer profile files:\n" + "\n".join(str(p) for p in missing))
        joined = ";".join(str(p).replace("\\", "/") for p in setting_paths)
        cmd.extend(["--load-settings", joined, "--slice", "0", "--outputdir", str(out_dir)])
        cmd.extend(str(p) for p in paths)
    elif stype == "prusa":
        if len(paths) != 1:
            raise SystemExit("Prusa CLI prepare-plate is not implemented; use Orca or slice one STL at a time.")
        settings = slicer.get("settings") or []
        for s in settings:
            cmd.extend(["--load", str(s)])
        cmd.extend(["--export-gcode", str(paths[0]), "--output", str(gcode_path)])
    else:
        raise SystemExit(f"Unknown slicer.type: {stype}")

    extra = slicer.get("extra_args") or []
    if extra:
        cmd.extend(str(x) for x in extra)

    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    produced: Path | None = None
    if gcode_path.is_file():
        produced = gcode_path
    else:
        plates = sorted(out_dir.glob("plate_*.gcode"), key=lambda p: p.stat().st_mtime, reverse=True)
        if plates:
            produced = plates[0]
            if produced.name != gcode_path.name:
                produced.rename(gcode_path)
                produced = gcode_path
        else:
            candidates = sorted(out_dir.glob("*.gcode"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                produced = candidates[0]
                if produced.name != gcode_path.name:
                    produced.rename(gcode_path)
                    produced = gcode_path

    if produced is None:
        if proc.returncode != 0:
            raise SystemExit(f"Slicer failed with code {proc.returncode}")
        raise SystemExit("Slicer finished but no .gcode was produced")
    if proc.returncode not in (0, None) and proc.returncode != 0:
        print(f"Warning: slicer exit code {proc.returncode} but G-code was produced", file=sys.stderr)
    return produced


def read_pat(cfg: dict) -> str:
    key = cfg["github"].get("token_key", "GITHUB_TINA_PAT")
    env_val = __import__("os").environ.get(key)
    if env_val:
        return env_val.strip()
    token_file = Path(cfg["github"]["token_file"])
    if not token_file.is_file():
        raise SystemExit(f"Token file not found: {token_file}")
    prefix = f"{key}="
    for line in token_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"Key {key} not found in {token_file}")


def git_run(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout.strip())
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr.strip(), file=sys.stderr)
        raise SystemExit(f"git {' '.join(args)} failed ({proc.returncode})")


def ensure_git_repo(cfg: dict) -> None:
    if not (ROOT / ".git").is_dir():
        git_run(["init"], ROOT)
        git_run(["branch", "-M", cfg["github"].get("branch", "main")], ROOT)
    remote = cfg["github"]["remote"]
    proc = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        git_run(["remote", "add", "origin", remote], ROOT)


def publish_print_folder(
    cfg: dict,
    print_slug: str,
    gcode_files: list[Path],
    readme_md: str,
    message: str | None = None,
) -> None:
    if not cfg["github"].get("enabled", True):
        print("GitHub publish disabled in config")
        return
    if not gcode_files:
        raise SystemExit("No G-code files to publish")
    dest_dir = resolve_path(cfg, "prints") / slugify(print_slug)
    dest_dir.mkdir(parents=True, exist_ok=True)
    readme_path = dest_dir / "README.md"
    readme_path.write_text(readme_md, encoding="utf-8")
    for gcode_path in gcode_files:
        shutil.copy2(gcode_path, dest_dir / gcode_path.name)
    ensure_git_repo(cfg)
    rel_readme = readme_path.relative_to(ROOT)
    git_run(["add", str(rel_readme)], ROOT)
    for gcode_path in gcode_files:
        git_run(["add", str((dest_dir / gcode_path.name).relative_to(ROOT))], ROOT)
    status = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if status.returncode == 0:
        print("No changes to commit for print folder")
        return
    msg = message or f"Add print folder: {print_slug}"
    git_run(["commit", "-m", msg], ROOT)
    token = read_pat(cfg)
    branch = cfg["github"].get("branch", "main")
    push_url = f"https://x-access-token:{token}@github.com/noel-15/tina_2.git"
    proc = subprocess.run(
        ["git", "push", push_url, f"HEAD:{branch}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.stdout:
        print(proc.stdout.strip())
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr.strip(), file=sys.stderr)
        raise SystemExit("git push failed")
    print(f"Pushed prints/{print_slug}/ to GitHub ({branch})")


def publish_gcode(cfg: dict, gcode_path: Path, message: str | None = None, print_slug: str | None = None) -> None:
    """Publish one G-code into prints/<print_slug>/ with a minimal README."""
    slug = slugify(print_slug or gcode_path.stem.replace("-plate", ""))
    readme = build_readme_simple(cfg, slug, [gcode_path.name], notes=[])
    publish_print_folder(cfg, slug, [gcode_path], readme, message=message)


def build_readme_simple(cfg: dict, title: str, gcode_names: list[str], notes: list[str]) -> str:
    p = cfg["printer"]
    lines = [
        f"# {title.replace('-', ' ').title()}",
        "",
        "Printer: **WEEFUN Tina 2**",
        f"Bed (config): {p['bed_x_mm']} x {p['bed_y_mm']} x {p['bed_z_mm']} mm",
        "",
        "## G-code files",
        "",
    ]
    for name in gcode_names:
        lines.append(f"- `{name}`")
    lines.extend(
        [
            "",
            "## Print steps",
            "",
            "1. Copy the `.gcode` file(s) below to the **root** of a **FAT32** microSD card.",
            "2. Insert the card into the Tina 2 and select the file on the printer menu.",
            "3. Use **PLA** unless a kit note says otherwise; first print: nozzle ~200 C, bed ~60 C.",
            "4. Stay nearby for the first layer; adjust temps in Orca if needed and re-slice.",
            "",
        ]
    )
    if notes:
        lines.append("## Notes")
        lines.append("")
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")
    lines.append("## Preview")
    lines.append("")
    lines.append("Regenerate a preview STL with: `python scripts/tina2_prep.py preview inbox/<slug> --prefix <slug>`")
    lines.append("")
    return "\n".join(lines)


def build_readme_kit(cfg: dict, kit: dict, gcode_files: list[Path]) -> str:
    title = slugify(kit.get("name", "print"))
    notes: list[str] = []
    if kit.get("assembly"):
        notes.append(f"Assembly: {kit['assembly']}")
    for group in kit.get("plate_groups") or []:
        gid = group.get("id", "plate")
        if group.get("orient_note"):
            notes.append(f"**{gid}**: {group['orient_note']}")
        for part in group.get("parts") or []:
            notes.append(f"**{gid}** includes `{part['stl']}` x{part.get('count', 1)}")
    names = [g.name for g in gcode_files]
    return build_readme_simple(cfg, title, names, notes)


def deploy_sd(cfg: dict, gcode_path: Path) -> None:
    drive = cfg.get("sd") or {}
    sd = drive.get("drive")
    if not sd:
        print("sd.drive not set in config; skipping SD deploy")
        return
    sd_path = Path(sd)
    if not sd_path.exists():
        raise SystemExit(f"SD path not found: {sd_path}")
    dest = sd_path / gcode_path.name
    shutil.copy2(gcode_path, dest)
    print(f"Copied to {dest}")


def prepare_one(
    cfg: dict,
    src: Path,
    *,
    scale: float | None = None,
    target_mm: float | None = None,
    fit_bed: bool = False,
    no_push: bool = False,
    deploy: bool = False,
    prefix: str | None = None,
    print_slug: str | None = None,
    readme_notes: list[str] | None = None,
) -> Path:
    work_dir = resolve_path(cfg, "work")
    out_dir = resolve_path(cfg, "out")
    slug = slugify(print_slug or prefix or src.stem)
    work_stl = work_dir / f"{slug}.stl"
    slice_input: Path
    if src.suffix.lower() == ".3mf" and not (fit_bed or target_mm is not None or scale is not None):
        slice_input = src
        print(f"Slicing 3MF plate directly (keeps Bambu/Orca layout): {src.name}")
    else:
        convert_to_stl(src, work_stl, cfg)
        mesh = load_mesh(work_stl)
        if fit_bed:
            factor = fit_factor(mesh, cfg)
            print(f"fit-bed scale factor: {factor:.4f}")
            mesh = scale_mesh(mesh, factor)
        elif target_mm is not None:
            factor = target_factor(mesh, target_mm)
            print(f"target-mm scale factor: {factor:.4f}")
            mesh = scale_mesh(mesh, factor)
        elif scale is not None:
            mesh = scale_mesh(mesh, scale)
        write_stl(mesh, work_stl)
        slice_input = work_stl
    gcode = run_slice(cfg, slice_input, out_dir, gcode_name=f"{slug}-plate.gcode")
    print(f"G-code: {gcode}")
    if not no_push:
        notes = [f"Source file: `{src.name}`"]
        if readme_notes:
            notes.extend(readme_notes)
        readme = build_readme_simple(cfg, slug, [gcode.name], notes)
        publish_print_folder(cfg, slug, [gcode], readme)
    if deploy:
        deploy_sd(cfg, gcode)
    return gcode


def cmd_prepare(args: argparse.Namespace) -> None:
    cfg = load_config(Path(args.config) if args.config else None)
    src = Path(args.input).resolve()
    if src.is_dir():
        stls = sorted(src.glob("*.stl"))
        three_mfs = sorted(src.glob("*.3mf"))
        if not stls and len(three_mfs) == 1:
            prepare_one(
                cfg,
                three_mfs[0],
                scale=args.scale,
                target_mm=args.target_mm,
                fit_bed=args.fit_bed,
                no_push=args.no_push,
                deploy=args.deploy,
                prefix=args.prefix or slugify(src.name),
                readme_notes=getattr(args, "note", None) or None,
            )
            return
        if not stls:
            raise SystemExit(f"No .stl or single .3mf in {src}")
        if getattr(args, "separate", False):
            folder_prefix = args.prefix or slugify(src.name)
            for stl in stls:
                print(f"\n=== {stl.name} ===")
                prepare_one(
                    cfg,
                    stl,
                    scale=args.scale,
                    target_mm=args.target_mm,
                    fit_bed=args.fit_bed,
                    no_push=args.no_push,
                    deploy=args.deploy,
                    prefix=folder_prefix,
                )
            return
        prepare_plate(
            cfg,
            src,
            only=getattr(args, "only", None),
            exclude=getattr(args, "exclude", None),
            scale=args.scale,
            target_mm=args.target_mm,
            fit_bed=args.fit_bed,
            no_push=args.no_push,
            deploy=args.deploy,
            prefix=args.prefix,
            gcode_name=getattr(args, "gcode_name", None),
        )
        return
    if not src.is_file():
        raise SystemExit(f"Input not found: {src}")
    prepare_one(
        cfg,
        src,
        scale=args.scale,
        target_mm=args.target_mm,
        fit_bed=args.fit_bed,
        no_push=args.no_push,
        deploy=args.deploy,
        prefix=args.prefix,
        readme_notes=getattr(args, "note", None) or None,
    )


def plate_exclude_defaults(cfg: dict) -> list[str]:
    plate = cfg.get("plate") or {}
    return list(plate.get("exclude_by_default") or [])


def find_kit_manifest(src_dir: Path, prefix: str) -> dict | None:
    kits_dir = ROOT / "config" / "kits"
    if not kits_dir.is_dir():
        return None
    folder_key = slugify(src_dir.name)
    prefix_key = slugify(prefix)
    for path in sorted(kits_dir.glob("*.yaml")):
        with path.open(encoding="utf-8") as f:
            kit = yaml.safe_load(f)
        if not kit:
            continue
        matches = [slugify(m) for m in kit.get("folder_match") or [kit.get("name", "")]]
        if folder_key in matches or prefix_key in matches or slugify(kit.get("name", "")) == prefix_key:
            return kit
    return None


def apply_scale_to_mesh(
    mesh: trimesh.Trimesh,
    cfg: dict,
    *,
    fit_bed: bool,
    target_mm: float | None,
    scale: float | None,
    label: str,
) -> trimesh.Trimesh:
    if fit_bed:
        factor = fit_factor(mesh, cfg)
        print(f"{label} fit-bed scale factor: {factor:.4f}")
        return scale_mesh(mesh, factor)
    if target_mm is not None:
        factor = target_factor(mesh, target_mm)
        print(f"{label} target-mm scale factor: {factor:.4f}")
        return scale_mesh(mesh, factor)
    if scale is not None:
        return scale_mesh(mesh, scale)
    return mesh


def write_work_stl(
    src: Path,
    work_dir: Path,
    work_name: str,
    cfg: dict,
    *,
    fit_bed: bool,
    target_mm: float | None,
    scale: float | None,
) -> Path:
    work_stl = work_dir / work_name
    convert_to_stl(src, work_stl, cfg)
    mesh = load_mesh(work_stl)
    mesh = apply_scale_to_mesh(mesh, cfg, fit_bed=fit_bed, target_mm=target_mm, scale=scale, label=work_name)
    write_stl(mesh, work_stl)
    return work_stl


def expand_kit_group(
    src_dir: Path,
    work_dir: Path,
    plate_prefix: str,
    group: dict,
    cfg: dict,
    *,
    fit_bed: bool,
    target_mm: float | None,
    scale: float | None,
) -> list[Path]:
    paths: list[Path] = []
    gid = slugify(group["id"])
    for part in group.get("parts") or []:
        src = src_dir / part["stl"]
        if not src.is_file():
            raise SystemExit(f"Kit missing STL: {src}")
        count = int(part.get("count", 1))
        stem = slugify(Path(part["stl"]).stem)
        for i in range(count):
            suffix = f"-{i + 1:02d}" if count > 1 else ""
            work_name = f"{plate_prefix}-{gid}-{stem}{suffix}.stl"
            paths.append(
                write_work_stl(
                    src,
                    work_dir,
                    work_name,
                    cfg,
                    fit_bed=fit_bed,
                    target_mm=target_mm,
                    scale=scale,
                )
            )
    return paths


def export_plate_preview(work_stls: list[Path], dest: Path, *, spread_mm: float = 18.0) -> Path:
    """Combined STL; spread copies on a grid so duplicates are visible in Orca."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    scene = trimesh.Scene()
    cols = 5
    for idx, path in enumerate(work_stls):
        mesh = load_mesh(path)
        row, col = divmod(idx, cols)
        mesh = mesh.copy()
        mesh.apply_translation([col * spread_mm, row * spread_mm, 0.0])
        scene.add_geometry(mesh, node_name=path.stem)
    scene.export(dest)
    return dest


def prepare_kit_plates(
    cfg: dict,
    src_dir: Path,
    kit: dict,
    *,
    fit_bed: bool = False,
    target_mm: float | None = None,
    scale: float | None = None,
    no_push: bool = False,
    deploy: bool = False,
    prefix: str | None = None,
) -> list[Path]:
    work_dir = resolve_path(cfg, "work")
    out_dir = resolve_path(cfg, "out")
    plate_prefix = slugify(prefix or kit.get("name") or src_dir.name)
    preview_dir = ROOT / cfg["paths"].get("preview", "preview")
    gcodes: list[Path] = []
    all_work: list[Path] = []

    print(f"Kit: {kit.get('name', plate_prefix)}")
    if kit.get("assembly"):
        print(f"Assembly: {kit['assembly']}")

    for group in kit.get("plate_groups") or []:
        gid = slugify(group["id"])
        if group.get("orient_note"):
            print(f"  [{gid}] {group['orient_note']}")
        work_paths = expand_kit_group(
            src_dir,
            work_dir,
            plate_prefix,
            group,
            cfg,
            fit_bed=fit_bed,
            target_mm=target_mm,
            scale=scale,
        )
        all_work.extend(work_paths)
        gcode_name = f"{plate_prefix}-{gid}-plate.gcode"
        gcode = run_slice(cfg, work_paths, out_dir, gcode_name=gcode_name)
        print(f"G-code ({gid}, {len(work_paths)} objects): {gcode}")
        if deploy:
            deploy_sd(cfg, gcode)
        gcodes.append(gcode)

    if not no_push and gcodes:
        readme = build_readme_kit(cfg, kit, gcodes)
        publish_print_folder(cfg, plate_prefix, gcodes, readme)

    inventory_preview = preview_dir / f"{plate_prefix}-inventory-plate.stl"
    export_plate_preview(all_work, inventory_preview)
    print(f"Inventory preview (all pieces, spread on grid): {inventory_preview}")
    print("(Assembled look is not in STLs — see MakersWorld photos; print then assemble.)")
    return gcodes


def resolve_plate_stls(
    src: Path,
    only: list[str] | None,
    exclude: list[str] | None,
    cfg: dict | None = None,
) -> list[Path]:
    if not src.is_dir():
        raise SystemExit("Plate input must be a folder of STLs")
    stls = sorted(src.glob("*.stl"))
    if only:
        names = {n.lower() for n in only}
        stls = [p for p in stls if p.name.lower() in names]
    else:
        merged_exclude = list(plate_exclude_defaults(cfg or {}))
        if exclude:
            merged_exclude.extend(exclude)
        if merged_exclude:
            bad = {n.lower() for n in merged_exclude}
            stls = [p for p in stls if p.name.lower() not in bad]
    if exclude and only:
        bad = {n.lower() for n in exclude}
        stls = [p for p in stls if p.name.lower() not in bad]
    if not stls:
        raise SystemExit("No STLs selected for plate")
    return stls


def prepare_plate(
    cfg: dict,
    src_dir: Path,
    *,
    only: list[str] | None = None,
    exclude: list[str] | None = None,
    scale: float | None = None,
    target_mm: float | None = None,
    fit_bed: bool = False,
    no_push: bool = False,
    deploy: bool = False,
    prefix: str | None = None,
    gcode_name: str | None = None,
) -> Path:
    work_dir = resolve_path(cfg, "work")
    out_dir = resolve_path(cfg, "out")
    plate_prefix = slugify(prefix or src_dir.name)
    kit = find_kit_manifest(src_dir, plate_prefix)
    if kit and kit.get("plate_groups"):
        gcodes = prepare_kit_plates(
            cfg,
            src_dir,
            kit,
            fit_bed=fit_bed,
            target_mm=target_mm,
            scale=scale,
            no_push=no_push,
            deploy=deploy,
            prefix=prefix,
        )
        return gcodes[-1]

    stls = resolve_plate_stls(src_dir, only, exclude, cfg)
    work_paths: list[Path] = []
    for src in stls:
        base_slug = f"{plate_prefix}-{slugify(src.stem)}"
        work_stl = work_dir / f"{base_slug}.stl"
        convert_to_stl(src, work_stl, cfg)
        mesh = load_mesh(work_stl)
        if fit_bed:
            factor = fit_factor(mesh, cfg)
            print(f"{src.name} fit-bed scale factor: {factor:.4f}")
            mesh = scale_mesh(mesh, factor)
        elif target_mm is not None:
            factor = target_factor(mesh, target_mm)
            print(f"{src.name} target-mm scale factor: {factor:.4f}")
            mesh = scale_mesh(mesh, factor)
        elif scale is not None:
            mesh = scale_mesh(mesh, scale)
        write_stl(mesh, work_stl)
        work_paths.append(work_stl)
    out_gcode = gcode_name or f"{plate_prefix}-plate.gcode"
    preview_dir = ROOT / cfg["paths"].get("preview", "preview")
    preview_stl = preview_dir / f"{plate_prefix}-plate.stl"
    export_plate_preview(work_paths, preview_stl)
    print(f"Combined preview (open in Orca): {preview_stl}")
    gcode = run_slice(cfg, work_paths, out_dir, gcode_name=out_gcode)
    print(f"Plate G-code ({len(work_paths)} parts): {gcode}")
    if not no_push:
        readme = build_readme_simple(
            cfg,
            plate_prefix,
            [gcode.name],
            notes=[f"Source folder: `{src_dir.name}`"],
        )
        publish_print_folder(cfg, plate_prefix, [gcode], readme)
    if deploy:
        deploy_sd(cfg, gcode)
    return gcode


def cmd_preview(args: argparse.Namespace) -> None:
    cfg = load_config(Path(args.config) if args.config else None)
    src = Path(args.input).resolve()
    if not src.is_dir():
        raise SystemExit("preview input must be a folder of STLs (same selection as prepare)")
    plate_prefix = slugify(getattr(args, "prefix", None) or src.name)
    preview_dir = ROOT / cfg["paths"].get("preview", "preview")
    kit = find_kit_manifest(src, plate_prefix)
    preview_stl = (
        preview_dir / f"{plate_prefix}-inventory-plate.stl"
        if kit and kit.get("plate_groups")
        else preview_dir / f"{plate_prefix}-plate.stl"
    )
    if preview_stl.is_file() and not getattr(args, "rebuild", False):
        print(f"Opening existing preview: {preview_stl}")
    else:
        if kit and kit.get("plate_groups"):
            work_dir = resolve_path(cfg, "work")
            all_work: list[Path] = []
            for group in kit["plate_groups"]:
                all_work.extend(
                    expand_kit_group(
                        src,
                        work_dir,
                        plate_prefix,
                        group,
                        cfg,
                        fit_bed=False,
                        target_mm=None,
                        scale=None,
                    )
                )
            export_plate_preview(all_work, preview_stl)
            print(f"Wrote inventory preview ({len(all_work)} pieces): {preview_stl}")
        else:
            stls = resolve_plate_stls(src, getattr(args, "only", None), getattr(args, "exclude", None), cfg)
            work_dir = resolve_path(cfg, "work")
            work_paths: list[Path] = []
            for s in stls:
                wp = work_dir / f"{plate_prefix}-{slugify(s.stem)}.stl"
                convert_to_stl(s, wp, cfg)
                work_paths.append(wp)
            export_plate_preview(work_paths, preview_stl)
            print(f"Wrote combined preview: {preview_stl}")
    exe = Path(cfg["slicer"]["executable"])
    if not exe.is_file():
        raise SystemExit(f"Slicer not found: {exe}")
    subprocess.Popen([str(exe), str(preview_stl.resolve())], cwd=ROOT)


def cmd_prepare_plate(args: argparse.Namespace) -> None:
    cfg = load_config(Path(args.config) if args.config else None)
    src = Path(args.input).resolve()
    prepare_plate(
        cfg,
        src,
        only=args.only,
        exclude=args.exclude,
        scale=args.scale,
        target_mm=args.target_mm,
        fit_bed=args.fit_bed,
        no_push=args.no_push,
        deploy=args.deploy,
        prefix=args.prefix,
        gcode_name=args.gcode_name,
    )


def _bed_limits(cfg: dict) -> tuple[float, float, float]:
    p = cfg["printer"]
    return float(p["bed_x_mm"]), float(p["bed_y_mm"]), float(p["bed_z_mm"])


def cmd_review(args: argparse.Namespace) -> None:
    """Agent/user checklist after prepare: parts, bed fit, artifacts, GitHub link."""
    cfg = load_config(Path(args.config) if args.config else None)
    src = Path(args.input).resolve()
    if not src.is_dir():
        raise SystemExit("review input must be a folder of STLs")
    plate_prefix = slugify(getattr(args, "prefix", None) or src.name)
    gcode_dir = resolve_path(cfg, "prints")
    print_folder = gcode_dir / plate_prefix
    preview_dir = ROOT / cfg["paths"].get("preview", "preview")
    kit = find_kit_manifest(src, plate_prefix)
    preview_path = (
        preview_dir / f"{plate_prefix}-inventory-plate.stl"
        if kit and kit.get("plate_groups")
        else preview_dir / f"{plate_prefix}-plate.stl"
    )
    readme_path = print_folder / "README.md"
    bx, by, bz = _bed_limits(cfg)
    stls = resolve_plate_stls(src, getattr(args, "only", None), getattr(args, "exclude", None), cfg)
    issues: list[str] = []
    print(f"=== Plate review: {plate_prefix} ===")
    print(f"Parts ({len(stls)}): {', '.join(s.name for s in stls)}")
    for s in stls:
        mesh = load_mesh(s)
        ext = mesh.bounds[1] - mesh.bounds[0]
        print(f"  {s.name}: {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm")
        if ext[0] > bx or ext[1] > by or ext[2] > bz:
            issues.append(f"{s.name} exceeds bed ({bx}x{by}x{bz} mm)")
    if preview_path.is_file():
        comb = load_mesh(preview_path)
        ext = comb.bounds[1] - comb.bounds[0]
        print(f"Combined preview STL: {preview_path}")
        print(f"  combined bounds: {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm")
    else:
        issues.append(f"missing preview STL: {preview_path}")
    gcode_path = print_folder / f"{plate_prefix}-plate.gcode"
    legacy_flat: list[Path] = []
    if print_folder.is_dir():
        gcodes = sorted(print_folder.glob("*.gcode"))
        if gcodes:
            for g in gcodes:
                kb = g.stat().st_size / 1024
                print(f"G-code: {g} ({kb:.1f} KB)")
                if kb < 5:
                    issues.append(f"{g.name} suspiciously small")
        else:
            issues.append(f"no .gcode in {print_folder}")
        if not readme_path.is_file():
            issues.append(f"missing README: {readme_path}")
    elif gcode_path.is_file():
        kb = gcode_path.stat().st_size / 1024
        print(f"G-code: {gcode_path} ({kb:.1f} KB)")
        if kb < 5:
            issues.append("G-code suspiciously small")
    else:
        legacy_flat = sorted(gcode_dir.glob(f"{plate_prefix}*-plate.gcode"))
        if legacy_flat:
            for g in legacy_flat:
                kb = g.stat().st_size / 1024
                print(f"G-code (legacy flat): {g} ({kb:.1f} KB)")
            issues.append("G-code still in flat prints/ — re-run prepare to publish print folder + README")
        else:
            issues.append(f"missing print folder: {print_folder}")
    repo = cfg["github"].get("remote", "").rstrip("/").replace(".git", "")
    if repo and print_folder.is_dir():
        print(f"GitHub: {repo}/tree/main/prints/{plate_prefix}")
    elif repo and gcode_path.is_file():
        print(f"GitHub: {repo}/blob/main/prints/{plate_prefix}/{gcode_path.name}")
    print(f"View combined shape in Orca: File -> Open -> {preview_path}")
    if issues:
        print("STATUS: FAIL")
        for i in issues:
            print(f"  - {i}")
        raise SystemExit(1)
    print("STATUS: OK")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Tina 2 print preparation")
    p.add_argument("--config", help="Path to tina2.yaml")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("info", help="Show mesh bounding box")
    sp.add_argument("input")
    sp.set_defaults(func=lambda a: mesh_info(Path(a.input)))

    sp = sub.add_parser("convert", help="Convert input to STL in work dir")
    sp.add_argument("input")
    sp.set_defaults(
        func=lambda a: print(
            convert_to_stl(
                Path(a.input),
                resolve_path(load_config(), "work") / f"{slugify(Path(a.input).stem)}.stl",
                load_config(),
            )
        )
    )

    sp = sub.add_parser("slice", help="Slice STL to G-code")
    sp.add_argument("input")
    sp.set_defaults(
        func=lambda a: print(
            run_slice(load_config(), Path(a.input), resolve_path(load_config(), "out"))
        )
    )

    sp = sub.add_parser("publish", help="Copy gcode to prints/ and push to GitHub")
    sp.add_argument("input")
    sp.add_argument("-m", "--message")
    sp.set_defaults(
        func=lambda a: publish_gcode(load_config(), Path(a.input), a.message)
    )

    sp = sub.add_parser("deploy", help="Copy gcode to SD card")
    sp.add_argument("input")
    sp.set_defaults(func=lambda a: deploy_sd(load_config(), Path(a.input)))

    sp = sub.add_parser("prepare", help="Full pipeline; folders → one combined plate G-code")
    sp.add_argument("input")
    sp.add_argument(
        "--only",
        nargs="+",
        metavar="FILE",
        help="On a folder: include only these STLs (overrides plate.exclude_by_default)",
    )
    sp.add_argument("--exclude", nargs="+", metavar="FILE", help="Extra STLs to skip on a folder")
    sp.add_argument("--gcode-name", help="Output filename for folder plate (default: <prefix>-plate.gcode)")
    sp.add_argument(
        "--separate",
        action="store_true",
        help="Folder only: one G-code per STL instead of a combined plate",
    )
    sp.add_argument("--scale", type=float, help="Uniform scale factor")
    sp.add_argument("--target-mm", type=float, dest="target_mm", help="Scale so longest edge equals this mm")
    sp.add_argument("--fit-bed", action="store_true", help="Uniform scale to fit configured bed")
    sp.add_argument("--no-push", action="store_true", help="Skip GitHub push")
    sp.add_argument("--deploy", action="store_true", help="Copy gcode to SD after slice")
    sp.add_argument("--prefix", help="Slug prefix for folder plate / work STLs")
    sp.add_argument(
        "--note",
        action="append",
        dest="note",
        metavar="TEXT",
        help="Extra line(s) for prints/<slug>/README.md",
    )
    sp.set_defaults(func=cmd_prepare)

    sp = sub.add_parser("preview", help="Open Orca with one combined plate STL (same parts as prepare)")
    sp.add_argument("input", help="Folder of STLs")
    sp.add_argument("--only", nargs="+", metavar="FILE")
    sp.add_argument("--exclude", nargs="+", metavar="FILE")
    sp.add_argument("--prefix", help="Plate name slug (default: folder name)")
    sp.add_argument("--rebuild", action="store_true", help="Regenerate preview STL before opening")
    sp.set_defaults(func=cmd_preview)

    sp = sub.add_parser("review", help="Validate plate outputs and print paths for user")
    sp.add_argument("input", help="Folder of STLs (same as prepare)")
    sp.add_argument("--only", nargs="+", metavar="FILE")
    sp.add_argument("--exclude", nargs="+", metavar="FILE")
    sp.add_argument("--prefix", help="Plate slug (default: folder name)")
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser(
        "prepare-plate",
        help="Alias for prepare on a folder (combined plate)",
    )
    sp.add_argument("input", help="Folder containing STLs")
    sp.add_argument(
        "--only",
        nargs="+",
        metavar="FILE",
        help="Include only these STL filenames (e.g. ring.stl rod.stl roller_plain.stl)",
    )
    sp.add_argument(
        "--exclude",
        nargs="+",
        metavar="FILE",
        help="Skip these STL filenames (e.g. roller_bumps.stl roller_round.stl)",
    )
    sp.add_argument("--gcode-name", help="Output filename in prints/ (default: <prefix>-plate.gcode)")
    sp.add_argument("--scale", type=float, help="Uniform scale factor applied to every part")
    sp.add_argument("--target-mm", type=float, dest="target_mm")
    sp.add_argument("--fit-bed", action="store_true")
    sp.add_argument("--no-push", action="store_true")
    sp.add_argument("--deploy", action="store_true")
    sp.add_argument("--prefix", help="Slug prefix for work STLs and default gcode name")
    sp.set_defaults(func=cmd_prepare_plate)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
