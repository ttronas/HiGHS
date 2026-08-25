"""Download the MIPLIB2017 *benchmark* instances and reference files.

Instances (v2, ~317 MB) are unpacked into a gitignored cache:
    benchmark/instances/

Reference material (diffs against the Mittelmann benchmark page) is fetched
into the committed directory `benchmark/reference/` with --fetch-reference:
    - the raw 12-thread result table (plato.asu.edu/ftp/milp_tables/12threads.res)
    - the MIPLIB2017 instance-name lists (benchmark-v1.test / benchmark-v2.test)
    - the latest MIPLIB2017 solutions file (*.solu) for validation

Use inside the devcontainer:
    uv run python scripts/download_instances.py
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import benchmark_dir  # noqa: E402

DEFAULT_BENCHMARK_ZIP = "https://miplib.zib.de/downloads/benchmark.zip"
MIPLIB_BASE = "https://miplib.zib.de/downloads/"

REFERENCE_FILES = {
    "mittelmann-12threads.res": "https://plato.asu.edu/ftp/milp_tables/12threads.res",
    "benchmark-v1.test": MIPLIB_BASE + "benchmark-v1.test",
    "benchmark-v2.test": MIPLIB_BASE + "benchmark-v2.test",
    "miplib2017.solu": MIPLIB_BASE + "miplib2017-v36.solu",
}


def fetch(url: str, dest: Path, chunk: int = 1 << 20) -> None:
    print(f"downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "highs-benchmark/0.1"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as fh:
        total = resp.headers.get("Content-Length")
        got = 0
        while True:
            block = resp.read(chunk)
            if not block:
                break
            fh.write(block)
            got += len(block)
            if total:
                print(f"\r  {got * 100 // int(total)}%", end="", flush=True)
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Download MIPLIB2017 benchmark data")
    ap.add_argument("--url", default=DEFAULT_BENCHMARK_ZIP,
                    help="benchmark.zip URL (default: official miplib.zib.de)")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="instance target dir (default benchmark/instances)")
    ap.add_argument("--cache-dir", type=Path, default=None,
                    help="where to store the zip (default benchmark/.cache)")
    ap.add_argument("--fetch-reference", action="store_true",
                    help="also fetch reference tables/lists into benchmark/reference/")
    args = ap.parse_args()

    root = benchmark_dir()
    out_dir = args.out_dir or root / "instances"
    cache_dir = args.cache_dir or root / ".cache"

    if args.fetch_reference:
        ref_dir = root / "reference"
        ref_dir.mkdir(parents=True, exist_ok=True)
        (ref_dir / "README.md").write_text(
            "# Reference data\n\n"
            "Fetched by: `uv run python scripts/download_instances.py --fetch-reference`\n"
            "- `mittelmann-12threads.res`: H. Mittelmann's MILP benchmark table "
            "(https://plato.asu.edu/ftp/milp.html, 12 threads, 7200 s limit).\n"
            "- `benchmark-v{1,2}.test`: MIPLIB2017 benchmark-set instance lists.\n"
            "- `miplib2017.solu`: best-known solution values for validation.\n"
        )
        for name, url in REFERENCE_FILES.items():
            dest = ref_dir / name
            try:
                fetch(url, dest)
            except Exception as exc:  # noqa: BLE001
                print(f"  warning: could not fetch {name}: {exc}")
        print(f"reference material -> {ref_dir}")

    if out_dir.exists() and any(out_dir.rglob("*.mps")):
        print(f"instances already present in {out_dir}; skipping download")
        return 0

    cache_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "benchmark.zip"
    if not zip_path.exists():
        fetch(args.url, zip_path)
    else:
        print(f"using cached archive {zip_path}")

    print("unpacking ...")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for member in names:
            zf.extract(member, out_dir)

    instances = [p for p in out_dir.rglob("*") if p.is_file() and p.suffix == ".mps"]
    print(f"unpacked {len(instances)} instances -> {out_dir}")
    if not instances:
        print("  (no .mps files found; the archive layout may differ - listing:)")
        for member in names[:20]:
            print("   ", member)
    return 0


if __name__ == "__main__":
    sys.exit(main())
