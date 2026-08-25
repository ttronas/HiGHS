# Reference data

Reference material for the MIPLIB2017 benchmark, kept in-repo for a self-contained
benchmarking setup. Refresh with:

    uv run python scripts/download_instances.py --fetch-reference

Files:
- `mittelmann-12threads.res` - H. Mittelmann's MILP benchmark result table
  (https://plato.asu.edu/ftp/milp.html; 12 threads, 7200 s limit, Ryzen 9 5900X).
  Used by `summarize.py --reference` for context only (v1-preprocessed instances,
  so not directly comparable to local runs).
- `benchmark-v1.test` / `benchmark-v2.test` - MIPLIB2017 benchmark-set instance
  name lists (v1 deprecated, v2 current).
- `miplib2017-v36.solu` - best-known/optimal objective values of all MIPLIB2017
  instances, usable for validating reported solutions.

Attribution: benchmark page by H. Mittelmann, https://plato.asu.edu/ftp/milp.html;
instance set & solution file by the MIPLIB 2017 team, https://miplib.zib.de.
