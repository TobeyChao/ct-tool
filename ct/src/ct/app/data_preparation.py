"""共享的数据准备与校验内核：选中表 → layout → Excel 读取 → issues + 主键集。

``validate`` 与 ``export`` 消费**同一份**内核，避免两套重复的布局构建、Excel
读取、主键 / CodeName / 跨表 ref 校验。两个入口各自保留自己的诊断包装与选中表范围：

- ``canonical_validate`` 把结果摊平成 ``list[Issue]``（缺 Excel 报 WorkspaceIssue
  并继续处理其他表）；
- ``run_canonical_export`` 在缺 Excel 时抛 ``FileNotFoundError``、过滤无匹配时抛
  ``ValueError``、有校验问题时抛 ``CanonicalValidationError``。

本模块**不写任何文件**、不合并译文、不产出产物。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.diagnostics.errors import Issue, IssueCode, ValidationIssue, WorkspaceIssue
from ct.excel.canonical_reader import CanonicalParsedRows, read_canonical_excel
from ct.excel.layout import Layout, build_layout
from ct.schema.hashing import compute_schema_hash
from ct.schema.resources import (
    CODENAME_FIELD,
    EnumResource,
    RecordResource,
    TableResource,
)


def records_map(workspace: CanonicalWorkspace) -> dict[str, RecordResource]:
    return {record.name: record for record in workspace.records}


def enums_map(workspace: CanonicalWorkspace) -> dict[str, EnumResource]:
    return {enum.name: enum for enum in workspace.enums}


def select_tables(
    workspace: CanonicalWorkspace, table_filter: str | None
) -> tuple[TableResource, ...]:
    """选中表：``table_filter`` 为精确匹配（不接受逗号列表/大小写模糊）。"""
    return tuple(
        table
        for table in workspace.tables
        if table_filter is None or table.table == table_filter
    )


def excel_path_of(workspace: CanonicalWorkspace, table: TableResource) -> Path:
    excel_dir = workspace.resolve("excel_dir")
    return excel_dir / (table.excel_file or f"{table.table}.xlsx")


@dataclass(frozen=True)
class PreparedTable:
    """成功读取的一张表：布局、Excel 路径与解析结果。"""

    table: TableResource
    layout: Layout
    excel_path: Path
    parsed: CanonicalParsedRows


@dataclass(frozen=True)
class PreparationResult:
    """内核输出。``issues`` 的顺序与逐表发现顺序一致（缺 Excel 在表位置处插入）。"""

    selected: tuple[TableResource, ...]
    prepared: tuple[PreparedTable, ...]
    missing_excel: tuple[Path, ...]
    id_sets: dict[str, set] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    #: 过滤值没有匹配到任何表时记录该值（两个入口各自决定怎么报）
    unknown_table: str | None = None


def primary_issues(table: TableResource, parsed: CanonicalParsedRows, seen: set) -> list[Issue]:
    """主键为空 / 重复校验，并填充 ``seen``（该表主键集合）。"""
    issues: list[Issue] = []
    for index, row in enumerate(parsed.rows, start=1):
        pk = row.get(table.primary)
        excel_row = (
            parsed.excel_rows[index - 1] if index - 1 < len(parsed.excel_rows) else None
        )
        if pk is None:
            issues.append(
                ValidationIssue(
                    table.table,
                    IssueCode.TYPE,
                    "主键为空",
                    row_index=index,
                    excel_row=excel_row,
                    field=table.primary,
                )
            )
        elif pk in seen:
            issues.append(
                ValidationIssue(
                    table.table,
                    IssueCode.DUPLICATE_PK,
                    f"主键重复: {pk!r}",
                    row_index=index,
                    excel_row=excel_row,
                    field=table.primary,
                    value=pk,
                )
            )
        else:
            seen.add(pk)
    return issues


def codename_issues(table: TableResource, parsed: CanonicalParsedRows) -> list[Issue]:
    """CodeName 索引的数据闸门：**声明了索引的表，每行必须有一个非空且唯一的 CodeName**。

    为什么必须有这道闸门（实测）：导出器建桶表时对空串 `continue`，桶里也**不判重**
    —— 于是两行写同一个 CodeName 时导出**不报错**，运行期 `ByCodeName()` 只命中探测序
    更靠前的那一行，另一行**永远查不到**，且全程没有任何提示。CodeName 的语义就是
    「这张表按它唯一索引」，静默少一行属于最难查的那类缺陷。

    只对**声明了 codename 索引**的表校验：没声明索引的表里 CodeName 就是个普通字段。
    """
    if not any(index.kind == "codename" for index in table.indexes):
        return []
    issues: list[Issue] = []
    seen: dict[str, int] = {}
    for index, row in enumerate(parsed.rows, start=1):
        excel_row = (
            parsed.excel_rows[index - 1] if index - 1 < len(parsed.excel_rows) else None
        )
        value = row.get(CODENAME_FIELD)
        text = "" if value is None else str(value)
        if text == "":
            issues.append(
                ValidationIssue(
                    table.table,
                    IssueCode.TYPE,
                    f"{CODENAME_FIELD} 为空（该表声明了 codename 索引，"
                    "空值这一行永远查不到）",
                    row_index=index,
                    excel_row=excel_row,
                    field=CODENAME_FIELD,
                    value=value,
                )
            )
        elif text in seen:
            issues.append(
                ValidationIssue(
                    table.table,
                    IssueCode.DUPLICATE_CODENAME,
                    f"{CODENAME_FIELD} 重复: {text!r}"
                    f"（首次出现在第 {seen[text]} 行）",
                    row_index=index,
                    excel_row=excel_row,
                    field=CODENAME_FIELD,
                    value=text,
                )
            )
        else:
            seen[text] = index
    return issues


def ref_issues(
    table: TableResource, parsed: CanonicalParsedRows, id_sets: dict[str, set]
) -> list[Issue]:
    """跨表 ref 外键值校验：``field.ref`` 的值必须存在于引用表主键集。"""
    ref_fields = [field for field in table.fields if field.ref]
    if not ref_fields:
        return []
    issues: list[Issue] = []
    for row_index, row in enumerate(parsed.rows, start=1):
        excel_row = (
            parsed.excel_rows[row_index - 1]
            if row_index - 1 < len(parsed.excel_rows)
            else None
        )
        for field in ref_fields:
            target_table = field.ref.partition(".")[0]
            target_field = field.ref.partition(".")[2] or "id"
            value = row.get(field.name)
            values = value if isinstance(value, list) else [value]
            target_ids = id_sets.get(target_table)
            if target_ids is None:
                issues.append(
                    ValidationIssue(
                        table.table,
                        IssueCode.REF,
                        f"引用表 {target_table} 的数据未加载，无法校验",
                        row_index=row_index,
                        excel_row=excel_row,
                        field=field.name,
                        value=value,
                    )
                )
                continue
            for v in values:
                if v is None:
                    continue
                if v not in target_ids:
                    issues.append(
                        ValidationIssue(
                            table.table,
                            IssueCode.REF,
                            f"值 {v!r} 在引用表 {target_table}.{target_field} 中不存在",
                            row_index=row_index,
                            excel_row=excel_row,
                            field=field.name,
                            value=v,
                        )
                    )
    return issues


def prepare_tables(
    workspace: CanonicalWorkspace,
    *,
    table_filter: str | None = None,
    before_table: Callable[[TableResource], None] | None = None,
    after_table: Callable[[TableResource, CanonicalParsedRows], None] | None = None,
    excel_bytes: Mapping[Path, bytes] | None = None,
) -> PreparationResult:
    """读取并校验选中的表，返回 prepared / 缺失 / 主键集 / issues。

    缺 Excel 的表**不进入** ``prepared`` 与 ``id_sets``（其 ref 校验因此不可用），
    并就地插入一条 ``WorkspaceIssue``，保持与旧 ``canonical_validate`` 相同的输出顺序。

    ``before_table`` / ``after_table`` 让调用方在不复制内核的前提下保留自己的
    逐表行为（export 用它们做取消检查与进度日志；validate 两者都不传）。
    """
    selected = select_tables(workspace, table_filter)
    if table_filter is not None and not selected:
        return PreparationResult((), (), (), {}, [], unknown_table=table_filter)

    records = records_map(workspace)
    enums = enums_map(workspace)
    prepared: list[PreparedTable] = []
    missing: list[Path] = []
    id_sets: dict[str, set] = {}
    issues: list[Issue] = []

    for table in selected:
        if before_table is not None:
            before_table(table)
        excel_path = excel_path_of(workspace, table)
        if not excel_path.exists():
            missing.append(excel_path)
            issues.append(
                WorkspaceIssue(
                    table.table, IssueCode.WORKSPACE, f"Excel 文件不存在: {excel_path}"
                )
            )
            continue
        layout = build_layout(
            table,
            schema_hash=compute_schema_hash(table, (*workspace.records, *workspace.enums)),
            records=records,
        )
        parsed = read_canonical_excel(
            excel_path,
            layout,
            table,
            records=records,
            enums=enums,
            data=(excel_bytes or {}).get(excel_path),
        )
        issues.extend(parsed.issues)
        seen: set = set()
        issues.extend(primary_issues(table, parsed, seen))
        issues.extend(codename_issues(table, parsed))
        prepared.append(PreparedTable(table, layout, excel_path, parsed))
        id_sets[table.table] = seen
        if after_table is not None:
            after_table(table, parsed)

    # 跨表 ref 外键值校验需要全部选中表的主键集，故在所有表读完后单独一轮
    for item in prepared:
        issues.extend(ref_issues(item.table, item.parsed, id_sets))

    return PreparationResult(
        selected=selected,
        prepared=tuple(prepared),
        missing_excel=tuple(missing),
        id_sets=id_sets,
        issues=issues,
    )
