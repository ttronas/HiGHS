"""Run the MIPLIB benchmark for one or more solvers, with result caching.

Design:
  * Both solvers get identical threads / time-limit / MIP-gap (matching the
    Mittelmann setup at https://plato.asu.edu/ftp/milp.html).
  * Results are cached at
        results/{solver}/{solver_version}/{machine}/{instance}.json
    so Gurobi (or any solver) is only re-run when its version, the options,
    or the machine change. Delete the file (or pass --force) to re-run.
  * A run whose file already exists is reported as "cached" and skipped.

Examples (inside the devcontainer, from benchmark/):
  uv run python scripts/run_benchmark.py --solver highs gurobi --subset 3
  uv run python scripts/run_benchmark.py --solver gurobi --subset 1 --force
  uv run python scripts/run_benchmark.py --solver highs --instance p_air05
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    instances_dir,
    load_json,
    machine_id,
    options_hash,
    results_dir,
    result_path,
    save_json,
    sha256_file,
    utcnow_iso,
)
from solvers import KNOWN_SOLVERS, RunParams, make_solvers  # noqa: E402


def discover_instances(inst_root: Path) -> list[Path]:
    if not inst_root.exists():
        return []
    return sorted(set(p for p in inst_root.rglob("*") if p.is_file() and _is_model(p)))


def _is_model(p: Path) -> bool:
    name = p.name.lower()
    if name.endswith((".mps", ".lp")):
        return True
    if name.endswith((".mps.gz", ".lp.gz", ".mps.zst")):
        return True
    return False


_MODEL_SUFFIXES = (".mps", ".lp", ".mps.gz", ".lp.gz", ".mps.zst", ".zst", ".gz")


def model_key(p: Path) -> str:
    """Canonical instance name, e.g. `30n20b8.mps.gz` -> `30n20b8`."""
    name = p.name
    changed = True
    while changed:
        changed = False
        for suf in _MODEL_SUFFIXES:
            if name.lower().endswith(suf):
                name = name[: -len(suf)]
                changed = True
        # .gz is inside the *_suffix above; no infinite loop since we only shrink.
    return name


def prune_results(results_root: Path, inst_set: str, active_stems: set[str]) -> int:
    """Remove cached results whose instance no longer exists in the set folder.

    Only touches the nested layout results/{solver}/{ver}/{machine}/{set}/.
    """
    removed = 0
    if not results_root.exists():
        return removed
    for solver_dir in results_root.iterdir():
        if not solver_dir.is_dir():
            continue
        for version_dir in solver_dir.iterdir():
            if not version_dir.is_dir():
                continue
            for machine_dir in version_dir.iterdir():
                if not machine_dir.is_dir():
                    continue
                set_dir = machine_dir / inst_set
                if not set_dir.is_dir():
                    continue
                for jf in set_dir.glob("*.json"):
                    if jf.stem not in active_stems:
                        jf.unlink(missing_ok=True)
                        removed += 1
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="MIPLIB benchmark runner (cached).")
    ap.add_argument("--solver", nargs="+", choices=KNOWN_SOLVERS,
                    default=["highs", "gurobi"], metavar="NAME",
                    help="solvers to run (default: highs gurobi)")
    ap.add_argument("--instances-root", type=Path, default=None,
                    help="directory with instance files " f"(default {instances_dir()})")
    ap.add_argument("--results-root", type=Path, default=None,
                    help="root for result caches (default {results_dir()})")
    ap.add_argument("--highs-bin", type=Path, default=None,
                    help="HiGHS executable (default <repo>/build/bin/highs)")
    ap.add_argument("--threads", type=int, default=12,
                    help="solver threads - same for every solver (default 12)")
    ap.add_argument("--time-limit", type=float, default=7200.0,
                    help="per-instance time limit in seconds (default 7200)")
    ap.add_argument("--mip-gap", type=float, default=1e-4,
                    help="relative MIP gap tolerance (default 1e-4)")
    ap.add_argument("--highs-parallel", choices=["on", "off"],
                    default="on", help="HiGHS --parallel (default on)")
    ap.add_argument("--subset", type=int, default=None, metavar="N",
                    help="limit to the first N instances (smoke test)")
    ap.add_argument("--instance", action="append", default=[], metavar="NAME",
                    help="only run the named instance(s); may repeat")
    ap.add_argument("--set", default=None, metavar="NAME",
                    help="test-set tag for the cache path (default: the name of "
                         "--instances-root), so dropped problems never collide "
                         "with other sets' caches")
    ap.add_argument("--prune", action="store_true",
                    help="delete cached results for instances that are no longer "
                         "present in this set's folder before running")
    ap.add_argument("--force", action="store_true",
                    help="ignore cache and re-run every selected instance")
    ap.add_argument("--no-cache", action="store_true",
                    help="ignore cached results: re-benchmark instances that "
                         "already have a results file (identical to --force "
                         "for the cache-skip decision; kept as a distinct flag)")
    ap.add_argument("--workdir", type=Path, default=None,
                    help="scratch dir for temp files (default $TMPDIR/benchmark)")
    args = ap.parse_args()

    inst_root = args.instances_root or instances_dir()
    results_root = args.results_root or results_dir()
    inst_set = args.set or inst_root.name
    highs_bin = args.highs_bin or (inst_root.parent.parent / "build" / "bin" / "highs")
    if not Path(highs_bin).exists():
        # fall back to common repo layout
        repo = Path(__file__).resolve().parents[2]
        highs_bin = repo / "build" / "bin" / "highs"

    solvers = make_solvers(args.solver, Path(highs_bin))

    instances = discover_instances(inst_root)
    if not instances:
        print(f"no instances found under {inst_root}")
        print("run:  uv run python scripts/download_instances.py")
        return 1

    if args.instance:
        wanted = {w.lower() for w in args.instance}
        instances = [p for p in instances if model_key(p).lower() in wanted]
        have = {model_key(p).lower() for p in instances}
        if wanted != have:
            miss = sorted(wanted - have)
            print(f"warning: instance(s) not found: {miss}")
    if args.subset:
        instances = instances[: args.subset]
    print(f"instances: {len(instances)}")
    print(f"set: {inst_set}")

    if args.prune:
        removed = prune_results(results_root, inst_set,
                                {p.stem for p in instances})
        if removed:
            print(f"pruned {removed} stale cached result(s)")
        else:
            print("prune: nothing to remove")

    machine = machine_id()
    workdir = args.workdir or (Path.home() / ".benchmark-work")
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"machine: {machine}")

    all_ok = True
    for solver in solvers:
        available = solver.check_available()
        if available:
            print(f"\n[solver] {solver.name}: SKIPPED - {available}")
            all_ok = False
            continue
        version = solver.version()
        print(f"\n[solver] {solver.name} {version}")
        for inst in instances:
            ih = sha256_file(inst)
            oh = options_hash(threads=args.threads, time_limit=args.time_limit,
                              mip_gap=args.mip_gap, highs_parallel=args.highs_parallel)
            params = RunParams(
                threads=args.threads,
                time_limit=args.time_limit,
                mip_gap=args.mip_gap,
                highs_parallel=args.highs_parallel,
                instance_hash=ih,
                options_hash=oh,
                machine=machine,
                run_date=utcnow_iso(),
            )
            dest = result_path(results_root, solver.name, version, machine,
                               inst.stem, inst_set=inst_set)
            stale = False
            if dest.exists() and not args.force and not args.no_cache:
                old = load_json(dest)
                key_ok = bool(old and old.get("instance_hash") == ih and
                              old.get("options_hash") == oh)
                if old and (old.get("status") == "error" or not key_ok):
                    stale = True
                elif key_ok:
                    # HiGHS edits don't bump the version string - treat a
                    # changed binary as a cache miss.
                    if solver.name == "highs" and \
                            old.get("binary_sha256") != getattr(solver, "binary_hash", lambda: None)():
                        stale = True
                    else:
                        print(f"  cached {inst.stem}")
                        continue
            if stale:
                print(f"  re-running {inst.stem} (stale cache)")
            print(f"  running {solver.name} {inst.stem} ...", end=" ", flush=True)
            record = solver.solve(inst, params, workdir)
            record["solver_version"] = version
            record["instance_set"] = inst_set
            save_json(dest, record)
            tag = f"{record['status']} t={record['runtime_s']:8.2f}s"
            if record.get("objective") is not None:
                tag += f" obj={record['objective']:.9g}"
            print(tag)

    print("\ndone")
    print(f"summarize with:  uv run python scripts/summarize.py")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
