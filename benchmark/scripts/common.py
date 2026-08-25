"""Shared helpers for the benchmark harness (paths, hashing, result records)."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Directory layout under a results root:
#   results/{solver}/{solver_version}/{machine}/{set}/{instance}.json
# (`set` is the test-set tag: the folder the problems were dropped into, or an
# explicit --set name. Legacy flat records without a set dir are still readable.)
RESULT_INDEX = ["solver", "solver_version", "machine", "set", "instance"]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def benchmark_dir() -> Path:
    return repo_root() / "benchmark"


def instances_dir() -> Path:
    return benchmark_dir() / "instances"


def results_dir() -> Path:
    return benchmark_dir() / "results"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def options_hash(**opts: Any) -> str:
    """Deterministic hash of run-relevant options/parameters."""
    raw = json.dumps(opts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def machine_id() -> str:
    """A stable identifier for the machine the run executed on.

    Timings are not portable across machines, so results are keyed per
    machine; the identifier is intentionally coarse (CPU model + counts).
    """
    if sys.platform.startswith("linux"):
        try:
            info = {}
            with open("/proc/cpuinfo") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("model name"):
                        info["model"] = line.split(":", 1)[1].strip()
                    elif line.startswith("physical id"):
                        info.setdefault("sockets", set()).add(line.split(":", 1)[1].strip())
            with open("/proc/meminfo") as fh:
                for line in fh:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        info["ram_gb"] = round(kb / (1024 * 1024), 1)
                        break
            nproc = os.cpu_count() or 0
        except OSError:
            info = {"model": platform.processor() or platform.machine(), "ram_gb": None}
            nproc = os.cpu_count() or 0
        tag = [
            info.get("model") or "cpu",
            f"{nproc}cpu",
            (f"{info['ram_gb']}g" if info.get("ram_gb") else "ram?"),
        ]
    else:
        tag = [platform.machine(), platform.system(), f"{os.cpu_count() or 0}cpu"]
    raw = "-".join(re.sub(r"[^A-Za-z0-9]+", "-", str(part)).strip("-") for part in tag)
    raw = re.sub(r"-{2,}", "-", raw).strip("-").lower()
    if len(raw) > 110:
        raw = raw[:110] + "-" + hashlib.sha1(raw.encode()).hexdigest()[:8]
    return raw


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def save_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True))
    os.replace(tmp, path)


def result_path(results_root: Path, solver: str, solver_version: str,
                machine: str, instance: str, inst_set: str | None = None) -> Path:
    base = results_root / solver / solver_version / machine
    if inst_set:
        base = base / inst_set
    return base / f"{instance}.json"


def run_capture(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
