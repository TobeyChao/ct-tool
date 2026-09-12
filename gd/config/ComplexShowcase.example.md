# Complex schema example

This example covers every currently supported canonical field shape without
changing the active `gd` workspace. Copy the referenced `types/*.yaml` into
`gd/config/types/` and the body below into
`gd/config/schemas/ComplexShowcase.yaml` when a real table is needed.

Covered features: scalars, a named enum, a nested Record, scalar / Enum /
Record vectors, fixed Excel expansion via `excel_columns`, cross-table `ref`,
top-level `i18n`, top-level `server_only`, and the table-level `codename`
query index.

```yaml
table: ComplexShowcase
primary: Id
fields:
  - name: Id
    type: int32
    comment: 主键（int32）
  - name: CodeName
    type: string
    comment: 代号查询键；声明 codename 索引后每行必须非空且唯一
  - name: DisplayName
    type: string
    i18n: true
    comment: 多语言显示名（i18n 只允许顶层 string）
  - name: Rarity
    type: ShowcaseRarity
    comment: 具名 Enum（config/types/ShowcaseRarity.yaml）
  - name: Bounds
    type: RewardBounds
    comment: 嵌套 Record（config/types/RewardBounds.yaml）
  - name: ItemTypeId
    type: int32
    ref: ItemType.Id
    comment: 跨表引用 ItemType.Id 的外键
  - name: Tags
    type: vector<int32>
    comment: 变长标量 vector，Excel 用 [1,2,3] 文法
  - name: Rarities
    type: vector<ShowcaseRarity>
    excel_columns: 3
    comment: 定长 Enum vector，最多三个槽位
  - name: SpawnPoints
    type: vector<WorldPosition>
    excel_columns: 2
    comment: 定长 Record vector，Record vector 必须配 excel_columns
  - name: IsActive
    type: bool
    server_only: true
    comment: 仅服务端；不进客户端 Binary，但保留在 JSON
indexes:
  - kind: codename
```

`indexes` 条目只接受 `kind` 一个键 —— codename 固定指向名为 `CodeName` 的
`string` 字段，不写 `field`。声明该索引后，每行的 `CodeName` 必须非空且表内
唯一，否则 `ct export` 的「解析校验」阶段与 `ct validate` 都会以
`IssueCode.DUPLICATE_CODENAME` 失败（空值报 `type`）；未声明该索引时，
`CodeName` 只是一个普通字段。
