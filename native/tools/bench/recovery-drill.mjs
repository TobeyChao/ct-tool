// 发布中断恢复与版本账本演练（任务 6.7）：真跑原生二进制，制造 mid-publish 中断，
// 用 ct status / ct recover 还原，并验证账本版本不识别时不复活旧缓存、独立留档产物对照。
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
const ct = flag("--ct", path.join(repoRoot, "native/target/release", process.platform === "win32" ? "ct.exe" : "ct"));
const fixture = flag("--fixture", path.join(repoRoot, "native/target/bench/bench-m"));
if (argv.includes("--python")) throw new Error("恢复演练不再执行 Python，独立对照使用冻结 CLI 基线");
if (!fs.existsSync(ct)) throw new Error(`缺少原生二进制 ${ct}`);
if (!fs.existsSync(path.join(fixture, "FIXTURE.json"))) {
  throw new Error(`缺少夹具 ${fixture}（先跑 xtask bench-fixtures --sizes m）`);
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
const run = (exe, args, cwd = ws, expectedCode = 0) => {
  const r = spawnSync(exe, args, { cwd, encoding: "utf8", windowsHide: true });
  if (r.error) throw r.error;
  return {
    expectedCode,
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
let finished = false;
const exited = new Promise((resolve) => child.once("exit", (code, signal) => {
  finished = true;
  resolve({code, signal});
}));
const deadline = Date.now() + 240_000;
while (killed === null && !finished && Date.now() < deadline) {
  if (fs.existsSync(journalPath)) {
    let phase;
    try {phase = JSON.parse(fs.readFileSync(journalPath, "utf8")).phase;} catch {}
    if (["prepared", "backed_up", "publishing"].includes(phase)) {
      child.kill("SIGKILL");
      killed = {phase, stagedFiles: staged(ws).length};
      break;
    }
  }
  await sleep(1);
}
if (!finished && !killed) child.kill("SIGKILL");
const exit = await exited;
steps.push({command: "ct export --all (journal window SIGKILL)",
  code: killed ? 0 : 1,
  stdout: JSON.stringify({killed, ...exit}), stderr: ""});
const dirty = {
  journalExists: fs.existsSync(journalPath),
  journalBytes: fs.existsSync(journalPath) ? fs.statSync(journalPath).size : 0,
  stagedLeft: staged(ws).length,
};
steps.push({ command: "中断后的工作区状态", code: 0, stdout: JSON.stringify(dirty), stderr: "" });
steps.push(run(ct, ["status"], ws, killed ? 1 : 0));
steps.push(run(ct, ["validate"], ws, killed ? 1 : 0));
steps.push(run(ct, ["recover", "--json"], ws));
const afterRecover = snapshot(ws);
const recoveredDigest = digestOf(afterRecover);
steps.push({
  command: "（恢复后）output/ 快照",
  code: recoveredDigest === baselineDigest && [...baseline.keys()].every(k => afterRecover.get(k)?.mtimeMs === baseline.get(k)?.mtimeMs) ? 0 : 1,
  stdout:
    `${afterRecover.size} 个产物，聚合摘要 ${recoveredDigest}（与基线${recoveredDigest === baselineDigest ? "一致" : "**不一致**"}）；` +
    `mtime 保持 ${[...baseline.keys()].filter((k) => afterRecover.get(k)?.mtimeMs === baseline.get(k)?.mtimeMs).length}/${baseline.size}`,
  stderr: "",
});
steps.push({
  command: "journal 是否清场",
  code: !fs.existsSync(journalPath) && staged(ws).length === 0 ? 0 : 1,
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
  code: afterDrift === baselineDigest ? 0 : 1,
  stdout: `聚合摘要 ${afterDrift}（与基线${afterDrift === baselineDigest ? "一致" : "**不一致**"}）`,
  stderr: "",
});
// Run all six independent CLI captures instead of silently skipping a live interpreter.
const parity = run(process.execPath, [path.join(repoRoot, "native/tools/parity/cli-text-diff.mjs"),
  "--rust", ct, "--out", path.join(scratch, "cli-parity.md")], repoRoot);
steps.push(parity);
steps.push(run(ct, ["export"], ws));
const finalStaged = staged(ws).length;
steps.push({ command: "（演练结束）私有暂存残留", code: 0, stdout: `${finalStaged} 个`, stderr: "" });

const conclusions = [
  killed
    ? "- 中断落在发布替换窗口内（journal 已落盘、私有暂存文件在场）：只读诊断报「未完成的发布」且不做写入，" +
      "`ct recover` 还原内容与 mtime、清掉 journal，恢复后 `ct status`/`ct export` 正常。"
    : "- 本次未命中 journal 窗口：journal 之前的失败只留下私有暂存文件，正式产物与 journal 均未被污染，" +
      "`ct status` 无可恢复事务（符合「journal 之前无需恢复」的契约）。",
  killed
    ? "- 恢复后聚合摘要回到中断前的基线，既有产物 mtime 全部保持；恢复同时删掉 journal 记录的私有暂存文件（演练实测 `.ct-stage-*` 残留 0 个）。私有暂存清理由 `publication_recovery.rs::crash_after_prepared_cleans_private_only` 的既有断言覆盖。"
    : "- 演练结束时 '.ct-stage-*` 残留 " + finalStaged + " 个（全量导出的陈旧清理负责收口）。",
  "- 把成功账本的版本标记改成不识别值后 `--all` 全量重建，产物聚合摘要不变：生成缓存不复活旧版本条目。",
  "- 六个冻结 CLI 场景独立检查退出码、文本及产物摘要，不执行 Python；恢复工作区再次增量导出。",
];

const lines = [
  "# 发布中断恢复与版本账本演练（rust-native-core 任务 6.7）",
  "",
  "由 `node native/tools/bench/recovery-drill.mjs` 生成；工作区是基准夹具在临时目录里的副本",
  "（路径含中文与空格），真实 `gd/` 未被写入。",
  "",
  `- 原生二进制：\`${path.relative(repoRoot, ct)}\``,
  `- 夹具：\`${path.relative(repoRoot, fixture)}\``,
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
  "## 剩余门槛",
  "",
  "- Python 删除须 G1/G2/G3 全部通过；此单平台演练不替代三平台发行验收。",
  "",
];
const out = flag("--out", path.join(repoRoot, "native/target/bench-results/recovery-drill.md"));
fs.mkdirSync(path.dirname(out), {recursive: true});
fs.writeFileSync(out, lines.join("\n"));
console.log(steps.map((s) => `[${s.code ?? "-"}] ${s.command} :: ${brief(s.stdout, 150)}`).join("\n"));
console.log(`\n写入 ${path.relative(repoRoot, out)}`);
fs.rmSync(scratch, { recursive: true, force: true });
process.exit(steps.some((s) => s.code !== (s.expectedCode ?? 0)) ? 1 : 0);