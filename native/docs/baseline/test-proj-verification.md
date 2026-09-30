# Independent reader preparation — 2026-09-30

Task 7.3 is accepted on main, macOS arm64. The official test-proj entry uses Node + Rust
preparation and a standalone .NET 10 reader. G3, other-platform release/benchmark execution,
and Python deletion remain incomplete. The updated three-platform CI definition has not
been executed remotely and is not evidence of platform acceptance.

## Supported scope and independent references

`test-proj/python-retirement.json` audits every one of the 19 Python scripts with source
hash, explicit reason and current related capability. `prepare.py` and
`gen_scalars_bench.py` are replaced formal preparation entries; the remaining 17 are
historical experiments. Reports/readmes mark old commands and measurements as historical.
Nothing is deleted. `check-retirement.mjs` rejects new or changed unaudited scripts.
Three ConfigAccessorBench reader C# files remain active independent dependencies; their
source scope is now included in fingerprint and coverage validation.

`independent-oracles.json` and its checksum pin 32 files: 25 workspace inputs, four
scalar/FNV references, a scalar schema, and two provenance source snapshots. All 31
existing inputs/references/snapshots were byte-compared to Git main `8dc7b81`.
The schema transcribes the frozen scalar preparation script's order and types.

`xtask accessor-fixtures --root <checkout> --out <temporary path>` verifies the archive
before producing outputs. Current Rust generators recreate Scalars Binary and C# and
must match the independent main golden bytes. The JSON reference is copied without
JavaScript number parsing, preserving signed/unsigned 64-bit bounds. The C# reader then
reads these newly generated native outputs, rather than testing old Python outputs alone.
The regular native export also produces five C# files, twelve JSON files and three
language Binary bundles in a temporary workspace. Expected values are not regenerated.
FNV requires all nine vectors; the reader requires all 127 checks, including CodeName,
sparse i18n, language switching and twelve scalar types. Missing references cannot skip.

## Executed commands and results

The temporary source copy excludes ct/, gd/, build outputs and interpreter caches. PATH
is an explicit Rust/Node/.NET/linker/git/POSIX allowlist without Python; Python and virtual
environment variables are cleared. Workspace packages are compiled against this copy,
offline; shared Cargo dependency/target caches are a build optimization. .NET SDK/package
cache is reused. No Python is installed or executed by these entries.

```sh
env -u PYTHONHOME -u PYTHONPATH -u PYTHONEXECUTABLE -u VIRTUAL_ENV -u CONDA_PREFIX PATH="$task_clean_root/bin" CARGO_TARGET_DIR=/Users/tobeychao/Documents/Projects/ct-tool/native/target "$task_clean_root/bin/cargo" build --manifest-path "$task_clean_root/checkout/native/Cargo.toml" -p ct-cli -p ct-xtask --locked --offline -j1
env -u PYTHONHOME -u PYTHONPATH -u PYTHONEXECUTABLE -u VIRTUAL_ENV -u CONDA_PREFIX PATH="$task_clean_root/bin" CARGO_TARGET_DIR=/Users/tobeychao/Documents/Projects/ct-tool/native/target "$task_clean_root/bin/cargo" test --manifest-path "$task_clean_root/checkout/native/Cargo.toml" --workspace --locked --offline --no-fail-fast -j1
node "$task_clean_root/checkout/test-proj/check-retirement.mjs"
CT_NATIVE_BIN=/Users/tobeychao/Documents/Projects/ct-tool/native/target/debug/ct CT_XTASK_BIN=/Users/tobeychao/Documents/Projects/ct-tool/native/target/debug/xtask node "$task_clean_root/checkout/test-proj/ExportAccessorVerify/prepare-native.mjs"
native/target/debug/xtask compat-fixtures --out /tmp/ct-native-7-3-excel-inputs
native/target/debug/xtask fingerprint --root "$task_clean_root/checkout"
native/target/debug/xtask fingerprint --root "$task_clean_root/checkout" --check
```

All commands use the controlled environment above. Cargo: 331 passed, 0 failed/ignored,
77 target summaries. Independent C#: 127 checks, 0 mismatches. Audit: 19/19 classified.
Compatibility preparation: 129 versioned inputs/goldens verified and six Excel workbooks
rebuilt. Explicit-checkout fingerprint generation/check succeeded.

The first full run found a stale fingerprint without the new test-proj scope and a
previous compatibility manifest accidentally pinning an ignored local `.pyc` cache.
The fingerprint was refreshed; only the cache entry was removed from that manifest.
All 129 versioned inputs/goldens and their checksums remain unchanged. A regression now
checks both cache absence/presence and rejection of an unknown golden. The final full
run passed. No user cache files were removed and no necessary test was skipped.

Negative execution rejects changed FNV SHA before generating anything, rejects a missing
FNV file in the actual C# process, rejects an added unaudited Python script and rejects
modified historical source. Cargo also checks missing oracle, reproducible generation,
old-engine absence and unknown golden rejection.

Raw evidence: [environment](test-proj-evidence/environment.json),
[main provenance](test-proj-evidence/provenance.json),
[build](test-proj-evidence/build.txt), [final Cargo](test-proj-evidence/workspace-tests.txt),
[first Cargo run](test-proj-evidence/first-workspace-tests.txt),
[independent reader](test-proj-evidence/reader.txt), [audit](test-proj-evidence/audit.txt),
[negative entries](test-proj-evidence/negative.json),
[oracle rejection](test-proj-evidence/oracle-negative.json),
[compatibility preparation](test-proj-evidence/compat.txt),
[fingerprint](test-proj-evidence/fingerprint.txt).
