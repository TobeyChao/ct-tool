# Rust S/M/L benchmark fixture migration (2026-09-30)

The S/M/L input generator is now `cargo run --manifest-path native/Cargo.toml -p ct-xtask -- bench-fixtures`.
It uses a fixed seed (`20260918`), native Schema/Excel/template/i18n APIs, and writes only to
the selected output directory. `r` and `r-full` continue to use the frozen shape manifest.
The old Python generator remains as historical source material; it is not called by xtask.

All three tiers were generated from an empty `/tmp/ct-native-g3-*/` directory on macOS arm64
and passed `ct validate --root <fixture>` using the native executable:

| Tier | Tables | Rows per table | Nonempty data cells | Translated entries | Input digest |
|---|---:|---:|---:|---:|---|
| S | 10 | 100 | 18,454 | 4,000 | `sha256:182fec0442aa271bb3bed162c4dd9b7d98b0dba5d9a0aa22180fb8d6f4862b7b` |
| M | 50 | 2,000 | 1,847,536 | 400,000 | `sha256:b3398c1d3c3479adbbcc0918bd67e6ab486a445305d1d4b93e00a8807f23dd23` |
| L | 100 | 10,000 | 18,480,119 | 4,000,000 | `sha256:6a6c1d320315187d92b7e8bb6c7be97e01762a703303a5c6a8c71cb7e68559ad` |

The S tier was independently regenerated in a second empty directory and produced the
same input digest. Each tier contains a changed `T001.xlsx` and an `en/T001.json`
mutation; the changed workbook contains `bench-mutation`. Output/cache/journal directories
are removed after generation. `cargo test -p ct-xtask` passed 16/16 tests.
After appending a comment to a disposable S fixture's `config/global.yaml`, `xtask bench`
exited nonzero before measurement with an explicit input-digest mismatch.

The old S/M/L performance reports were measured with Python-generated inputs and do not
contain an input digest. The benchmark runner now rejects mismatched fixture reports and
defaults to a native-fixture archive for S/M/L. The first five-sample S run is retained at
[`bench-s-macos-native.json`](bench-s-macos-native.json); a second five-sample run against
that archive returned `regression-pass` for cold, hot CLI, hot worker, one-table change,
and one-translation change. Its raw result is
[`bench-s-macos-native-verification.json`](bench-s-macos-native-verification.json).

The M tier now also has a five-sample native-fixture archive at
[`bench-m-macos-native.json`](bench-m-macos-native.json) and an independent five-sample
rerun at [`bench-m-macos-native-verification.json`](bench-m-macos-native-verification.json).
All five scenarios returned `regression-pass` with the same fixture and artifact digests.
Baseline/rerun median times (ms) were cold 9539/9854, hot CLI 5428/5729,
hot worker 5505/5802, one-table change 5719/6140, and one-translation change 6188/5564.
All sampled process-tree RSS values stayed below the M absolute cap (1.25 GiB).

The first five-sample L capture is now retained at
[`bench-l-macos-native.json`](bench-l-macos-native.json). It contains 607 artifacts per
scenario and preserves the recorded fixture digest. Median times (ms) were cold 98954,
hot CLI 59415, hot worker 56569, one-table change 58583, and one-translation change 58649.
All sampled process-tree peaks stayed below 7.5 GiB (largest 7,590,704 KiB).
This initial capture has `no-baseline` verdicts; it is not a completed regression check.
An independent five-sample L rerun is in progress. Some compatibility builds/checks ran
during the first capture; the raw sample spread is retained and the independent run is
required before accepting the entry.

L regression and other-platform archives remain to be measured.
Task 7.1 stays open until those regression entries and clean-environment checks are complete.
