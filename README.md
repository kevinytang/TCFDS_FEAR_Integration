# TCFDS–FEAR Integration

**Georgia Tech MS Thesis — Kevin Y. Tang, advisor Dr. John Dec**
*"Improving Atmospheric Entry Environment Prediction Using Machine-Learning Surrogate Models"*

This repository contains the full data-generation pipeline for a machine-learning surrogate study of hypersonic atmospheric entry. It couples three high-fidelity solvers — a 3-DOF Fortran trajectory propagator, NASA FUN3D inviscid CFD, and the FEAR ablation code — to produce training data for neural-network surrogates of aerodynamic and thermal response.

The reference mission is the **Stardust capsule Earth return (15 January 2006)**, used for validation against published flight data.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Component Descriptions](#3-component-descriptions)
4. [Dependencies](#4-dependencies)
5. [Quick Start](#5-quick-start)
6. [Detailed Usage](#6-detailed-usage)
7. [Data Flow](#7-data-flow)
8. [Configuration Reference](#8-configuration-reference)
9. [Output Files](#9-output-files)
10. [Validation](#10-validation)
11. [Project Roadmap](#11-project-roadmap)

---

## 1. Project Overview

The project is organized into three tasks:

| Task | Status | Description |
|---|---|---|
| **Task 1** | Complete | Build and validate **TCFDS** (Trajectory-CFD Solver) — coupled 3-DOF trajectory + FUN3D CFD + FEAR ablation |
| **Task 2** | In progress | Train mission-specific ML surrogates for aerodynamic coefficients and ablation response using DoE sampling |
| **Task 3** | Future | Integrate surrogates into the trajectory propagator; perform landing footprint UQ |

This repository implements Task 1 and the data-generation pipeline for Task 2.

### Physical Problem

A capsule (0.81 m diameter, Stardust geometry) enters Earth's atmosphere at hypersonic speed (~12.8 km/s). The coupled simulation:
- Propagates the 6-state trajectory (velocity, flight path angle, heading, altitude, longitude, latitude) with RK4
- Calls FUN3D for inviscid aerodynamic coefficients (C_L, C_D) when flight conditions change significantly
- Post-processes the trajectory through FEAR to compute TPS ablation (mass loss, surface recession, frontal area change)

---

## 2. Repository Structure

```
TCFDS_FEAR_Integration/
│
├── Trajectory_CFD_Integration/       # Git submodule — TCFDS coupled solver
│   ├── control.py                    # Master controller (Python)
│   ├── config.nml                    # Fortran namelist: shared state between all components
│   ├── history.csv                   # Trajectory time-history output
│   ├── Reentry_3DOF_NonPlanar/       # Fortran trajectory propagator
│   │   ├── main.f90                  # RK4 integrator, equations of motion
│   │   ├── mod_atmosphere.f90        # NASA 1976 / NRLMSISE-00 atmosphere
│   │   ├── mod_gravity.f90           # Point-mass gravity model
│   │   ├── nrlmsise00_sub.for        # NRLMSISE-00 legacy Fortran 77 library
│   │   └── reentry.exe               # Compiled trajectory executable
│   └── fun3D_Solver/                 # FUN3D CFD driver + geometry
│       ├── run_fun3d.py              # pyCAPS/FUN3D driver script
│       ├── run_075_70deg.py          # Legacy single-run CFD script
│       ├── cfd_control.nml           # CFD mesh/solver parameters
│       ├── *.csm                     # OpenCSM geometry files (3 cone angles)
│       ├── *.STEP                    # CAD geometry (imported by .csm files)
│       └── reentryCFD/               # pyCAPS working directory for CFD runs
│
├── Pipeline/                         # Automated DoE → TCFDS → FEAR pipeline (Task 2)
│   ├── doe_pipeline.py               # Top-level pipeline orchestrator
│   ├── doe_generator.py              # Design of Experiments case generator
│   ├── prebuild_fun3d_meshes.py      # Pre-generate FUN3D volume meshes
│   ├── fear_input_writer.py          # Write FEAR boundary condition inputs
│   ├── fear_output_reader.py         # Parse FEAR outputs → training data CSV
│   ├── pipeline_config.yaml          # All pipeline configuration (edit before running)
│   └── README.md                     # Detailed pipeline deployment guide
│
├── Mesh_Inputs/                      # FEAR 2D Gmsh meshes (one per cone geometry)
│   ├── Stardust_054_59deg/           # 59.6° cone (Stardust nominal)
│   ├── 054_50deg/                    # 50° cone
│   └── 054_70deg/                    # 70° cone
│
├── Design_of_Experiment/             # Task 1 manual DoE data (pre-automation)
│   ├── manipulationForFEAR.m         # MATLAB: TCFDS output → FEAR boundary conditions
│   ├── Run*.xlsx                     # Per-run TCFDS + FEAR results
│   └── DOE_Cases.xlsx                # DoE case table
│
├── FEAR_Output/                      # Reference FEAR results for validation
│   └── StardustNominal/              # Nominal Stardust entry FEAR run
│       ├── out_*.dat                 # FEAR time-snapshot outputs (Tecplot fepoint)
│       ├── TCdata_*.dat              # Temperature/carbon time histories
│       └── recession.dat            # Surface recession data
│
├── fun3d_meshes/                     # Pre-built FUN3D 3D volume meshes
│   ├── cone_50deg/                   # 50° cone mesh + mesh_ready.flag
│   ├── cone_59deg/                   # 59.6° cone mesh + mesh_ready.flag
│   └── cone_70deg/                   # 70° cone mesh + mesh_ready.flag
│
└── Kevin_Y__Tang_Thesis_Proposal.pdf # Thesis proposal document
```

---

## 3. Component Descriptions

### Trajectory Propagator (`Reentry_3DOF_NonPlanar/`)

A 3-DOF non-planar reentry trajectory solver written in Fortran 90. Integrates six states — inertial speed V, flight path angle γ, heading angle ψ, altitude h, longitude θ, latitude φ — using 4th-order Runge-Kutta with a fixed 0.05 s sub-step over 5-second intervals.

Physics included:
- Drag and lift from aerodynamic coefficients (C_L, C_D) passed via `config.nml`
- Earth rotation (Coriolis + centrifugal terms)
- Point-mass gravity: g = μ_e / (R_e + h)²
- Selectable atmosphere: NASA 1976 Standard (`ATM_MODEL=1`) or NRLMSISE-00 (`ATM_MODEL=2`)

The executable reads initial conditions and current CFD coefficients from `config.nml` and writes updated states back to the same file each step.

### FUN3D CFD Driver (`fun3D_Solver/run_fun3d.py`)

A pyCAPS-based driver that configures and runs NASA FUN3D for a single inviscid hypersonic flow condition. Given Mach number, temperature, and angle of attack from `config.nml`, it:
1. Loads the appropriate cone geometry (`.csm` → STEP import)
2. Optionally generates a 3D volume mesh via AFLR4 (surface) + AFLR3 (volume), or loads a pre-built mesh
3. Configures FUN3D boundary conditions and solver settings
4. Runs `nodet_mpi` in parallel
5. Extracts C_L and C_D and writes them back to `config.nml`

Solver settings: DLDFSS flux, van Albada limiter, 1800 iterations (first 600 at 1st order), CFL ramp 0.1→10.0.

### Master Controller (`control.py`)

Orchestrates the coupled simulation loop:
1. Reads current states from `config.nml`
2. Calls `reentry.exe` as a subprocess for each 5-second step
3. Triggers FUN3D only when Mach, temperature, or AoA change >10% from the last CFD run (adaptive trigger reduces FUN3D calls to ~1–2 per trajectory)
4. Logs all states to `history.csv`

### MATLAB Post-Processor (`Design_of_Experiment/manipulationForFEAR.m`)

Reads `history.csv` and the per-run Excel files from TCFDS and converts them to FEAR aerodynamic heating boundary conditions:
- **Stagnation heat flux** (Sutton-Graves): q_s = K √(ρ/r_n) V³, K = 1.7415×10⁻⁴
- **Recovery enthalpy**: H_r = V²/2
- **Film coefficient**: ρ_e u_e C_h0 = Q_cw / H_r (cold-wall, blowing correction = 0.5)
- Heat flux distribution: cosine profile on nose sphere, linear taper to 75% at cone base

### FEAR Ablation Solver (external)

FEAR (Finite Element Ablation and Thermal Response) is an external solver not included in this repository. It runs on the boundary conditions produced by `manipulationForFEAR.m` (Task 1) or `fear_input_writer.py` (Task 2 pipeline).

Mesh: 2D axisymmetric in Gmsh — 20 quad elements through PICA TPS thickness (6 cm), 56 radial elements. Material layers: PICA (ρ = 1600 kg/m³) over 6061 aluminum. Time step: 0.06 s.

Outputs used as surrogate training data: total mass loss, stagnation surface recession, frontal area change.

### Pipeline (`Pipeline/`)

The automated Task 2 data-generation pipeline. Given a `pipeline_config.yaml`, it:
1. Pre-builds FUN3D meshes for all cone geometries (once)
2. Generates a Latin Hypercube DoE over the perturbation space around the nominal trajectory
3. Runs TCFDS for each case in parallel (configurable concurrency)
4. Writes FEAR inputs for each case
5. Runs FEAR sequentially for each case
6. Extracts FEAR time histories and writes aggregate training data CSVs

See `Pipeline/README.md` for full deployment instructions.

---

## 4. Dependencies

### Required software

| Tool | Purpose | Notes |
|---|---|---|
| **FUN3D** (NASA Langley) | Inviscid CFD solver | `nodet_mpi` executable required |
| **ESP / pyCAPS** (NASA) | Geometry, mesh, and FUN3D orchestration | ESP 1.28+ required; sets Python environment |
| **AFLR3 / AFLR4** | Volume/surface mesh generation | Bundled with ESP |
| **FEAR** | Finite Element Ablation and Thermal Response | External; provide path in config |
| **Gmsh** | FEAR mesh preparation | Used to generate `.msh` files in `Mesh_Inputs/` |
| **MATLAB** | Task 1 FEAR input post-processing | Required for `manipulationForFEAR.m` only |
| **gfortran** | Compile trajectory Fortran code | ≥ 4.9 |
| **MPI** | Parallel FUN3D execution | OpenMPI or MPICH |

### Python packages

```
numpy
scipy       # Latin Hypercube sampler (≥ 1.7)
f90nml      # Fortran namelist I/O
pyyaml      # pipeline_config.yaml parsing
pyCAPS      # bundled with ESP — do not pip install
```

Install Python dependencies (activate ESP environment first):
```bash
pip install numpy scipy f90nml pyyaml
```

---

## 5. Quick Start

### Step 0 — Clone
```bash
git clone --recurse-submodules https://github.com/kevinytang/TCFDS_FEAR_Integration.git
cd TCFDS_FEAR_Integration
```

### Step 1 — Compile trajectory solver
```bash
cd Trajectory_CFD_Integration/Reentry_3DOF_NonPlanar/
gfortran -O2 mod_atmosphere.f90 mod_gravity.f90 main.f90 -o reentry.exe
cd ../../
```

### Step 2 — Set up Python environment
```bash
# Activate ESP shell environment (sets PATH, LD_LIBRARY_PATH for pyCAPS/FUN3D)
source /path/to/ESP/ESPenv.sh

# Install Python dependencies into ESP's Python
pip install numpy scipy f90nml pyyaml
```

### Step 3 — Configure paths
Edit `Pipeline/pipeline_config.yaml`:
```yaml
paths:
  fun3d_executable:  /absolute/path/to/nodet_mpi   # ← required
  fear_executable:   /absolute/path/to/FEAR         # ← required
```

### Step 4 — Pre-build FUN3D meshes (once)
```bash
python Pipeline/prebuild_fun3d_meshes.py --config Pipeline/pipeline_config.yaml
# Builds meshes for all 3 cone angles; takes a few minutes each
```

### Step 5a — Run a single coupled TCFDS simulation (Task 1)
```bash
cd Trajectory_CFD_Integration/
python control.py
# Output: history.csv, updated config.nml
```

### Step 5b — Run the full automated pipeline (Task 2)
```bash
python Pipeline/doe_pipeline.py --config Pipeline/pipeline_config.yaml
# Runs 21-case LHS DoE by default; see Pipeline/README.md for options
```

---

## 6. Detailed Usage

### Running a single TCFDS case manually

The trajectory propagator and FUN3D communicate through `config.nml`. To run a single case:

```bash
cd Trajectory_CFD_Integration/
source /path/to/ESP/ESPenv.sh

# Edit config.nml to set initial conditions, then:
python control.py

# To use a pre-built mesh (skips AFLR4/AFLR3 each CFD call):
python control.py --mesh-dir ../fun3d_meshes/cone_59deg
```

Key `config.nml` parameters:

| Namelist | Parameter | Description |
|---|---|---|
| `&INITIAL_CONDITIONS` | `V0`, `GAMMA0`, `PSI0`, `ALT0` | Entry interface state |
| `&VEHICLE_PARAM` | `M`, `AREF`, `LREF` | Vehicle mass, reference area/length |
| `&CONTROL_SETTINGS` | `T_STEP`, `TOL` | Step size (s), CFD re-trigger tolerance (%) |
| `&ATMOSPHERE_INPUT` | `ATM_MODEL` | 1 = NASA 1976, 2 = NRLMSISE-00 |

### Running the automated pipeline

```bash
# Full 21-case run
python Pipeline/doe_pipeline.py --config Pipeline/pipeline_config.yaml

# Quick 1-case test (meshes already built)
python Pipeline/doe_pipeline.py --n-cases 1 --skip-prebuild

# Resume after interruption
python Pipeline/doe_pipeline.py --resume
```

See `Pipeline/README.md` for the complete guide including troubleshooting.

### Compiling with NRLMSISE-00 atmosphere

```bash
cd Trajectory_CFD_Integration/Reentry_3DOF_NonPlanar/
# See CompileCommands.txt for full flags including nrlmsise00_sub.for linkage
gfortran -O2 mod_atmosphere.f90 mod_gravity.f90 nrlmsise00_sub.for main.f90 -o reentry.exe
```

### Running FEAR manually (Task 1 workflow)

1. Run TCFDS to produce `history.csv`
2. Open MATLAB, run `Design_of_Experiment/manipulationForFEAR.m` to generate boundary conditions
3. Copy generated files into the FEAR run directory and execute FEAR
4. FEAR outputs land in `FEAR_Output/` (reference nominal results already committed)

---

## 7. Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Task 1 — TCFDS Loop                         │
│                                                                     │
│  config.nml ──► reentry.exe (Fortran RK4) ──► config.nml          │
│       ▲               │ Mach, Temp, AoA changed >10%?              │
│       │               ▼                                             │
│  CL, CD ◄──── run_fun3d.py (pyCAPS → FUN3D nodet_mpi)             │
│       │                                                             │
│  history.csv ◄── control.py logs every step                        │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼ (Task 1 post-processing)
┌─────────────────────────────────────────────────────────────────────┐
│  manipulationForFEAR.m (MATLAB)                                     │
│    Sutton-Graves heat flux, recovery enthalpy, film coefficient     │
│         │                                                           │
│         ▼                                                           │
│  FEAR (external) ──► mass loss, recession, frontal area            │
│         │            (→ Design_of_Experiment/Run*.xlsx)            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                  Task 2 — Automated Pipeline                        │
│                                                                     │
│  pipeline_config.yaml                                               │
│       │                                                             │
│  doe_generator.py ──► runs/doe_cases.csv (LHS)                     │
│       │                                                             │
│  [parallel] control.py × N cases ──► runs/case_XXX/history.csv    │
│       │                                                             │
│  fear_input_writer.py ──► runs/case_XXX/fear_inputs/              │
│       │                                                             │
│  FEAR × N cases ──► runs/case_XXX/fear_outputs/                   │
│       │                                                             │
│  fear_output_reader.py ──► training_data/summary.csv              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. Configuration Reference

All Task 2 settings live in `Pipeline/pipeline_config.yaml`.

### Nominal initial conditions

Stardust Earth return entry interface (15 Jan 2006, 09:57:15 UTC):

```yaml
nominal_ic:
  V0:         12765.0    # m/s  inertial velocity
  gamma0:     -7.412     # deg  flight path angle
  psi0:       352.8      # deg  heading from east
  alt0:       82701.0    # m    altitude
  lon0:       240.7917   # deg  longitude
  lat0:       41.2323    # deg  latitude
  alpha0:     2.4        # deg  angle of attack
  cone_angle: 59.6       # deg  geometry selector (50 | 59.6 | 70)
  mass:       45.7       # kg
  Aref:       0.516159   # m²
```

### Perturbation ranges

Continuous variables: `[min_delta, max_delta]` added to nominal.
Discrete variables: list of absolute values sampled randomly.

```yaml
perturbation_ranges:
  V0:         [-200.0, 200.0]    # m/s
  gamma0:     [-0.5,   0.5  ]   # deg
  cone_angle: [50, 59.6, 70]    # discrete
  mass:       [-2.0,   2.0  ]   # kg
  Aref_pct:   [-5.0,   5.0  ]   # % of nominal Aref
  # ... see pipeline_config.yaml for full list
```

### DoE settings

```yaml
doe:
  n_cases: 21
  method:  lhs      # lhs | full_factorial | random | from_file
  seed:    42
```

### Geometry files

Three cone geometries are supported. All have the same outer diameter (0.81 m) and differ in half-angle and nose radius:

| `cone_angle` | CSM file | Nose radius |
|---|---|---|
| 50° | `054_50deg.csm` | 0.26 m |
| 59.6° (Stardust) | `Stardust_054_59deg.csm` | 0.21 m |
| 70° | `054_70deg.csm` | 0.14 m |

---

## 9. Output Files

### TCFDS trajectory output (`history.csv`)

| Column | Units | Description |
|---|---|---|
| `step` | — | Trajectory step number |
| `time` | s | Simulation time |
| `V` | m/s | Inertial speed |
| `gamma` | deg | Flight path angle |
| `alt` | m | Altitude |
| `Mach` | — | Mach number |
| `CL`, `CD` | — | Aerodynamic coefficients |
| `q_stag` | W/m² | Stagnation heat flux (Sutton-Graves) |

### Pipeline training data (`training_data/`)

`summary.csv` — one row per DoE case, input parameters plus:

| Column | Description |
|---|---|
| `peak_mach` | Maximum Mach number |
| `peak_q_stag` | Peak stagnation heat flux (W/m²) |
| `total_mass_loss_kg` | Total ablated TPS mass |
| `total_frontal_area_loss_m2` | Total frontal area lost to ablation |
| `max_stag_recession_mm` | Maximum stagnation point recession depth |

### Reference FEAR output (`FEAR_Output/StardustNominal/`)

Nominal Stardust entry FEAR run used for validation. Key files:
- `out_*.dat` — Tecplot fepoint snapshots every 0.06 s (880+ files for full trajectory)
- `TCdata_Stardust_054_59deg.dat` — temperature/carbon time history
- `recession.dat` — surface recession time history
- `3DFEAR_Stardust_054_59deg.plt` — final Tecplot solution file

---

## 10. Validation

The TCFDS framework is validated against the Stardust Earth return mission:

**Trajectory validation:** Published flight data from NASA DC-8 airborne observation campaign (15 January 2006). Entry interface conditions: V₀ = 12,765 m/s, γ₀ = −7.412°, h₀ = 82,701 m.

**CFD validation:** FUN3D inviscid C_D compared against published Stardust aerodynamic database (59.6° blunt cone, Mach 10–35).

**Thermal validation:** FEAR stagnation heat flux and recession compared against Sutton-Graves engineering estimates and published TPS performance data for PICA material.

Reference results are committed in `FEAR_Output/StardustNominal/` and `Design_of_Experiment/NominalRun.xlsx`.

---

## 11. Project Roadmap

- [x] **Task 1** — TCFDS framework (trajectory + FUN3D + FEAR coupling)
- [x] **Task 1** — Stardust validation
- [x] **Task 1** — Manual DoE data collection (21 cases, `Design_of_Experiment/`)
- [x] **Task 2** — Automated pipeline (`Pipeline/`) replacing manual workflow
- [ ] **Task 2** — Train aerodynamic surrogate (neural network on FUN3D C_L, C_D data)
- [ ] **Task 2** — Train ablation surrogate (neural network on FEAR mass loss / recession data)
- [ ] **Task 3** — Integrate surrogates into trajectory propagator
- [ ] **Task 3** — Landing footprint uncertainty quantification (Monte Carlo)

---

## License

Research code — Georgia Institute of Technology. Contact Kevin Y. Tang for reuse inquiries.
