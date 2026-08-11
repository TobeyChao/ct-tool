"""结构化 Issue 测试：渲染文本快照与分类。"""

from __future__ import annotations

from ct.schema.models import TableSchema
from ct.validate.errors import IssueCode, ValidationIssue, report_errors
from ct.validate.refs import validate_refs
from ct.validate.types import validate_table


def _table_schema() -> TableSchema:
    return TableSchema(
        table="Item",
        primary="Id",
        fields=[
            {"name": "Id", "type": "int32"},
            {"name": "Price", "type": "float"},
        ],
    )


def test_validation_issue_render_matches_legacy_text() -> None:
    issue = ValidationIssue(
        table="Item",
        code=IssueCode.TYPE,
        message="期望整数类型，实际值为 'abc'（str）",
        row_index=1,
        field="Price",
        value="abc",
    )
    assert issue.render() == "[Item.xlsx] 第1行 Price：期望整数类型，实际值为 'abc'（str）"


def test_validate_table_returns_typed_issues() -> None:
    schema = _table_schema()
    rows = [
        {"Id": 1, "Price": "abc"},
        {"Id": 1, "Price": 2.0},
    ]
    issues = validate_table(rows, schema)

    assert all(isinstance(i, ValidationIssue) for i in issues)
    codes = [i.code for i in issues]
    assert IssueCode.TYPE in codes
    assert IssueCode.DUPLICATE_PK in codes
    pk_issue = next(i for i in issues if i.code == IssueCode.DUPLICATE_PK)
    assert pk_issue.field == "Id"
    assert pk_issue.value == 1
    assert "主键值 1 重复（首次出现在第1行）" in pk_issue.message


def test_validate_refs_returns_ref_issues() -> None:
    schema = TableSchema(
        table="Item",
        primary="Id",
        fields=[
            {"name": "Id", "type": "int32"},
            {"name": "TypeId", "type": "int32", "ref": "ItemType.Id"},
        ],
    )
    issues = validate_refs([{"Id": 1, "TypeId": 99}], schema, {"ItemType": {1}})
    assert len(issues) == 1
    assert issues[0].code == IssueCode.REF
    assert issues[0].value == 99
    assert "ItemType.Id 中不存在" in issues[0].message


def test_report_errors_renders_legacy_format(capsys) -> None:
    issue = ValidationIssue(
        table="Item",
        code=IssueCode.TYPE,
        message="期望整数类型，实际值为 'abc'（str）",
        row_index=3,
        field="Price",
    )
    report_errors([issue])
    captured = capsys.readouterr()
    assert "\n验证发现 1 个错误：\n" in captured.err
    assert "  ✗ [Item.xlsx] 第3行 Price：期望整数类型，实际值为 'abc'（str）" in captured.err


def test_issue_to_dict_carries_structure() -> None:
    issue = ValidationIssue(
        table="Item",
        code=IssueCode.REF,
        message="值 99 不存在",
        row_index=2,
        field="TypeId",
        value=99,
    )
    data = issue.to_dict()
    assert data["code"] == "ref"
    assert data["row_index"] == 2
    assert data["field"] == "TypeId"
    assert data["value"] == 99
