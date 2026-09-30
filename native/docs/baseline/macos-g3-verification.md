# macOS clean-source and delivery acceptance (2026-09-30)

G3 passes for the supported scope: macOS arm64. Windows is deferred and Linux is
unsupported, as requested on 2026-09-30. This does not claim their acceptance.
The Python tree is still present in the main checkout pending the documentation,
retirement inventory and deletion tasks.

The temporary source copy excluded `ct/`, real `gd/`, Cargo targets, Node modules,
Flutter build products, local caches and generated benchmark inputs. The explicit
tool allowlist contains no executable `python`, `python3` or `py`; Python and virtual
environment variables were removed. Existing Rust, Flutter, npm and .NET SDK caches
were reused. This is a clean source/build-input check, not a machine without SDKs.
[Environment and exact tool paths](macos-g3/environment.json) and
[tested source fingerprint](macos-g3/tested-source-tree.json) are retained.

| Check | Actual result |
|---|---|
| Offline locked Cargo workspace | 332 passed, 0 failed, 0 ignored |
| Real packaged panel HTTP | 39 passed, 0 skipped |
| Real packaged panel Playwright | 115 passed, 0 skipped |
| Flutter launcher / analysis | 15 passed / no issues |
| Independent C# reader | 127 checked, 0 mismatches |
| Compatibility fixtures | 129 frozen inputs verified, 6 Excel inputs regenerated |
| S/M/L from empty output | All regenerated and validated; all three archived input digests match |
| ZIP / signed app / mounted DMG | Actual CLI, worker, static resources, native HTTP and stdin EOF smoke passed |
| Payload guards | No Python/Flask; changed binary, interpreter payload and missing executable permission rejected |

[Machine-readable totals](macos-g3/results.json) and all raw logs are in
[`macos-g3/`](macos-g3/). The successful browser run is `browser-retry.txt`, the
successful packaging run is `launcher-package-third.txt`. Earlier failures are retained.

Commands used in the allowlisted environment (`TASK_MAC_G3` is the recorded temporary
root; Cargo target cache points to the repository's `native/target`):

```sh
cargo test --manifest-path "$TASK_MAC_G3/checkout/native/Cargo.toml" --workspace --offline --locked
cargo run --manifest-path "$TASK_MAC_G3/checkout/native/Cargo.toml" -p ct-xtask --locked -- dist --out "$TASK_MAC_G3/dist"
ditto -x -k "$TASK_MAC_G3/dist/ct-native-0.0.0-aarch64-apple-darwin.zip" "$TASK_MAC_G3/unpacked"
node native/tools/check-package.mjs --package "$TASK_MAC_G3/unpacked"
native/target/debug/xtask runtime-check --binary "$TASK_MAC_G3/unpacked/bin/ct" --out /tmp/ct-native-macos-g3-unpacked-runtime.txt
native/target/debug/xtask bench-fixtures --sizes s,m,l --out "$TASK_MAC_G3/fixtures"
native/target/debug/xtask compat-fixtures --out "$TASK_MAC_G3/compat"
# Each regenerated tier is passed to the unpacked ct validate command.
# In checkout/web: npm ci --offline; npm run test:http; npm test.
# CT_WEB_BIN points to unpacked/bin/ct for both Web suites.
# In checkout/launcher: flutter pub get --offline; flutter test; flutter analyze.
# CT_LAUNCHER_TEST_BIN points to unpacked/bin/ct.
CT_NATIVE_BIN="$TASK_MAC_G3/unpacked/bin/ct" CT_XTASK_BIN=./native/target/debug/xtask node "$TASK_MAC_G3/checkout/test-proj/ExportAccessorVerify/prepare-native.mjs"
RUNTIME_PACKAGE="$TASK_MAC_G3/dist/ct-native-0.0.0-aarch64-apple-darwin" bash "$TASK_MAC_G3/checkout/launcher/tool/build_macos.sh"
```

The actual DMG was checksum-verified, mounted read-only, checked for payloads and its
embedded runtime smoke-tested before detaching. Its runtime SHA-256 matches the
unpacked ZIP and app: `47c306b913dc642185534426c8cc39de52ea2bed32553070c12ab203391c92fe`.
Launcher lifecycle tests use a real subprocess and accepted 81-table export to check
safe stopping, complete publication, no orphan PID, fresh instance ID and browser
opening once after HTTP readiness. They do not claim manual GUI interaction.

Failures and repairs: npm 11 rejected absolute `--prefix` installation, so CI uses
`working-directory: web`; the controlled SDK tool list initially lacked `rsync` and
`lipo`, which were added before the full build passed. Playwright's Chromium 1193 was
initially absent; Node 26 stalled extracting it, while the existing Node 24 installer
completed. The final Node 26 browser suite passed all scenarios. No scenario was removed.
The direct Rust toolchain's `rust-objcopy` emitted a missing LLVM library warning during
debug stripping; release compilation and every isolated runtime check passed, with the
actual resulting binary size/checksum retained. The zip executable-mode bug was fixed
and covered by a Rust test plus actual unzip/run verification.

The macOS workflow now builds the native distribution and launcher, checks payloads,
and runs HTTP/browser/Flutter/C# acceptance without installing or calling Python.
The legacy Python workflow is manual-only pending deletion. Remote CI has not run;
these results are local executions of its required checks.
