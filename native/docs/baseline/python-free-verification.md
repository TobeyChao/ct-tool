# Native verification migration — 2026-09-30

Task 7.4 removes live Python requirements from fingerprints, coverage, benchmark regression
and CLI parity. G3 and Python deletion remain open pending the other migration tasks and
Windows/Linux release execution. Verification evidence below is macOS arm64 only.

## Changes and source boundaries

- `reference-tests.json` freezes main `8dc7b81`: 85 Python source files and 690 test functions,
  including their source hashes/names. A SHA-256 sidecar and the original native source-tree
  snapshot preserve provenance. The native-origin inventory had 84 files/687 functions;
  main's three additional checks are explicitly mapped by `compat-matrix.json`.
- Current `ct-source-tree/2` fingerprints cover native, Web, launcher, OpenSpec, CI and independent reader sources (test-proj added in 7.3),
  always retain the frozen historical test inventory, and never scan or execute `ct/`.
  Native inventory includes crate unit tests as well as integration tests. `--root` selects
  an explicit checkout; `--check` requires matching source hashes and test inventory.
- Coverage always validates frozen reference mappings, required native tests/functions,
  and the three extra main checks. It has no early return for absent `ct/tests`.
- CLI parity always uses six immutable independent captures. It checks the capture SHA-256
  before launching ct, compares exit codes/text/artifacts, refuses live-Python options,
  and writes new reports to target/ or explicit output. A source snapshot preserves the
  historical live capture script; the tool cannot overwrite the reference file.
- Bench regression requires the same fixture digest, size/platform, all five unique native
  scenarios, positive timings and valid output hashes. Missing/corrupt archives fail before
  measurement. `--record-baseline` explicitly collects a first report, without claiming
  regression passed. Failed timing/artifact/memory checks return nonzero with raw evidence.
  Explicit `--python` remains a historical opt-in until the deletion gate, never a formal
  default or fallback.
- Recovery drill no longer probes for a Python entry. It runs the six static CLI comparisons
  and checks native journal recovery, hashes, mtimes and incremental export. Expected failed
  read-only diagnostics are checked as expected failures, not treated as successful writes.

The extra main checks concern replacement while a reader is open, backed_up recovery and
Unity `.meta` preservation when generated file spelling changes case. Recovery was already
covered by the frozen journal matrix. The deployment case exposed a native gap: sync now
matches names case-insensitively, retains destination spelling and the corresponding GUID,
and rejects ambiguous case collisions before cleanup. Tests check content, GUID, file count
and idempotence; the open-reader test checks replacement and temporary-file cleanup.
Windows-specific behavior still requires the G3 Windows run.

## Executed evidence

Targeted `ct-tests-compat` + `ct-xtask`: 208 passed, 0 failed/ignored. CLI parity: all six
scenarios matched exits/text and 11 artifact hashes each. S one-sample regression against
the frozen native-fixture report: all five scenarios `regression-pass`. It verifies the
entry; the existing five-sample S/M evidence remains the performance acceptance record.
The M recovery drill hit phase `prepared`, killed the process, recovered all 307 artifact
hashes and mtimes, cleaned private staging and ran the six independent CLI comparisons.
Tampered CLI checksum and missing benchmark archive were explicitly rejected before
launch/measurement; unit checks reject incomplete archives, invalid samples and digests.

A temporary source copy excludes `ct/`, gd/, build outputs and dependency directories.
Its PATH contains an explicit Rust/Node/linker/git/POSIX-tool allowlist with no Python.
PYTHONHOME/PYTHONPATH/PYTHONEXECUTABLE/VIRTUAL_ENV/CONDA_PREFIX are cleared. Dependencies
are resolved offline; a shared Cargo cache is only a build optimization. The first run
revealed omitted `cat`/`sleep` in the test harness allowlist, not a Python dependency;
the allowlist was corrected before acceptance. An archived checkout has no Git metadata;
its nullable dirty-path count is now accepted only with an empty commit, while all source
hashes/test inventories remain mandatory. Raw command logs and environment details
are retained with this record. Clean-checkout fingerprint generation/check succeeded;
full workspace and CLI results are recorded after the corrected run below.

Final clean-source workspace run: **328 passed, 0 failed/ignored** across 77 result targets.
Clean CLI run: all six scenarios matched exits/text/artifacts. The test count increased
from 324 before this task; absence of ct/ did not remove checks. Current fingerprint
generation/check also succeeded in the isolated PATH against the source-only copy.

Evidence: [environment](python-free-environment.json), [final workspace](python-free-workspace-tests.txt),
[targeted tests](python-free-targeted-tests.txt), [CLI parity](python-free-cli-parity.md),
[negative entries](python-free-negative-checks.txt), [fingerprint](python-free-fingerprint.txt),
[recovery drill](python-free-recovery-drill.md), [S regression entry](bench-s-native-entry-verification.json).
The two pre-acceptance failures are retained in [allowlist run](python-free-first-tests.txt)
and [Git metadata run](python-free-git-metadata-tests.txt), rather than concealed or skipped.

Commands (task_clean_root was the temporary root recorded in environment.json):

```sh
env -u PYTHONHOME -u PYTHONPATH -u PYTHONEXECUTABLE -u VIRTUAL_ENV -u CONDA_PREFIX PATH="$task_clean_root/bin" CARGO_TARGET_DIR=/Users/tobeychao/Documents/Projects/ct-tool/native/target "$task_clean_root/bin/cargo" test --manifest-path "$task_clean_root/checkout/native/Cargo.toml" --workspace --locked --offline --no-fail-fast -j 1
native/target/debug/xtask fingerprint --root "$task_clean_root/checkout"
native/target/debug/xtask fingerprint --check --root "$task_clean_root/checkout"
node native/tools/parity/cli-text-diff.mjs --rust native/target/debug/ct --out /tmp/ct-native-cli-parity.md
native/target/debug/xtask bench --size s --runs 1 --fixture-root /tmp/ct-native-g3-Zj4oHA --out /tmp/ct-native-7-4-bench-s.json
node native/tools/bench/recovery-drill.mjs --ct native/target/release/ct --fixture /tmp/ct-native-g3-Zj4oHA/bench-m --out /tmp/ct-native-7-4-recovery.md
```
