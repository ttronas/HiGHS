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
import subprocess
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

try:
    import yaml as _yaml  # noqa: F401
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False
from solvers import KNOWN_SOLVERS, RunParams, make_solvers  # noqa: E402

# Auto-repeat rule: solves faster than this are re-run so timing noise is
# averaged out (spec: <5 s solves get repeated 3 times).
REPEAT_THRESHOLD_S = 5.0
AUTO_REPEATS = 3


def git_provenance(repo: Path) -> dict[str, object]:
    """Commit + dirty flag of the working tree (provenance for transcripts)."""
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": None, "git_dirty": None}
    return {"git_commit": commit or None, "git_dirty": dirty}


def apply_repeat_stats(record: dict[str, object], times: list[float]) -> None:
    """Fold multiple runs into the record: runtime_s becomes the mean."""
    if len(times) <= 1:
        return
    times_sorted = sorted(times)
    mean = sum(times) / len(times)
    record["runs"] = [round(t, 4) for t in times]
    record["repeats"] = len(times)
    record["runtime_mean_s"] = round(mean, 4)
    record["runtime_min_s"] = round(times_sorted[0], 4)
    record["runtime_max_s"] = round(times_sorted[-1], 4)
    record["runtime_s"] = round(mean, 4)


def discover_instances(inst_root: Path) -> list[Path]:
    if not inst_root.exists():
        return []
    return sorted(set(p for p in inst_root.rglob("*") if p.is_file() and _is_model(p)))


def canonical_set_name(source: Path) -> str:
    name = source.stem if source.is_file() else source.name
    if name.endswith("-instances"):
        name = name[:-len("-instances")]
    return {"miplib2017-benchmark": "miplib2017"}.get(name, name)


def instances_from_file(instances_file: Path, roots: list[Path]) -> list[Path]:
    indexed: dict[str, list[Path]] = {}
    for root in roots:
        for instance in discover_instances(root.resolve()):
            indexed.setdefault(model_key(instance).lower(), []).append(instance)

    instances: list[Path] = []
    seen: set[Path] = set()
    missing: list[str] = []
    for raw in instances_file.read_text().splitlines():
        entry = raw.split("#", 1)[0].strip()
        if not entry:
            continue
        key = model_key(Path(entry)).lower()
        matches = indexed.get(key, [])
        if not matches:
            missing.append(entry)
            continue
        if len(matches) > 1:
            raise ValueError(f"ambiguous instance '{entry}': {matches}")
        instance = matches[0]
        if instance not in seen:
            instances.append(instance)
            seen.add(instance)
    if missing:
        raise ValueError(f"instances not found: {', '.join(missing)}")
    return instances


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
    ap.add_argument("--instances-root", type=Path, action="append", default=None,
                    help="directory with instance files; may repeat "
                         f"(default {instances_dir()})")
    ap.add_argument("--instances-file", type=Path, default=None,
                    help="file listing instance names; derives result set name")
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
                    help="test-set tag override for ad-hoc sources")
    ap.add_argument("--prune", action="store_true",
                    help="delete cached results for instances that are no longer "
                         "present in this set's folder before running")
    ap.add_argument("--force", action="store_true",
                    help="ignore cache and re-run every selected instance")
    ap.add_argument("--repeats", default="auto", metavar="N|auto",
                    help="runs per instance; 'auto' repeats fast solves "
                         f"(<{REPEAT_THRESHOLD_S}s) {AUTO_REPEATS}x and averages "
                         "(default auto). Averaged runs are stored as runs[], "
                         "runtime_mean_s/min/max, with runtime_s = mean.")
    ap.add_argument("--no-cache", action="store_true",
                    help="ignore cached results: re-benchmark instances that "
                         "already have a results file (identical to --force "
                         "for the cache-skip decision; kept as a distinct flag)")
    ap.add_argument("--highs-options", type=str, default=None,
                    help="JSON string of HiGHS options passed without rebuild "
                         "(e.g. '{\"presolve\":\"off\",\"mip_heuristic_effort\":0.2}')")
    ap.add_argument("--highs-options-file", type=Path, default=None,
                    help="YAML or JSON file mapping HiGHS option name -> value "
                         "(all params changeable; no rebuild needed)")
    ap.add_argument("--workdir", type=Path, default=None,
                    help="scratch dir for temp files (default $TMPDIR/benchmark)")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[2]
    roots = args.instances_root or [instances_dir()]
    if len(roots) > 1 and not args.instances_file:
        print("error: multiple --instances-root requires --instances-file")
        return 1
    inst_root = roots[0]
    results_root = args.results_root or results_dir()
    source = args.instances_file or inst_root
    expected_set = canonical_set_name(source)
    if args.set and expected_set in {"fast", "super-fast", "miplib2017"} and \
            args.set != expected_set:
        print(f"error: {source.name} requires result set '{expected_set}'")
        return 1
    inst_set = args.set or expected_set
    highs_bin = args.highs_bin or (repo / "build" / "bin" / "highs")

    solvers = make_solvers(args.solver, Path(highs_bin))

    if args.instances_file:
        if not args.instances_file.is_file():
            print(f"instances file not found: {args.instances_file}")
            return 1
        search_roots = roots + [
            repo / "benchmark" / "examples",
            repo / "benchmark" / "sets" / "miplib2017-benchmark",
        ]
        unique_roots: list[Path] = []
        for root in search_roots:
            resolved_root = root.resolve()
            if resolved_root not in unique_roots:
                unique_roots.append(resolved_root)
        try:
            instances = instances_from_file(args.instances_file, unique_roots)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
    else:
        instances = discover_instances(inst_root)
    if not instances:
        print(f"no instances found under {source}")
        print("run:  uv run python scripts/download_instances.py")
        return 1

    if args.instance:
        wanted = {model_key(Path(w)).lower() for w in args.instance}
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

    if args.repeats == "auto":
        fixed_repeats, auto_repeats = 1, True
    else:
        try:
            fixed_repeats = int(args.repeats)
        except ValueError:
            print(f"error: --repeats must be an integer or 'auto', got {args.repeats!r}")
            return 1
        if fixed_repeats < 1:
            print("error: --repeats must be >= 1")
            return 1
        auto_repeats = False

    # ---- HiGHS runtime options (no rebuild needed) -----------------
    highs_options: dict = {}
    if args.highs_options:
        import json as _json
        try:
            highs_options.update(_json.loads(args.highs_options))
        except Exception as exc:
            print(f"error: --highs-options invalid JSON: {exc}")
            return 1
    if args.highs_options_file:
        if not args.highs_options_file.is_file():
            print(f"error: --highs-options-file not found: {args.highs_options_file}")
            return 1
        import json as _json
        text = args.highs_options_file.read_text()
        try:
            if args.highs_options_file.suffix in (".yaml", ".yml"):
                if not _HAS_YAML:
                    print("error: YAML options file requires pyyaml (uv sync)")
                    return 1
                import yaml as _yaml2
                data = _yaml2.safe_load(text) or {}
            else:
                data = _json.loads(text)
        except Exception as exc:
            print(f"error: parsing {args.highs_options_file}: {exc}")
            return 1
        if not isinstance(data, dict):
            print(f"error: {args.highs_options_file} must contain a mapping")
            return 1
        highs_options.update(data)
    if highs_options:
        print(f"highs_options: {highs_options}")

    provenance = git_provenance(repo)

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
                              mip_gap=args.mip_gap, highs_parallel=args.highs_parallel,
                              repeats_policy=args.repeats,
                              highs_options=highs_options)
            params = RunParams(
                threads=args.threads,
                time_limit=args.time_limit,
                mip_gap=args.mip_gap,
                highs_parallel=args.highs_parallel,
                highs_options=highs_options,
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

            n_runs = fixed_repeats if not auto_repeats else 1
            times: list[float] = []
            record: dict[str, object] | None = None
            while True:
                print(f"  running {solver.name} {inst.stem} "
                      f"(run {len(times) + 1}/{n_runs})...",
                      end=" ", flush=True)
                record = solver.solve(inst, params, workdir)
                record["solver_version"] = version
                record["instance_set"] = inst_set
                record.update(provenance)
                times.append(float(record["runtime_s"]))
                print(f"{record['status']} t={record['runtime_s']:8.2f}s")
                # Auto policy: a first solve under the threshold triggers
                # repetition to AUTO_REPEATS total runs (averaged later).
                if (auto_repeats and len(times) == 1
                        and record.get("status") != "error"
                        and times[-1] < REPEAT_THRESHOLD_S):
                    n_runs = AUTO_REPEATS
                if record.get("status") == "error" or len(times) >= n_runs:
                    break
            apply_repeat_stats(record, times)

            tag = f"{record['status']} t={record['runtime_s']:8.2f}s"
            if record.get("repeats"):
                tag += f" ({record['repeats']} runs averaged)"
            if record.get("objective") is not None:
                tag += f" obj={record['objective']:.9g}"
            save_json(dest, record)
            print(tag)

    print("\ndone")
    print(f"summarize with:  uv run python scripts/summarize.py")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
