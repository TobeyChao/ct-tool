"""定宽体积提示：声明定宽的稀疏表在导出输出里被点名，稠密表不被点名。

定宽现在是 schema 声明（缺省 true），密度不再是决策者 —— 但**体积代价**仍要让人
看见，否则「声明定宽」就变成一笔看不见的账。提示落在那张表自己的输出行上，不阻断导出。
"""

from __future__ import annotations

from openpyxl import Workbook

from _helpers import build_project
from ct.app.canonical_export import run_canonical_export


class _Collector:
    """最小 ProgressReporter：只收集 log 行。"""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def step_started(self, step: str) -> None:
        pass

    def step_finished(self, step: str) -> None:
        pass

    def log(self, line: str, *, err: bool = False) -> None:
        self.lines.append(line)


def _workspace(tmp_path, *, filled: int):
    """10 个 int32 字段、每行只填 `filled` 个（含主键）⇒ 填充率 = filled/10。"""
    fields = [{"name": "Id", "type": "int32"}] + [
        {"name": f"F{i}", "type": "int32"} for i in range(1, 10)
    ]
    root = build_project(
        tmp_path / "gd",
        schemas=[{"table": "Sparse", "primary": "Id", "fields": fields}],
    )
    from _helpers import make_workbook

    make_workbook(
        root,
        "Sparse",
        [[row + 1] + [row + j for j in range(1, filled)] for row in range(200)],
    )
    return root


def _layout_line(root) -> str:
    reporter = _Collector()
    run_canonical_export(root, reporter=reporter)
    return next(line for line in reporter.lines if line.startswith("Sparse："))


def test_sparse_uniform_table_is_flagged(tmp_path) -> None:
    """填充率 20% ⇒ 定宽约 1.9x ⇒ 提示作者可以声明 uniform: false。"""
    line = _layout_line(_workspace(tmp_path, filled=2))
    assert "⚠" in line
    assert "uniform: false" in line


def test_dense_uniform_table_is_not_flagged(tmp_path) -> None:
    """全字段填写 ⇒ 定宽不膨胀 ⇒ 不给提示（避免噪音）。"""
    line = _layout_line(_workspace(tmp_path, filled=10))
    assert "⚠" not in line


def test_layout_precedes_fill_rate_without_causal_arrow(tmp_path) -> None:
    """填充率是诊断数字 ⇒ 该行不得排成「填充率 X% → 布局」那种读作因果的形状。"""
    line = _layout_line(_workspace(tmp_path, filled=10))
    assert line.startswith("Sparse：定宽（schema 声明）｜填充率 ")
    assert "→ 定宽" not in line
    assert "→ 变长" not in line


def test_non_uniform_table_reports_no_uniform_volume(tmp_path) -> None:
    """显式 uniform: false 的表报告为变长，不给体积对比。"""
    root = _workspace(tmp_path, filled=10)
    schema = root / "config" / "schemas" / "Sparse.yaml"
    schema.write_text(
        schema.read_text(encoding="utf-8").replace(
            "primary: Id", "primary: Id\nuniform: false"
        ),
        encoding="utf-8",
    )
    line = _layout_line(root)
    assert "变长" in line
    assert " B" not in line
