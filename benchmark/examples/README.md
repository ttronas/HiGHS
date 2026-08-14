# Example test set

Seven tiny MIPs (~6–30 binary/integer variables) so you can try the harness
without downloading the 317 MB MIPLIB benchmark set:

```bash
cd benchmark
uv run python scripts/run_benchmark.py --instances-root examples --time-limit 60 --threads 4
uv run python scripts/summarize.py --set examples
```

- `knapsack.lp`            0-1 knapsack
- `blending.lp`            mixed integer (continuous + integer vars)
- `lot-sizing.lp`          production / lot-sizing
- `setcover.lp`            set cover
- `assignment.lp`          5x5 assignment
- `facility-location.lp`   capacitated facility location
- `maxcut.lp`              cut-polytope style MIP

All are small enough for *any* Gurobi license type (including the free /
size-limited one), so the full solver suite works out of the box.

To add problems of your own, drop `.mps` / `.lp` (also gzip/zstd) files into a
folder and point `--instances-root` at it - see the harness README for the
"sets" concept.