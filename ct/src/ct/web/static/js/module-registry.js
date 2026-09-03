/* module-registry: boots the AppShell then mounts business module pages.
   Kept separate from app-shell so the shell (core) has no business imports;
   only this registry depends on business modules. */
import { bootstrap, getPageState } from "./app-shell.js";
import { mount as mountSchema } from "./modules/schema.js";
import { mount as mountExport } from "./modules/export.js";
import { mount as mountI18n } from "./modules/i18n.js";
import { mount as mountLogs } from "./modules/logs.js";
import { mount as mountHistory } from "./modules/history.js";

const MOUNTERS = {
  schema: mountSchema,
  export: mountExport,
  i18n: mountI18n,
  logs: mountLogs,
  history: mountHistory,
};

const started = bootstrap().then(({ activateModule, getPageState: gps }) => {
  window.__ct = { activateModule, getPageState: gps };
});

async function mountActive() {
  await started;
  const moduleId = window.__ct.getPageState ? currentModule() : "export";
  const container = document.getElementById("page-" + moduleId);
  const mounter = MOUNTERS[moduleId];
  if (mounter && container && !container.dataset.mounted) {
    container.dataset.mounted = "1";
    await mounter(container);
  }
}

function currentModule() {
  const match = location.hash.match(/#\/([a-z]+)/);
  return match ? match[1] : "export";
}

function onModuleActivated(event) {
  const moduleId = event.detail;
  const container = document.getElementById("page-" + moduleId);
  const mounter = MOUNTERS[moduleId];
  if (mounter && container && !container.dataset.mounted) {
    container.dataset.mounted = "1";
    mounter(container).catch((e) => console.error(e));
  }
}

window.addEventListener("hashchange", mountActive);
window.addEventListener("ct:module", onModuleActivated);
mountActive();
