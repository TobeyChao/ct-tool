# Complex schema example

This example covers every currently supported canonical field shape without
changing the active `gd` workspace. Copy `types/*.yaml` to
`gd/config/types/` and `schema.yaml` to `gd/config/schemas/` when a real table
is needed.

Covered features: all scalar types, enum, nested records, scalar vectors,
enum vectors, record vectors, fixed Excel expansion via `excel_columns`,
cross-table `ref`, top-level `i18n`, and top-level `server_only`.
