"""Download Mittelmann LP benchmark public instances (49).

Downloads the 49 public LP instances from the Mittelmann LPfeas/LPopt
benchmark (https://plato.asu.edu/ftp/lpfeas.html) into:

    benchmark/sets/lp-mittelmann/

All runs use production mode (solver=choose, 60s, CPU only) — no solver
override. Subset generation after caching:

    uv run python scripts/filter_sets.py --set lp-mittelmann
    # -> sets/subsets/lp-mittelmann-fast-instances.txt

Sources mirror Mittelmann file table: plato.asu.edu/ftp/lptestset/ is the
primary mirror (Mészáros collection). The 16 undisclosed instances are not
fetched.

Usage:
    uv run python scripts/download_lp.py
    uv run python scripts/download_lp.py --out-dir benchmark/sets/lp-mittelmann --force
"""

from __future__ import annotations

import argparse
import bz2
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import benchmark_dir  # noqa: E402

PLATO = "https://plato.asu.edu/ftp/lptestset"

# 49 public instances (lpfeas.html, lpfeas_logs, dimensions table)
# Ordered as on the page up to set-cover (before undisclosed energy1..thor)
PUBLIC_INSTANCES = [
    "L1_sixm",
    "Linf_520c",
    "a2864",
    "bdry2",
    "cont1",
    "cont11",
    "datt256",
    "dlr1",
    "ex10",
    "fhnw-bin1",
    "fome13",
    "graph40-40",
    "irish-e",
    "neos",
    "neos3",
    "neos3025225",
    "neos5052403",
    "neos5251015",
    "ns1687037",
    "ns1688926",
    "nug08-3rd",
    "pds-100",
    "psched3-3",
    "qap15",
    "rail02",
    "rail4284",
    "rmine15",
    "s82",
    "s100",
    "s250r10",
    "savsched1",
    "scpm1",
    "shs1023",
    "square41",
    "stat96v2",
    "storm_1000",
    "stp3d",
    "support10",
    "tpl-tub-ws",
    "woodlands09",
    "Dual2_5000",
    "Primal2_1000",
    "thk_48",
    "thk_63",
    "L1_six1000",
    "L2CTA3D",
    "degme",
    "dlr2",
    "set-cover",
]

# Explicit alias: instance -> plato filename (without base), when heuristic fails.
# Built from directory listing of https://plato.asu.edu/ftp/lptestset/
ALIAS = {
    "L1_sixm": "L1_sixm250obs.bz2",
    "L1_six1000": "L1_sixm1000obs.bz2",
    "datt256": "datt256_lp.mps.bz2",
    "fhnw-bin1": "fhnw-binschedule1.mps.bz2",
    "irish-e": "irish-electricity.mps.bz2",
    "neos3025225": "neos-3025225.mps.bz2",
    "neos5052403": "neos-5052403-cygnet.mps.bz2",
    "neos5251015": "neos-5251015.mps.bz2",
    "pds-100": "pds/pds-100.bz2",
    "psched3-3": "physiciansched3-3.mps.bz2",
    "rail4284": "rail/rail4284.bz2",
    "storm_1000": "misc/stormG2_1000.bz2",
    "support10": "supportcase10.mps.bz2",
    "tpl-tub-ws": "tpl-tub-ws1617.mps.bz2",
    "set-cover": "set-cover-model.mps.bz2",
    "cont1": "misc/cont1.bz2",
    "cont11": "misc/cont11.bz2",
    "neos": "misc/neos.bz2",
    "neos3": "misc/neos3.bz2",
    "ns1687037": "misc/ns1687037.bz2",
    "ns1688926": "misc/ns1688926.bz2",
    "nug08-3rd": "nug/nug08-3rd.bz2",
    "fome13": "fome/fome13.bz2",
}

# Fallback candidates heuristic: try these suffixes in order if ALIAS misses
CANDIDATE_SUFFIXES = [
    "{name}.mps.bz2",
    "{name}.bz2",
    "{name}_lp.mps.bz2",
    "misc/{name}.bz2",
    "pds/{name}.bz2",
    "rail/{name}.bz2",
    "nug/{name}.bz2",
    "fome/{name}.bz2",
    "network/{name}.mps.bz2",
    "{name}.mps",
]


def candidate_urls(name: str) -> list[str]:
    urls: list[str] = []
    if name in ALIAS:
        urls.append(f"{PLATO}/{ALIAS[name]}")
    # heuristic expansions (dedupe)
    for tmpl in CANDIDATE_SUFFIXES:
        fn = tmpl.format(name=name)
        url = f"{PLATO}/{fn}"
        if url not in urls:
            urls.append(url)
    # lower-case fallback for case-sensitive plato
    for url in list(urls):
        low = url.lower()
        if low not in urls:
            urls.append(low)
    return urls


def fetch(url: str, dest: Path, timeout: int = 30) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "highs-benchmark/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fh:
            while True:
                block = resp.read(1 << 20)
                if not block:
                    break
                fh.write(block)
        return True
    except Exception as exc:  # noqa: BLE001
        if dest.exists():
            dest.unlink(missing_ok=True)
        print(f"    miss {url}: {exc}")
        return False


def _ensure_emps() -> Path | None:
    """Return path to emps binary, compiling it from netlib if needed."""
    import shutil, subprocess
    # Check in PATH and common locations
    for cand in [Path("/tmp/emps"), Path("/usr/local/bin/emps"), shutil.which("emps")]:
        if cand and Path(cand).exists():
            return Path(cand)
    # Compile from netlib source
    try:
        src = Path("/tmp/emps.c")
        bin_path = Path("/tmp/emps")
        if not src.exists():
            req = urllib.request.Request("https://www.netlib.org/lp/data/emps.c",
                                         headers={"User-Agent": "highs-benchmark/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(src, "wb") as fh:
                fh.write(resp.read())
        # compile
        res = subprocess.run(["gcc", "-O2", str(src), "-o", str(bin_path)],
                             capture_output=True, timeout=30)
        if bin_path.exists():
            return bin_path
    except Exception:
        pass
    return None


def decompress_bz2(src: Path, dst: Path) -> bool:
    # Decompress .bz2 -> raw, then detect emps vs MPS and expand if needed,
    # finally gzip to .mps.gz if dst is .gz.
    import gzip as _gzip
    import subprocess, shutil, tempfile
    try:
        # Step 1: bunzip to temp
        tmp_raw = Path(tempfile.gettempdir()) / f"lp_raw_{src.stem}"
        with bz2.open(src, "rb") as fin, open(tmp_raw, "wb") as fout:
            while True:
                chunk = fin.read(1 << 20)
                if not chunk:
                    break
                fout.write(chunk)
        # Step 2: detect if raw is MPS (contains ROWS) or emps binary
        is_mps = False
        try:
            with open(tmp_raw, "rb") as fh:
                head = fh.read(8192)
                text = head.decode(errors="ignore")
                if "ROWS" in text and "NAME" in text:
                    is_mps = True
        except Exception:
            is_mps = False

        tmp_mps = tmp_raw  # default if already MPS
        emps_bin = None
        if not is_mps:
            emps_bin = _ensure_emps()
            if emps_bin and emps_bin.exists():
                # emps reads from stdin or file and writes MPS to stdout
                tmp_mps2 = Path(tempfile.gettempdir()) / f"lp_mps_{src.stem}.mps"
                # emps expects file arg or stdin; use file arg
                res = subprocess.run([str(emps_bin), str(tmp_raw)],
                                     stdout=open(tmp_mps2, "wb"),
                                     stderr=subprocess.PIPE, timeout=120)
                if tmp_mps2.exists() and tmp_mps2.stat().st_size > 1024:
                    # sanity check MPS header
                    try:
                        with open(tmp_mps2, "rb") as fh:
                            h = fh.read(4096).decode(errors="ignore")
                            if "ROWS" in h:
                                tmp_raw.unlink(missing_ok=True)
                                tmp_mps = tmp_mps2
                            else:
                                print(f"    emps output for {src.name} not MPS, keeping raw")
                                tmp_mps2.unlink(missing_ok=True)
                    except Exception:
                        tmp_mps2.unlink(missing_ok=True)
                else:
                    print(f"    emps failed for {src.name}: {res.stderr.decode(errors='ignore')[:200]}")
            else:
                print(f"    warning: emps not available, keeping raw {src.name} (may fail to parse)")

        # Step 3: compress to final dst if needed
        if str(dst).endswith(".gz"):
            # tmp_mps -> dst gz
            with open(tmp_mps, "rb") as fin, _gzip.open(dst, "wb", compresslevel=1) as gz:
                while True:
                    chunk = fin.read(1 << 20)
                    if not chunk:
                        break
                    gz.write(chunk)
            # cleanup
            if tmp_mps != tmp_raw:
                tmp_mps.unlink(missing_ok=True)
            tmp_raw.unlink(missing_ok=True)
        else:
            # dst is .mps, move
            if tmp_mps != tmp_raw:
                tmp_mps.rename(dst)
                tmp_raw.unlink(missing_ok=True)
            else:
                tmp_raw.rename(dst)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"    decompress failed {src}: {exc}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Download Mittelmann LP public instances (49)")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="target dir (default benchmark/sets/lp-mittelmann)")
    ap.add_argument("--force", action="store_true",
                    help="re-download even if files exist")
    ap.add_argument("--instance", action="append", default=None,
                    help="only fetch named instance(s) (repeatable)")
    ap.add_argument("--list-only", action="store_true",
                    help="print instance list and exit")
    args = ap.parse_args()

    if args.list_only:
        for name in PUBLIC_INSTANCES:
            print(name)
        return 0

    wanted = set(PUBLIC_INSTANCES)
    if args.instance:
        req = set(args.instance)
        unknown = req - wanted
        if unknown:
            print(f"error: unknown instance(s): {sorted(unknown)}")
            return 1
        wanted = req

    root = benchmark_dir()
    out_dir = args.out_dir or root / "sets" / "lp-mittelmann"
    out_dir.mkdir(parents=True, exist_ok=True)

    # optional cache dir for raw .bz2
    cache_dir = root / ".cache" / "lp-mittelmann"
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"target: {out_dir} ({len(wanted)} instances)")
    ok, fail, skipped = 0, 0, 0
    for name in PUBLIC_INSTANCES:
        if name not in wanted:
            continue
        # harness supports .mps and .mps.gz; emit .mps.gz (gzip level 1, fast) to save disk
        dest_mps = out_dir / f"{name}.mps"
        dest_gz = out_dir / f"{name}.mps.gz"
        dest_final = dest_gz  # prefer compressed
        if (dest_mps.exists() or dest_gz.exists()) and not args.force:
            skipped += 1
            print(f"  cached {name}")
            continue
        urls = candidate_urls(name)
        tmp_bz2 = cache_dir / f"{name}.bz2"
        fetched = False
        for url in urls:
            print(f"  fetching {name} from {url} ...")
            if fetch(url, tmp_bz2):
                fetched = True
                break
        if not fetched:
            print(f"  !! failed to fetch {name} (tried {len(urls)} URLs)")
            fail += 1
            continue
        # decompress
        # remove old dest if any
        dest_mps.unlink(missing_ok=True)
        dest_gz.unlink(missing_ok=True)
        if tmp_bz2.suffix == ".bz2":
            if decompress_bz2(tmp_bz2, dest_final):
                # quick sanity via gzip header peek
                try:
                    import gzip as _gz
                    with _gz.open(dest_final, "rt", errors="ignore") as fh:
                        head = fh.read(2000)
                    if "NAME" not in head and "ROWS" not in head and "OBJSENSE" not in head:
                        print(f"    warning: {name}.mps.gz header unexpected, first 500 chars: {head[:500]!r}")
                    else:
                        print(f"  ok {name} -> {dest_final.name} ({dest_final.stat().st_size/1e6:.1f} MB gz)")
                        ok += 1
                except Exception:
                    print(f"  ok {name} -> {dest_final.name}")
                    ok += 1
            else:
                fail += 1
        else:
            tmp_bz2.rename(dest_final)
            ok += 1

    print(f"\ndone: {ok} ok, {skipped} cached, {fail} failed -> {out_dir}")
    if fail:
        print("  Some instances failed — check URLs or fetch manually from:")
        print("    https://plato.asu.edu/ftp/lptestset/")
        print("    https://plato.asu.edu/ftp/lpfeas.html (column s)")
        print("  Then run: uv run python scripts/filter_sets.py --set lp-mittelmann")
    else:
        print(f"  Next: uv run python scripts/run_benchmark.py --instances-root {out_dir} --set lp-mittelmann --time-limit 60")
        print("        uv run python scripts/filter_sets.py --set lp-mittelmann")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
