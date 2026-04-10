"""
fear_input_writer.py
====================
Python port of Design_of_Experiment/manipulationForFEAR.m

Reads a completed TCFDS history.csv and writes the FEAR boundary condition
input files (FEAR_BC.dat, FEARin.dat) for that case.  Also copies the
geometry-fixed files (Gmsh .msh, sf_list.txt) into the case fear_inputs/
directory.

NOTE: The FEAR mesh (.msh) is a 2D Gmsh mesh completely separate from the
FUN3D 3D volume mesh.  It lives in Mesh_Inputs/ and is copied unchanged.

Usage (standalone):
  python fear_input_writer.py \\
      --history   runs/case_000/history.csv \\
      --output    runs/case_000/fear_inputs \\
      --config    pipeline_config.yaml \\
      --cone-angle 59.6
"""

import argparse
import csv
import math
import shutil
from pathlib import Path

import numpy as np
import yaml


# ─────────────────────────────────────────────────────────────────────────────
# Physical constants
# ─────────────────────────────────────────────────────────────────────────────
K_EARTH = 1.7415e-4   # Sutton-Graves constant for Earth [W·s³/(kg·m²·√m)]
GAMMA   = 1.4         # ratio of specific heats (calorically perfect)
BLOWING_CORRECTION = 0.5  # constant blowing correction factor applied in FEAR


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def write_fear_inputs(history_csv: Path, output_dir: Path,
                      config: dict, cone_angle: float) -> None:
    """
    Generate all FEAR input files for one TCFDS case.

    Parameters
    ----------
    history_csv : Path
        Path to the completed TCFDS history.csv for this case.
    output_dir : Path
        Directory where FEAR_BC.dat, FEARin.dat, .msh, sf_list.txt are written.
        Created if it does not exist.
    config : dict
        Parsed pipeline_config.yaml.
    cone_angle : float
        Cone half-angle in degrees (50 | 59.6 | 70).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    geo = _get_geometry(config, cone_angle)
    r_nose = geo["r_nose"]
    pipeline_dir = Path(__file__).parent

    # ── 1. Read trajectory history ──────────────────────────────────────────
    rows = _read_history(history_csv)
    if not rows:
        raise RuntimeError(f"history.csv is empty: {history_csv}")

    stop_time = float(rows[-1]["time"])

    # ── 2. Compute aerothermal quantities ───────────────────────────────────
    bc_data = _compute_bc_data(rows, r_nose)

    # ── 3. Write FEAR_BC.dat ────────────────────────────────────────────────
    bc_path = output_dir / "FEAR_BC.dat"
    _write_fear_bc(bc_data, bc_path, r_nose)
    print(f"[FEAR inputs] FEAR_BC.dat → {bc_path}")

    # ── 4. Write FEARin.dat from template ──────────────────────────────────
    mesh_inputs = (pipeline_dir / config["paths"]["mesh_inputs_dir"]).resolve()
    template_path = mesh_inputs / geo["fearindat_template"]
    fearindat_path = output_dir / "FEARin.dat"
    msh_filename = geo["msh"]
    _write_fearindat(template_path, fearindat_path, msh_filename, stop_time)
    print(f"[FEAR inputs] FEARin.dat  → {fearindat_path}")

    # ── 5. Copy FEAR mesh (.msh) — 2D Gmsh mesh, separate from FUN3D mesh ──
    msh_src = mesh_inputs / geo["msh_dir"] / geo["msh"]
    if not msh_src.exists():
        # Try top-level of mesh_inputs dir
        msh_src = mesh_inputs / geo["msh"]
    if msh_src.exists():
        shutil.copy2(msh_src, output_dir / geo["msh"])
        print(f"[FEAR inputs] {geo['msh']} (FEAR mesh) → {output_dir}")
    else:
        print(f"[FEAR inputs] WARNING: FEAR mesh not found at {msh_src}")

    # ── 6. Copy sf_list.txt (geometry-fixed spatial heat flux factors) ──────
    sf_list_rel = geo.get("sf_list")
    if sf_list_rel:
        sf_src = mesh_inputs / sf_list_rel
        if sf_src.exists():
            shutil.copy2(sf_src, output_dir / "sf_list.txt")
            print(f"[FEAR inputs] sf_list.txt → {output_dir}")
        else:
            print(f"[FEAR inputs] WARNING: sf_list.txt not found at {sf_src}. "
                  "Run extractNode.py for this geometry first.")
    else:
        print(f"[FEAR inputs] WARNING: sf_list not configured for cone_angle={cone_angle}°. "
              "Run extractNode.py to generate it.")


# ─────────────────────────────────────────────────────────────────────────────
# Aerothermal calculations (port of manipulationForFEAR.m)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_bc_data(rows: list[dict], r_nose: float) -> list[dict]:
    """
    Compute FEAR boundary condition quantities at each trajectory timestep.

    Returns list of dicts with keys:
      time, pressure_Pa, rho_u_CH0, q_stag, radiative_heating,
      blowing, temperature_K, p_shock_atm
    """
    results = []
    for row in rows:
        V    = float(row["v"])           # m/s
        rho  = float(row["density"])     # kg/m³
        p_fs = float(row["pressure"])    # Pa  (freestream)
        T    = float(row["temperature"]) # K
        M    = float(row["mach"])
        t    = float(row["time"])        # s

        # Stagnation convective heat flux — Sutton-Graves
        if V > 0 and rho > 0:
            q_stag = K_EARTH * math.sqrt(rho / r_nose) * V**3   # W/m²
        else:
            q_stag = 0.0

        # Recovery enthalpy
        Hr = V**2 / 2.0  # J/kg

        # Film coefficient (cold-wall)
        rho_u_CH0 = q_stag / Hr if Hr > 0 else 0.0

        # Normal shock pressure
        if M > 1.0:
            p_shock_Pa = p_fs * (2*GAMMA*M**2 - (GAMMA - 1)) / (GAMMA + 1)
        else:
            p_shock_Pa = p_fs   # subsonic — use freestream
        p_shock_atm = p_shock_Pa / 101325.0

        results.append({
            "time":             t,
            "pressure_Pa":      p_shock_Pa,
            "rho_u_CH0":        rho_u_CH0,
            "q_stag":           q_stag,
            "radiative_heating": 0.0,   # not modelled — set to 0
            "blowing":          BLOWING_CORRECTION,
            "temperature_K":    T,
            "p_shock_atm":      p_shock_atm,
            "Hr":               Hr,
        })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# File writers
# ─────────────────────────────────────────────────────────────────────────────

def _write_fear_bc(bc_data: list[dict], out_path: Path, r_nose: float) -> None:
    """
    Write FEAR_BC.dat with BC 4 (heating), BC 6 (temperature/radiation),
    and BC 10 (post-shock pressure).

    Format matches the existing hand-crafted FEAR_BC.dat exactly.
    IMPORTANT: No scientific notation — FEAR parser requires fixed-point format.
    """
    n = len(bc_data)

    with open(out_path, "w") as f:

        # ── BC 4: Aerodynamic heating (TPS front surface) ───────────────────
        # Header:  BC_ID  type  flag_time  flag_style  flag_spatial  flag_scalar
        #   flag_spatial = -1 → node-based spatial multipliers from sf_list.txt
        f.write(f"400   4   1   2  -1    0\n")
        f.write(f"1   1   {_fmt(r_nose)}\n")  # n_sets=1, set_id=1, nose_radius
        f.write(f"{n}\n")                      # number of time points

        # Columns: time  pressure(Pa)  rho_u_CH0  q_stag(W/m²)  radiative(W/m²)  blowing
        for d in bc_data:
            f.write(
                f"  {_fmt(d['time'])}  {_fmt(d['pressure_Pa'])}  "
                f"{_fmt(d['rho_u_CH0'])}  {_fmt(d['q_stag'])}  "
                f"{_fmt(d['radiative_heating'])}  {_fmt(d['blowing'])}\n"
            )

        f.write("\n")

        # ── BC 6: Temperature / radiation outward ───────────────────────────
        f.write(f"600   6   1   3    1.0    0\n")
        f.write(f"{n}\n")
        for d in bc_data:
            f.write(f"  {_fmt(d['time'])}  {_fmt(d['temperature_K'])}\n")

        f.write("\n")

        # ── BC 10: Post-shock pressure ──────────────────────────────────────
        f.write(f"1000   10   1   3    1.0    0\n")
        f.write(f"{n}\n")
        for d in bc_data:
            f.write(f"  {_fmt(d['time'])}  {_fmt(d['p_shock_atm'])}\n")

        f.write("\n")

        # ── BC 11: Zero recession at TPS/structure bondline (fixed) ────────
        f.write("1100   11   0   0    0.0    0\n")

        # ── BC 8 & 9: Velocity and displacement constraints (fixed) ─────────
        f.write("800   8   0   0    0.0    0\n")
        f.write("900   9   0   0    0.0    0\n")


def _write_fearindat(template_path: Path, out_path: Path,
                     msh_filename: str, stop_time: float) -> None:
    """
    Write FEARin.dat by modifying the template:
      - Line 2: mesh filename
      - Line 12: stop time (set to trajectory duration)

    All other lines are preserved verbatim.
    """
    if not template_path.exists():
        raise FileNotFoundError(f"FEARin.dat template not found: {template_path}")

    with open(template_path) as f:
        lines = f.readlines()

    # Line indices (0-based):
    #   0  = comment for mesh file
    #   1  = mesh filename  ← replace
    #   2  = comment for BC file
    #   3  = BC style + path  ← update path to ./FEAR_BC.dat
    #   4  = comment for timestep
    #   5  = timestep line
    #   ...
    #  10  = comment for stop time
    #  11  = stop time        ← replace

    out_lines = list(lines)

    # Update mesh filename (line index 1)
    if len(out_lines) > 1:
        out_lines[1] = f"{msh_filename}\n"

    # Update BC file path to relative path within fear_inputs/ (line index 3)
    if len(out_lines) > 3:
        out_lines[3] = f"2   FEAR_BC.dat   \n"

    # Update stop time (line index 11)
    if len(out_lines) > 11:
        out_lines[11] = f"{_fmt(stop_time)}\n"

    with open(out_path, "w") as f:
        f.writelines(out_lines)


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(val: float) -> str:
    """Format float without scientific notation (FEAR requirement)."""
    # Use enough decimal places to preserve precision
    if abs(val) == 0:
        return "0.00000000"
    magnitude = math.floor(math.log10(abs(val))) if val != 0 else 0
    decimals = max(8, 8 - magnitude)
    decimals = min(decimals, 12)
    result = f"{val:.{decimals}f}"
    # Safety: strip any accidental 'e' notation
    if 'e' in result.lower():
        result = f"{val:.12f}"
    return result


def _read_history(csv_path: Path) -> list[dict]:
    """Read history.csv, skip rows with missing/empty data."""
    rows = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip rows where required fields are empty
            if all(row.get(k, "").strip() for k in ("time", "v", "density", "pressure")):
                rows.append(row)
    return rows


def _get_geometry(config: dict, cone_angle: float) -> dict:
    """Look up geometry config entry for the given cone angle."""
    geo_map = config.get("geometry_files", {})
    # Try exact match first, then nearest
    key = str(cone_angle)
    if key in geo_map:
        return geo_map[key]
    # Try float keys
    for k, v in geo_map.items():
        if abs(float(k) - cone_angle) < 0.1:
            return v
    raise KeyError(f"No geometry_files entry for cone_angle={cone_angle}°. "
                   "Add it to pipeline_config.yaml.")


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate FEAR input files from a completed TCFDS history.csv")
    parser.add_argument("--history",    required=True, help="Path to history.csv")
    parser.add_argument("--output",     required=True, help="Output directory for FEAR inputs")
    parser.add_argument("--config",     default="pipeline_config.yaml")
    parser.add_argument("--cone-angle", type=float, required=True,
                        help="Cone half-angle in degrees (50 | 59.6 | 70)")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    write_fear_inputs(
        history_csv=Path(args.history),
        output_dir=Path(args.output),
        config=config,
        cone_angle=args.cone_angle,
    )


if __name__ == "__main__":
    main()
