## 1. Schema model and canonical semantics

- [x] 1.1 Add the ordered `EnumItem(name, comment)` resource model, reject legacy string values, and verify repository round-trip, empty/duplicate/name/256-item boundary tests pass.
- [x] 1.2 Update schema hashing, dependency/identity helpers and all Enum consumers to use structured items while ignoring comments for wire output; verify comment edits change template hash, canonical defaults use the first item name, and Binary maps it to ordinal 0.
- [x] 1.3 Remove `separator` from canonical field payloads and enforce vector/ref/`excel_columns` combinations at load and candidate validation; verify old separator and invalid Record/ref vector schemas fail with located diagnostics.
- [x] 1.4 Introduce one recursive canonical default-value helper for scalar, Enum, Record and vector types; verify unit tests cover every default and nested Records.

## 2. Vector cell parsing and Excel reconstruction

- [x] 2.1 Implement the strict bracketed variable-vector tokenizer/parser with typed numeric, bool, Enum and JSON-escaped string tokens; verify acceptance, whitespace, escaping and malformed-location unit tests.
- [x] 2.2 Connect the bracket parser to canonical Excel reading and remove separator-based splitting; verify blank/`[]`, valid typed examples, unbracketed input, custom delimiters and invalid element diagnostics through reader tests.
- [x] 2.3 Rework fixed scalar/Enum/string vector reconstruction so the last explicitly filled slot determines length and earlier holes use defaults; verify `[filled, empty, filled]`, `[empty, filled, empty]`, `[empty, empty, filled]` and all-empty cases.
- [x] 2.4 Rework fixed Record vector reconstruction so any filled descendant activates a slot and missing prior slots/leaves default recursively; verify empty-leading, interior-hole, partial-Record and trailing-empty reader tests.
- [x] 2.5 Make named Record reconstruction recursive by full stable path rather than final leaf name; verify `Position.Area.{X,Y}/Z` and repeated leaf names under different parents produce the correct nested object without collisions.

## 3. Header layout tree

- [x] 3.1 Add the explicit header-node tree with mutually exclusive `field|record|array|slot` kind, derived leafness, stable path, role, depth, own comment, child list, slot index and leaf span; verify scalar slots and equal-text siblings retain unique identities.
- [x] 3.2 Expand named Records and fixed vectors recursively, derive flat leaf columns from the same tree, and compute `D` plus `header_rows=2D`; verify flat, Record, nested Record, fixed scalar vector and fixed Record vector layouts.
- [x] 3.3 Introduce `template-layout/2` and persist sufficient node/leaf identity for regeneration and data mapping; verify v2 round-trip retains slot paths, spans, depth and schema hash, an existing workbook with missing/corrupt/v1 manifest is left untouched, and a new path without workbook or manifest still generates normally.
- [x] 3.4 Serialize tracked layout manifests as deterministic four-space pretty JSON with sorted keys and one trailing newline, independently from one-record-per-line business JSON.

## 4. Workbook header rendering and styling

- [x] 4.1 Render paired comment/field rows from the node tree and implement horizontal non-leaf plus vertical shallow-leaf merges; verify exact merge ranges for flat, `DropRange.Min/Max`, nested `Position.Area.{X,Y}/Z` and fixed Record vector fixtures.
- [x] 4.2 Render field/type rich text and the agreed normal/Record/array/slot/primary tokens plus exact Enum/ref type accents; verify workbook XML and reload tests preserve names, annotations, fonts and fills, including role-precedence combinations.
- [x] 4.3 Apply borders after merges with precedence data divider > outer > top-level > sibling/slot > inner; verify representative perimeter/intersection cells have the winning edge and merged interiors have no stray dividers.
- [x] 4.4 Apply comment/field alignment, deterministic wrapped-height estimation clamped to 30–60 pt, 38 pt field heights and `freeze_panes=A{2D+1}`; verify a `D=3` workbook reloads with `A7`, expected height bounds and no frozen column.
- [x] 4.5 Attach legacy Excel Notes to every Enum leaf anchor, including fixed Enum slots, with type and ordered item comments; verify Note text/order, dimensions and absence of hidden sheets or helper columns.
- [x] 4.6 Ensure generated worksheets contain no AutoFilter and add a regression assertion that reloads representative workbooks with `auto_filter.ref` unset.

## 5. Data-entry assistance

- [x] 5.1 Add whole-data-region bool/int32 and float/double validations plus int64, ref and variable-vector prompts from `data_start_row` through row 1,048,576; verify bounds, blank handling, the >15-digit int64 text guidance, ref target text, prompt-only fallbacks and canonical-validation disclaimers after reload.
- [x] 5.2 Add ordered inline Enum validation when the complete serialized formula is at most 255 characters and a visible warning-only fallback above the limit; verify both boundaries and that neither path creates hidden workbook state.
- [x] 5.3 Remove all data-area conditional-format colors and zebra striping; keep the data area neutral white while retaining non-visual validation and Notes.
- [x] 5.4 Make template regeneration authoritative for merges, dimensions, styles, Notes, validations, conditional formatting, freeze panes and metadata while mapping only canonical data values from a compatible v2 manifest; verify stale tool-managed effects are removed, v2 values survive, and v1/untracked workbooks remain untouched with an actionable error.

## 6. Schema workbench and change planning

- [x] 6.1 Update workspace snapshot/candidate/API serialization for ordered Enum items and comments; verify API round-trip and validation-error tests use the new shape only.
- [x] 6.2 Update the Enum editor to show read-only ordinals and editable names/comments plus append, explicit rename, delete and reorder actions; encode rename commands with oldName/newName/originalOrdinal and verify component/browser tests preserve selection and Draft undo/redo behavior.
- [x] 6.3 Update add-field vector controls to remove separator, explain bracket examples and distinguish variable input from maximum expanded slots; verify Record permits only expanded slots and ref cannot become vector.
- [x] 6.4 Extend Change Plan comparison to classify comments as wire-safe, preserve ordinal for explicit rename, and report shifted old/new ordinals for insertion/reorder/delete; verify focused planner tests cover each operation and generated API-name impact.
- [x] 6.5 Scan scalar Enum cells, fixed Enum slots and bracketed Enum vectors for exact item names; atomically rewrite explicit renames, never infer delete+add, and block deletion of used values with table/field/row/value locations; verify all three storage shapes, unused deletion and rollback-on-failure tests.

## 7. Canonical JSON formatting

- [x] 7.1 Replace whole-document pretty printing with outer framing plus compact per-record serialization; verify nested Records/vectors, Unicode, escaped newlines, Schema order, finite-number rejection, commas, empty tables and exactly one final newline.
- [x] 7.2 Add text-level canonical export tests asserting one Excel record maps to one physical JSON line while parsed JSON content remains unchanged.

## 8. Controlled fixture cutover

- [x] 8.1 Confirm fixture workbooks are closed, remove the stale `gd/excel/~$item.xlsx` lock if present, convert test YAML Enums to structured items, remove separator declarations and discard v1 canonical layout manifests; verify the workspace schema loads with no compatibility path while `gd/cache/panel_history.json` remains intact.
- [x] 8.2 Delete and regenerate the controlled `gd/excel/Item.xlsx`, `ItemType.xlsx`, `Quest.xlsx` and `UIConfig.xlsx` templates, preserving no old presentation state; verify their headers, merges, Notes, validations and conditional formatting match the new rules.
- [x] 8.3 Refill the small fixture dataset using bracketed variable vectors and representative fixed-slot gaps/Enum/bool values; from `ct/`, verify `.venv/bin/ct validate --root ../gd` succeeds and specifically exercises Min and Max as distinct Item columns.
- [x] 8.4 Remove and rebuild generated fixture artifacts under `gd/output` and disposable canonical cache state while preserving `gd/cache/panel_history.json`; from `ct/`, verify `.venv/bin/ct export --root ../gd` succeeds and generated JSON uses one row per line.

## 9. Integration verification

- [x] 9.1 Run focused schema, Excel layout/reader/template, export, schema-workspace and web tests; verify every affected suite passes without unexpected warnings and the deliberate over-limit Enum warning is asserted.
- [x] 9.2 Run the full `ct` pytest suite and CLI `status`, `validate`, `export` smoke flow against `gd`; verify all commands succeed and status reports regenerated templates aligned with Schema.
- [x] 9.3 Open representative flat, nested Record and fixed Record-vector workbooks in a desktop spreadsheet application and record visual QA for text, contrast, borders, merges, Notes, dropdowns, stripes and frozen headers.
