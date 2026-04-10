# Pipeline README

Step-by-step guide for deploying and running the TCFDS → FEAR training data pipeline on a shared server.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Repository Setup](#2-repository-setup)
3. [Environment Setup](#3-environment-setup)
4. [Configuration](#4-configuration)
5. [Pre-build FUN3D Meshes](#5-pre-build-fun3d-meshes)
6. [Run the Pipeline](#6-run-the-pipeline)
7. [Resume After Interruption](#7-resume-after-interruption)
8. [Output Files](#8-output-files)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

### Python packages

```
numpy
scipy          # LatinHypercube sampler
f90nml         # Fortran namelist I/O
pyyaml         # pipeline_config.yaml parsing
pyCAPS         # ESP Engineering Sketch Pad Python interface
```

Install with:

```bash
pip install numpy scipy f90nml pyyaml
# pyCAPS is bundled with ESP — see ESP installation notes below
```

### ESP / pyCAPS (Engineering Sketch Pad)

pyCAPS ships with the ESP (Engineering Sketch Pad) distribution. You must enter the ESP shell environment before running any FUN3D or pyCAPS commands.

> **API compatibility:** The `prebuild_fun3d_meshes.py` script targets ESP 1.28+ (pyCAPS ≥ 3.x). The older `workDir` keyword argument to `pyCAPS.Problem()` was removed in newer versions; the script does not use it.

```bash
source /path/to/ESP/ESPenv.sh    # sets PATH, LD_LIBRARY_PATH, etc.
```

Verify the environment is active:

```bash
python -c "import pyCAPS; print(dir(pyCAPS))"
```

> **Note:** Some ESP versions do not expose `pyCAPS.__version__`. The `dir()` check above is more reliable.

### FUN3D

FUN3D must be compiled and installed. The pipeline expects `nodet_mpi` (the parallel FUN3D executable). Update `paths.fun3d_executable` in `pipeline_config.yaml` to the full absolute path.

Verify:

```bash
which nodet_mpi    # or full path
mpirun --version
```

### FEAR (Finite Element Ablation and Thermal Response)

The `./FEAR` executable must exist and be executable. Update `paths.fear_executable` in `pipeline_config.yaml`. FEAR runs sequentially (one case at a time).

```bash
chmod +x /path/to/FEAR
/path/to/FEAR --help    # or just ./FEAR to confirm it starts
```

### MPI

MPI (OpenMPI or MPICH) is required for FUN3D parallel runs. Confirm:

```bash
mpirun -np 1 hostname
```

---

## 2. Repository Setup

Clone with submodules (the trajectory solver lives in a git submodule):

```bash
git clone --recurse-submodules https://github.com/kevinytang/TCFDS_FEAR_Integration.git
cd TCFDS_FEAR_Integration
```

If you cloned without `--recurse-submodules`, initialize the submodule manually:

```bash
git submodule update --init --recursive
```

Compile the Fortran trajectory executable inside the submodule:

```bash
cd Trajectory_CFD_Integration/Reentry_3DOF_NonPlanar/
make          # or gfortran reentry.f90 -o reentry.exe
cd ../../
```

---

## 3. Environment Setup

Create and activate a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install numpy scipy f90nml pyyaml
```

> **Important:** Always activate both the `.venv` and the ESP shell environment before running any pipeline commands:
>
> ```bash
> source /path/to/ESP/ESPenv.sh
> source .venv/bin/activate
> ```

---

## 4. Configuration

Copy and edit `Pipeline/pipeline_config.yaml`. The key fields to set for your server:

```yaml
paths:
  fear_executable:   /absolute/path/to/FEAR        # ← set this
  fun3d_executable:  /absolute/path/to/nodet_mpi   # ← set this
  tcfds_dir:         ../Trajectory_CFD_Integration
  mesh_inputs_dir:   ../Mesh_Inputs
  fun3d_meshes_dir:  ../fun3d_meshes
  runs_dir:          ../runs
  training_data_dir: ../training_data

tcfds:
  max_parallel_cases: 3    # ← tune to available CPU cores
  mpi_procs:          10   # ← MPI ranks per FUN3D call
```

### DoE settings

```yaml
doe:
  n_cases: 21      # number of perturbed trajectory cases to generate
  method:  lhs     # lhs | full_factorial | random | from_file
  seed:    42      # random seed for reproducibility
```

Available DoE methods:

| `method` | Description |
|---|---|
| `lhs` | Latin Hypercube Sampling — best space coverage for NN training data |
| `full_factorial` | All combinations of discrete + continuous levels |
| `random` | Uniform random sampling |
| `from_file` | Read cases from a pre-existing CSV; set `from_file: path/to/cases.csv` |

### Perturbation ranges

The nominal trajectory IC and the perturbation ranges around it are set in `pipeline_config.yaml`. Edit `nominal_ic` and `perturbation_ranges` to match your vehicle and scenario:

```yaml
nominal_ic:
  V0:         12765.0    # m/s
  gamma0:     -7.412     # deg
  psi0:       352.8      # deg
  alt0:       82701.0    # m
  lon0:       240.7917   # deg
  lat0:       41.2323    # deg
  alpha0:     2.4        # deg angle of attack
  cone_angle: 59.6       # deg (discrete: 50 | 59.6 | 70)
  mass:       45.7       # kg
  Aref:       0.516159   # m²

perturbation_ranges:
  V0:         [-200.0, 200.0]
  gamma0:     [-0.5,   0.5  ]
  psi0:       [-5.0,   5.0  ]
  alt0:       [-500.0, 500.0]
  lon0:       [-2.0,   2.0  ]
  lat0:       [-2.0,   2.0  ]
  cone_angle: [50, 59.6, 70]   # discrete list — randomly assigned
  mass:       [-2.0,   2.0 ]
  Aref_pct:   [-5.0,   5.0 ]   # percentage perturbation applied to Aref
```

### Geometry files

Each cone angle maps to specific geometry files. The paths under `geometry_files` point inside `Mesh_Inputs/` for the FEAR 2D Gmsh mesh (`.msh`) and inside `fun3D_Solver/` for the FUN3D geometry (`.csm`). These typically do not need to change unless new geometries are added.

---

## 5. Pre-build FUN3D Meshes

FUN3D needs a 3D unstructured volume mesh (`.b8.ugrid`) generated once per vehicle geometry via pyCAPS (AFLR4 surface mesh + AFLR3 volume mesh). Pre-building avoids regenerating the mesh on every CFD call.

> **Note:** This is the FUN3D 3D mesh only. The FEAR 2D Gmsh mesh (`.msh` in `Mesh_Inputs/`) is a completely separate mesh and does not need to be regenerated.

```bash
cd TCFDS_FEAR_Integration/
source /path/to/ESP/ESPenv.sh
source .venv/bin/activate

python Pipeline/prebuild_fun3d_meshes.py --config Pipeline/pipeline_config.yaml
```

This will:
- Run AFLR4 + AFLR3 for each cone geometry (50°, 59.6°, 70°)
- Store resulting mesh files in `fun3d_meshes/cone_XXdeg/`
- Write `mesh_ready.flag` upon completion

To force regeneration of an existing mesh:

```bash
python Pipeline/prebuild_fun3d_meshes.py --config Pipeline/pipeline_config.yaml --force
```

Pre-building takes on the order of 10–30 minutes per geometry. Once done, all pipeline runs will reuse the pre-built meshes.

---

## 6. Run the Pipeline

From the repository root (with both ESP and `.venv` environments active):

```bash
python Pipeline/doe_pipeline.py --config Pipeline/pipeline_config.yaml
```

### Common options

```
--config       Path to pipeline_config.yaml (default: Pipeline/pipeline_config.yaml)
--n-cases N    Override the number of cases from the config (e.g., --n-cases 5 for a test run)
--resume       Skip cases that already have completed outputs (see below)
--skip-prebuild  Skip Stage 0 mesh pre-build (assumes meshes already exist)
```

### What happens

```
Stage 0:  Pre-build FUN3D meshes (skipped if mesh_ready.flag exists per geometry)
Stage 1:  Generate DoE cases → runs/doe_cases.csv
Stage 2:  Run TCFDS for each case (parallel, up to max_parallel_cases at once)
            Each case: runs/case_000/ … case_020/
              config.nml, history.csv
Stage 3:  Write FEAR inputs for each case
            runs/case_000/fear_inputs/
              FEARin.dat, FEAR_BC.dat, sf_list.txt, <geometry>.msh
Stage 4:  Run FEAR for each case (sequential)
            runs/case_000/fear_outputs/
              out_001.dat … out_N.dat, TCdata_*.dat
Stage 5:  Extract time history from FEAR outputs
            training_data/case_000_history.csv
Stage 6:  Write aggregate summary
            training_data/summary.csv
```

### Example: small test run

```bash
# Run 1 nominal case to verify the full pipeline works end-to-end
python Pipeline/doe_pipeline.py --n-cases 1 --skip-prebuild
```

### Example: full 21-case run

```bash
python Pipeline/doe_pipeline.py --n-cases 21
```

---

## 7. Resume After Interruption

If the pipeline is interrupted (network drop, job timeout, etc.), restart with `--resume`:

```bash
python Pipeline/doe_pipeline.py --resume
```

Resume logic:
- **TCFDS already done:** `runs/case_XXX/history.csv` exists and is non-empty → skip TCFDS re-run
- **FEAR already done:** `runs/case_XXX/fear_outputs/` contains `out_*.dat` files → skip FEAR re-run
- Cases not yet started are run normally

The DoE case list (`runs/doe_cases.csv`) is regenerated with the same seed, so case assignments are reproducible.

---

## 8. Output Files

### Per-case outputs

```
runs/
  doe_cases.csv                     # DoE table: one row per case, all parameters
  case_000_nominal/                 # or case_001, case_002, ...
    config.nml                      # Fortran namelist: ICs and CFD state
    history.csv                     # TCFDS trajectory time history (step, time, v, alt, CL, CD, ...)
    fear_inputs/
      FEARin.dat                    # FEAR simulation control file
      FEAR_BC.dat                   # Boundary conditions (heating, pressure, radiation)
      sf_list.txt                   # Spatial multiplier list (geometry-fixed)
      Stardust_054_59deg.msh        # FEAR 2D Gmsh mesh (geometry-fixed copy)
    fear_outputs/
      out_001.dat … out_N.dat       # FEAR Tecplot fepoint snapshots (every 0.06 s)
      TCdata_*.dat                  # FEAR temperature/carbon data
```

### Training data outputs

```
training_data/
  case_000_history.csv              # Time history of ablation quantities, ~5 s intervals
  case_001_history.csv
  ...
  summary.csv                       # One row per case: IC params + peak/integrated quantities
```

#### `case_XXX_history.csv` columns

| Column | Units | Description |
|---|---|---|
| `time_s` | s | Simulation time |
| `frontal_area_m2` | m² | Current frontal area (axisymmetric) |
| `frontal_area_loss_m2` | m² | Area lost since t=0 |
| `mass_loss_kg` | kg | Ablated mass since t=0 |
| `stag_recession_mm` | mm | Stagnation point recession depth |

#### `summary.csv` columns

Input parameters (V0, gamma0, psi0, alt0, lon0, lat0, cone_angle, mass, Aref) plus:

| Column | Description |
|---|---|
| `peak_mach` | Maximum Mach number during trajectory |
| `peak_q_stag` | Peak stagnation heat flux (W/m²) |
| `total_flight_time` | Total trajectory duration (s) |
| `total_mass_loss_kg` | Total ablated mass |
| `total_frontal_area_loss_m2` | Total frontal area lost |
| `max_stag_recession_mm` | Maximum stagnation recession |

---

## 9. Troubleshooting

### `FEAR executable not found`

Check the `paths.fear_executable` value in `pipeline_config.yaml`. Use an absolute path:

```yaml
paths:
  fear_executable: /home/username/FEAR/FEAR
```

Ensure it is executable: `chmod +x /path/to/FEAR`

### `FUN3D nodet_mpi not found` / MPI errors

Set the full path in the config:

```yaml
paths:
  fun3d_executable: /home/username/fun3d/build/nodet_mpi
```

Verify MPI is available: `which mpirun` or `module load openmpi`

### `EGADS_NOTFOUND` / `caps_build Error: ocsmBuild fails!` during mesh prebuild

This error means EGADS could not find the `.STEP` geometry file referenced by a `.csm` file.

**Check 1 — STEP files are present.** All three geometry files must exist in `Trajectory_CFD_Integration/fun3D_Solver/`:

```
Stardust_054_59deg.STEP
054_50deg.STEP
054_70deg.STEP
```

**Check 2 — STEP files have Unix line endings.** If the files were created or edited on Windows they will have CRLF line endings, which EGADS cannot parse. Convert them:

```bash
sed -i 's/\r//' Trajectory_CFD_Integration/fun3D_Solver/*.STEP
```

Verify with `file *.STEP` — the output should say `ASCII text`, not `ASCII text, with CRLF line terminators`.

### `pyCAPS not found` / `import pyCAPS` fails

The ESP environment is not active. Run:

```bash
source /path/to/ESP/ESPenv.sh
python -c "import pyCAPS"
```

Check your ESP installation directory — `ESPenv.sh` or `ESPenv.csh` should be at the top level.

### `config.nml not found` in TCFDS run

The template `config.nml` must exist inside the `Trajectory_CFD_Integration/` submodule. Verify:

```bash
ls Trajectory_CFD_Integration/config.nml
```

If missing, it should be part of the submodule. Pull latest:

```bash
git submodule update --remote
```

### Empty or missing `history.csv`

The trajectory executable (`reentry.exe`) or CFD solver failed silently. Check:

1. Is `reentry.exe` compiled? `ls Trajectory_CFD_Integration/Reentry_3DOF_NonPlanar/reentry.exe`
2. Run a single case manually to see the error output:

```bash
cd runs/case_000/
python ../../Trajectory_CFD_Integration/control.py \
    --workdir . \
    --config config.nml \
    --mesh-dir ../../fun3d_meshes/cone_59deg
```

### FEAR produces no `out_*.dat` files

FEAR requires all input files to be present in the same directory before it runs. Check `runs/case_XXX/fear_inputs/` contains:

- `FEARin.dat`
- `FEAR_BC.dat`
- `sf_list.txt`
- The `.msh` mesh file named exactly as referenced in `FEARin.dat` line 1

Run FEAR manually to see its error output:

```bash
cd runs/case_000/fear_inputs/
/path/to/FEAR
```

### `scipy.stats.qmc` not found

Requires scipy ≥ 1.7. Upgrade:

```bash
pip install --upgrade scipy
```

### Pipeline runs hang with no output

TCFDS cases may be deadlocked inside MPI. Check with:

```bash
ps aux | grep nodet_mpi
```

Reduce `max_parallel_cases` or `mpi_procs` in the config to avoid over-subscribing cores.

### Out-of-disk-space

Each FEAR run produces many `out_*.dat` snapshot files (one per 0.06 s timestep). For a 300 s trajectory that is ~5000 files per case. Plan for ~1–5 GB per case depending on mesh size. Clean up `fear_outputs/` for completed cases if disk is limited.
