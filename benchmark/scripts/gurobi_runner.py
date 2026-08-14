"""Gurobi benchmark worker.

Runs a single instance through Gurobi's python interface and writes a JSON
result. Designed to be invoked by :mod:`solvers` as a subprocess so Gurobi's
license session is isolated per instance.

Usage:
    python gurobi_runner.py --instance FILE --out OUT.json \\
        --threads N --time-limit T --mip-gap G
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STATUS_NAMES = {
    1: "loaded",
    2: "optimal",
    3: "infeasible",
    4: "infeasible_or_unbounded",
    5: "unbounded",
    6: "cutoff",
    7: "iteration_limit",
    8: "node_limit",
    9: "time_limit",
    10: "solution_limit",
    11: "interrupted",
    12: "numerical",
    13: "suboptimal",
    14: "objective_limit",
    15: "user_obj_limit",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--threads", type=int, default=12)
    ap.add_argument("--time-limit", type=float, default=7200.0)
    ap.add_argument("--mip-gap", type=float, default=1e-4)
    args = ap.parse_args()

    record: dict = {"status": "error", "error": None}
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"gurobipy import failed: {exc}"
        write(args.out, record)
        return 2

    try:
        model = gp.read(str(args.instance))
        model.Params.Threads = args.threads
        model.Params.TimeLimit = args.time_limit
        model.Params.MIPGap = args.mip_gap
        model.Params.LogToConsole = 0
        model.optimize()
    except gp.GurobiError as exc:
        record["error"] = str(exc)
        write(args.out, record)
        return 1

    status = model.Status
    record["status"] = STATUS_NAMES.get(status, f"status_{status}")
    record["status_code"] = status
    try:
        record["runtime_s"] = float(model.Runtime)
    except Exception:  # noqa: BLE001
        record["runtime_s"] = None
    record["objective"] = _opt_float(model.ObjVal)
    record["objbound"] = _opt_float(model.ObjBound)
    record["mipgap"] = _opt_float(model.MIPGap)
    try:
        record["nodecount"] = int(model.NodeCount)
    except Exception:  # noqa: BLE001
        record["nodecount"] = None
    record["barrier_iter"] = _opt_int(model.BarIterCount)
    record["simplex_iter"] = _opt_int(model.IterCount)
    try:
        record["gurobi_version"] = ".".join(str(v) for v in gp.gurobi.version())
    except Exception:  # noqa: BLE001
        record["gurobi_version"] = None
    write(args.out, record)
    return 0


def _opt_float(value) -> float | None:
    try:
        f = float(value)
        return f
    except (TypeError, ValueError):
        return None


def _opt_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def write(path: Path, record: dict) -> None:
    record["run_date"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
