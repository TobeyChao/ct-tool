/* core/task: persistent task state for long-running work (survives module switch). */
import { api } from "./api.js";

const listeners = new Set();
let tasks = [];
let timer = null;

export function onTasks(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  for (const fn of listeners) fn(tasks);
}

export async function refresh() {
  try {
    tasks = await api("/api/tasks");
    notify();
  } catch (e) { /* keep last known tasks */ }
}

export function startPolling(intervalMs = 1500) {
  if (timer) return;
  refresh();
  timer = window.setInterval(refresh, intervalMs);
}

export function stopPolling() {
  if (timer) { window.clearInterval(timer); timer = null; }
}
