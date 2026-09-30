"""生成 Schema 工作区对照 golden（rust-native-core 任务 3.12）。

运行方式（仓库根目录）::

    ct/.venv/Scripts/python.exe native/fixtures/schema_state/generate.py

输入：workspace/（基线工作区）与 commands.json（草稿命令序列，Rust 测试共用）。
产物：golden.json —— Python 计算的 schemaRevision、resourceHash、schemaHash、
candidateHash、netDiff 与 Goods 表的 dump_yaml 字节，供 Rust 侧逐项对照。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent.parent / "ct" / "src"))

from ct.app.schema_workspace.candidate import candidate_hash, merge_indexes  # noqa: E402
from ct.app.schema_workspace.commands_reducer import Command, apply_commands  # noqa: E402
from ct.app.schema_workspace.netdiff import compute_net_diff  # noqa: E402
from ct.app.schema_workspace.snapshot import (  # noqa: E402
    build_schema_revision,
    capture_schema_contents,
)
from ct.config import load_config  # noqa: E402
from ct.schema.hashing import compute_resource_hash, compute_schema_hash  # noqa: E402
from ct.schema.resource_repository import YamlResourceRepository, dump_yaml  # noqa: E402
from ct.schema.resources import resource_to_data  # noqa: E402

WORKSPACE = HERE / "workspace"


def main() -> None:
    config = load_config(WORKSPACE)
    contents = capture_schema_contents(config)
    revision = build_schema_revision(config, contents=contents)

    repo = YamlResourceRepository(
        config.resolve("schemas_dir"), config.resolve("types_dir"), contents=contents
    )
    workspace = repo.load()
    base = workspace.resources

    commands = [
        Command(type=entry["kind"], payload=entry["payload"])
        for entry in json.loads((HERE / "commands.json").read_text(encoding="utf-8"))
    ]
    base_indexes = {
        table.resource_id: table.indexes for table in workspace.tables
    }
    state = apply_commands((base, base_indexes), commands)
    resources, indexes = state
    merged = merge_indexes(resources, indexes)
    net_diff = compute_net_diff((base, base_indexes), (merged, indexes), commands, cursor=len(commands))

    goods = next(r for r in merged if getattr(r, "table", None) == "Goods")
    item = next(r for r in base if getattr(r, "table", None) == "Item")

    golden = {
        "schemaRevision": revision.to_payload(),
        "configDigest": revision.config_digest,
        "resourceHashes": {
            resource.resource_id: compute_resource_hash(resource) for resource in base
        },
        "schemaHashItem": compute_schema_hash(item, tuple(base)),
        "candidateHash": candidate_hash(resources, indexes),
        "netDiff": net_diff.to_payload(),
        "goodsYaml": dump_yaml(resource_to_data(goods)),
        "rarityYaml": dump_yaml(
            resource_to_data(next(r for r in merged if getattr(r, "name", None) == "Rarity"))
        ),
    }
    out = HERE / "golden.json"
    out.write_bytes(json.dumps(golden, ensure_ascii=False, indent=2).encode("utf-8"))
    print("wrote", out)
    print("revision:", revision.revision[:16])
    print("candidate:", golden["candidateHash"][:16])


if __name__ == "__main__":
    main()
