"""把真实导出产物（bin + 生成的 accessor + JSON 真值）放到本验证工程里。

用法：CT_TOOL=/path/to/ct-tool ct/.venv/bin/python prepare.py
"""
import json, os, shutil, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CT = Path(os.environ.get("CT_TOOL", "/Users/tobeychao/Documents/Projects/ct-tool"))
sys.path.insert(0, str(CT / "ct" / "src"))
from ct.app.canonical_export import run_canonical_export  # noqa: E402

FIX = CT / "ct/tests/fixtures/repository_cutover/workspace"
# 工作区放在系统临时目录：不要把导出中间物留在这个工程里
# （否则会被 .NET SDK 的默认 Compile 通配扫到，导致 accessor 被编译两次）
ws = Path(tempfile.mkdtemp(prefix="exportverify-"))
for section in ("config", "excel", "i18n"):
    shutil.copytree(FIX / section, ws / section)
run_canonical_export(ws)

out = HERE / "generated"
if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True)
for f in (ws / "output" / "generated" / "csharp").glob("*.cs"):
    shutil.copy2(f, out / f.name)

fixtures = HERE / "fixtures"
if fixtures.exists():
    shutil.rmtree(fixtures)
fixtures.mkdir(parents=True)
for lang in ("zh", "en", "ja"):
    shutil.copy2(ws / "output" / "binary" / f"data_{lang}.bin", fixtures / f"data_{lang}.bin")
for f in (ws / "output" / "json").glob("*_*.json"):
    shutil.copy2(f, fixtures / f.name)

# FNV 对照表：C# 运行期实现必须与 Python 导出器逐位一致
from ct.export.index_query import fnv1a_64  # noqa: E402
samples = ["consumable", "equipment", "material", "A", "a", "Ａ", "中文代码", "x" * 64, "with space"]
(fixtures / "fnv_vectors.tsv").write_text(
    "".join(f"{s}\t{fnv1a_64(s)}\n" for s in samples), encoding="utf-8"
)

man = {p.stem: json.loads(p.read_text(encoding="utf-8"))
       for p in (ws / "excel" / "layout_manifests").glob("*.json")}
(fixtures / "manifests.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
print("uniform 决策:", {k: v["uniform"] for k, v in sorted(man.items())})
print(f"生成 {len(list(out.glob('*.cs')))} 个 accessor, JSON 真值 {len(list(fixtures.glob('*_zh.json')))} 份")
