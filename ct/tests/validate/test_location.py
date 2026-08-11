"""定位信息测试：excel_row / column / value 填充与 struct 叶子列。"""

from __future__ import annotations

from ct.schema.models import TableSchema
from ct.validate.errors import IssueCode, ValidationIssue
from ct.validate.refs import validate_refs
from ct.validate.types import validate_table


def test_render_new_format_with_exact_location() -> None:
    issue = ValidationIssue(
        table="Item",
        code=IssueCode.TYPE,
        message="期望整数类型，实际值为 'abc'（str）",
        row_index=1,
        excel_row=6,
        column=2,  # 0-based → 列 C
        field="Price",
        value="abc",
    )
    assert (
        issue.render()
        == "[Item.xlsx] Excel 第6行 · 列C (Price) · 当前值 'abc' → 期望整数类型，实际值为 'abc'（str）"
    )


def test_validate_table_populates_location() -> None:
    schema = TableSchema(
        table="Item",
        primary="Id",
        fields=[
            {"name": "Id", "type": "int32"},
            {"name": "Price", "type": "float"},
        ],
    )
    issues = validate_table(
        [{"Id": 1, "Price": "abc"}], schema, excel_rows=[3]
    )
    assert len(issues) == 1
    assert issues[0].excel_row == 3
    assert issues[0].column == 1  # Price 是第 2 列（0-based）
    assert issues[0].field == "Price"
    assert issues[0].value == "abc"


def test_struct_leaf_column_location() -> None:
    schema = TableSchema(
        table="Item",
        primary="Id",
        fields=[
            {"name": "Id", "type": "int32"},
            {"name": "Name", "type": "string"},
            {
                "name": "DropRange",
                "type": "struct",
                "fields": [
                    {"name": "Min", "type": "int32"},
                    {"name": "Max", "type": "int32"},
                ],
            },
        ],
    )
    issues = validate_table(
        [{"Id": 1, "Name": "x", "DropRange": {"Min": "abc", "Max": 2}}],
        schema,
        excel_rows=[5],
    )
    min_issue = next(i for i in issues if i.field == "DropRange.Min")
    assert min_issue.excel_row == 5
    assert min_issue.column == 2  # DropRange 展开为 C(Min)/D(Max)
    assert min_issue.value == "abc"
    assert "列C (DropRange.Min)" in min_issue.render()


def test_array_field_column_location() -> None:
    schema = TableSchema(
        table="Item",
        primary="Id",
        fields=[
            {"name": "Id", "type": "int32"},
            {"name": "Tags", "type": "array", "element": "int32"},
        ],
    )
    issues = validate_table(
        [{"Id": 1, "Tags": [1, "x"]}], schema, excel_rows=[4]
    )
    assert issues[0].field == "Tags"
    assert issues[0].column == 1
    assert issues[0].excel_row == 4


def test_duplicate_pk_location() -> None:
    schema = TableSchema(
        table="Item",
        primary="Id",
        fields=[{"name": "Id", "type": "int32"}],
    )
    issues = validate_table(
        [{"Id": 1}, {"Id": 1}], schema, excel_rows=[3, 4]
    )
    pk = next(i for i in issues if i.code == IssueCode.DUPLICATE_PK)
    assert pk.excel_row == 4
    assert pk.column == 0
    assert pk.value == 1


def test_ref_issue_location() -> None:
    schema = TableSchema(
        table="Item",
        primary="Id",
        fields=[
            {"name": "Id", "type": "int32"},
            {"name": "ItemTypeId", "type": "int32", "ref": "ItemType.Id"},
        ],
    )
    issues = validate_refs(
        [{"Id": 1, "ItemTypeId": 99}],
        schema,
        {"ItemType": {1}},
        excel_rows=[8],
    )
    assert issues[0].excel_row == 8
    assert issues[0].column == 1
    assert issues[0].value == 99
