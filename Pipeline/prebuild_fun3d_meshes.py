"""
prebuild_fun3d_meshes.py
========================
Pre-generates FUN3D 3D volume meshes (via pyCAPS AFLR4 + AFLR3) for each
vehicle geometry defined in pipeline_config.yaml.

Meshes are stored in fun3d_meshes/<subdir>/ and marked with mesh_ready.flag
so that run_fun3d.py can skip mesh generation on subsequent CFD calls.

NOTE: These are FUN3D 3D volume meshes (.b8.ugrid).
      The FEAR 2D Gmsh meshes (.msh) live in Mesh_Inputs/ and are handled
      separately by fear_input_writer.py.

Usage:
  python Pipeline/prebuild_fun3d_meshes.py [--config Pipeline/pipeline_config.yaml]

  # Force regeneration even if flag exists:
  python Pipeline/prebuild_fun3d_meshes.py --force
"""

import argparse
import os
import shutil
from pathlib import Path

import yaml


FLAG_FILE = "mesh_ready.flag"


def prebuild_all(config: dict, force: bool = False) -> None:
    """
    Build FUN3D meshes for all geometries in geometry_files config section.

    Parameters
    ----------
    config : dict
        Parsed pipeline_config.yaml.
    force : bool
        If True, rebuild even if mesh_ready.flag already exists.
    """
    pipeline_dir     = Path(__file__).parent
    fun3d_meshes_dir = (pipeline_dir / config["paths"]["fun3d_meshes_dir"]).resolve()
    tcfds_dir        = (pipeline_dir / config["paths"]["tcfds_dir"]).resolve()
    cfd_solver_dir   = tcfds_dir / "fun3D_Solver"
    cfd_control_nml  = cfd_solver_dir / "cfd_control.nml"

    geo_map = config.get("geometry_files", {})

    for cone_angle_str, geo in geo_map.items():
        subdir   = geo.get("fun3d_mesh_subdir", f"cone_{cone_angle_str}deg")
        mesh_dir = fun3d_meshes_dir / subdir
        flag     = mesh_dir / FLAG_FILE
        csm_file = geo["csm"]

        if flag.exists() and not force:
            print(f"[Prebuild] {subdir}: mesh already built (mesh_ready.flag exists) — skipping. "
                  "Use --force to rebuild.")
            continue

        print(f"\n[Prebuild] Building FUN3D mesh for cone_angle={cone_angle_str}° "
              f"({csm_file}) → {mesh_dir}")

        mesh_dir.mkdir(parents=True, exist_ok=True)

        try:
            _build_mesh(csm_file, cfd_solver_dir, cfd_control_nml, mesh_dir, subdir)
            flag.write_text("ok")
            print(f"[Prebuild] {subdir}: DONE ✓")
        except Exception as e:
            print(f"[Prebuild] {subdir}: FAILED — {e}")
            raise


def _build_mesh(csm_filename: str, cfd_solver_dir: Path,
                cfd_control_nml: Path, output_dir: Path, case_name: str) -> None:
    """
    Run pyCAPS AFLR4 + AFLR3 for one geometry and copy the resulting
    mesh files to output_dir.
    """
    import pyCAPS
    import f90nml

    var = f90nml.read(str(cfd_control_nml))["cfd_var"]

    csm_path = cfd_solver_dir / csm_filename
    if not csm_path.exists():
        raise FileNotFoundError(f"CSM geometry file not found: {csm_path}")

    prob_name = f"mesh_prebuild_{case_name}"
    caps_work = output_dir / "caps_work"
    caps_work.mkdir(exist_ok=True)

    # EGADS resolves IMPORT paths relative to cwd, not the CSM file location.
    # Keep cwd inside cfd_solver_dir for the entire mesh build.
    orig_dir = Path.cwd()
    os.chdir(cfd_solver_dir)
    caps_prob = pyCAPS.Problem(problemName=prob_name,
                               capsFile=str(csm_path),
                               outLevel=1)

    # ── Surface mesh (AFLR4) ─────────────────────────────────────────────────
    print(f"  → AFLR4 surface mesh …")
    aflr4 = caps_prob.analysis.create(aim="aflr4AIM", name="aflr4")
    aflr4.input.Mesh_Length_Factor = var.get("Mesh_Length_Factor")
    aflr4.input.max_scale          = var.get("max_scale")
    aflr4.input.ideal_min_scale    = var.get("min_scale")
    aflr4.input.ff_cdfr            = var.get("ff_cdfr")
    aflr4.input.Mesh_Sizing = {
        "blunt":    {"edgeWeight":   var.get("edgeWeight"),
                     "scaleFactor":  var.get("blunt_scaleFactor")},
        "Farfield": {"bcType":       "Farfield",
                     "scaleFactor":  var.get("farfield_scaleFactor")},
    }
    aflr4.runAnalysis()

    # ── Volume mesh (AFLR3) ──────────────────────────────────────────────────
    print(f"  → AFLR3 volume mesh …")
    aflr3 = caps_prob.analysis.create(aim="aflr3AIM", name="aflr3")
    aflr3.input["Surface_Mesh"].link(aflr4.output["Surface_Mesh"])
    aflr3.input.Mesh_Sizing = {
        "blunt":    {"bcType": "Inviscid"},
        "Farfield": {"bcType": "Farfield"},
    }
    aflr3.runAnalysis()

    # ── Copy mesh files to output_dir ────────────────────────────────────────
    # pyCAPS creates its scratch dir relative to cfd_solver_dir (our chdir target).
    # Use os.scandir to avoid glob dotfile exclusion (pyCAPS may name files ".b8.ugrid").
    scratch = cfd_solver_dir / prob_name / "Scratch" / "aflr3"
    mesh_suffixes = (".b8.ugrid", ".lb8.ugrid", ".mapbc", ".surf")
    copied = 0

    if scratch.exists():
        for entry in os.scandir(scratch):
            if entry.name.endswith(mesh_suffixes) and entry.is_file():
                shutil.copy2(entry.path, output_dir / entry.name)
                print(f"  → Copied {entry.name} → {output_dir}")
                copied += 1
    else:
        # Fallback: search entire cfd_solver_dir tree
        for p in cfd_solver_dir.rglob("*"):
            if p.name.endswith(mesh_suffixes) and p.is_file():
                shutil.copy2(p, output_dir / p.name)
                print(f"  → Copied {p.name} → {output_dir}")
                copied += 1

    if copied == 0:
        raise RuntimeError(f"No mesh files (.b8.ugrid) found after AFLR3 run in {caps_work}")

    print(f"  → {copied} mesh file(s) copied to {output_dir}")
    os.chdir(orig_dir)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Pre-build FUN3D 3D volume meshes for all configured geometries")
    parser.add_argument("--config", default="pipeline_config.yaml",
                        help="Path to pipeline_config.yaml")
    parser.add_argument("--force", action="store_true",
                        help="Rebuild even if mesh_ready.flag exists")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    prebuild_all(config, force=args.force)
    print("\n[Prebuild] All FUN3D meshes ready.")


if __name__ == "__main__":
    main()
