# Compatibility fixture migration — 2026-09-30

Task 7.2 is accepted on main, macOS arm64. This removes executable Python dependencies
from the six fixture domains' formal preparation and template comparison paths. It does
not delete the historical scripts or pass the overall G3 gate.

## Independent inputs and expectations

`native/fixtures/compat-manifest.json` pins 130 files across binary, excel, export_pipeline,
fingerprints, schema_state and template, plus seven historical generator/comparator text
snapshots. Inputs and expectations originate from the native branch checkpoint `2d7dfc9`,
imported into main by `084be27`. Existing expected values were not rewritten.

Excel reader inputs are rebuilt from the legacy workbooks' extracted, checksummed OOXML
parts in `native/fixtures/excel/source/`. The packer only uses XML bytes and ZIP; it does
not call the native Excel writer or reader. Schema, hashing, Binary, export and template
inputs/expected values remain immutable versioned source files. Tests produce actual
results in temporary directories and compare against these independent expectations.

The independent template reader parses XML/ZIP directly. It compares all frozen properties:
cells, fills, rich text, merges, freeze panes, validations, comments, widths, heights and
custom properties. Existing color/width/height normalization and generated timestamp
normalization match the historical comparator. It calls neither the template writer's
layout logic nor the native Excel cell reader.

## Executed verification

```sh
cargo test --manifest-path native/Cargo.toml -p ct-tests-compat --locked -j 1
cargo build --manifest-path native/Cargo.toml -p ct-xtask --locked -j 1
native/target/debug/xtask compat-fixtures --out /tmp/ct-native-compat-inputs-a
native/target/debug/xtask compat-fixtures --out /tmp/ct-native-compat-inputs-b
native/target/debug/xtask template-compare native/target/tmp/template/template_v1.structure.rust.xlsx native/fixtures/template/expected/template_v1.semantics.json
native/target/debug/xtask template-compare native/target/tmp/template/template_v2a.v2a.rust.xlsx native/fixtures/template/expected/template_v2a.semantics.json
cargo test --manifest-path native/Cargo.toml --workspace --locked --no-fail-fast -j 1
openspec validate native-web-python-retirement --strict
```

The compatibility package passed 188 tests, 0 failed/ignored. This includes `excel_edge`
8/8, `template_semantics` 9/9, the 130-file oracle integrity test, and all other compatibility
targets. Full workspace passed 324 tests, 0 failed/ignored. Raw logs:
[compatibility package](compat-fixtures-tests.txt) and [workspace](compat-fixtures-workspace-tests.txt).
OpenSpec strict validation passed.

Both empty-directory preparations verified 130 files and generated all six workbooks.
The six output SHA-256 values were identical across the two directories. The same
preparation and v1 template comparison succeeded with PATH containing only the generated
fixture directory, where no executable Python or other tools exist.

The independent template reader also matched both frozen openpyxl workbooks. A deliberately
modified header failed at `$.cells.2,1` and `$.rich_runs.2,1`. A deliberately corrupted
OOXML source failed its SHA-256 check before any regeneration output was written.
The CI matrix now explicitly runs `compat-fixtures` on Linux/macOS/Windows; remote CI
execution has not been claimed as completed.

The full workspace run still includes the existing fingerprint code's Python-version
probe. Removing that probe and replacing optional live-tree coverage checks belong to
7.4; the entire test chain is not yet claimed to be Python-free. G3, L benchmark regression,
three-platform release evidence, and the deletion gate remain open.
