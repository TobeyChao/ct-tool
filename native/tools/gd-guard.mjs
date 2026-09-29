// gd 守卫：任何命令跑完，真实工作区 `gd/` 必须一个字节都没变。
//
// 用法：node native/tools/gd-guard.mjs -- <命令> [参数...]
//       node native/tools/gd-guard.mjs --status          # 只查当前状态
//
// 为什么需要：本仓库所有测试/基准/自检都规定只写临时目录（bench 里就断言了
// realWorkspaceUntouched）。历史上出现过一次「跑完一堆命令后 gd/ 被改了 41 个文件」，
// 事后逐个复跑才排掉嫌疑——所以把「跑完就查」变成工具，而不是靠人记得。
import { spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";

const repoRoot = path.resolve(import.meta.dirname, "../..");
const git = (args) => {
  const result = spawnSync("git", args, { cwd: repoRoot, encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(`git ${args.join(" ")} 失败：${result.error ?? result.stderr}`);
  }
  return result.stdout;
};

function state() {
  const dirty = git(["status", "--porcelain", "gd"]).trim();
  const lines = dirty ? dirty.split("\n") : [];
  return { lines, hash: dirty };
}

const before = state();
if (before.lines.length > 0) {
  console.error(`[gd-guard] 进入时 gd/ 已经是脏的（${before.lines.length} 项）：`);
  for (const l of before.lines.slice(0, 10)) console.error("  " + l);
  process.exit(2);
}

const argv = process.argv.slice(2);
if (argv[0] === "--status") {
  console.log("[gd-guard] gd/ 干净");
  process.exit(0);
}
if (argv[0] !== "--") {
  console.error("用法：node native/tools/gd-guard.mjs -- <命令> [参数...] | --status");
  process.exit(64);
}

const [cmd, ...rest] = argv.slice(1);
if (!cmd) {
  console.error("缺少命令");
  process.exit(64);
}
const run = spawnSync(cmd, rest, { cwd: repoRoot, stdio: "inherit" });
const code = run.status ?? 1;

const after = state();
if (after.lines.length > 0) {
  console.error(
    `\n[gd-guard] 失败：\`${cmd} ${rest.join(" ")}\` 之后 gd/ 出现 ${after.lines.length} 项改动：`,
  );
  for (const l of after.lines.slice(0, 15)) console.error("  " + l);
  console.error("  → 这条路径会写真实工作区，必须改成临时副本。");
  process.exit(1);
}
if (code === 0) {
  console.log(`[gd-guard] 通过：\`${cmd} ${rest.join(" ")}\` 未改动 gd/`);
} else {
  console.error(`[gd-guard] 命令退出码 ${code}；gd/ 未改动：\`${cmd} ${rest.join(" ")}\``);
}
process.exit(code);
