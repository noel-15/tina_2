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


def run_slice(cfg: dict, stl_path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    slicer = cfg["slicer"]
    exe = Path(slicer["executable"])
    if not exe.is_file():
        raise SystemExit(
            f"Slicer not found: {exe}\nInstall Orca Slicer and set slicer.executable in config/tina2.yaml"
        )
    stype = slicer.get("type", "orca").lower()
    gcode_path = out_dir / f"{stl_path.stem}.gcode"
    if gcode_path.is_file():
        gcode_path.unlink()

    cmd: list[str] = [str(exe)]
    settings = slicer.get("settings") or []
    if stype == "orca":
        if settings:
            joined = ";".join(str(Path(s)) for s in settings)
            cmd.extend(["--load-settings", joined])
        cmd.extend(
            [
                "--slice",
                "0",
                "--export-gcode",
                "--outputdir",
                str(out_dir),
                str(stl_path),
            ]
        )
    elif stype == "prusa":
        for s in settings:
            cmd.extend(["--load", str(s)])
        cmd.extend(["--export-gcode", str(stl_path), "--output", str(gcode_path)])
    else:
        raise SystemExit(f"Unknown slicer.type: {stype}")

    extra = slicer.get("extra_args") or []
    if extra:
        cmd[1:1] = [str(x) for x in extra]

    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout)
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"Slicer failed with code {proc.returncode}")

    if not gcode_path.is_file():
        candidates = sorted(out_dir.glob(f"{stl_path.stem}*.gcode"))
        if not candidates:
            candidates = sorted(out_dir.glob("*.gcode"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise SystemExit("Slicer finished but no .gcode was produced")
        gcode_path = candidates[0]
    return gcode_path


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


def cmd_prepare(args: argparse.Namespace) -> None:
    cfg = load_config(Path(args.config) if args.config else None)
    src = Path(args.input).resolve()
    if not src.is_file():
        raise SystemExit(f"Input not found: {src}")
    work_dir = resolve_path(cfg, "work")
    out_dir = resolve_path(cfg, "out")
    work_stl = work_dir / f"{slugify(src.stem)}.stl"
    convert_to_stl(src, work_stl)
    mesh = load_mesh(work_stl)
    if args.fit_bed:
        factor = fit_factor(mesh, cfg)
        print(f"fit-bed scale factor: {factor:.4f}")
        mesh = scale_mesh(mesh, factor)
    elif args.target_mm is not None:
        factor = target_factor(mesh, args.target_mm)
        print(f"target-mm scale factor: {factor:.4f}")
        mesh = scale_mesh(mesh, factor)
    elif args.scale is not None:
        mesh = scale_mesh(mesh, args.scale)
    write_stl(mesh, work_stl)
    gcode = run_slice(cfg, work_stl, out_dir)
    print(f"G-code: {gcode}")
    if not args.no_push:
        publish_gcode(cfg, gcode)
    if args.deploy:
        deploy_sd(cfg, gcode)


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

    sp = sub.add_parser("prepare", help="Full pipeline: convert, scale, slice, push, optional SD")
    sp.add_argument("input")
    sp.add_argument("--scale", type=float, help="Uniform scale factor")
    sp.add_argument("--target-mm", type=float, dest="target_mm", help="Scale so longest edge equals this mm")
    sp.add_argument("--fit-bed", action="store_true", help="Uniform scale to fit configured bed")
    sp.add_argument("--no-push", action="store_true", help="Skip GitHub push")
    sp.add_argument("--deploy", action="store_true", help="Copy gcode to SD after slice")
    sp.set_defaults(func=cmd_prepare)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
