# responsive-app-shell.html 审查报告

- **审查对象**:`ct/docs/design/responsive-app-shell.html`(983 行,静态高保真原型,内联 CSS/JS)
- **日期**:2026-09-06
- **方法**:全文静态审查 + 本地 HTTP 服务托管后浏览器实测(桌面 1280×720 / 窄屏 375×720 两档),覆盖 i18n 过滤/切表/列显隐、草稿增删撤销、审查计划、类型选择器、快速打开、删除资源、断点切换等交互路径;所有「实测」标记的问题均在浏览器中复现并取到实际状态值。
- **处理状态**:2026-09-06 已按本报告全部修复并通过 29 项 Playwright 回归;修复记录见文末「六、修复与验证」。

---

## TL;DR

壳层、响应式断点、可访问性骨架(inert / 焦点管理 / Esc 逐层退栈)做得扎实;问题集中在**弹窗流程的状态一致性**上。共确认:

| 类别 | 数量 |
|------|------|
| 实测复现的 Bug | 8 |
| 代码级问题(静态发现) | 10 |
| 小 nit / 可优化项 | 7 |

最严重的三个:**添加字段草稿命令 `type` 键重复导致审查计划恒空**、**切表后过滤/列显隐不重放**、**「查看影响」恒为空计划**。

---

## 一、实测复现的 Bug(按严重度)

### B1. [P1] pushDraft 对象 `type` 键重复,添加字段的命令类型被覆盖

- **位置**:L835(`openAddField` 的提交回调)
- **代码**:
  ```js
  pushDraft({type:'add_field',owner:currentResource(),field:v,type:typePickerSel,role});
  ```
  对象字面量里 `type` 出现两次,后值静默覆盖前值,`cmd.type` 实际是 `'int32'`/`'string'` 等类型表达式,而非 `'add_field'`。
- **后果**:`impactRows()` 中 `c.type==='add_field'` 永远匹配不到,「审查并应用」对添加字段恒显示 0 条影响。
- **实测**:推入 Foo、Bar 两个字段后草稿栏计「2 条未应用变更」,审查计划中 impacts = 0、风险徽标「安全」;`draft.cmds` 实际内容为 `{type:'int32',field:'Foo'}`。
- **修复**:第二个键改名为 `fieldType`(或 `expr`),`impactRows` 同步取用。

### B2. [P1] 切表后不重放视图状态:状态过滤与列显隐双双失效

- **位置**:L874–L875(`renderRows` / `switchTable`)
- **现象**:`switchTable → renderRows` 重建 tbody,但既不重放 active 的状态过滤 pill,也不重放 colvis 的列显隐。
- **实测**:
  - 选「待审」过滤后只剩 1003 一行;切到 Quest 表后 pill 仍高亮「待审」,但 2001(missing)、2002(translated)两行全部显示;
  - 取消勾选「译文」列(单元格 `display:none` 生效)后切回 Item,列重新出现,checkbox 仍处于未勾选状态。
- **修复**:在 `renderRows` 末尾统一调用一个 `applyViewState()`,重放当前 active pill 的行过滤 + colvis 各列的 display 状态。

### B3. [P2] 添加字段弹窗重开后显示 int32,实际提交的却是上次的类型

- **位置**:L824(`let typePickerSel='int32'`)、L826(模板硬编码 `<span id="af-type-txt">int32</span>`)
- **现象**:`typePickerSel` 是模块级变量且不随弹窗重置,弹窗模板却总是显示 `int32`。
- **实测**:选过 `string` 后取消、重开弹窗——触发器显示 `int32`,内部 `typePickerSel === 'string'`;直接填名添加,草稿里存入 `type:'string'`。用户所见与实际提交不一致。
- **修复**:`openAddField` 开头重置 `typePickerSel='int32'`,或由变量渲染触发器文本。

### B4. [P2] 删除资源弹窗的「查看影响」恒为空计划

- **位置**:L810–L812(`openDeleteResource` 的 `#dl-seeplan`)
- **现象**:点击「查看影响」直接 `openChangePlan()`,但此时删除命令还没 `pushDraft`,计划读到的草稿为空。
- **实测**:对被引用的 Item 打开删除弹窗 → 查看影响:0 条影响、风险「安全」、放弃草稿可用——与用户预期(预览这次删除的影响面)完全不符。
- **修复**:让 `openChangePlan` 接受一个假想命令参数,参与 `impactRows()` / `planBlocked()` 计算。

### B5. [P2] 非 Schema 页 ⌘P 快速打开无任何可见反馈

- **位置**:L775–L782(`openResource`)、L906(快速打开回车)
- **现象**:`openResource` 只改 Schema 页的 `rtitle`/树高亮,不切页。
- **实测**:在导出页 ⌘P → 输入 Quest → 回车:仍停留在 `page-export`,Schema 页在底下被静默改成 Quest(`.rtitle h1` 已变),界面零反馈。
- **修复**:`openResource` 里判断当前 active 页,非 `page-schema` 时先切页。

### B6. [P2] src-more 展开尾标不随 resize 重估,两个方向都出错

- **位置**:L731–L743(`initSrcMore` 的 `moreReady` 一次性标记)、L964–L974(resize 处理器不调 `initSrcMore`)
- **现象**:`dataset.moreReady` 置位后永不重估;resize 只重算光晕和 sticky 偏移。
- **实测**:
  - 375 宽全新加载 → 1003 行正确生成 1 个「展开」按钮;
  - 放大到 1280(文本已不截断)→ 按钮残留在已不截断的行上(expandables=1);
  - 反向 1280→375 → 该有的按钮不出现(srcMoreBtns=0)。
- **影响**:对一份「响应式」原型,拖窗口宽度正是核心演示路径。
- **修复**:resize(去抖)时清 `moreReady` 并对 active 页重跑 `initSrcMore`;或改用 ResizeObserver 按元素重估。

### B7. [P3] 草稿栏计数用 `cmds.length`,撤销后与审查计划自相矛盾

- **位置**:L786–L793(`updateDraftBar`,文案在 L790)
- **现象**:文案取 `draft.cmds.length` 而非 `draft.cursor`。
- **实测**:推 2 条撤销 1 次后,栏内仍写「2 条未应用变更」;而审查计划的 `impactRows` 用 `slice(0,cursor)` 只算 1 条——同屏两处数字对不上。
- **修复**:文案改用 `draft.cursor`(待应用条数)。

### B8. [P3] 类型选择器 vector\<T\> 映射是死分支

- **位置**:L853(`openTypePicker` 列表点击)
- **代码**:
  ```js
  cb(b.dataset.v==='vector&lt;T&gt;'?'vector<int32>':b.dataset.v)
  ```
  `data-v="vector&lt;T&gt;"` 经 HTML 解析后 `dataset.v` 是 `'vector<T>'`,与带实体的字面量比较永假——映射到 `vector<int32>` 的意图从未生效。
- **实测**:点「容器 vector\<T\>」行后 `typePickerSel === 'vector<T>'`(非具体类型)会被存进草稿。
- **修复**:直接比较 `'vector<T>'`。

---

## 二、代码级问题(静态审查发现)

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| C1 | L690 `openMask` | 焦点陷阱选择器不过滤 disabled 按钮:D1 资源被引用时「删除」disabled,Shift+Tab 对它 `focus()` 失败卡住,Tab 可能逃出弹窗 | 选择器加 `:not([disabled])` |
| C2 | L690 `openMask` | 嵌套弹窗都给标题设同一 id `dlg-title`,顶层弹窗 `aria-labelledby` 解析到下层弹窗标题 | 用计数器生成唯一 id |
| C3 | L191–L193 | 折叠分组(`gbody` 0fr + overflow hidden)只是视觉藏起,0 尺寸的行按钮仍在 Tab 序里 | 折叠态补 `visibility:hidden`(带过渡)或 inert |
| C4 | L895 vs L910/L980 | 帮助弹窗宣传 ⌘Z/⇧⌘Z 撤销,但全局键盘只接了 ⌘P 和 Escape | 补快捷键或删文案 |
| C5 | L772 | `REVERSE` 只登记了 Item:删 ItemType(被 Item.ItemTypeId 引用)不会被阻止,与「不提供级联删除」叙事矛盾 | mock 数据补 `ItemType:['Item.ItemTypeId']` |
| C6 | L810 | 删除弹窗硬编码「将移除:8 个字段 · 12 行数据」,删 Monster(9 字段)也显示 8 | 从 META/数据拼装 |
| C7 | L826/L831–837 | `#af-pk`(主键)、`#af-req`(必填)、`#af-sep`(分隔符)控件从未被读取,不进 pushDraft | 读值入草稿或删掉控件 |
| C8 | L745/L937 | 保存译文不更新状态徽标:missing 填完保存仍显示 missing,「缺失」过滤下也不消失 | `commitInlineEdit` 同步改 `rows[i][4]` 并重渲染徽标 |
| C9 | L771 | `META` 缺 `ItemType.Id`:点该类型链接后标题变「ItemType.Id · 未知」、eyebrow 变 Table,树高亮仍停在 Item(实测确认) | META 补 ref 条目;`openResource` 对 `Table.Field` 形式高亮目标表 |
| C10 | L745/L753 | 译文经 innerHTML 直拼,含 `</textarea>` 或 HTML 会破坏结构/注入 | 原型风险低;搬进正式 Vue 面板前必须改文本插值 |

---

## 三、小 nit / 可优化项

1. **draftbar 位置**:在 `#page-schema` 内部,切到其他页后「N 条未应用变更」不可见——可提到壳层,或侧栏挂角标。
2. **状态文案不一致**:徽标显示英文 key(translated/stale/missing),过滤 pill 用中文(待审/缺失);全屏编辑弹窗 dhead 语言硬编码 `en`,切到 ja 也不变。
3. **弹窗关闭动画**:只有遮罩淡出,dialog 没有 scale 回退(打开有),观感略突兀。
4. **HTML 合法性**:`ev-sum` 里 dt/dd 没包 `<dl>`(L651–655),渲染无碍但不合法。
5. **a11y 细节**:`group-toggle` 缺 `aria-expanded`;`.rrow` 选中态无 `aria-current`;`.btn:disabled`(撤销/重做等)没有视觉样式,看起来仍可点。
6. **导出 mock 一致性**:进度跑完后 ohero「2 张表待导出」徽标与待处理数字不更新;翻译进度弹窗的「按表」pill 切了没内容;`showApplied` 的「已应用:Item · Quest」硬编码。
7. **焦点初始化不一致**:无 `data-focus` 的弹窗(翻译进度)初始焦点落在右上 ✕,其他弹窗都校正到表单/取消按钮。

---

## 四、值得保留的亮点(修复时别动)

- `syncInert` 对侧栏抽屉/内容面板的焦点序管理(关起即 inert,桌面常驻不禁用),实测侧栏收起时点击被正确拒绝;
- Esc 分层退栈(dialog > 侧栏抽屉 > 面板抽屉 > 列菜单)、嵌套弹窗关闭后恢复下层 inert;
- resize 跨断点「只收不展」+ rAF 节流,避免残留遮罩/面板叠开;
- `prepareGlow` 包裹滚动容器的同时,用 `#page-i18n .scroll-holder` 配套规则(L125)保住了 flex 高度链——i18n 宽表在两档视口下都能正确充满剩余高度;
- tab 键盘左右切换、`role="tablist"` 语义、可滚动区域 `tabindex=0` + region 命名。

---

## 五、实测记录(附录)

- 测试环境:IAB Chromium,`python3 -m http.server` 托管 design 目录(file:// 不可直接导航)。
- 覆盖路径:
  - i18n:状态过滤(全部/待审)→ 切表(Item↔Quest);colvis 取消「译文」→ 切表;375↔1280 视口切换下的 src-more;
  - Schema:添加字段 ×3(Foo/Bar/Baz/Qux)→ 撤销 → 审查计划;类型选择器选 string / vector\<T\>;取消后重开弹窗;删除资源(Item,被引用)→ 查看影响;
  - 全局:导出页 ⌘P → Quest → 回车;桌面/窄屏截图(布局正常,未发现裁切;窄屏「列」按钮右缘 353 < 375,未裁)。
- 原始现场:草稿命令实际值为 `{type:'int32'|'string',field:…}`(应为 `type:'add_field'`),审查计划 impacts=0,快速打开后 activePage 仍为 page-export。

---

## 六、修复与验证(2026-09-06)

原型 `responsive-app-shell.html` 已按本报告全部修复,并通过 29 项 Playwright 回归(Chromium,http 托管,1280/320–1600 两档视口),无 console 错误。逐项对应:

| # | 修复内容 |
|---|---------|
| B1 | 草稿命令重复 `type` 键改为 `type:'add_field'` + `fieldType`;审查计划能显示添加字段影响 |
| B2 | 新增 `applyViewState()`(状态过滤 + 列显隐),`renderRows` 末尾重放;切表后过滤/列显隐保持 |
| B3 | `openAddField` 开头重置 `typePickerSel='int32'`,显示与提交一致 |
| B4 | `openChangePlan(extraCmd)` 支持预览:删除弹窗「查看影响」显示该删除的影响/风险/未加入草稿提示,预览态禁用应用 |
| B5 | `openResource` 非 Schema 页自动切页 + rAF 布局刷新 |
| B6 | `initSrcMore` 改为全量重算(可增可删),resize 处理器重跑;展开/收起随宽度双向收敛 |
| B7 | 草稿计数改用 `cursor`(含显隐判断与「放弃」计数) |
| B8 | `vector<T>` 比较改为解析后值,正确映射 `vector<int32>` |
| C1 | 焦点陷阱与 `firstFocusable` 过滤 `:not([disabled])` |
| C2 | 弹窗标题 id 用递增序列 `dlg-title-N`,嵌套不再重名 |
| C3 | 折叠分组 `gbody` 置 `inert` + `group-toggle` 补 `aria-expanded` |
| C4 | 新增 ⌘Z / ⇧⌘Z 撤销/重做快捷键(帮助文档不再虚标) |
| C5 | `REVERSE` 修正方向并补全(ItemType/ItemDropRange 均被保护);blocker 文案改为动态引用列表 |
| C6 | 删除弹窗字段/行数改为按资源动态取值(Monster 显示 9) |
| C7 | 添加字段读取 `#af-pk/#af-req/#af-sep` 进草稿命令(并升级为 Bug 处理) |
| C8 | 保存译文同步更新状态/徽标(中文标签)+ 重放过滤;`tr.dataset.status` 同步 |
| C9 | `openResource` 支持 `Table.Field` 形式,跳转目标表、标题/子标题正确 |
| C10 | 新增 `esc()`,译文/原文所有插值转义(含 textarea 内容) |
| nit | ① draftbar 移到壳层(各页可见,`.main` 改 flex 列) ② 徽标中文化、全屏编辑语言动态取激活 pill ③ 关闭动画补 dialog scale 回退 ④ ev-sum 包 `<dl>` ⑤ disabled 视觉态、rrow `aria-current` ⑥ re-export 完成后徽标/数字联动、「按表/按语言」双视图、已应用名单动态 ⑦ 进度弹窗初始焦点落到 pill |
| 补充 | 选表弹窗仅「全部」pill 初始 active;Escape 跳过 `.closing` 掩码(修复关不掉上层弹窗的隐患) |

另:`#draft-review` 的 `addEventListener` 改为 `()=>openChangePlan()`,避免事件对象被当作预览参数。nit ⑦ 经复核为误报——进度弹窗初始焦点本就落在首个 pill 而非 ✕。

**后续处置**:添加字段弹窗按 change `fix-field-role-constraint-rules` 重新设计——「必填」与「主键」checkbox 一并移除(主键字段名固定 `Id`、不通过新增字段指派),工具强制约束(ref 外键有效性、代号 `Code` 索引非空/唯一)以只读提示呈现;代号字段 `Code` 为可选固定名字段(string / 非 i18n / 非 server_only / 一表至多一个);C7 当时将 `req` 读入草稿,现改为移除 `req` 与 `pk`——与 C7 建议的「读值入草稿或删掉控件」两条路线中的"删掉控件"一致,不构成矛盾。

---

## 七、独立复核(2026-09-07)

对修复后的版本做了独立回归(不依赖第六节的验证路径):

- **配套 e2e 脚本**:`responsive-app-shell_e2e.py` 当前含 48 个断言(含 2.1–2.7 角色×约束新规则),实测 **48/48 通过、无 console 错误**。
- **pytest**:`ct/tests/schema/test_role_boundaries.py` 11/11 通过(separator/excel_columns/主键 server_only 新校验)。
- **浏览器抽查**(IAB Chromium,1280/375 两档):B1 命令结构 `{'type':'add_field',field:'Foo',fieldType:'int32',role:''}` 正确;B7 撤销 1 次后栏显「1 条未应用变更」;B5 导出页 ⌘P 回车正确落 Schema 页;⌘⇧Z 键盘重做可用;布局冒烟正常——资源面板默认收起后字段表满宽、操作列(↑↓×)进入视口、禁用箭头呈灰态,较修复前观感更好。

### 新发现(轻微,1 条,已修复)

- **[P3] 撤销归零后「重做」按钮不可达**:`updateDraftBar` 以 `draft.cursor` 为显隐条件,全部撤销后草稿栏整体隐藏(cmds 仍在重做分支),栏内重做按钮随之不可点。实测 ⌘⇧Z 键盘重做仍可用(光标 0→1、栏复现),故仅为 UI 可达性缺口。
  **修复(2026-09-07)**:`updateDraftBar` 显隐条件改为「无待应用且无重做分支才隐藏」;归零态文案「已全部撤销 · 可重做」,撤销/审查禁用、重做可用,persistFail 提示在两种文案下均保留。e2e 补 `reg-b7b-bar-kept`/`reg-b7b-redo-works` 两条用例,回归 50/50 通过、无 console 错误。
