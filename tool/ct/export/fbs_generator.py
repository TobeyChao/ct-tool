"""生成 FlatBuffers 容器 schema（container.fbs）。

各表的 .fbs 文本由 SchemaRepository（YAML 适配器）提供，见
``ct.schema.repository.YamlSchemaRepository.fbs_sources``。
"""

from __future__ import annotations

from pathlib import Path


def generate_container_fbs(output_dir: Path) -> Path:
    """生成 container.fbs，定义 BundledTable 和 DataBundle。"""
    fbs_dir = output_dir / "fbs"
    fbs_dir.mkdir(parents=True, exist_ok=True)

    content = """\
table BundledTable {
  name: string;
  data: [ubyte];
}

table DataBundle {
  tables: [BundledTable];
}

root_type DataBundle;
"""
    out_path = fbs_dir / "container.fbs"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    return out_path
