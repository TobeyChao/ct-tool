## 1. Baseline and delivery gates

- [x] 1.1 Capture the current 4 Schema files, 4 Excel files, JSON, FBS, Binary and C#/Lua outputs as repository-cutover fixtures, and verify the fixture export succeeds with `cd ct && pytest` plus a recorded full export.
- [x] 1.2 Add a feature entry gate that keeps the production Schema module on the old read-only path until the new end-to-end apply test passes, and verify neither UI exposes two writable Schema flows simultaneously.
- [x] 1.3 Add Playwright to the Python test environment, drive the local Web Panel without a frontend build chain, define the v4 screenshot fixtures and viewport/zoom matrix, and verify CI/local baseline captures plus a packaged 720×460 launcher smoke capture.

## 2. Canonical Type Expression and named resources

- [x] 2.1 Implement scalar/named/vector Type Expression models, parser and canonical serializer, and verify round-trip, reserved-name, malformed-expression and nested-vector unit tests.
- [x] 2.2 Update FieldDef and all schema hashing/serialization paths to consume the Type Expression AST instead of mutually exclusive type fields, and verify model/hash tests cover every node kind.
- [x] 2.3 Implement named Record and Enum models plus `config/types/*.yaml` repository loading/writing, and verify mixed Table/Record/Enum workspace fixtures load deterministically.
- [x] 2.4 Introduce stable resource IDs, draft field IDs and canonical field paths without persisting UUID noise to YAML, and verify rename/move/path identity tests.
- [x] 2.5 Add global name and generated FBS-name collision validation, and verify conflicts report both resource/field locations without traceback.
- [x] 2.6 Update Workspace construction so CLI, Web, Excel, validation and generators receive one canonical resource graph, and verify no downstream module reparses raw type strings.
- [x] 2.7 Enforce v1 role boundaries (`i18n` and `server_only` only on top-level Table fields, no i18n/server-only Record leaves), and verify load and Candidate errors preserve precise resource paths.
- [x] 2.8 Fix named Enum wire type to FlatBuffers `byte` across canonical model, API and editor display, and verify requests cannot mutate it.

## 3. Dependencies, references and repository cutover

- [x] 3.1 Extend dependency analysis to named Record/Enum edges and reverse references while retaining cross-table ref order, and verify direct, indirect, missing-target and deterministic-order tests.
- [x] 3.2 Reject invalid dependency cycles and deletion of referenced resources/fields with complete paths, and verify direct/indirect cycle and multi-reference deletion tests.
- [x] 3.3 Implement explicit resource/field rename commands that update all candidate references atomically, and verify undo plus old-path→new-path mapping tests.
- [x] 3.4 In one reviewable repository change, create deterministic named types for the 2 inline Enums and 1 inline struct, convert the 1 array to vector, and update all 4 tracked Schema files and test fixtures without adding a runtime migration reader or command.
- [x] 3.5 Update the 4 tracked Excel workbooks through explicit reviewed column/path mappings, verify their small data sets cell-by-cell, and compare JSON/FBS/Binary/C#/Lua output against the pre-cutover golden wherever semantics are unchanged.
- [x] 3.6 Remove old struct/array/inline-enum parser and writer branches; add a read-only fail-fast error with file/field/new-format guidance, and verify product CLI/Web exposes no migrate-schema command, upgrade page or automatic old-format mutation.

## 4. Excel layout and data change planning

- [x] 4.1 Implement canonical column layout generation for scalar, Enum, Record, single-cell vector and expanded `vector<Record>`, and verify path/order/header-depth unit tests.
- [x] 4.2 Generate Excel headers from the layout model with aligned rich-text annotations matching the Web type expressions, and verify workbook render/golden tests.
- [x] 4.3 Implement `cache/template_layouts/<table>.json` manifests tied to schema/layout revision, and verify create/read/corruption/missing-cache behavior.
- [x] 4.4 Update the Excel reader to reconstruct Record and expanded `vector<Record>` values, skip fully empty trailing groups and retain exact row/column paths in issues, and verify reader tests.
- [x] 4.5 Implement stable-path and explicit-rename column mapping for template updates, and verify reorder/rename/Record expansion tests never copy by raw column position.
- [x] 4.6 Add data scans for deleted columns, `excel_columns` shrink, Enum value removal and type conversion, and verify blocking plans include concrete rows, columns and sample values.
- [x] 4.7 Add untracked-layout preflight with reviewable inference and no silent writeback, and verify missing-manifest workbooks cannot bypass review.

## 5. Export pipeline and query indexes

- [x] 5.1 Update validation and JSON export for named Record/Enum and `vector<Record>`, replacing old struct/array semantics, and verify scalar, Enum, Record, vector and `vector<Record>` JSON golden output.
- [x] 5.2 Generate one deterministic shared `types.fbs` for all named Record/Enum definitions, make Table schemas include it, reject duplicate symbols/include cycles, and verify generated schemas compile without copied definitions or accidental native struct.
- [x] 5.3 Update Binary serialization for Record and `vector<Record>`, and verify byte-level round trips against generated readers for empty, partial and full groups.
- [x] 5.4 Update C# and Lua field accessors for the new type model, and verify both languages return the same Record/vector values while top-level Table i18n/server-only behavior remains unchanged.
- [x] 5.5 Add table-level Code and Group index models plus Candidate data validation, and verify Code type/non-empty/exact-string uniqueness, Group repeated values, integer-primary independence and rejection of i18n index fields.
- [x] 5.6 Generate symmetrical C#/Lua Code and Group APIs with deterministic missing and ordering semantics, and verify generated-code integration tests.
- [x] 5.7 Define the production hash algorithm over the reader's exact UTF-8 string, implement buckets retaining that string with case-sensitive ordinal confirmation and no trim/case-fold/NFC/NFKC, and verify C#/Lua golden plus injectable-collision tests for hit, wrong-string and missing queries.
- [x] 5.8 Add normal-bucket and adversarial-collision benchmarks proving original-value checks stay bucket-local, and record candidate comparisons and latency without a full-table scan.
- [x] 5.9 Verify changing only separator or `excel_columns` leaves FBS/Binary/Accessor wire contracts unchanged while changing template hash and plan output.
- [x] 5.10 Replace Excel-only incremental detection with per-Table `schema_fingerprint` and `data_fingerprint`, including transitive Record/Enum dependencies, indexes, parsing inputs and format versions; verify direct/indirect shared-type changes re-export every dependent Table while ref-target data-only changes do not cascade.
- [x] 5.11 Add semantic `i18n_fingerprints[lang]` over valid source keys plus effective text/confirmed, language config and merge-policy version; verify translation-only edits, confirmation toggles, missing/corrupt files and added/removed languages are detected without hashing derived status/source/orphans or formatting.
- [x] 5.12 Split artifact reuse so schema controls FBS/Accessor, data controls primary JSON/main bytes, per-language i18n controls language JSON/i18n bytes, and bundle fingerprints control only the corresponding Bundle; verify an en-only edit does not rewrite primary/ja/FBS/Accessor artifacts.
- [x] 5.13 Compute final i18n fingerprints after canonical sync when source data changes, publish fingerprints only with successful artifacts, and verify export does not immediately self-invalidate or hide a failed language build behind old cached bytes.

## 6. Workspace Draft and Change Plan domain

- [x] 6.1 Implement WorkspaceSnapshot revision hashing across managed Schema, transitive type dependencies, Excel, i18n language files/config and generation inputs, and verify deterministic hashes plus external-change detection without treating derived formatting as semantic output changes.
- [x] 6.2 Define and implement the complete Draft command set and reducer with undo/redo cursor semantics, and verify add/delete/rename/move/property/index command tests.
- [x] 6.3 Build Candidate Workspace from base revision plus commands and run full type/name/dependency/data/generator validation, and verify cross-resource errors block planning.
- [x] 6.4 Implement Change Plan risk classification and per-artifact impact records for Schema, Excel, FBS, Binary and Accessors, and verify golden plans for safe, data-dependent, destructive, incompatible and dependency-breaking edits.
- [x] 6.5 Add stable issue locations and “return to field/resource” identifiers to every plan problem, and verify Web API payloads never return only generic error strings.
- [x] 6.6 Persist versioned Draft command logs in IndexedDB keyed by workspace and base revision, keep only small preferences in localStorage, and verify refresh recovery, stale/rebase-or-discard behavior and quota-failure warning without losing the in-memory Draft.

## 7. Transactional Apply and Web API

- [x] 7.1 Implement same-filesystem staging, workspace apply lock and plan manifest/token storage with a default two-hour `expiresAt`, and verify concurrent, content-stale, restarted-incomplete or expired plans are rejected before writes.
- [x] 7.2 Generate all Candidate files in staging and run Schema reload, Excel reread, FBS/Binary and Accessor postchecks, and verify any generator failure prevents publish.
- [x] 7.3 Implement durable journal, transaction backup and stepwise `os.replace` publishing of workspace files plus matching layout/export cache state, and verify successful apply yields one internally consistent revision and clears only applied Draft commands.
- [x] 7.4 Implement startup recovery for interrupted publishing at every journal phase, and verify fault-injection tests recover a complete old or new revision, never a mixed set.
- [x] 7.5 Add Workspace snapshot, validate, change-plan and apply endpoints using structured JSON and plan hashes, and verify API contract and stale-source tests.
- [x] 7.6 Route existing Schema read endpoints through WorkspaceSnapshot, remove direct writable endpoints after the v4 cutover, and verify production routes expose only one write protocol.
- [x] 7.7 Surface long-running plan/apply progress and failures through persistent task state, and verify changing Web modules does not lose task status or actionable errors.
- [x] 7.8 Preflight every publish target for writability/file locks, with Windows Excel/Office coverage, and verify a locked `.xlsx` fails before backup/publish with exact paths, close-and-retry guidance and unchanged workspace/cache bytes.

## 8. Web Panel foundation and design system

- [x] 8.1 Split static CSS into token/base/layout/component/module layers using the approved forest-green palette and contrast values, and verify no production module defines duplicate brand/status colors.
- [x] 8.2 Split frontend code into native ES module core, shared components and module boundaries without adding a build chain, and verify the packaged panel loads offline from the Python distribution.
- [x] 8.3 Implement unified AppShell, top workspace header and desktop/mobile module navigation, and verify all five existing modules are reachable by keyboard and route.
- [x] 8.4 Implement shared ModuleHeader, CommandBar, DataTable, Inspector, StatusBadge, InlineIssue, TaskBar, Dialog, Toast and EmptyState contracts, and verify component state fixtures.
- [x] 8.5 Add shared API, error, task and focus management, and verify actionable errors persist while Toast remains limited to completed lightweight actions.
- [x] 8.6 Add reduced-motion, visible-focus, contrast and hidden/inert accessibility rules, and verify automated checks plus keyboard traversal of shared fixtures.

## 9. Adaptive Schema workspace shell

- [x] 9.1 Implement a route/store model for resource, tab, selection path, navigation stack, pane preferences and scroll positions independent of DOM visibility, and verify resize does not mutate domain state.
- [x] 9.2 Implement `wide` three-pane projection at `>=1360px` with resizable resource and inspector areas, and verify widths persist by layout class without table misalignment.
- [x] 9.3 Implement `medium` main+inspector projection with one temporary resource selector, and verify close leaves no strip, space, scrim or focusable hidden content.
- [x] 9.4 Implement `<960px` resources→editor→properties page stack and `<600px` bottom module navigation, and verify application/system Back follows the expected hierarchy.
- [x] 9.5 Implement Activity Tab `activeTool/null` behavior for side areas with clipped grid-track motion instead of off-screen translation, and verify collapsed inspector always has a restore control.
- [x] 9.6 Implement compact field-row rendering and shared desktop table column templates, and verify 720×460 and 390×844 editing without global horizontal scroll or covered actions.

## 10. Schema editing experience

- [x] 10.1 Implement Tables/Records/Enums resource pages and atomic resource switching, and verify title, metadata, tabs, content and inspector never show mixed resources.
- [x] 10.2 Implement Table and Record field editors with add/delete/rename/reorder, type expression, roles and comments, and verify each action emits a Draft command rather than a file write.
- [x] 10.3 Implement Enum value editing, read-only fixed `byte` wire-type display and reverse-reference navigation, and verify duplicate/empty/removal-with-data validation plus rejection of wire-type mutation.
- [x] 10.4 Implement the searchable type picker with base/Enum/Record groups and orthogonal single/vector toggle, and verify it cannot edit a named type inline or create nested vectors.
- [x] 10.5 Implement field Inspector sections for ref, i18n, server_only, comment and Excel input layout, and verify illegal combinations show local and backend errors at the same path.
- [x] 10.6 Implement Table query-index cards with generated API previews and data preflight summaries, and verify Records/Enums do not expose index controls.
- [x] 10.7 Implement dependency/reference views and blocked delete/rename flows with navigation to each use site, and verify no cascade-delete path is available.
- [x] 10.8 Implement Draft summary, undo/redo, reset-current-field, discard-all and “审查并应用” entry, and verify resource/pane/module navigation retains pending changes.
- [x] 10.9 Implement Change Plan and Excel data-mapping detail pages with grouped risks, path mapping, row samples and return-to-field actions, and verify primary Apply stays disabled for blockers.

## 11. Resource discovery and large-list behavior

- [x] 11.1 Build the DOM-independent ResourceIndex and shared fuzzy scorer with highlighted match ranges, and verify abbreviations, multi-word queries, ties and deterministic ordering.
- [x] 11.2 Implement left resource filtering with match/total counts, temporary search expansion, empty state and restored group preferences, and verify collapsed-group keyboard scenarios.
- [x] 11.3 Implement `Cmd/Ctrl+P` Quick Open with recent resources, all-resource search, type disambiguation and full keyboard controls, and verify it works while the resource pane is absent.
- [x] 11.4 Implement the shared fixed-row virtual list for resource tree and Quick Open with stable keys, overscan and accessible position metadata, and verify one rendering path is used at all item counts.
- [x] 11.5 Run 100/1,000/10,000 resource benchmarks for first paint, input latency, scroll, DOM nodes and memory, and record acceptable thresholds plus any overscan tuning.

## 12. Existing module visual redesign

- [x] 12.1 Move Export into the shared shell/CommandBar/TaskBar while preserving current export/cancel behavior, and verify existing export API and tests remain unchanged.
- [x] 12.2 Move i18n into shared DataTable/Inspector patterns with existing sync/status/compact semantics, and verify translation files and state counts are unchanged.
- [x] 12.3 Move Logs to the shared full-width viewer and persistent issue details, and verify module/level/search filters plus links from task failures.
- [x] 12.4 Move History to the shared module layout while retaining the backend’s latest-five limit, and verify record ordering and log navigation.
- [x] 12.5 Remove duplicated module CSS, old top-level tabs and obsolete modal navigation only after parity tests pass, and verify no dead selectors, handlers or writable Schema routes remain.

## 13. End-to-end qualification and cutover

- [x] 13.1 Add an end-to-end flow starting from the repository-cutover new-format workspace, edit Table/Record/Enum and `vector<Record>`, configure indexes, review and atomically apply, and verify all YAML/Excel/JSON/FBS/Binary/C#/Lua outputs.
- [x] 13.2 Add end-to-end stale-plan (including externally edited translation files), blocked-reference, destructive-Excel and interrupted-publish cases, and verify every failure leaves the original workspace byte-for-byte consistent.
- [x] 13.3 Execute the required viewport and 100%/125%/150% zoom screenshot matrix through Playwright in CI/local runs plus the packaged launcher smoke run, and verify no pane strip, overlap, table header drift, clipped action or stale mixed-resource content.
- [x] 13.4 Complete keyboard, focus restoration, reduced-motion and hidden/inert accessibility walkthroughs, and record fixes for every blocking issue.
- [x] 13.5 Run the full `cd ct && pytest` suite, generated C#/Lua integration checks and performance baselines, and attach passing results to the change review.
- [x] 13.6 After the architecture/cleanup gate in section 14 passes, enable the v4 production entry, remove the temporary feature gate and old writable Schema path, and verify a clean install plus packaged launcher workspace completes the same end-to-end flow.

## 14. Architecture and maintainability gate

- [x] 14.1 Add an AST-based import-boundary test for `delivery (cli/web) → app → schema/excel/validate/export/cache → diagnostics/config`, and verify lower layers cannot import `ct.app`, `ct.web` or `ct.cli` and no dependency cycle is introduced.
- [x] 14.2 Extract shared Issue/Location contracts into a dependency-neutral diagnostics module, keep Schema repository limited to canonical resource persistence/source locations, and move all FBS text generation into `ct/export`; verify repository tests do not import generators and schema domain does not import validation/application code.
- [x] 14.3 Organize Workspace transaction code under `ct/app/schema_workspace/` with explicit snapshot, command/reducer, candidate, plan, apply/publish and recovery responsibilities; verify validate/plan paths are side-effect free and only apply/publish can write managed files.
- [x] 14.4 Reduce `ct/web/app.py` to application factory/dependency wiring/blueprint registration, split routes and response presenters by module, and verify route modules contain no direct YAML/Excel/cache writes, `os.replace`, or generator orchestration.
- [x] 14.5 Keep one shared Accessor/Index model for C# and Lua and one canonical Type Expression dispatcher for all downstream modules; verify an AST/text guard finds no old struct/array/inline-enum parsing anywhere in product code.
- [x] 14.6 Complete the planned ES-module split so core/store/router/task/focus code has no imports from business modules, modules communicate only through public core/shared contracts, and verify the old monolithic `app.js`, obsolete modal CSS and mutable duplicate state owners are removed after parity.
- [x] 14.7 Perform behavior-preserving extractions as separately tested green steps before adding new behavior, run focused tests after each boundary move, then run `git diff --check`, the full pytest suite, architecture guards and dead-code/obsolete-route scans before cutover.
