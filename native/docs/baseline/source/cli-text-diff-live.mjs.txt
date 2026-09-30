// CLI 文本与产物差异对照（任务 6.4）：同一夹具跑原生内核，与 Python 参照的留档基线逐项比对；
// 只有 --live-python 才同机再跑一次解释器（用于刷新留档），默认路径零 Python 依赖。
// 逐字节比对正式产物，并比对归一化后的 stdout/stderr 文本。
// 只写系统临时目录的副本，绝不触碰真实 gd/。
//
// 用法：node native/tools/parity/cli-text-diff.mjs [--rust <ct.exe>] [--keep]
//       [--live-python] [--python <ct.exe>] [--python-golden <json>]
//
// 默认零外部语言依赖：Python 侧取自留档基线 JSON（不启动任何解释器）。
// 只有显式 --live-python 才同机配对实测，并把实测结果写回留档基线供后续离线复比。
import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const repoRoot = path.resolve(import.meta.dirname, "../../..");
const fixture = path.join(repoRoot, "native/fixtures/export_pipeline/workspace");
const argv = process.argv.slice(2);
const flagValue = (name, fallback) => {
  const index = argv.indexOf(name);
  return index >= 0 && argv[index + 1] ? path.resolve(argv[index + 1]) : fallback;
};
const pythonCt = flagValue("--python", path.join(repoRoot, "ct/.venv/Scripts/ct.exe"));
const pythonGoldenPath = flagValue(
  "--python-golden",
  path.join(repoRoot, "native/docs/baseline/cli-text-diff-python.json")
);
// 默认不跑 Python：留档基线才是本工具的验收路径；--live-python 才要求解释器在位。
const livePython = process.argv.includes("--live-python");
const rustCt = flagValue(
  "--rust",
  path.join(repoRoot, "native/target/release/ct.exe")
);
const keep = argv.includes("--keep");

const copyTree = (src, dst) => {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const from = path.join(src, entry.name);
    const to = path.join(dst, entry.name);
    if (entry.isDirectory()) copyTree(from, to);
    else fs.copyFileSync(from, to);
  }
};
const sha = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");

/// 收集 output/ 下的正式产物：相对路径（小写归一，跨平台大小写差异另列）→ sha256。
function outputTree(root) {
  const out = new Map();
  const base = path.join(root, "output");
  if (!fs.existsSync(base)) return out;
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else {
        const key = path
          .relative(base, full)
          .replaceAll("\\", "/")
          .toLowerCase();
        out.set(key, { sha: sha(fs.readFileSync(full)), bytes: fs.statSync(full).size });
      }
    }
  };
  walk(base);
  return out;
}

/// 压成 "共 13 条（bundle 2、table_bytes 3…）" 的一行摘要。
function cacheSummary(root) {
  const counts = cacheCounts(root);
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const parts = Object.entries(counts)
    .map(([name, value]) => `${name} ${value}`)
    .join("、");
  return parts.length === 0 ? "0 条" : `${total} 条（${parts}）`;
}

/// 生成缓存键（文件名即内容哈希）只做数量与目录集合对照，不要求跨引擎同名。
function cacheCounts(root) {
  const base = path.join(root, "cache/artifacts");
  if (!fs.existsSync(base)) return {};
  const out = {};
  for (const entry of fs.readdirSync(base, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    out[entry.name] = fs.readdirSync(path.join(base, entry.name)).length;
  }
  return out;
}

/// 归一化文本：路径分隔符、临时目录前缀、耗时数字、行尾。
function normalize(text, root) {
  const rootKey = root.replaceAll("\\", "/").toLowerCase();
  return text
    .replaceAll("\\", "/")
    .replace(/\r\n/g, "\n")
    .split(rootKey)
    .join("<WS>")
    .replace(/\b\d+(\.\d+)?\s*(s|秒|ms)\b/g, "<TIME>")
    .split("\n")
    .map((line) => line.trimEnd())
    .filter((line) => line.length > 0)
    .join("\n");
}

function decode(buffer, encoding) {
  if (!buffer) return "";
  try {
    return new TextDecoder(encoding).decode(Buffer.from(buffer));
  } catch {
    return buffer.toString("utf8");
  }
}

function run(exe, encoding, workspace, args, label) {
  const result = spawnSync(exe, args, {
    cwd: workspace,
    windowsHide: true,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) throw new Error(`${exe} ${label} 启动失败: ${result.error.message}`);
  const stdout = decode(result.stdout, encoding);
  const stderr = decode(result.stderr, encoding);
  return {
    label,
    code: result.status,
    text: normalize(
      stdout + (stderr ? `\n[stderr]\n${stderr}` : ""),
      workspace
    ),
  };
}

const engines = [
  { key: "rust", exe: rustCt, encoding: "utf8", root: null },
];
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ct-parity-"));
for (const engine of engines) {
  if (!fs.existsSync(engine.exe)) throw new Error(`缺少 ${engine.key} 入口：${engine.exe}`);
  engine.root = path.join(scratch, engine.key);
  copyTree(fixture, engine.root);
}
const pythonRoot = path.join(scratch, "python");

const scenarios = [
  ["export"],
  ["export"],
  ["export", "--all"],
  ["validate"],
  ["status"],
  ["i18n", "status"],
];

function goldenPath() {
  return pythonGoldenPath;
}
function readGolden() {
  if (!fs.existsSync(goldenPath())) return null;
  return JSON.parse(fs.readFileSync(goldenPath(), "utf8"));
}
function snapshotTree(root) {
  const tree = outputTree(root);
  return { entries: Object.fromEntries(tree), cache: cacheSummary(root) };
}
function treeFromEntries(entries) {
  return new Map(Object.entries(entries));
}

// Python 侧：同机实测（--live-python）或离线留档，二者都不改判定口径。
let pythonMode = "golden";
let golden = readGolden();
const pythonRuns = [];
if (livePython) {
  if (!fs.existsSync(pythonCt)) throw new Error(`--live-python 需要 Python 参照入口：${pythonCt}`);
  copyTree(fixture, pythonRoot);
  pythonMode = "live";
} else if (!golden) {
  throw new Error(
    `缺少 Python 留档基线：${path.relative(repoRoot, goldenPath())}\n` +
      "  生成方式（一次性，需要仓库内 Python 参照）：\n" +
      "    node native/tools/parity/cli-text-diff.mjs --live-python"
  );
}

const lines = [];
const diffs = [];
for (let index = 0; index < scenarios.length; index += 1) {
  const args = scenarios[index];
  const label = `ct ${args.join(" ")}`;
  const rs = run(engines[0].exe, engines[0].encoding, engines[0].root, args, label);
  const rsTree = snapshotTree(engines[0].root);
  let py;
  let pyTree;
  if (livePython) {
    py = run(pythonCt, "gbk", pythonRoot, args, label);
    pyTree = snapshotTree(pythonRoot);
    pythonRuns.push({ label, ...py, tree: pyTree });
  } else {
    const saved = golden.runs[index];
    if (!saved || saved.label !== label) {
      throw new Error(`留档基线第 ${index + 1} 项与当前场景表不匹配（${label}），请用 --live-python 重新生成`);
    }
    py = { label: saved.label, code: saved.code, text: saved.text };
    pyTree = { entries: saved.tree.entries, cache: saved.tree.cache };
  }
  const pyMap = treeFromEntries(pyTree.entries);
  const rsMap = treeFromEntries(rsTree.entries);
  const keys = new Set([...pyMap.keys(), ...rsMap.keys()]);
  const mismatched = [...keys].filter((key) => pyMap.get(key)?.sha !== rsMap.get(key)?.sha);
  const textSame = py.text === rs.text;
  lines.push(
    `- ${label}：退出码 ${py.code}/${rs.code}，文本${textSame ? "一致" : "**不一致**"}，` +
      `正式产物 ${Object.keys(pyTree.entries).length}/${Object.keys(rsTree.entries).length} 个，字节${mismatched.length === 0 ? "一致" : `**${mismatched.length} 个不一致**`}，` +
      `生成缓存 ${pyTree.cache} vs ${rsTree.cache}`
  );
  if (!textSame) {
    diffs.push(
      `### 文本差异：${label}\n\n\`\`\`text\n--- python ---\n${py.text}\n--- rust ---\n${rs.text}\n\`\`\``
    );
  }
  if (mismatched.length) {
    diffs.push(
      `### 产物差异：${label}\n\n` +
        mismatched
          .map((key) => `- \`${key}\`：python ${pyMap.get(key)?.sha ?? "缺失"} / rust ${rsMap.get(key)?.sha ?? "缺失"}`)
          .join("\n")
    );
  }
}

if (livePython) {
  fs.writeFileSync(
    goldenPath(),
    JSON.stringify(
      {
        schema: "ct-cli-text-golden/1",
        generatedBy: "node native/tools/parity/cli-text-diff.mjs --live-python",
        fixture: path.relative(repoRoot, fixture),
        pythonEntry: path.relative(repoRoot, pythonCt),
        runs: pythonRuns,
      },
      null,
      2
    ) + "\n"
  );
}

const report = [
  "# CLI 文本与产物对照（留档 Python 基线 vs 原生内核）",
  "",
  "由 `node native/tools/parity/cli-text-diff.mjs` 生成；夹具是",
  "`native/fixtures/export_pipeline/workspace` 的临时副本，真实 `gd/` 未被写入。",
  "",
  `- Python 侧来源：${pythonMode === "live" ? `同机实测 \`${path.relative(repoRoot, pythonCt)}\`（已刷新留档基线）` : `离线留档 \`${path.relative(repoRoot, goldenPath())}\`（本次未启动任何 Python 解释器）`}`,
  `- 原生内核：\`${path.relative(repoRoot, rustCt)}\``,
  "",
  "## 场景结果",
  "",
  ...lines,
  "",
  "## 已知且刻意保留的差异",
  "",
  "- 控制台编码：Python 在中文 Windows 下按locale(GBK) 输出，原生内核统一 UTF-8。",
  "  本对照按各自编码解码后再比文本，因此差异只反映内容本身。",
  "- 生成缓存条目名是「引擎内部 canonical 键」的内容哈希，不要求跨引擎同名；",
  "  正式产物 `output/**` 才要求逐字节一致。",
  "- Windows 上 `output/json/Item_en.json` 一类产物名，Python 经 `os.path.normcase`",
  "  会把大小写归一，原生内核保留原大小写；本对照按小写键比较，差异不会误报。",
  "",
  diffs.length ? `## 未解决差异\n\n${diffs.join("\n\n")}` : "## 未解决差异\n\n无。",
  "",
].join("\n");

const outFile = path.join(repoRoot, "native/docs/baseline/cli-text-diff.md");
fs.writeFileSync(outFile, report);
console.log(report);
console.log(`\n写入 ${path.relative(repoRoot, outFile)}`);
if (!keep) fs.rmSync(scratch, { recursive: true, force: true });
else console.log(`临时目录保留：${scratch}`);
process.exit(diffs.length ? 1 : 0);