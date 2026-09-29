/* core/labels: 状态码 → 展示文案。
   后端契约只存状态码（见 ct/web/history.py），本地化统一在这一层。 */

export const RESULT_LABEL = {
  success: "成功",
};

export function resultLabel(code) {
  return RESULT_LABEL[code] ?? String(code ?? "");
}
