"""
doe_pipeline.py
===============
Master orchestrator for the TCFDS → FEAR training data pipeline.

Stages:
  0. Pre-build FUN3D 3D volume meshes (once per geometry)
  1. Generate DoE cases from nominal IC
  2. Run TCFDS (trajectory + FUN3D) for each case — parallel across cases
  3. Write FEAR inputs (FEAR_BC.dat, FEARin.dat, FEAR 2D mesh, sf_list.txt)
  4. Run FEAR for each case — sequential (FEAR cannot run in parallel)
  5. Extract time-history of mass loss and frontal area from FEAR outputs
  6. Aggregate results into training_data/

Usage:
  cd TCFDS_FEAR_Integration/
  python Pipeline/doe_pipeline.py --config Pipeline/pipeline_config.yaml

  # Limit number of cases:
  python Pipeline/doe_pipeline.py --n-cases 5

  # Resume after interruption (skips completed cases):
  python Pipeline/doe_pipeline.py --resume

  # Skip mesh pre-build (meshes already exist):
  python Pipeline/doe_pipeline.py --skip-prebuild
"""

import argparse
import csv
import shutil
import subprocess
import sys
import time as _time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import f90nml
import yaml

# Local pipeline modules
sys.path.insert(0, str(Path(__file__).parent))
import doe_generator
import fear_input_writer
import fear_output_reader
import prebuild_fun3d_meshes


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args   = _parse_args()
    config = _load_config(args.config)

    pipeline_dir   = Path(args.config).parent.resolve()
    tcfds_dir      = (pipeline_dir / config["paths"]["tcfds_dir"]).resolve()
    mesh_inputs    = (pipeline_dir / config["paths"]["mesh_inputs_dir"]).resolve()
    fun3d_meshes   = (pipeline_dir / config["paths"]["fun3d_meshes_dir"]).resolve()
    runs_dir       = (pipeline_dir / config["paths"]["runs_dir"]).resolve()
    training_dir   = (pipeline_dir / config["paths"]["training_data_dir"]).resolve()

    runs_dir.mkdir(parents=True, exist_ok=True)
    training_dir.mkdir(parents=True, exist_ok=True)

    max_workers = config["tcfds"].get("max_parallel_cases", 3)
    fear_exe    = config["paths"]["fear_executable"]

    # Override n_cases from CLI if provided
    if args.n_cases is not None:
        config["doe"]["n_cases"] = args.n_cases

    print("=" * 60)
    print("  TCFDS-FEAR Training Data Pipeline")
    print("=" * 60)
    print(f"  Config      : {args.config}")
    print(f"  Runs dir    : {runs_dir}")
    print(f"  Training dir: {training_dir}")
    print(f"  DoE method  : {config['doe']['method']}  "
          f"(n={config['doe']['n_cases']})")
    print(f"  Max parallel TCFDS workers: {max_workers}")
    print("=" * 60)

    # ── Stage 0: Pre-build FUN3D meshes ─────────────────────────────────────
    if not args.skip_prebuild:
        print("\n[Stage 0] Pre-building FUN3D 3D volume meshes …")
        prebuild_fun3d_meshes.prebuild_all(config, force=False)
    else:
        print("\n[Stage 0] Skipping FUN3D mesh pre-build (--skip-prebuild)")

    # ── Stage 1: Generate DoE cases ──────────────────────────────────────────
    doe_csv = runs_dir / "doe_cases.csv"
    if doe_csv.exists() and args.resume:
        print(f"\n[Stage 1] Reusing existing DoE cases: {doe_csv}")
        cases = _read_doe_csv(doe_csv)
    else:
        print("\n[Stage 1] Generating DoE cases …")
        cases = doe_generator.generate(config, doe_csv)

    print(f"          {len(cases)} cases generated.")

    # ── Stage 2: Run TCFDS in parallel ──────────────────────────────────────
    print(f"\n[Stage 2] Running TCFDS ({max_workers} workers in parallel) …")
    case_dirs = _prepare_case_dirs(cases, runs_dir, tcfds_dir, config)

    failed_tcfds = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for case, case_dir in zip(cases, case_dirs):
            history_csv = case_dir / "history.csv"
            if args.resume and _history_has_data(history_csv):
                print(f"  [{case['case_id']}] TCFDS already done — skipping.")
                continue
            fut = pool.submit(_run_tcfds, case, case_dir, tcfds_dir,
                              fun3d_meshes, config)
            futures[fut] = case["case_id"]

        for fut in as_completed(futures):
            cid = futures[fut]
            try:
                fut.result()
                print(f"  [{cid}] TCFDS complete ✓")
            except Exception as e:
                print(f"  [{cid}] TCFDS FAILED: {e}")
                failed_tcfds.append(cid)

    if failed_tcfds:
        print(f"\n  WARNING: {len(failed_tcfds)} TCFDS cases failed: {failed_tcfds}")

    # ── Stages 3–5: FEAR (sequential) ───────────────────────────────────────
    print("\n[Stages 3–5] FEAR inputs → FEAR run → output extraction (sequential) …")
    summary_rows = []

    for case, case_dir in zip(cases, case_dirs):
        cid         = case["case_id"]
        history_csv = case_dir / "history.csv"
        fear_in_dir = case_dir / "fear_inputs"
        fear_out_dir= case_dir / "fear_outputs"

        if not _history_has_data(history_csv):
            print(f"  [{cid}] No TCFDS history — skipping FEAR.")
            continue

        cone_angle = float(case.get("cone_angle",
                                    config["nominal_ic"]["cone_angle"]))

        # ── Stage 3: Write FEAR inputs ───────────────────────────────────────
        if args.resume and (fear_in_dir / "FEARin.dat").exists():
            print(f"  [{cid}] FEAR inputs already written — skipping.")
        else:
            print(f"  [{cid}] Writing FEAR inputs …")
            try:
                fear_input_writer.write_fear_inputs(
                    history_csv=history_csv,
                    output_dir=fear_in_dir,
                    config=config,
                    cone_angle=cone_angle,
                )
            except Exception as e:
                print(f"  [{cid}] FEAR input writer FAILED: {e}")
                continue

        # ── Stage 4: Run FEAR ────────────────────────────────────────────────
        skip_fear = (args.resume and
                     any(fear_out_dir.glob("out_*.dat")) and
                     fear_out_dir.exists())
        if skip_fear:
            print(f"  [{cid}] FEAR outputs exist — skipping FEAR run.")
        else:
            print(f"  [{cid}] Running FEAR …")
            fear_out_dir.mkdir(parents=True, exist_ok=True)
            success = _run_fear(fear_exe, fear_in_dir, fear_out_dir)
            if not success:
                print(f"  [{cid}] FEAR FAILED — skipping output extraction.")
                continue

        # ── Stage 5: Extract time-history ────────────────────────────────────
        hist_csv_out = training_dir / f"{cid}_history.csv"
        if args.resume and hist_csv_out.exists():
            print(f"  [{cid}] FEAR history already extracted — skipping.")
            rows = _read_doe_csv(hist_csv_out)
        else:
            print(f"  [{cid}] Extracting FEAR time-history …")
            try:
                rows = fear_output_reader.extract_time_history(
                    fear_dir=fear_out_dir,
                    output_csv=hist_csv_out,
                    config=config,
                )
            except Exception as e:
                print(f"  [{cid}] FEAR output reader FAILED: {e}")
                continue

        # ── Append summary row ───────────────────────────────────────────────
        fear_summary = fear_output_reader.get_summary(rows)
        traj_summary = _traj_summary(history_csv)
        summary_row  = {
            "case_id": cid,
            **{k: case[k] for k in ("V0", "gamma0", "psi0", "alt0", "lon0",
                                     "lat0", "cone_angle", "mass", "Aref")
               if k in case},
            **traj_summary,
            **fear_summary,
        }
        summary_rows.append(summary_row)
        print(f"  [{cid}] Done ✓  mass_loss={fear_summary.get('total_mass_loss_kg',0):.4f} kg")

    # ── Write summary CSV ────────────────────────────────────────────────────
    summary_csv = training_dir / "summary.csv"
    if summary_rows:
        _write_csv(summary_rows, summary_csv)
        print(f"\n[Pipeline] Summary ({len(summary_rows)} cases) → {summary_csv}")

    print("\n" + "=" * 60)
    print(f"  Pipeline complete.")
    print(f"  Training data: {training_dir}")
    if failed_tcfds:
        print(f"  Failed TCFDS cases: {failed_tcfds}")
    print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Case directory setup
# ─────────────────────────────────────────────────────────────────────────────

def _prepare_case_dirs(cases, runs_dir, tcfds_dir, config):
    """Create per-case directory and write config.nml from the DoE row."""
    case_dirs = []
    for case in cases:
        cid      = case["case_id"]
        case_dir = runs_dir / cid
        case_dir.mkdir(parents=True, exist_ok=True)

        cfg_path = case_dir / "config.nml"
        _write_case_config(cfg_path, case, tcfds_dir, config)
        case_dirs.append(case_dir)
    return case_dirs


def _write_case_config(cfg_path: Path, case: dict, tcfds_dir: Path, config: dict):
    """Write a config.nml for this case, seeded with DoE initial conditions."""
    # Start from the template in the submodule
    template = tcfds_dir / "config.nml"
    if template.exists():
        params = f90nml.read(str(template))
    else:
        raise FileNotFoundError(f"Template config.nml not found: {template}")

    nominal = config["nominal_ic"]
    init    = params["initial_conditions"]
    veh     = params["vehicle_param"]
    ctrl    = params["control_settings"]

    # Overwrite initial conditions with DoE values
    init["v0"]     = float(case.get("V0",     nominal["V0"]))
    init["gamma0"] = float(case.get("gamma0", nominal["gamma0"]))
    init["psi0"]   = float(case.get("psi0",   nominal["psi0"]))
    init["alt0"]   = float(case.get("alt0",   nominal["alt0"]))
    init["lon0"]   = float(case.get("lon0",   nominal["lon0"]))
    init["lat0"]   = float(case.get("lat0",   nominal["lat0"]))
    init["alpha0"] = float(nominal.get("alpha0", 2.4))

    # Vehicle parameters
    veh["m"]    = float(case.get("mass", nominal["mass"]))
    veh["aref"] = float(case.get("Aref", nominal["Aref"]))

    # Reset current_states to initial values
    cs = params["current_states"]
    cs["step"] = 0;  cs["time"] = 0.0
    cs["v"]    = init["v0"];   cs["gamma"] = init["gamma0"]
    cs["psi"]  = init["psi0"]; cs["alt"]   = init["alt0"]
    cs["lon"]  = init["lon0"]; cs["lat"]   = init["lat0"]
    cs["cl"]   = 0.0;          cs["cd"]    = 0.0

    with open(cfg_path, "w") as f:
        f90nml.write(params, f)


# ─────────────────────────────────────────────────────────────────────────────
# Subprocess runners
# ─────────────────────────────────────────────────────────────────────────────

def _run_tcfds(case: dict, case_dir: Path, tcfds_dir: Path,
               fun3d_meshes: Path, config: dict) -> None:
    """Run control.py for one DoE case (called in a worker process)."""
    cone_angle = float(case.get("cone_angle", config["nominal_ic"]["cone_angle"]))
    geo        = config.get("geometry_files", {})
    geo_entry  = _find_geo(geo, cone_angle)
    subdir     = geo_entry.get("fun3d_mesh_subdir", f"cone_{cone_angle}deg")
    mesh_dir   = fun3d_meshes / subdir

    control_py = tcfds_dir / "control.py"
    cmd = [
        sys.executable, str(control_py),
        "--workdir", str(case_dir),
        "--config",  str(case_dir / "config.nml"),
    ]
    if (mesh_dir / "mesh_ready.flag").exists():
        cmd += ["--mesh-dir", str(mesh_dir)]

    print(f"  [{case['case_id']}] Starting TCFDS …  cmd: {' '.join(cmd[-4:])}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        raise RuntimeError(f"control.py exited with code {result.returncode}")


def _run_fear(fear_exe: str, fear_in_dir: Path, fear_out_dir: Path) -> bool:
    """
    Run ./FEAR from fear_in_dir.  FEAR writes output to its working directory.
    Move output files to fear_out_dir afterward.
    """
    # FEAR reads FEARin.dat from its current working directory
    fear_exe_path = Path(fear_exe)
    if not fear_exe_path.is_absolute():
        # Resolve relative to the fear_in_dir
        fear_exe_abs = (fear_in_dir / fear_exe_path).resolve()
        if not fear_exe_abs.exists():
            # Try PATH
            fear_exe_abs = fear_exe_path
    else:
        fear_exe_abs = fear_exe_path

    result = subprocess.run(
        [str(fear_exe_abs)],
        cwd=str(fear_in_dir),
        capture_output=False,
    )

    if result.returncode != 0:
        print(f"  FEAR exited with code {result.returncode}")
        return False

    # Move out_*.dat and other FEAR output files to fear_out_dir
    fear_out_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("out_*.dat", "TCdata_*.dat", "recession.dat",
                    "3DFEAR_*.dat", "mesh_out_*.dat", "NodeOut_*.dat",
                    "stats.dat", "Debug_std_out.dat"):
        for src in fear_in_dir.glob(pattern):
            shutil.move(str(src), str(fear_out_dir / src.name))

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_geo(geo_map: dict, cone_angle: float) -> dict:
    for k, v in geo_map.items():
        if abs(float(k) - cone_angle) < 0.1:
            return v
    raise KeyError(f"No geometry_files entry for cone_angle={cone_angle}°")


def _history_has_data(history_csv: Path) -> bool:
    if not history_csv.exists():
        return False
    with open(history_csv) as f:
        reader = csv.DictReader(f)
        return any(True for _ in reader)


def _traj_summary(history_csv: Path) -> dict:
    """Extract scalar summary stats from the trajectory history CSV."""
    machs, times, cls, cds = [], [], [], []
    with open(history_csv) as f:
        for row in csv.DictReader(f):
            try:
                machs.append(float(row["mach"]))
                times.append(float(row["time"]))
                cls.append(float(row["cl"]))
                cds.append(float(row["cd"]))
            except (KeyError, ValueError):
                pass
    if not machs:
        return {}
    return {
        "peak_mach":         max(machs),
        "total_flight_time": max(times),
        "cl_mean":           sum(cls) / len(cls),
        "cd_mean":           sum(cds) / len(cds),
    }


def _read_doe_csv(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(rows: list[dict], out_path: Path) -> None:
    if not rows:
        return
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def _parse_args():
    parser = argparse.ArgumentParser(
        description="TCFDS-FEAR automated training data pipeline")
    parser.add_argument("--config",        default="Pipeline/pipeline_config.yaml",
                        help="Path to pipeline_config.yaml")
    parser.add_argument("--n-cases",       type=int, default=None,
                        help="Override doe.n_cases from config")
    parser.add_argument("--resume",        action="store_true",
                        help="Skip stages already completed for each case")
    parser.add_argument("--skip-prebuild", action="store_true",
                        help="Skip FUN3D mesh pre-build (meshes already exist)")
    return parser.parse_args()


if __name__ == "__main__":
    main()
