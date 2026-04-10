"""
doe_generator.py
================
Generates Design of Experiments cases from a nominal initial condition.

Supported methods:
  lhs           — Latin Hypercube Sampling (scipy.stats.qmc)
  full_factorial — all combinations of discrete levels
  random         — uniform random sampling
  from_file      — load pre-defined cases from a CSV

Usage (standalone):
  python doe_generator.py --config pipeline_config.yaml --output runs/doe_cases.csv

Returns:
  CSV file where each row is one DoE case with all perturbed parameters.
"""

import argparse
import csv
import itertools
import math
import random as _random
from pathlib import Path

import numpy as np
import yaml


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def generate(config: dict, output_path: Path) -> list[dict]:
    """
    Generate DoE cases and write them to *output_path*.

    Parameters
    ----------
    config : dict
        Parsed pipeline_config.yaml content.
    output_path : Path
        Destination CSV file.

    Returns
    -------
    list[dict]
        List of case parameter dicts (one per case).
    """
    nominal = config["nominal_ic"]
    ranges  = config["perturbation_ranges"]
    doe_cfg = config["doe"]

    method  = doe_cfg.get("method", "lhs").lower()
    n_cases = int(doe_cfg.get("n_cases", 21))
    seed    = doe_cfg.get("seed", 42)

    # Split variables into continuous and discrete
    continuous_vars, continuous_ranges = _parse_continuous(ranges)
    discrete_vars,   discrete_levels   = _parse_discrete(ranges)

    if method == "lhs":
        cases = _lhs(nominal, continuous_vars, continuous_ranges,
                     discrete_vars, discrete_levels, n_cases, seed)
    elif method == "full_factorial":
        cases = _full_factorial(nominal, continuous_vars, continuous_ranges,
                                discrete_vars, discrete_levels)
    elif method == "random":
        cases = _random_sample(nominal, continuous_vars, continuous_ranges,
                               discrete_vars, discrete_levels, n_cases, seed)
    elif method == "from_file":
        from_file = doe_cfg.get("from_file")
        if not from_file:
            raise ValueError("doe.from_file must specify a CSV path when method=from_file")
        cases = _from_file(Path(from_file), nominal)
    else:
        raise ValueError(f"Unknown DoE method: '{method}'. "
                         "Choose from: lhs, full_factorial, random, from_file")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(cases, output_path)
    print(f"[DoE] Generated {len(cases)} cases ({method}) → {output_path}")
    return cases


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _parse_continuous(ranges: dict):
    """Return (var_names, [(lo, hi), ...]) for variables with [min_delta, max_delta]."""
    names, bounds = [], []
    for var, val in ranges.items():
        if isinstance(val, list) and len(val) == 2 and not _is_discrete_list(val):
            names.append(var)
            bounds.append((float(val[0]), float(val[1])))
    return names, bounds


def _parse_discrete(ranges: dict):
    """Return (var_names, [levels_list, ...]) for variables with a list of absolute levels."""
    names, levels = [], []
    for var, val in ranges.items():
        if isinstance(val, list) and _is_discrete_list(val):
            names.append(var)
            levels.append([float(v) for v in val])
    return names, levels


def _is_discrete_list(val: list) -> bool:
    """A list with >2 elements, or any non-monotone 2-element list, is discrete."""
    if len(val) > 2:
        return True
    # 2-element list: treat as discrete if values are not min/max style
    # (convention: a range has val[0] < 0 or val[1] > 0 centered-ish around 0)
    return False


def _apply_nominal(nominal: dict, continuous_vars: list, continuous_deltas: list,
                   discrete_vars: list, discrete_choices: list) -> dict:
    """Build one case dict by applying deltas and discrete choices to nominal."""
    case = dict(nominal)
    for var, delta in zip(continuous_vars, continuous_deltas):
        if var == "Aref_pct":
            case["Aref"] = nominal["Aref"] * (1.0 + delta / 100.0)
        else:
            case[var] = nominal.get(var, 0.0) + delta
    for var, choice in zip(discrete_vars, discrete_choices):
        case[var] = choice
    return case


def _lhs(nominal, cont_vars, cont_ranges, disc_vars, disc_levels, n_cases, seed):
    """Latin Hypercube Sampling for continuous vars; random discrete assignment."""
    try:
        from scipy.stats.qmc import LatinHypercube, scale
    except ImportError:
        raise ImportError("scipy is required for LHS. Install with: pip install scipy")

    rng = np.random.default_rng(seed)
    cases = []

    if cont_vars:
        sampler = LatinHypercube(d=len(cont_vars), seed=seed)
        samples = sampler.random(n=n_cases)           # shape (n_cases, n_vars), in [0,1]
        lo = np.array([r[0] for r in cont_ranges])
        hi = np.array([r[1] for r in cont_ranges])
        deltas = scale(samples, lo, hi)               # scale to [lo, hi]
    else:
        deltas = np.empty((n_cases, 0))

    for i in range(n_cases):
        cont_deltas  = list(deltas[i]) if cont_vars else []
        disc_choices = [_random.choice(lvls) for lvls in disc_levels]
        case = _apply_nominal(nominal, cont_vars, cont_deltas, disc_vars, disc_choices)
        case["case_id"] = f"case_{i:03d}"
        cases.append(case)

    return cases


def _full_factorial(nominal, cont_vars, cont_ranges, disc_vars, disc_levels):
    """All combinations of discrete levels; continuous vars held at nominal (delta=0)."""
    if not disc_levels:
        # Nothing to vary discretely — return single nominal case
        case = dict(nominal)
        case["case_id"] = "case_000"
        return [case]

    combos = list(itertools.product(*disc_levels))
    cases = []
    for i, combo in enumerate(combos):
        cont_deltas  = [0.0] * len(cont_vars)
        disc_choices = list(combo)
        case = _apply_nominal(nominal, cont_vars, cont_deltas, disc_vars, disc_choices)
        case["case_id"] = f"case_{i:03d}"
        cases.append(case)
    return cases


def _random_sample(nominal, cont_vars, cont_ranges, disc_vars, disc_levels, n_cases, seed):
    """Uniform random sampling."""
    _random.seed(seed)
    rng = np.random.default_rng(seed)
    cases = []
    for i in range(n_cases):
        cont_deltas  = [rng.uniform(lo, hi) for lo, hi in cont_ranges]
        disc_choices = [_random.choice(lvls) for lvls in disc_levels]
        case = _apply_nominal(nominal, cont_vars, cont_deltas, disc_vars, disc_choices)
        case["case_id"] = f"case_{i:03d}"
        cases.append(case)
    return cases


def _from_file(csv_path: Path, nominal: dict) -> list[dict]:
    """Load cases directly from a CSV. Missing columns fall back to nominal value."""
    if not csv_path.exists():
        raise FileNotFoundError(f"from_file CSV not found: {csv_path}")
    cases = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            case = dict(nominal)
            for key, val in row.items():
                try:
                    case[key] = float(val)
                except (ValueError, TypeError):
                    case[key] = val
            if "case_id" not in case:
                case["case_id"] = f"case_{i:03d}"
            cases.append(case)
    return cases


def _write_csv(cases: list[dict], output_path: Path):
    if not cases:
        return
    fieldnames = list(cases[0].keys())
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cases)


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate DoE cases for TCFDS-FEAR pipeline")
    parser.add_argument("--config", default="pipeline_config.yaml",
                        help="Path to pipeline_config.yaml")
    parser.add_argument("--output", default=None,
                        help="Output CSV path (default: runs/doe_cases.csv relative to config)")
    args = parser.parse_args()

    config_path = Path(args.config)
    with open(config_path) as f:
        config = yaml.safe_load(f)

    if args.output:
        output_path = Path(args.output)
    else:
        pipeline_dir = config_path.parent
        runs_dir = (pipeline_dir / config["paths"]["runs_dir"]).resolve()
        output_path = runs_dir / "doe_cases.csv"

    generate(config, output_path)


if __name__ == "__main__":
    main()
