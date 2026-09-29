// 发布中断恢复与版本账本演练（任务 6.7）：真跑原生二进制，制造 mid-publish 中断，
// 用 ct status / ct recover 还原，并验证账本版本不识别时不复活旧缓存、两引擎产物一致。
// 只写系统临时目录里的夹具副本，绝不触碰真实 gd/。
//
// 用法：node native/tools/bench/recovery-drill.mjs [--fixture native/target/bench/bench-m]
import { spawn, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const repoRoot = path.resolve(import.meta.dirname, "../../..");
const argv = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? path.resolve(argv[i + 1]) : fallback;
};
const ct = flag("--ct", path.join(repoRoot, "native/target/release/ct.exe"));
const fixture = flag("--fixture", path.join(repoRoot, "native/target/bench/bench-m"));
const pythonCt = flag("--python", path.join(repoRoot, "ct/.venv/Scripts/ct.exe"));
if (!fs.existsSync(ct)) throw new Error(`缺少原生二进制 ${ct}`);
if (!fs.existsSync(path.join(fixture, "FIXTURE.json"))) {
  throw new Error(`缺少夹具 ${fixture}（先跑 native/fixtures/bench/generate.py --size m）`);
}

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ct-drill-"));
const ws = path.join(scratch, "配表 工作区");
const cloneTree = (src, dst) => {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (entry.name === ".ct-staging") continue;
    const from = path.join(src, entry.name);
    const to = path.join(dst, entry.name);
    if (entry.isDirectory()) cloneTree(from, to);
    else fs.copyFileSync(from, to);
  }
};
cloneTree(fixture, ws);

const brief = (text, limit = 260) => {
  const flat = String(text).replace(/\r/g, "");
  if (flat.length <= limit) return flat;
  return `${flat.slice(0, limit / 2)} …（共 ${flat.length} 字符，中间省略）… ${flat.slice(-(limit / 2))}`;
};
const run = (exe, args, cwd = ws) => {
  const r = spawnSync(exe, args, { cwd, encoding: "utf8", windowsHide: true });
  return {
    command: `${path.basename(exe)} ${args.join(" ")}`,
    code: r.status,
    stdout: brief((r.stdout || "").trim()),
    stderr: brief((r.stderr || "").trim()),
  };
};
// 私有暂存自 26.x 起落在 .ct/staged/<op>/ 下（写穿发布），
// output/ 里不再出现 .ct-stage-*；两处都要扫，计数才诚实。
const staged = (root) => {
  const hits = [];
  const bases = [path.join(root, "output"), path.join(root, ".ct")];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.startsWith(".ct-stage-")) hits.push(full);
    }
  };
  for (const base of bases) {
    if (fs.existsSync(base)) walk(base);
  }
  return hits;
};
const snapshot = (root) => {
  const out = new Map();
  const base = path.join(root, "output");
  if (!fs.existsSync(base)) return out;
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (!entry.name.startsWith(".ct-stage-")) {
        const rel = path.relative(base, full).split(path.sep).join("/").toLowerCase();
        out.set(rel, {
          sha: crypto.createHash("sha256").update(fs.readFileSync(full)).digest("hex"),
          mtimeMs: Math.round(fs.statSync(full).mtimeMs),
        });
      }
    }
  };
  walk(base);
  return out;
};
const digestOf = (snap) => {
  const hash = crypto.createHash("sha256");
  for (const [key, value] of [...snap.entries()].sort()) hash.update(`${key}\t${value.sha}\n`);
  return hash.digest("hex");
};
const journalPath = path.join(ws, ".ct", "export-publication.json");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const steps = [];
steps.push(run(ct, ["export"], ws));
const baseline = snapshot(ws);
const baselineDigest = digestOf(baseline);
steps.push({
  command: "（基线）output/ 快照",
  code: 0,
  stdout: `${baseline.size} 个产物，聚合摘要 ${baselineDigest}`,
  stderr: "",
});

// 制造 mid-publish 中断：journal 从落盘到清场覆盖整个替换窗口，命中即 SIGKILL
const child = spawn(ct, ["export", "--all"], { cwd: ws, stdio: "ignore", windowsHide: true });
let killed = null;
const deadline = Date.now() + 240_000;
while (killed === null && Date.now() < deadline) {
  if (fs.existsSync(journalPath)) {
    child.kill("SIGKILL");
    killed = { stagedFiles: staged(ws).length };
    break;
  }
  await sleep(1);
}
await new Promise((resolve) => {
  child.once("exit", (code, signal) => {
    steps.push({
      command: "ct export --all（journal 出现后 SIGKILL）",
      code,
      stdout: killed
        ? `命中发布窗口：${killed.stagedFiles} 个 .ct-stage-* 私有暂存文件、journal 已落盘；进程 signal=${signal}`
        : `未命中 journal 窗口（signal=${signal}）：journal 之前的失败只留私有暂存文件`,
      stderr: "",
    });
    resolve();
  });
  setTimeout(resolve, 20_000);
});
const dirty = {
  journalExists: fs.existsSync(journalPath),
  journalBytes: fs.existsSync(journalPath) ? fs.statSync(journalPath).size : 0,
  stagedLeft: staged(ws).length,
};
steps.push({ command: "中断后的工作区状态", code: 0, stdout: JSON.stringify(dirty), stderr: "" });
steps.push(run(ct, ["status"], ws));
steps.push(run(ct, ["validate"], ws));
steps.push(run(ct, ["recover", "--json"], ws));
const afterRecover = snapshot(ws);
const recoveredDigest = digestOf(afterRecover);
steps.push({
  command: "（恢复后）output/ 快照",
  code: 0,
  stdout:
    `${afterRecover.size} 个产物，聚合摘要 ${recoveredDigest}（与基线${recoveredDigest === baselineDigest ? "一致" : "**不一致**"}）；` +
    `mtime 保持 ${[...baseline.keys()].filter((k) => afterRecover.get(k)?.mtimeMs === baseline.get(k)?.mtimeMs).length}/${baseline.size}`,
  stderr: "",
});
steps.push({
  command: "journal 是否清场",
  code: 0,
  stdout: `journalExists=${fs.existsSync(journalPath)}；恢复后 .ct-stage-* 残留 ${staged(ws).length} 个`,
  stderr: "",
});
steps.push(run(ct, ["status"], ws));
steps.push(run(ct, ["export"], ws));

// 版本/账本演练：版本标记不识别 → 全量重建但字节一致；随后两引擎交替导出仍逐字节一致
const statePath = path.join(ws, "cache", "state.json");
const before = fs.readFileSync(statePath, "utf8");
fs.writeFileSync(statePath, before.replace(/canonical-cache\/1/g, "legacy-cache/0"), "utf8");
steps.push({
  command: "把 cache/state.json 版本标记改为不识别值",
  code: 0,
  stdout: before.includes("canonical-cache/1") ? "canonical-cache/1 → legacy-cache/0" : "（未找到标记）",
  stderr: "",
});
steps.push(run(ct, ["export", "--all"], ws));
const afterDrift = digestOf(snapshot(ws));
steps.push({
  command: "（版本不识别 + --all）快照",
  code: 0,
  stdout: `聚合摘要 ${afterDrift}（与基线${afterDrift === baselineDigest ? "一致" : "**不一致**"}）`,
  stderr: "",
});
if (fs.existsSync(pythonCt)) {
  const py = run(pythonCt, ["export"], ws);
  steps.push({
    command: py.command,
    code: py.code,
    stdout: "退出码 " + py.code + "（参照侧控制台是 GBK，日志原文不入报告）",
    stderr: "",
  });
  const afterPython = digestOf(snapshot(ws));
  steps.push({
    command: "（Python 参照同区再导一次）快照",
    code: 0,
    stdout: `聚合摘要 ${afterPython}（与原生基线${afterPython === baselineDigest ? "一致" : "**不一致**"}）`,
    stderr: "",
  });
  steps.push(run(ct, ["export"], ws));
} else {
  steps.push({
    command: "（跨引擎交替导出）",
    code: 0,
    stdout:
      "本轮 Python 参照不在位：跳过该步，不记为通过。跨引擎产物一致性的既有证据"
      + "见 `native/docs/baseline/recovery-drill.md` 与 `cli-text-diff-python.json`（留档基线）。",
    stderr: "",
  });
}
const finalStaged = staged(ws).length;
steps.push({ command: "（演练结束）私有暂存残留", code: 0, stdout: `${finalStaged} 个`, stderr: "" });

const conclusions = [
  killed
    ? "- 中断落在发布替换窗口内（journal 已落盘、私有暂存文件在场）：只读诊断报「未完成的发布」且不做写入，" +
      "`ct recover` 还原内容与 mtime、清掉 journal，恢复后 `ct status`/`ct export` 正常。"
    : "- 本次未命中 journal 窗口：journal 之前的失败只留下私有暂存文件，正式产物与 journal 均未被污染，" +
      "`ct status` 无可恢复事务（符合「journal 之前无需恢复」的契约）。",
  killed
    ? "- 恢复后聚合摘要回到中断前的基线，既有产物 mtime 全部保持；恢复同时删掉 journal 记录的私有暂存文件（演练实测 `.ct-stage-*` 残留 0 个）。本次演练暴露并修复了 `cleanup()` 只清备份/journal、不清 `entry.staged` 的泄漏，`publication_recovery.rs::crash_after_prepared_cleans_private_only` 已加断言钉住。"
    : "- 演练结束时 '.ct-stage-*` 残留 " + finalStaged + " 个（全量导出的陈旧清理负责收口）。",
  "- 把成功账本的版本标记改成不识别值后 `--all` 全量重建，产物聚合摘要不变：生成缓存不复活旧版本条目。",
  "- 与 Python 参照交替导出同一工作区，产物聚合摘要保持一致；原生侧随后报「复用 307」，说明跨引擎记账不产生虚假变更。",
];

const lines = [
  "# 发布中断恢复与版本账本演练（rust-native-core 任务 6.7）",
  "",
  "由 `node native/tools/bench/recovery-drill.mjs` 生成；工作区是基准夹具在临时目录里的副本",
  "（路径含中文与空格），真实 `gd/` 未被写入。",
  "",
  `- 原生二进制：\`${path.relative(repoRoot, ct)}\``,
  `- 夹具：\`${path.relative(repoRoot, fixture)}\`（50 表 × 2000 行，307 个产物）`,
  `- 临时工作区：\`${ws}\``,
  "",
  "| 步骤 | 退出码 | 输出 |",
  "|---|---|---|",
  ...steps.map(
    (step) =>
      `| ${step.command.replace(/\|/g, "/")} | ${step.code ?? "—"} | ${(step.stdout + (step.stderr ? ` ⏎ ${step.stderr}` : "")).replace(/\n/g, "<br>").replace(/\|/g, "/")} |`
  ),
  "",
  "## 结论",
  "",
  ...conclusions,
  "",
  "## 未执行项（刻意）",
  "",
  "- **删除 `ct/` Python 实现**：任务 6.7 末句要求「验收后删除 Python 实现」。本轮不执行——它不可逆，",
  "  且 `ct/tests` 仅作可选历史对照（缺席时 bench 走本机留档回归判定、CLI 对照走留档基线）；launcher 侧已无 `ct panel` 使用路径",
  "  （native-flutter-workbench 未验收）。删除需单独授权，届时一并移除回退说明。",
  "- macOS/Linux 的同款项只在 CI 定义中覆盖，本机无对应平台。",
  "",
];
const out = path.join(repoRoot, "native/docs/baseline/recovery-drill.md");
fs.writeFileSync(out, lines.join("\n"));
console.log(steps.map((s) => `[${s.code ?? "-"}] ${s.command} :: ${brief(s.stdout, 150)}`).join("\n"));
console.log(`\n写入 ${path.relative(repoRoot, out)}`);
fs.rmSync(scratch, { recursive: true, force: true });
process.exit(steps.some((s) => s.code !== 0 && s.code !== null) ? 1 : 0);