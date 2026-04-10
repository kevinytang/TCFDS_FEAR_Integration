# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

This is a Georgia Tech MS thesis project titled **"Improving Atmospheric Entry Environment Prediction Using Machine-Learning Surrogate Models"** (Kevin Y. Tang, advisor Dr. John Dec). The work is organized into three tasks:

- **Task 1 (complete)**: Build and validate the **TCFDS** (Trajectory-CFD Solver) — a coupled framework integrating a 3-DOF Fortran trajectory propagator with NASA FUN3D CFD, post-processed through FEAR (Finite Element Ablation and Thermal Response) to generate high-fidelity training data.
- **Task 2 (in progress)**: Develop mission-specific ML surrogate models (neural networks) for aerodynamic coefficients (trained on FUN3D data) and ablation response (trained on FEAR data), using a Design of Experiments (DoE) sampling strategy near the nominal trajectory.
- **Task 3 (future)**: Integrate the surrogates into the trajectory propagator, replacing live FUN3D/FEAR calls, and perform uncertainty quantification for landing footprint prediction.

The code in this repo is primarily Task 1. The reference mission is the Stardust capsule Earth return (15 January 2006), used for validation.

## Build Commands

### Compile Fortran Trajectory Code
```bash
cd Trajectory_CFD_Integration/Reentry_3DOF_NonPlanar/
gfortran -O2 mod_atmosphere.f90 mod_gravity.f90 main.f90 -o reentry.exe
```

For NRLMSISE-00 atmosphere model (adds legacy Fortran 77 library):
```bash
# See CompileCommands.txt for full flags and nrlmsise00_sub.for linkage
```

### Python Environment
```bash
cd Trajectory_CFD_Integration/
source .venv/bin/activate
# Python 3.11; requires: f90nml, pyCAPS, numpy
```

## Run Commands

### Pre-build FUN3D Meshes (required once before running the pipeline)
```bash
# From repo root, with ESP environment active:
python Pipeline/prebuild_fun3d_meshes.py --config Pipeline/pipeline_config.yaml
# Outputs: fun3d_meshes/cone_50deg/, cone_59deg/, cone_70deg/ — each with .lb8.ugrid + .mapbc + mesh_ready.flag
```

**Known gotchas:**
- Requires ESP 1.28+ (pyCAPS ≥ 3.x). The old `workDir=` kwarg to `pyCAPS.Problem()` was removed; the script does not use it.
- `.STEP` files in `fun3D_Solver/` must have Unix (LF) line endings. Files sourced from Windows have CRLF, which causes a silent `EGADS_NOTFOUND` error. Fix: `sed -i 's/\r//' Trajectory_CFD_Integration/fun3D_Solver/*.STEP`
- All three STEP files must be present: `Stardust_054_59deg.STEP`, `054_50deg.STEP`, `054_70deg.STEP`

### Full Coupled Simulation (TCFDS)
```bash
cd Trajectory_CFD_Integration/
python control.py
# Output: history.csv (trajectory log), updated config.nml each step,
#         FUN3D outputs in fun3D_Solver/reentryCFD/Scratch/
```

### Pipeline (DoE Training Data Generation)
```bash
# From repo root (all 21 cases, parallel TCFDS, sequential FEAR):
python Pipeline/doe_pipeline.py --config Pipeline/pipeline_config.yaml

# Skip mesh pre-build if meshes already exist:
python Pipeline/doe_pipeline.py --config Pipeline/pipeline_config.yaml --skip-prebuild

# Resume after interruption (skips cases with existing history.csv):
python Pipeline/doe_pipeline.py --config Pipeline/pipeline_config.yaml --skip-prebuild --resume
```

**Before running on a new machine**, update these fields in `Pipeline/pipeline_config.yaml`:
- `paths.fun3d_executable` — absolute path to `nodet_mpi`
- `paths.fear_executable` — absolute path to `FEAR` binary

**Known gotchas:**
- `cfd_control.nml` `Num_Iter` must be **1800** (the solver needs 1800 iterations to converge). If accidentally set to 1, FUN3D runs one iteration and returns near-zero Cl/Cd.
- `--resume` skips cases that already have `history.csv`. If a previous run used wrong settings (e.g. `Num_Iter=1`), **delete `runs/`** before re-running to avoid carrying over bad data.
- The Fortran trajectory code hardcodes `open(file='../config.nml')` relative to its CWD. `control.py` handles this by running `reentry.exe` from `workdir/reentry_work/` so `../config.nml` resolves to the case-specific config. Do not change the Fortran CWD logic without accounting for this.

### MATLAB Post-Processing (TCFDS output → FEAR inputs)
```matlab
cd Design_of_Experiment/
manipulationForFEAR  % reads Run*.xlsx, outputs FEAR aerodynamic heating boundary conditions
```

## Architecture

### Data Flow
```
config.nml  ──►  reentry.exe (Fortran)  ──►  config.nml (updated states)
                                                     │
control.py ─────────────────────────────────────────►│
     │           ◄── Mach, Temp, AoA ──              │
     └──► run_075_70deg.py (ESP pyCAPS/FUN3D)  ──► Cl, Cd ──► config.nml
                                                               │
history.csv  ◄──────────────────────────────────────────────────
     │
manipulationForFEAR.m (MATLAB)  ──► FEAR boundary conditions (Excel)
     │
FEAR (external)  ──► mass loss, frontal area recession (ablation training data for Task 2)
```

### Master Controller (`control.py`)
Orchestrates the simulation loop by:
1. Reading/writing `config.nml` to pass state between Fortran and Python
2. Calling `reentry.exe` as a subprocess for each 5-second trajectory step (internally divided into 100 sub-steps of 0.05 s each)
3. Triggering CFD (`run_075_70deg.py`) only when Mach, Temperature, or AoA change >10% from the last CFD run — this adaptive triggering limits expensive FUN3D calls to 1-2 per trajectory rather than every step
4. Logging all states to `history.csv`

### Cross-Language Communication via `config.nml`
The Fortran namelist file is the sole data exchange mechanism between Fortran, Python, and the CFD driver:
- `&INITIAL_CONDITIONS`: V0, γ0, ψ0, altitude, longitude, latitude, AoA
- `&VEHICLE_PARAM`: mass, reference area/length
- `&CONTROL_SETTINGS`: timestep, end time, CFD re-trigger tolerance (10%)
- `&CURRENT_STATES`: updated each Fortran run with current V, γ, ψ, alt, Mach, Temp, Cl, Cd
- `&ATMOSPHERE_INPUT`: model selector (1=NASA standard, 2=NRLMSISE-00), date/time for NRLMSISE-00

### Trajectory Module (`Reentry_3DOF_NonPlanar/main.f90`)
- 6-state RK4 integration: V, γ (flight path angle), ψ (heading angle from east), h, θ (longitude), φ (latitude)
- Thrust T=0 and bank angle σ=0 (uncontrolled ballistic entry assumption)
- Physics modules: `mod_atmosphere.f90` (NASA or NRLMSISE-00), `mod_gravity.f90` (point-mass: g = μ_e/(R_e+h)²)
- Earth rotation (Coriolis + centrifugal) included in equations of motion
- Stardust initial conditions (from NASA DC-8 airborne observation): V₀=12,765 m/s, γ₀=−7.412°, ψ₀=352.8°, h₀=82,701 m, θ₀=240.7917°, φ₀=41.2323°, date 15 Jan 2006 09:57:15 UTC

### CFD Driver (`fun3D_Solver/run_075_70deg.py`)
- FUN3D is executed via the **Engineering Sketch Pad (ESP) pyCAPS API** (Analysis Interface Modules), which controls geometry, surface mesh (AFLR4), volume mesh (AFLR3), and the flow solver from a single Python script
- Geometry: OpenCSM `.csm` files; farfield is a sphere of radius 5 m
- Three test geometries (all 0.81 m diameter): Stardust 59.6° cone (R_nose=0.21 m), 50° cone (R_nose=0.26 m), 70° cone (R_nose=0.14 m)
- Inviscid, calorically perfect compressible flow; freestream Mach, temperature, and AoA applied at farfield boundary
- Solver settings: DLDFSS flux + van Albada limiter; first 600 iterations at first-order accuracy, then second-order; CFL ramp 0.1→10.0 over 1800 total iterations; limiter frozen at iteration 1200
- Convergence assessed by stabilization of aerodynamic coefficients (not residual threshold, due to strong bow shock)
- Returns force coefficients C_L, C_D to `control.py`

### Thermal Post-Processing (`Design_of_Experiment/manipulationForFEAR.m`)
Converts trajectory + CFD history to FEAR aerodynamic heating boundary conditions:
- **Stagnation heat flux** (Sutton-Graves): `q_s = K · √(ρ/r_n) · V³`, where K = 1.7415×10⁻⁴ for Earth
- **Recovery enthalpy**: `H_r = V²/2`
- **Film coefficient** (cold-wall): `ρ_e u_e C_h0 = Q_cw / H_r`; a blowing correction factor of 0.5 is applied in FEAR since Q_cw uses the stagnation value
- Heat flux distribution: cosine of angle from centerline on the spherical nose; linear decrease from nose-cone junction to 75% of that value at the cone base

### FEAR Setup
- Geometry and mesh preparation done in **Gmsh** (not pyCAPS)
- Mesh split into TPS layer (PICA — Phenolic Impregnated Carbon Ablator, ~6 cm thick) and load-bearing structure (6061 aluminum alloy)
- Boundary conditions assigned as Gmsh physical groups: aerodynamic heating + pressure + radiation on front surface; zero-recession at TPS/structure bondline
- Current mesh: 20 quadrilateral elements across TPS thickness, 56 elements across radial direction, 0.06 s time step
- FEAR outputs used as Task 2 ablation surrogate training data: mass loss, surface recession, frontal area change

## Key Design Decisions

- **Namelist I/O**: Language-agnostic disk-based communication between Fortran subprocess and Python controller; one file read/write per timestep
- **Inviscid CFD**: FUN3D runs in inviscid mode (pressure forces dominate for hypersonic blunt bodies); aerodynamic heating is handled separately via Sutton-Graves in post-processing
- **Adaptive CFD trigger**: 10% tolerance on Mach/Temp/AoA before re-running FUN3D, controlled by `TOL` in `config.nml`; reduces FUN3D calls from one-per-step to ~1–2 per full trajectory
- **Mission-specific DoE**: Task 2 training data is sampled near the nominal trajectory (not a globally applicable database), minimizing required high-fidelity evaluations
- **Modular atmosphere**: Switch between NASA 1976 standard atmosphere (ATM_MODEL=1) and NRLMSISE-00 (ATM_MODEL=2) via namelist; NRLMSISE-00 is the primary model (accounts for location, season, solar/geomagnetic activity) but does not model winds

## External Dependencies

| Tool | Purpose |
|------|---------|
| FUN3D (NASA Langley) | Fully Unstructured Navier-Stokes 3D inviscid CFD solver |
| ESP pyCAPS (AIM) | Engineering Sketch Pad — geometry/mesh/solver orchestration API |
| AFLR3/AFLR4 | Volume/surface mesh generation (called via CAPS AIM) |
| FEAR | Finite Element Ablation and Thermal Response solver |
| Gmsh | Geometry and mesh preparation for FEAR |
| NRLMSISE-00 | Legacy Fortran 77 empirical atmosphere library |
| MATLAB | TCFDS output post-processing and FEAR input generation |
| `f90nml` | Python library for reading/writing Fortran namelists |
