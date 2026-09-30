"""生成指纹对照 golden（rust-native-core 任务 5.2）。

运行方式（仓库根目录）::

    ct/.venv/Scripts/python.exe native/fixtures/fingerprints/generate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent.parent / "ct" / "src"))

from ct.cache.fingerprints import (  # noqa: E402
    data_fingerprint,
    effective_translation_semantics,
    i18n_fingerprint,
    schema_fingerprint,
)


def main() -> None:
    table = {"table": "Item", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]}
    deps = [{"kind": "enum", "name": "Rarity", "values": [{"name": "Common"}]}]
    indexes = [{"kind": "codename"}]
    schema_fp = schema_fingerprint(table, deps, indexes, codegen_version="incremental/2-schema-layout")
    data_fp = data_fingerprint(schema_fp, "excel-sha", parsing_inputs={"parser": "canonical/1"})
    entries = {
        "1001.Name": {"text": "Iron Sword", "confirmed": True, "status": "confirmed", "source": "铁剑"},
        "1002.Name": {"text": "", "confirmed": False, "status": "missing", "source": "铁盾"},
        "9999.Ghost": {"text": "幽灵", "confirmed": True, "status": "orphan", "source": "?"},  # 无效 key 不参与
    }
    valid_keys = {"1001.Name", "1002.Name"}
    i18n_fp = i18n_fingerprint(
        data_fp,
        lang="en",
        primary_lang="zh",
        enabled_langs=["zh", "en"],
        valid_keys=valid_keys,
        entries=entries,
    )

    golden = {
        "inputs": {
            "table": table,
            "dependencies": deps,
            "indexes": indexes,
            "codegen": "incremental/2-schema-layout",
            "excelHash": "excel-sha",
            "parsing": {"parser": "canonical/1"},
            "lang": "en",
            "primaryLang": "zh",
            "enabledLangs": ["zh", "en"],
            "validKeys": sorted(valid_keys),
            "entries": entries,
        },
        "schemaFingerprint": schema_fp,
        "dataFingerprint": data_fp,
        "i18nFingerprint": i18n_fp,
        "semantics": [list(item) for item in effective_translation_semantics(entries, valid_keys)],
    }
    out = HERE / "golden.json"
    out.write_bytes(json.dumps(golden, ensure_ascii=False, indent=2).encode("utf-8"))
    print("wrote", out)


if __name__ == "__main__":
    main()
