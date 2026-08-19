"""Solver drivers and registry.

Adding a new solver = create a subclass of :class:`Solver`, register it in
:data:`SOLVERS`, and (if it needs a Python API) add the package to
``benchmark/pyproject.toml``. Nothing else in the harness needs to change.

Each driver:
  * reports ``version()`` so cached results are keyed per solver version
  * implements ``solve(instance, params, workdir) -> record`` where record
    contains status/runtime/objective/... (see below)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import run_capture, sha256_file

EMPTY_STATUS = ""


@dataclass
class RunParams:
    """Options shared by every solver (kept identical across solvers)."""

    threads: int = 12
    time_limit: float = 7200.0
    mip_gap: float = 1e-4
    # HiGHS-specific knobs (ignored by drivers that don't need them)
    highs_parallel: str = "on"
    instance_hash: str = ""
    options_hash: str = ""
    machine: str = ""
    run_date: str = ""


class Solver:
    """Base class for a benchmarked MIP solver."""

    name: str = ""

    def check_available(self) -> str | None:
        """Return None if usable, else an error string why not."""
        return None

    def version(self) -> str:
        raise NotImplementedError

    def solve(self, instance: Path, params: RunParams, workdir: Path) -> dict[str, Any]:
        raise NotImplementedError

    # -- helpers ---------------------------------------------------------
    def _base_record(self, instance: Path, params: RunParams) -> dict[str, Any]:
        return {
            "solver": self.name,
            "solver_version": self.version(),
            "instance": instance.stem,
            "instance_file": str(instance),
            "machine": params.machine,
            "threads": params.threads,
            "time_limit": params.time_limit,
            "mip_gap_tol": params.mip_gap,
            "instance_hash": params.instance_hash,
            "options_hash": params.options_hash,
            "run_date": params.run_date,
        }


# ------------------------------------------------------------------------
# HiGHS (local build)
# ------------------------------------------------------------------------
_HIGHS_RUNNABLE: dict[str, tuple[str, str]] = {}  # key -> (exe, version)


class HiGHSSolver(Solver):
    name = "highs"

    def __init__(self, executable: Path):
        self.executable = Path(executable)
        self._version: str | None = None
        self._bin_hash: str | None = None
        self._commit: str | None = None

    def check_available(self) -> str | None:
        if not self.executable.exists():
            return (f"HiGHS executable not found at {self.executable}. "
                    "Build it with benchmark/scripts/build_highs.sh first.")
        return None

    def version(self) -> str:
        if self._version is None:
            proc = run_capture([str(self.executable), "--version"], timeout=30)
            match = re.search(r"(\d+\.\d+\.\d+(?:\.\d+)?)", proc.stdout)
            self._version = match.group(1) if match else "unknown"
        return self._version

    def binary_hash(self) -> str:
        """Content hash of the binary - catches HiGHS edits where the version
        string did not change (the norm while developing)."""
        if self._bin_hash is None:
            self._bin_hash = sha256_file(self.executable)
        return self._bin_hash

    def source_commit(self) -> str | None:
        """Commit of the HiGHS tree the binary was built from (best effort)."""
        if self._commit is None:
            try:
                proc = run_capture(
                    ["git", "-C", str(Path(__file__).resolve().parents[2]),
                     "rev-parse", "--short", "HEAD"], timeout=15)
                self._commit = proc.stdout.strip() or None
            except Exception:  # noqa: BLE001
                self._commit = None
        return self._commit

    def solve(self, instance: Path, params: RunParams, workdir: Path) -> dict[str, Any]:
        sol_file = workdir / f"{instance.stem}.sol"
        log_file = workdir / f"{instance.stem}.log"
        cmd = [
            str(self.executable),
            "--model_file", str(instance),
            "--time_limit", f"{params.time_limit}",
            "--threads", f"{params.threads}",
            "--parallel", params.highs_parallel,
            "--solution_file", str(sol_file),
        ]
        t0 = time.monotonic()
        # Log goes to stdout (output_flag default on); keep it for parsing.
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT)
        runtime = time.monotonic() - t0
        log_file.write_text((proc.stdout or b"").decode(errors="replace"))

        record = self._base_record(instance, params)
        record["status"] = "error"
        record["runtime_s"] = float(f"{runtime:.3f}")
        record["returncode"] = proc.returncode
        record["objective"] = None
        record["dual_bound"] = None
        record["gap"] = None
        record["binary_sha256"] = self.binary_hash()
        record["highs_source_commit"] = self.source_commit()

        if proc.returncode != 0 or not sol_file.exists():
            return record

        try:
            lines = sol_file.read_text().splitlines()
        except OSError:
            return record

        status = "unknown"
        objective = None
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if status == "unknown" and line == "Model status":
                continue
            if status == "unknown":
                status = line
                continue
            m = re.match(r"Objective\s+(-?[0-9.eE+]+)", line)
            if m and objective is None:
                objective = float(m.group(1))
        record["status"] = status
        record["objective"] = objective
        if status == "Optimal":
            record["gap"] = 0.0
            record["dual_bound"] = objective
        else:
            # Extract the (dual) bound + gap from the solver log if present.
            rec = parse_highs_log(log_file)
            record["dual_bound"] = rec["dual_bound"]
            record["gap"] = rec["gap"]
        return record


def parse_highs_log(log_file: Path) -> dict[str, Any]:
    """Best-effort parse of the HiGHS MIP log for bound / gap.

    The MIP report may not expose a single parseable bound line across
    versions; miss when not found (never raises).
    """
    out: dict[str, Any] = {"dual_bound": None, "gap": None}
    if not log_file.exists():
        return out
    try:
        text = log_file.read_text(errors="replace")
    except OSError:
        return out

    m = re.search(r"Objective bound:\s*(-?[0-9.eE+]+)", text)
    if m:
        out["dual_bound"] = float(m.group(1))
    m = re.search(r"mip_rel_gap\s*=\s*([0-9.eE+-]+)", text)
    if m:
        try:
            out["gap"] = float(m.group(1))
        except ValueError:
            out["gap"] = None
    return out


# ------------------------------------------------------------------------
# Gurobi (via gurobipy in the benchmark venv)
# ------------------------------------------------------------------------
class GurobiSolver(Solver):
    name = "gurobi"

    def __init__(self) -> None:
        self._version: str | None = None

    def check_available(self) -> str | None:
        if shutil.which("gurobipy") is None and not _gurobipy_importable():
            return "gurobipy not importable - run `uv sync` in benchmark/ first."
        return None

    def version(self) -> str:
        if self._version is None:
            try:
                import gurobipy  # noqa: PLC0415
            except Exception:
                self._version = "unknown"
            else:
                vi = gurobipy.gurobi.version()
                self._version = ".".join(str(v) for v in vi)
        return self._version

    def solve(self, instance: Path, params: RunParams, workdir: Path) -> dict[str, Any]:
        from common import load_json  # noqa: PLC0415

        out_json = workdir / f"{instance.stem}.gurobi.json"
        runner = Path(__file__).resolve().parent / "gurobi_runner.py"
        cmd = [
            sys.executable,
            str(runner),
            "--instance", str(instance),
            "--out", str(out_json),
            "--threads", str(params.threads),
            "--time-limit", f"{params.time_limit}",
            "--mip-gap", f"{params.mip_gap}",
        ]
        t0 = time.monotonic()
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        runtime = time.monotonic() - t0

        record = self._base_record(instance, params)
        record["returncode"] = proc.returncode
        if proc.returncode != 0 or not out_json.exists():
            record["status"] = "error"
            record["runtime_s"] = round(runtime, 3)
            record["objective"] = None
            record["dual_bound"] = None
            record["gap"] = None
            record["nodes"] = None
            data = load_json(out_json) if out_json.exists() else None
            record["gurobi_error"] = (data or {}).get("error")
            return record

        from common import load_json  # noqa: PLC0415

        data = load_json(out_json) or {}
        record["status"] = data.get("status", "unknown")
        record["runtime_s"] = float(data.get("runtime_s", runtime))
        record["objective"] = data.get("objective")
        record["dual_bound"] = data.get("objbound")
        record["gap"] = data.get("mipgap")
        record["nodes"] = data.get("nodecount")
        record["gurobi_error"] = data.get("error")
        return record


def _gurobipy_importable() -> bool:
    try:
        import gurobipy  # noqa: PLC0415, F401
        return True
    except Exception:
        return False


# ------------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------------
def make_solvers(specs: list[str], highs_executable: Path | None = None) -> list[Solver]:
    """Create solver instances from names.

    ``specs`` may be any mixture of ``highs`` and ``gurobi`` (plus future
    drivers registered below).
    """
    registry: dict[str, type[Solver]] = {
        "highs": HiGHSSolver,
        "gurobi": GurobiSolver,
    }
    solvers: list[Solver] = []
    for spec in specs:
        name = spec.strip().lower()
        if name not in registry:
            raise SystemExit(f"Unknown solver '{spec}'. Known: {', '.join(registry)}")
        if name == "highs":
            if highs_executable is None:
                raise SystemExit("HiGHS requires --highs-bin (defaulting to build/bin/highs).")
            solvers.append(registry[name](highs_executable))
        else:
            solvers.append(registry[name]())
    return solvers


KNOWN_SOLVERS = ("highs", "gurobi")
