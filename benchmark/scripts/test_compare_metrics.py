"""Unit tests for compare_versions.py metrics/plan layers (pure, no IO).

Run from benchmark/:
    uv run pytest scripts/test_compare_metrics.py -q
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_versions import (  # noqa: E402
    InstanceRow,
    build_pairs,
    correctness_mismatches,
    pair_stats,
    resolve_spec,
    shifted_geomean,
    solve_time,
)


def rec(status="Optimal", t=5.0, obj=10.0, **kw):
    d = {"status": status, "runtime_s": t, "objective": obj,
         "time_limit": kw.pop("time_limit", 60.0)}
    d.update(kw)
    return d


# ---- solve_time -------------------------------------------------------
def test_solve_time_repeats_aware():
    r = rec(t=99)
    r["runtime_mean_s"] = 2.5
    assert solve_time(r, 7200.0) == 2.5


def test_solve_time_timeout_clamped_to_limit():
    assert solve_time(rec(status="Time limit reached", t=60.5), 7200.0) == 60.5
    assert solve_time(rec(status="Time limit reached", t=40.0), 7200.0) == 60.0


def test_solve_time_missing_runtime_returns_limit():
    r = {"status": "Optimal", "time_limit": 30.0}
    assert solve_time(r, 7200.0) == 30.0


# ---- InstanceRow ------------------------------------------------------
def test_instance_row_relative_values():
    row = InstanceRow("x", t_a=4.0, t_b=3.0)
    assert row.delta_s == -1.0
    assert row.delta_pct == pytest.approx(-25.0)
    assert row.speedup == pytest.approx(4.0 / 3.0)


def test_instance_row_zero_baseline_guard():
    row = InstanceRow("x", t_a=0.0, t_b=1.0)
    assert math.isfinite(row.delta_pct)


# ---- shifted_geomean --------------------------------------------------
def test_shifted_geomean_known_value():
    vals = [1.0, 3.0]
    expect = math.exp((math.log(11.0) + math.log(13.0)) / 2) - 10.0
    assert shifted_geomean(vals) == pytest.approx(expect)


def test_shifted_geomean_empty():
    assert shifted_geomean([]) == float("inf")


# ---- pair_stats --------------------------------------------------------
def _two_sets():
    base = {"a": rec(t=2.0), "b": rec(t=8.0), "t1": rec(t=5.0),
            "to": rec(status="Time limit reached", t=60.0)}
    cur = {"a": rec(t=1.0), "b": rec(t=9.0), "t1": rec(t=5.0),
           "only_cur": rec(t=3.0),
           "to": rec(status="Time limit reached", t=61.0)}
    return base, cur


def test_pair_stats_exclusions_and_counts():
    base, cur = _two_sets()
    pr = pair_stats("A", "B", base, cur, 60.0, solved_only=True)
    names = [r.instance for r in pr.rows]
    assert names == ["a", "b", "t1"]          # 'to' excluded (timeout), only_cur excluded
    reasons = dict(pr.excluded)
    assert reasons["to"] == "timeout-or-unsolved"
    assert reasons["only_cur"] == "cur-only"
    assert pr.n_faster == 1 and pr.n_slower == 1


def test_pair_stats_include_timeouts():
    base, cur = _two_sets()
    pr = pair_stats("A", "B", base, cur, 60.0, solved_only=False)
    assert {r.instance for r in pr.rows} == {"a", "b", "t1", "to"}


def test_pair_stats_invalid_signal_excluded():
    base, cur = _two_sets()
    pr = pair_stats("A", "B", base, cur, 60.0, solved_only=True,
                    invalid_a={"b"})
    assert "b" not in {r.instance for r in pr.rows}
    assert any(i == "b" and "invalid-signal" in why for i, why in pr.excluded)


def test_pair_stats_aggregate_abs_and_rel():
    base, cur = _two_sets()
    agg = pair_stats("A", "B", base, cur, 60.0).aggregate()
    a, rel = agg["abs"], agg["rel"]
    assert agg["n_shared"] == 3
    assert a["mean_a_s"] == pytest.approx(5.0)
    assert a["total_saved_s"] == pytest.approx((2 - 1) + (8 - 9) + 0)
    assert a["min_b_s"] == 1.0 and a["max_b_s"] == 9.0
    # geomean ratio <1 would mean b faster overall; here mixed -> near 1
    assert 0.9 < rel["shifted_geomean_ratio"] < 1.1
    assert rel["faster"] == 1 and rel["slower"] == 1 and rel["equal"] == 1


# ---- correctness_mismatches --------------------------------------------
def test_correctness_status_mismatch():
    gt = {"i": rec(status="Infeasible")}
    cand = {"i": rec(status="Optimal")}
    assert len(correctness_mismatches(cand, gt)) == 1


def test_correctness_objective_tolerance():
    gt = {"i": rec(obj=100.0)}
    assert correctness_mismatches({"i": rec(obj=100.0 + 1e-9)}, gt) == []
    assert len(correctness_mismatches({"i": rec(obj=101.0)}, gt)) == 1


def test_correctness_respects_candidate_mip_gap():
    # stopping inside the configured gap is by design, not a mismatch
    gt = {"i": rec(obj=11507.9099)}
    cand = {"i": rec(obj=11507.4053, mip_gap_tol=1e-4)}
    assert correctness_mismatches(cand, gt) == []
    cand_strict = {"i": rec(obj=11507.4053, mip_gap_tol=0.0)}
    assert len(correctness_mismatches(cand_strict, gt)) == 1


def test_correctness_ignores_timeouts_and_unchecked_gt():
    gt = {"i": rec(), "j": rec(status="Time limit reached"),
          "k": rec(status="Optimal")}
    cand = {"i": rec(status="Time limit reached"), "k": rec()}
    assert correctness_mismatches(cand, gt) == []


# ---- build_pairs ---------------------------------------------------------
SPECS = ["a", "b", "c"]


def test_build_pairs_baseline():
    assert build_pairs("baseline", SPECS, None, None) == [("a", "b"), ("a", "c")]
    assert build_pairs("baseline", SPECS, "c", None) == [("c", "a"), ("c", "b")]


def test_build_pairs_neighbor_chain():
    assert build_pairs("neighbor", SPECS, None, None) == [("a", "b"), ("b", "c")]


def test_build_pairs_pairwise_explicit():
    got = build_pairs("pairwise", SPECS, None, "a>b, c>a")
    assert got == [("a", "b"), ("c", "a")]


def test_build_pairs_all_grid():
    got = build_pairs("all", SPECS, None, None)
    assert len(got) == 6 and ("c", "a") in got and ("b", "c") in got


def test_build_pairs_errors():
    with pytest.raises(ValueError):
        build_pairs("baseline", SPECS, "zzz", None)
    with pytest.raises(ValueError):
        build_pairs("pairwise", SPECS, None, "a>b, zzz>c")
    with pytest.raises(ValueError):
        build_pairs("pairwise", SPECS, None, "a:b")   # wrong separator
    with pytest.raises(ValueError):
        build_pairs("pairwise", SPECS, None, "")


# ---- resolve_spec ----------------------------------------------------------
def test_resolve_spec():
    assert resolve_spec("gurobi:12.0.3", "highs") == ("gurobi", "12.0.3")
    assert resolve_spec("1.15.1", "highs") == ("highs", "1.15.1")
