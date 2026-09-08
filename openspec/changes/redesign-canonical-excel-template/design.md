## Context

See [proposal.md](./proposal.md) for motivation. The current Excel implementation derives columns and header merges from flattened paths in separate stages. Record descendants are emitted at the wrong depth in some cases, while the template generator reconstructs parents by common prefixes. That split is the direct cause of ambiguous merges such as `DropRange.Min` and `DropRange.Max` being collapsed into one visible header.

The change crosses schema resources, the schema workbench, layout generation, workbook rendering, canonical reading and JSON serialization. Excel remains an interchange format: generated workbooks must work in common desktop spreadsheet applications without hidden support sheets or product-specific controls. OpenPyXL's legacy cell comments are rendered by Excel as Notes and are suitable for hover documentation.

## Goals / Non-Goals

**Goals:**

- Make one explicit header-node tree the source of truth for leaf columns, depth, comments, spans and merges.
- Keep workbook rendering and canonical reading deterministic from the same layout metadata.
- Make generated input assistance portable and fully reproducible during template regeneration.
- Preserve Enum byte ordinals deliberately while adding item documentation.
- Produce review-friendly JSON where each source row occupies one physical line.

**Non-Goals:**

- Preserving hand-authored workbook formatting, Notes, validation rules, conditional formatting or extra sheets.
- Providing compatibility readers or automated migrations for the old Enum value form, `separator`, or old vector cell syntax.
- Adding AutoFilter, checkbox controls, hidden lookup sheets, nested vectors or variable-width `vector<Record>` cells.
- Emitting Enum comments into FlatBuffers, C# or Lua runtime artifacts; comments are schema/editor documentation only.

## Decisions

### 1. Build an explicit header-node tree before flattening columns

Introduce a layout-level node model with, at minimum, stable path, display name, type annotation, comment, node kind, depth, children, leaf start/end column and optional fixed-slot index. Node kind is one mutually exclusive value: `field` for scalar/Enum leaves, `record`, `array`, or `slot`; leafness is derived from an empty child list, so a scalar slot can be both `kind=slot` and terminal without conflicting classifications. Semantic roles such as primary, Enum and ref remain separate attributes so they can affect styling and validation without changing tree structure.

The builder recursively expands named Records and fixed vectors. It computes leaf spans in one post-order pass, then derives the existing flat leaf-column mapping from the tree. The reader consumes those leaf mappings; the template renderer consumes both the tree and the leaf mappings. Stable paths include slot indices so two structurally identical siblings never share identity.

This is preferred to reconstructing hierarchy from dotted path strings because path-prefix grouping cannot distinguish every structural boundary and encourages rendering rules to diverge from reading rules.

### 2. Allocate two rows per depth and merge only by node identity

For a maximum tree depth `D`, depth `d` owns comment row `2d-1` and field row `2d`; data starts at `2D+1`.

- A non-leaf node merges its comment cell horizontally across its exact descendant leaf span on row `2d-1`, and merges its field cell over the same span on row `2d`.
- A leaf uses its own column on comment row `2d-1`, then vertically merges its field cell from row `2d` through row `2D`.
- Rows belonging to descendants are left available for those descendants; no rectangular merge may cover them.
- A merge is created from one node's computed span only. Adjacent nodes are never merged because their text, type or comment happens to match.
- Every schema-backed node uses the owning `FieldDef.comment`; a blank comment remains a deliberately blank cell and does not collapse the row. Generated fixed-vector slots use label `#N` and comment `第 N 个槽位；位于最后已填写槽位之前的空槽位使用默认值`, rather than borrowing the parent comment.

This regular paired-row grid is easier to inspect and test than variable row bands, and it keeps structural documentation next to the node it describes.

### 3. Centralize workbook appearance as semantic style tokens

The renderer maps node role to immutable style tokens rather than choosing colors from depth. The agreed pairs are:

| Role | Field background | Field/type text | Comment background | Comment text |
|---|---|---|---|---|
| Normal leaf | `E2E8F0` | `172033` / `64748B` | `DCE3EC` | `475569` |
| Record | `CFE8D8` | `172033` / `2F6B4A` | `DCE3EC` | `475569` |
| Array | `D7E6FA` | `172033` / `315B9A` | `DCE3EC` | `475569` |
| Slot | `E7D9F7` | `172033` / `6B4AA1` | `DCE3EC` | `475569` |
| Primary | `FBE6A5` | `172033` / `8A5A00` | `DCE3EC` | `475569` |

Field cells use centered, wrapped rich text: Aptos 11 bold for the name and Consolas 9 for the type. Comments use Aptos 9, left and vertically centered with indent 1 and wrapping; generated slot comments are centered. Comment rows start at 30 pt and may grow to 60 pt, while field rows are 38 pt. Comment height is estimated deterministically from explicit newlines plus wrapped character count across the merged column width; the maximum estimate among nodes on that row wins and is clamped to 30–60 pt.

Borders are also semantic: thin `CBD5E1` inside a node, medium `64748B` between siblings and slots, medium `1E293B` around top-level fields, medium `0F172A` around the complete header, and double `334155` between header and data. For each cell edge the precedence is data divider > outer frame > top-level boundary > sibling/slot boundary > inner line. The renderer applies the winning edge after merges are known so merged anchors and perimeter cells agree.

Header role precedence is primary > structural node kind > normal field. Enum leaves retain the normal leaf background but use `F3E8FF` for their type run; ref leaves use `CFFAFE` for their type run unless the Enum accent already applies. This makes role combinations deterministic without multiplying background styles.

The template freezes all header rows and no columns. It does not create AutoFilter metadata.

### 4. Use one built-in grammar for variable vectors

All non-expanded vectors use a JSON-like cell grammar with mandatory brackets and comma separators. Tokens are typed by element schema: numbers are unquoted, booleans are lowercase `true`/`false`, Enum items are unquoted identifiers, and strings are double-quoted with JSON escaping. Whitespace outside tokens is ignored. Blank, `[]` and `[ ]` all mean an empty vector.

Parsing is implemented as a dedicated tokenizer/parser rather than `split(',')`, so quoted string commas and escapes are unambiguous. It returns token locations for diagnostics and rejects trailing commas, missing brackets, invalid literals, old unbracketed values and nested vectors. The schema model and editor remove `separator`; there is therefore no per-field grammar for the reader and writer to reconcile.

This deliberately uses a strict subset instead of accepting arbitrary JSON, because element types and diagnostics remain controlled by the schema.

### 5. Treat `excel_columns` as maximum fixed slots

Expanded vectors have physical slots `0..N-1`. A slot is explicitly filled when any descendant leaf cell is non-empty. The actual vector ends at the last explicitly filled slot; all trailing empty slots are omitted. Any empty slot before that boundary is synthesized with the element type's canonical default, and missing leaves in a partially filled Record slot are defaulted recursively.

Canonical defaults are: integer `0`, floating point `0.0`, bool `false`, string `""`, the first declared Enum item's `name`, vector `[]`, and Record constructed recursively from its field defaults. Binary encoding maps that Enum name to ordinal 0; the canonical value is never an integer ordinal. The defaulting helper is shared by Excel reconstruction and validation so they cannot disagree. Current schema restrictions continue to reject nested vectors and vector refs.

A slot is empty only when all of its physical cells are `None` or whitespace-only strings; numeric zero, boolean false and an explicitly entered Enum name are filled values. Consequently a fully blank trailing slot is always omitted. An expanded `vector<string>` cannot represent a trailing empty-string element, and an all-string Record slot cannot represent a trailing all-default element; authors must use a non-default explicit value where possible, while variable `vector<string>` can represent an empty string as `[""]`. This limitation follows directly from the agreed last-filled-slot length rule and is documented rather than hidden behind a sentinel value.

This model is preferred to requiring contiguous input because it supports spreadsheet-like positional editing while retaining a deterministic length rule.

### 6. Model Enum values as ordered documented items

Replace `EnumResource.values: list[str]` with an ordered `EnumItem {name, comment}` collection. A name's list position is its byte ordinal and the first item is the default. Runtime generators consume item names and positions only; comments remain documentation.

Enum header leaves display the field name above `<EnumName> [enum]`. The header anchor receives one OpenPyXL `Comment` (Excel Note) containing the Enum type comment followed by each `name: comment` entry in declaration order. Fixed Enum slots each receive the same Note. This exposes documentation on hover without hidden state.

Data validation uses a literal inline list of item names only when Excel's serialized validation formula is at most 255 characters. If it exceeds that portable limit, the dropdown is omitted, but the header Note and an input warning remain. No hidden sheet, helper column or named range is introduced.

Comment-only edits do not affect ordinals. New items append by default. Rename, delete, insertion and reorder are compared by the change planner, which reports old/new ordinals and scans Excel values. An explicit rename preserves the item's position and transactionally rewrites exact occurrences in scalar Enum cells, fixed Enum slots and bracketed Enum vectors; an unpaired delete/add is not inferred as a rename. Deleting a used item remains blocked, while deleting an unused item and any insertion/reorder report all shifted ordinals as wire-level risk.

### 7. Apply input aids to the complete data region

Validation and conditional-format rules cover from `data_start_row` through Excel row 1,048,576. Bool cells receive a portable TRUE/FALSE list validation; TRUE uses fill/text `DCFCE7/166534`, FALSE uses `F1F5F9/475569`. Enum columns use fill/text `F3E8FF/581C87` and the inline dropdown when eligible. Ref columns use fill/text `ECFEFF/155E75` plus an input prompt naming the target; final cross-table validity remains the responsibility of validate/export and requires no hidden lookup data. Int32 uses bounded whole-number validation, while float/double use bounded decimal validation. Int64 receives a prompt rather than numeric DataValidation because Excel cannot exactly retain every 64-bit integer beyond 15 significant digits; the prompt tells authors to enter such values as text, and canonical validate/export remains authoritative.

When roles overlap, data assistance precedence is Bool > Enum > ref > ordinary zebra. Enum validation therefore wins over a ref prompt for an unusual Enum+ref combination. Variable vectors and over-limit Enums use prompt-only validation that always permits input, leaving syntax/value enforcement to validate/export.

Ordinary data columns keep a neutral white background without zebra striping. Bool, Enum and ref columns use only their type-specific fills, avoiding visual noise while retaining input guidance.

### 8. Serialize canonical JSON one source row per physical line

The JSON exporter writes the outer object/array framing itself and serializes each canonical row independently with compact separators, `ensure_ascii=False`, schema field order and strict finite-number handling. A comma is appended between row lines, not embedded through pretty-print indentation. Embedded control characters, including newlines in strings, remain JSON escapes, so a record can never create an extra physical line. Files end with one newline; an empty table uses a compact empty array.

This is preferred to post-processing pretty-printed JSON because line rewriting around nested structures and escaped strings is fragile.

### 9. Regeneration is authoritative for all tool-managed workbook features

Template generation recreates the workbook and reapplies the layout, merges, row/column dimensions, freeze panes, styles, Notes, validation, conditional formatting and metadata from schema. `template-layout/2` stores the new node/leaf identity. Regeneration with a compatible v2 manifest SHALL copy canonical data values by stable leaf path, but it does not merge arbitrary user workbook presentation state. When an existing workbook has a missing, corrupt or v1 manifest, it is deliberately incompatible and must be backed up/deleted before an empty template is generated; a genuinely new path with no workbook remains valid. The tool never guesses old header rows.

For this breaking change, fixtures are rebuilt instead of migrated. This keeps the production path free of temporary compatibility code and makes generated files evidence of the new canonical behavior.

## Risks / Trade-offs

- [Risk] A `2D` header can become tall for deeply nested Records. → Keep Record cycles/depth invalid at schema load, cap comment-row growth, and rely on frozen headers.
- [Risk] Excel implementations differ in rich-text, Note and validation rendering. → Use legacy Notes and standard list validation only, add package-level structure tests, and visually inspect representative files in desktop Excel/LibreOffice.
- [Risk] Whole-column conditional formatting can slow very large workbooks. → Use a constant number of formula rules per semantic column category and avoid materializing cell styles down the sheet.
- [Risk] Inline Enum lists can exceed Excel's portable formula limit. → Detect the exact serialized length, omit only the dropdown, retain documentation/warning, and report the fallback during generation.
- [Risk] Rejecting old Enum and vector syntax makes existing fixtures unreadable. → Treat this as an intentional cutover, rebuild controlled test data, and fail old schemas/cells with actionable diagnostics.
- [Risk] Enum reorder silently changes binary meaning if a consumer is not regenerated. → Surface ordinal deltas as a wire-level risk and require the normal full artifact rebuild.
- [Risk] Defaults can hide accidentally skipped fixed slots. → Explain synthesis in generated slot comments and test all gap patterns explicitly.
- [Risk] A trailing expanded element whose complete value equals visually blank defaults has no physical occupancy signal. → Document that it is omitted by definition, avoid sentinel syntax, and direct empty-string vector users to variable `[""]` form where available.

## Migration Plan

1. Land schema-model and parser changes together so old `values: [name]`, `separator`, and unbracketed vector cells fail explicitly rather than being misread.
2. Update the layout tree, recursively reconstruct nested Records in the reader, and update the template renderer behind the same canonical interfaces; add structural tests before replacing fixtures.
3. Update Enum consumers and JSON serialization, then update workbench/API payloads and change-planning risk output.
4. Close any open fixture workbook and remove the stale `~$item.xlsx` lock file if it remains.
5. Bump the layout manifest to `template-layout/2`; reject v1 for cutover while verifying a subsequent v2-to-v2 regeneration preserves canonical values.
6. Delete the tracked test workbooks and generated test outputs, update YAML fixtures to structured Enum items and bracket vectors, regenerate templates, manually refill the small canonical sample dataset, then run validate/export to rebuild outputs. Preserve unrelated panel history such as `gd/cache/panel_history.json`.
7. Run focused schema/layout/reader/export/workbench tests, the full pytest suite, and visual workbook inspection.

Rollback is a source-and-fixture revert through Git. No user-data migration state or hidden workbook state is written, so rollback does not require a reverse migrator.
