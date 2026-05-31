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


def convert_to_stl(src: Path, dest: Path) -> Path:
    if src.suffix.lower() == ".stl":
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return dest
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


def publish_gcode(cfg: dict, gcode_path: Path, message: str | None = None) -> None:
    if not cfg["github"].get("enabled", True):
        print("GitHub publish disabled in config")
        return
    gcode_dir = resolve_path(cfg, "gcode")
    gcode_dir.mkdir(parents=True, exist_ok=True)
    dest = gcode_dir / gcode_path.name
    shutil.copy2(gcode_path, dest)
    ensure_git_repo(cfg)
    git_run(["add", str(dest.relative_to(ROOT))], ROOT)
    status = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if status.returncode == 0:
        print("No changes to commit for gcode")
        return
    msg = message or f"Add gcode: {dest.stem}"
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
    print(f"Pushed {dest.name} to GitHub ({branch})")


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
) -> Path:
    work_dir = resolve_path(cfg, "work")
    out_dir = resolve_path(cfg, "out")
    base_slug = slugify(src.stem)
    if prefix:
        base_slug = f"{slugify(prefix)}-{base_slug}"
    work_stl = work_dir / f"{base_slug}.stl"
    convert_to_stl(src, work_stl)
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
    gcode = run_slice(cfg, work_stl, out_dir, gcode_name=f"{base_slug}.gcode")
    print(f"G-code: {gcode}")
    if not no_push:
        publish_gcode(cfg, gcode)
    if deploy:
        deploy_sd(cfg, gcode)
    return gcode


def cmd_prepare(args: argparse.Namespace) -> None:
    cfg = load_config(Path(args.config) if args.config else None)
    src = Path(args.input).resolve()
    if src.is_dir():
        stls = sorted(src.glob("*.stl"))
        if not stls:
            raise SystemExit(f"No .stl files in {src}")
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
    )


def plate_exclude_defaults(cfg: dict) -> list[str]:
    plate = cfg.get("plate") or {}
    return list(plate.get("exclude_by_default") or [])


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
    stls = resolve_plate_stls(src_dir, only, exclude, cfg)
    work_paths: list[Path] = []
    for src in stls:
        base_slug = f"{plate_prefix}-{slugify(src.stem)}"
        work_stl = work_dir / f"{base_slug}.stl"
        convert_to_stl(src, work_stl)
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
    gcode = run_slice(cfg, work_paths, out_dir, gcode_name=out_gcode)
    print(f"Plate G-code ({len(work_paths)} parts): {gcode}")
    if not no_push:
        publish_gcode(cfg, gcode)
    if deploy:
        deploy_sd(cfg, gcode)
    return gcode


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


def cmd_preview(args: argparse.Namespace) -> None:
    cfg = load_config(Path(args.config) if args.config else None)
    src = Path(args.input).resolve()
    if not src.is_dir():
        raise SystemExit("preview input must be a folder of STLs (same selection as prepare)")
    stls = resolve_plate_stls(src, getattr(args, "only", None), getattr(args, "exclude", None), cfg)
    exe = Path(cfg["slicer"]["executable"])
    if not exe.is_file():
        raise SystemExit(f"Slicer not found: {exe}")
    paths = [str(p.resolve()) for p in stls]
    print("Opening Orca Slicer with:", ", ".join(p.name for p in stls))
    subprocess.Popen([str(exe), *paths], cwd=ROOT)


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

    sp = sub.add_parser("publish", help="Copy gcode to gcode/ and push to GitHub")
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
    sp.set_defaults(func=cmd_prepare)

    sp = sub.add_parser("preview", help="Open Orca GUI with the same STLs as a folder prepare would use")
    sp.add_argument("input", help="Folder of STLs")
    sp.add_argument("--only", nargs="+", metavar="FILE")
    sp.add_argument("--exclude", nargs="+", metavar="FILE")
    sp.set_defaults(func=cmd_preview)

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
    sp.add_argument("--gcode-name", help="Output filename in gcode/ (default: <prefix>-plate.gcode)")
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
