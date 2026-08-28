# Tune search spaces

Each YAML file maps `HiGHS_option_name -> {type, ...}`.

* Omit an option = not tuned (stays at default).
* All `HighsOptions.h` options are eligible — see `ergo-code.github.io/HiGHS/dev/options/definitions/` for full list.

Types:
- `float: {low, high, [log: true]}` → `trial.suggest_float`
- `int: {low, high, [log: true]}` → `trial.suggest_int`
- `categorical: {choices: [...]}` → `trial.suggest_categorical`
- `bool` shorthand also works (maps to categorical true/false)

Example: `example.yaml` (8 dimensions). For larger spaces copy to `large.yaml` and add more entries.

No rebuild needed — options are written to a per-trial file `workdir/trial_*.opts` and passed via `--options_file`.
