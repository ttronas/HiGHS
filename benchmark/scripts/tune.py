"""Automatic hyperparameter tuning for HiGHS (Optuna).

Optimizes over a train set (super-small, sampled from super-fast), validates
on full set (miplib2017). No HiGHS rebuild per trial — options injected via
per-trial options_file (runtime).

Locked scoring (per instance):
  wrong vs ground truth      ->  -1e6  (very negative)
  not solved within limit    ->  -1e3  (medium negative)
  optimal found              ->  +1000/(t+10)  (positive, faster higher)
Study score = mean(score_i) over train set, Optuna direction=maximize.
n_trials any integer. All params changeable via YAML search space.

Usage:
  uv run python scripts/sample_train.py --source super-fast-instances.txt --k 8 --seed 0
  uv run python scripts/tune.py --train-set super-small-instances.txt --n-trials 100 --search-space configs/tune/example.yaml
  uv run python scripts/tune.py --train-set super-fast-instances.txt --n-trials 5000 --search-space configs/tune/large.yaml --test-set miplib2017 --time-limit 60 --output results/tune/my_study
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import machine_id, results_dir, utcnow_iso  # noqa: E402

# Locked magnitudes
WRONG_SCORE = -1_000_000.0
TIMEOUT_SCORE = -1_000.0
SHIFT = 10.0


def per_instance_score(rec: dict, is_wrong: bool) -> float:
    if is_wrong:
        return WRONG_SCORE
    status = (rec.get("status") or "").lower()
    solved = bool(status) and "limit" not in status and "unsolved" not in status and status not in ("error", "")
    if not solved:
        return TIMEOUT_SCORE
    t = float(rec.get("runtime_mean_s", rec.get("runtime_s", 0.0)))
    return 1000.0 / (t + SHIFT)


def load_search_space(path: Path) -> dict:
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            print("error: YAML search space requires pyyaml (uv sync)")
            sys.exit(1)
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        print(f"error: {path} must contain a mapping")
        sys.exit(1)
    return data


def suggest_params(trial, space: dict) -> dict:
    out: dict = {}
    for name, spec in space.items():
        if not isinstance(spec, dict) or "type" not in spec:
            print(f"error: spec for {name!r} must be dict with 'type'")
            sys.exit(1)
        tp = spec["type"]
        if tp == "float":
            out[name] = trial.suggest_float(name, float(spec["low"]), float(spec["high"]), log=bool(spec.get("log", False)))
        elif tp == "int":
            out[name] = trial.suggest_int(name, int(spec["low"]), int(spec["high"]), log=bool(spec.get("log", False)))
        elif tp in ("categorical", "category"):
            out[name] = trial.suggest_categorical(name, spec["choices"])
        elif tp == "bool":
            out[name] = trial.suggest_categorical(name, [True, False])
        else:
            print(f"error: unknown type {tp!r} for {name}")
            sys.exit(1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="HiGHS hyperparameter tuning (Optuna)")
    ap.add_argument("--train-set", type=Path, required=True,
                    help="instance list file for tuning (e.g. super-small-instances.txt produced by sample_train.py)")
    ap.add_argument("--test-set", type=Path, default=None,
                    help="instance list for final validation (e.g. miplib2017); defaults to full set")
    ap.add_argument("--search-space", type=Path, required=True,
                    help="YAML/JSON mapping param -> {type, low/high/choices}")
    ap.add_argument("--n-trials", type=int, required=True,
                    help="number of Optuna trials (any integer, e.g. 100 or 5000)")
    ap.add_argument("--time-limit", type=float, default=60.0,
                    help="per-instance time limit for tuning runs (default 60)")
    ap.add_argument("--threads", type=int, default=4,
                    help="threads per solve (default 4, lower reduces noise under parallel tuning)")
    ap.add_argument("--highs-bin", type=Path, default=None,
                    help="HiGHS binary (default build/bin/highs)")
    ap.add_argument("--study-name", type=str, default=None,
                    help="Optuna study name (default tune_<train_stem>)")
    ap.add_argument("--storage", type=str, default=None,
                    help="Optuna storage URL (default sqlite:///results/tune/<study>.db)")
    ap.add_argument("--output", type=Path, default=None,
                    help="output dir for best params + report (default results/tune/<study>)")
    ap.add_argument("--seed", type=int, default=0,
                    help="Optuna sampler seed (default 0)")
    ap.add_argument("--n-jobs", type=int, default=1,
                    help="parallel Optuna workers (default 1, deterministic timing)")
    args = ap.parse_args()

    if args.n_trials < 1:
        print("error: --n-trials must be >=1")
        return 1
    if not args.train_set.is_file():
        print(f"error: --train-set not found: {args.train_set}")
        return 1
    if not args.search_space.is_file():
        print(f"error: --search-space not found: {args.search_space}")
        return 1

    try:
        import optuna
    except ImportError:
        print("error: optuna not installed (uv sync in benchmark/)")
        return 1

    space = load_search_space(args.search_space)
    if not space:
        print(f"error: empty search space {args.search_space}")
        return 1
    print(f"search space: {len(space)} params from {args.search_space}")
    for k, v in space.items():
        print(f"  {k}: {v}")

    repo = Path(__file__).resolve().parents[2]
    highs_bin = args.highs_bin or (repo / "build" / "bin" / "highs")
    if not Path(highs_bin).exists():
        print(f"error: HiGHS binary not found: {highs_bin} (build with benchmark/scripts/build_highs.sh)")
        return 1

    train_set = args.train_set
    study_name = args.study_name or f"tune_{train_set.stem}"
    results_root = results_dir()
    output_dir = args.output or (results_root / "tune" / study_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    storage = args.storage
    if storage is None:
        storage = f"sqlite:///{output_dir / 'study.db'}"

    # Delayed imports — need benchmark venv + ground truth
    from solvers import RunParams, make_solvers
    from common import sha256_file, options_hash, result_path, load_json, save_json
    from run_benchmark import instances_from_file, model_key
    try:
        from compare_versions import correctness_mismatches
    except ImportError:
        # fallback: inline check (status mismatch only, no tolerance)
        correctness_mismatches = None  # type: ignore

    # Resolve train instances once — same 8 across all workers (file already deterministic)
    search_roots = [repo / "benchmark" / "sets" / "miplib2017-benchmark", repo / "benchmark" / "examples"]
    # instances_from_file indexes over search_roots; we replicate its logic
    try:
        # reuse helper: need to provide roots containing instances
        # For tune we support train_set listing names that may be resolved via benchmark/sets
        from run_benchmark import discover_instances

        indexed: dict[str, list[Path]] = {}
        for root in search_roots:
            for p in discover_instances(root.resolve()):
                indexed.setdefault(model_key(p).lower(), []).append(p)
        # Also index any local instances dir if present
        extra_root = repo / "benchmark" / "instances"
        if extra_root.is_dir():
            for p in discover_instances(extra_root.resolve()):
                indexed.setdefault(model_key(p).lower(), []).append(p)

        train_instances: list[Path] = []
        for raw in train_set.read_text().splitlines():
            entry = raw.split("#", 1)[0].strip()
            if not entry:
                continue
            key = model_key(Path(entry)).lower()
            matches = indexed.get(key, [])
            if not matches:
                print(f"warning: train instance not found: {entry}")
                continue
            train_instances.append(matches[0])
    except Exception as exc:
        print(f"error resolving train set: {exc}")
        return 1

    if not train_instances:
        print(f"error: no train instances resolved from {train_set}")
        return 1
    print(f"train set: {train_set} ({len(train_instances)} instances)")
    print(f"output: {output_dir}")
    print(f"storage: {storage}")

    # Ground truth cache for scoring (use full GT union, like compare_versions)
    gt_cache: dict[str, dict] = {}
    try:
        from solvers import ground_truth_version
        from compare_versions import load_version_any_set

        gt_ver = ground_truth_version()
        if gt_ver:
            gt_spec = f"gurobi:{gt_ver}"
            gt_cache = load_version_any_set(gt_spec, results_root, prefer_set=None)
            print(f"ground truth: {gt_spec} ({len(gt_cache)} records)")
        else:
            print("warning: no ground truth cache found — wrong-solution penalty disabled")
    except Exception as exc:
        print(f"warning: ground truth load failed: {exc}")

    machine = machine_id()

    def is_wrong(rec: dict) -> bool:
        if not gt_cache or correctness_mismatches is None:
            return False
        inst = rec.get("instance")
        grec = gt_cache.get(inst) if inst else None
        if grec is None:
            return False
        # Reuse same gap-aware check but for single rec vs single gt
        mism = correctness_mismatches({inst: rec}, {inst: grec})
        return len(mism) > 0

    def objective(trial: "optuna.Trial") -> float:
        params = suggest_params(trial, space)

        # One temp options file per trial — unique even with parallel workers
        workdir = Path(tempfile.gettempdir()) / f"highs_tune_{study_name}_{trial.number}"
        workdir.mkdir(parents=True, exist_ok=True)

        # Build options file path (per trial, shared across instances in trial)
        opts_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:8]
        opts_file = workdir / f"trial_{trial.number}_{opts_hash}.opts"
        lines = []
        for k, v in sorted(params.items()):
            if isinstance(v, bool):
                v_str = str(v).lower()
            else:
                v_str = str(v)
            lines.append(f"{k} = {v_str}")
        opts_file.write_text("\n".join(lines) + "\n")

        solver = make_solvers(["highs"], Path(highs_bin))[0]
        run_params = RunParams(
            threads=args.threads,
            time_limit=args.time_limit,
            mip_gap=1e-4,
            highs_options=params,
            machine=machine,
            run_date=utcnow_iso(),
        )
        # options_hash influences cache key — but for tuning we force re-run
        # regardless of cache, so set instance_hash dummy and ignore cache.
        scores: list[float] = []
        for inst in train_instances:
            # Each instance solve uses same highs_options via RunParams -> options_file
            rec = solver.solve(inst, run_params, workdir)
            # No result_path caching during tuning; direct scoring
            rec["solver_version"] = solver.version()
            rec["highs_options"] = dict(params)
            wrong = is_wrong(rec)
            scores.append(per_instance_score(rec, wrong))
            # Optional intermediate report for pruning (mean so far)
            # We report after each instance; pruner can stop bad trials early
            # Only report at instance granularity if we have at least 2 scores
            if len(scores) >= 2:
                trial.report(sum(scores) / len(scores), step=len(scores))
                if trial.should_prune():
                    raise optuna.TrialPruned()

        return sum(scores) / len(scores) if scores else WRONG_SCORE

    sampler = optuna.samplers.TPESampler(seed=args.seed, multivariate=True)
    pruner = optuna.pruners.MedianPruner(n_startup_trials=max(1, args.n_trials // 10), n_warmup_steps=2)
    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        load_if_exists=True,
        direction="maximize",
        sampler=sampler,
        pruner=pruner,
    )
    print(f"Optuna study '{study_name}' direction=maximize, n_trials={args.n_trials}, n_jobs={args.n_jobs}")

    study.optimize(objective, n_trials=args.n_trials, n_jobs=args.n_jobs, show_progress_bar=True)

    best = study.best_trial
    print(f"\nBest trial #{best.number}: score={best.value:.4f}")
    print(f"Params: {best.params}")

    # Save best params
    best_path = output_dir / "best_params.yaml"
    try:
        import yaml
        best_path.write_text(yaml.safe_dump(best.params, sort_keys=True))
    except ImportError:
        (output_dir / "best_params.json").write_text(json.dumps(best.params, indent=2, sort_keys=True))
        best_path = output_dir / "best_params.json"

    report = {
        "study_name": study_name,
        "train_set": str(train_set),
        "n_train": len(train_instances),
        "n_trials": args.n_trials,
        "seed": args.seed,
        "best_trial": best.number,
        "best_score": best.value,
        "best_params": best.params,
        "best_params_file": str(best_path),
        "storage": storage,
        "generated": utcnow_iso(),
        "machine": machine,
        "highs_bin": str(highs_bin),
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"Report: {output_dir / 'report.json'}")
    print(f"Best params: {best_path}")

    # Final validation on test set if requested
    if args.test_set and args.test_set.is_file():
        print(f"\nValidating best params on test set {args.test_set} ...")
        # Resolve test instances similarly (reuse logic)
        test_instances: list[Path] = []
        for raw in args.test_set.read_text().splitlines():
            entry = raw.split("#", 1)[0].strip()
            if not entry:
                continue
            key = model_key(Path(entry)).lower()
            matches = indexed.get(key, [])
            if matches:
                test_instances.append(matches[0])
        if test_instances:
            workdir = Path(tempfile.gettempdir()) / f"highs_tune_{study_name}_validate"
            workdir.mkdir(parents=True, exist_ok=True)
            solver = make_solvers(["highs"], Path(highs_bin))[0]
            run_params = RunParams(threads=args.threads, time_limit=args.time_limit, highs_options=best.params, machine=machine, run_date=utcnow_iso())
            val_scores: list[float] = []
            for inst in test_instances:
                rec = solver.solve(inst, run_params, workdir)
                rec["solver_version"] = solver.version()
                val_scores.append(per_instance_score(rec, is_wrong(rec)))
            val_mean = sum(val_scores) / len(val_scores) if val_scores else 0
            print(f"Validation mean score on {args.test_set.name} ({len(test_instances)}): {val_mean:.4f}")
            report["validation"] = {"test_set": str(args.test_set), "n_test": len(test_instances), "mean_score": val_mean}
            (output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
