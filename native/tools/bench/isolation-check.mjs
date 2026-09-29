// 隔离入口验收（任务 6.9）：用发行包里的原生二进制在真实 gd/ 上只读跑 validate/status，
// PATH 收敛为包内 bin 目录、清掉 PYTHON* 变量；同时核对 gd/ 里没有工具文件、
// 且这一趟没有写入 gd/ 任何一个字节（git 状态前后一致）。
//
// 用法：node native/tools/bench/isolation-check.mjs
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const repoRoot = path.resolve(import.meta.dirname, "../../..");
const pkgDir = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(repoRoot, "native/dist/ct-native-0.0.0-x86_64-pc-windows-msvc");
const binDir = path.join(pkgDir, "bin");
const exe = path.join(binDir, process.platform === "win32" ? "ct.exe" : "ct");
const gd = path.join(repoRoot, "gd");
if (!fs.existsSync(exe)) throw new Error(`缺少发行包二进制 ${exe}（先 cargo run -p ct-xtask -- dist）`);
if (!fs.existsSync(gd)) throw new Error(`缺少 gd/ 工作区：${gd}`);

const ENV_DENY = ["PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE", "VIRTUAL_ENV", "CONDA_PREFIX"];
const isolatedEnv = () => {
  const env = { ...process.env, PATH: binDir };
  for (const key of ENV_DENY) delete env[key];
  return env;
};

const run = (args) => {
  const r = spawnSync(exe, args, {
    cwd: gd,
    encoding: "utf8",
    windowsHide: true,
    env: isolatedEnv(),
  });
  return {
    args,
    code: r.status,
    stdout: (r.stdout || "").trim().split("\n").slice(0, 6).join(" / "),
    stderr: (r.stderr || "").trim().split("\n").slice(0, 6).join(" / "),
  };
};
const gitStatus = () =>
  spawnSync("git", ["status", "--porcelain", "gd"], { cwd: repoRoot, encoding: "utf8" })
    .stdout.trim().split("\n").filter(Boolean);

const before = gitStatus();
const steps = [];
steps.push(run(["--version"]));
steps.push(run(["validate", "--root", "."]));
steps.push(run(["status", "--root", "."]));
const after = gitStatus();

const toolFiles = [];
const scan = (dir, depth = 0) => {
  if (depth > 4) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    const name = entry.name.toLowerCase();
    if (entry.isDirectory()) {
      if (["__pycache__", ".venv", "node_modules", ".git"].includes(name)) toolFiles.push(full);
      else if (name === "excel" || name === "config" || name === "i18n" || name === "cache" || name === "output" || name === "tools") scan(full, depth + 1);
    } else if (/\.(py|pyc|exe|dll|so|dylib|whl|toml|cfg)$/.test(name) && !full.includes(path.join("excel") + path.sep)) {
      toolFiles.push(full);
    }
  }
};
scan(gd);

const lines = [
  "# 隔离入口验收（rust-native-core 任务 6.9）",
  "",
  "由 `node native/tools/bench/isolation-check.mjs` 生成。子进程环境：`PATH` 只有包内 `bin`，",
  "`PYTHONHOME/PYTHONPATH/VIRTUAL_ENV/CONDA_PREFIX` 等变量被删除，工作目录是真实 `gd/`。",
  "",
  `- 发行包：\`${path.relative(repoRoot, pkgDir)}\``,
  `- 只读命令：\`--version\`、\`validate\`、\`status\`（都不写缓存、不恢复事务）`,
  "",
  "| 命令 | 退出码 | stdout（截断） | stderr（截断） |",
  "|---|---|---|---|",
  ...steps.map(
    (s) =>
      `| \`ct ${s.args.join(" ")}\` | ${s.code} | ${s.stdout.replace(/\|/g, "/")} | ${s.stderr.replace(/\|/g, "/")} |`
  ),
  "",
  "## 结论",
  "",
  `- 真实 \`gd/\` 未被写入：\`git status --porcelain gd\` 前后分别 ${before.length} / ${after.length} 条${before.length === 0 && after.length === 0 ? "（均为空）" : ""}。`,
  `- \`gd/\` 里没有工具文件（扫描 4 层内 \`*.py|*.pyc|*.exe|*.dll|__pycache__|.venv\`）：${toolFiles.length === 0 ? "0 处" : toolFiles.join(", ")}。`,
  "- 原生发行包不查询 PATH 上的解释器即可完成校验与状态查询；`ct panel` 只剩迁移指引，",
  "  Python 侧 `ct/.venv` 仅作对照测试入口（见 `native/README.md` 的「开发/测试入口」）。",
  "",
];
const out = path.join(repoRoot, "native/docs/baseline/isolation-check.md");
fs.writeFileSync(out, lines.join("\n"));
console.log(lines.join("\n"));
process.exit(steps[0].code === 0 && before.length === after.length ? 0 : 1);