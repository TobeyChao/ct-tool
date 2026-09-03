# 大规模 Schema 资源发现模式调研

> 调研时间：2026-09-01
> 调研范围：VS Code 与 JupyterLab 的官方文档、官方设计规范和官方源码
> 目标：判断当 Table、Record、Enum 等资源持续增加时，Schema Editor  应采用怎样的浏览、过滤和快速打开模式。

## 结论

“左侧资源区负责浏览与局部过滤，独立 Quick Open 负责跨资源快速跳转”是成熟且有官方实现支撑的双层导航模式。

对  最合适的基线是：

1. 左侧资源区保留 `Tables / Records / Enums` 分组，用于理解结构、查看邻近资源和局部过滤。
2. 增加 `Cmd/Ctrl + P` Quick Open，用于不展开资源栏也能快速打开任意资源。
3. Quick Open 空查询时展示最近使用；开始输入后，将最近资源和全量资源统一交给模糊匹配评分。
4. 使用成熟的 fuzzy scorer，不能把排序简化成手写的“精确匹配 → 前缀匹配 → 包含匹配”三个桶。
5. 资源类型通过稳定图标、短标签或 description 表达；只在存在明确结果组时使用分隔标题。
6. 字段搜索不应永久排除，但应与资源搜索分模式：默认搜索 Table、Record、Enum；通过 `@` 或独立快捷键搜索当前资源字段。
7. 正式实现应选择支持虚拟化的列表或树组件，并通过实际性能测试确定优化策略。

其中，“资源超过 200 条才启用虚拟化”没有来自 VS Code、JupyterLab 或其他本次官方来源的依据。`200` 是任意阈值，不应进入设计规范或实现条件。

## 官方证据

### 1. VS Code：左侧树局部过滤

VS Code Explorer 在树获得焦点后提供 Find Control，并明确支持：

- 高亮模式与过滤模式切换；
- exact 与 fuzzy 匹配切换；
- 按 `Down` 进入第一个匹配项并继续键盘导航；
- 该能力适用于 VS Code 的所有 Tree View，而非 Explorer 特例。

这证明左栏内的局部过滤属于树浏览器的标准组成部分，而不是额外搜索页面。

官方来源：

- [VS Code User Interface：Advanced tree navigation](https://code.visualstudio.com/docs/editing/userinterface#_advanced-tree-navigation)
- [VS Code Views UX Guidelines](https://code.visualstudio.com/api/ux-guidelines/views)

### 2. VS Code：Quick Open 作为独立全局入口

VS Code 使用 `Cmd/Ctrl + P` 快速按名称搜索并打开文件。它与 Explorer 共存：Explorer 负责浏览，Quick Open 负责全局跳转。

官方文档还说明：

- 重复按 Quick Open 快捷键可以在最近打开的文件之间循环；
- Quick Open 可以连续打开多个结果；
- Quick Access 同一交互容器可承载文件、命令、当前文件符号等不同模式。

官方来源：

- [VS Code User Interface：Explorer 与 Quick Open](https://code.visualstudio.com/docs/editing/userinterface#_explorer-view)
- [VS Code Tips and Tricks：Quick Open](https://code.visualstudio.com/docs/editing/tips-and-tricks#_quick-open)
- [VS Code User Interface：Command Palette](https://code.visualstudio.com/docs/editing/userinterface#_command-palette)

### 3. VS Code：最近使用与全量搜索的组合

VS Code `AnythingQuickAccessProvider` 的官方源码显示：

- 无查询时首先取得 editor history；
- 使用 `recently opened` separator 标记最近打开分区；
- 有查询时历史记录也会进行匹配；
- 文件与工作区符号作为后续结果异步取得；
- 已出现在历史中的资源会从后续文件结果中排除，避免重复。

因此  的“空查询显示最近使用”有明确依据，但不应把最近资源在所有查询下永久固定在结果顶部。输入查询后，更合理的方式是让历史与全量结果参与统一评分，必要时仅施加轻量历史权重。

官方来源：

- [VS Code `anythingQuickAccess.ts`](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/contrib/search/browser/anythingQuickAccess.ts)

### 4. VS Code：真正的模糊匹配与排序

VS Code Quick Access 使用 `scoreItemFuzzy` 和 `compareItemsByFuzzyScore`，而不是简单的字符串包含判断。官方源码中的关键行为包括：

- 支持非连续字符匹配；
- 区分 label、description 和 path；
- label 前缀匹配获得显著加权；
- 在相同前缀下，更短、更精确的 label 获得额外加权；
- 返回匹配位置，用于高亮命中的字符；
- 使用 scorer cache，避免重复计算。

因此  不应自行维护“exact / prefix / contains”三段结果。该方法难以处理缩写、驼峰、多词查询、路径描述和同名资源，也容易出现排序不稳定。

官方来源：

- [VS Code `fuzzyScorer.ts`](https://github.com/microsoft/vscode/blob/main/src/vs/base/common/fuzzyScorer.ts)
- [VS Code `anythingQuickAccess.ts`](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/contrib/search/browser/anythingQuickAccess.ts)

### 5. VS Code：类型信息与结果分组

VS Code 官方设计规范建议：

- Tree item 可以使用 product icon 区分类型；
- Quick Pick 使用 icon 帮助辨认项目；
- description 和 detail 用于补充简短上下文；
- 当选择项确实存在多个明显分组时，可以使用 separator；
- Tree View 应避免没有必要的深层嵌套。

这支持  为 Table、Record、Enum 使用稳定的类型标识，也支持在 Quick Open 空状态中用“最近使用”等明确分区。

但本次官方来源没有证明“全部 / 表 / 类型”筛选 chips 是必须方案。它可以作为后续可用性测试中的增强项，不应在没有证据的情况下当作标准设计。

官方来源：

- [VS Code Views UX Guidelines](https://code.visualstudio.com/api/ux-guidelines/views)
- [VS Code Quick Picks UX Guidelines](https://code.visualstudio.com/api/ux-guidelines/quick-picks)
- [VS Code QuickPickItem API](https://code.visualstudio.com/api/references/vscode-api#QuickPickItem)

### 6. VS Code：大列表使用虚拟渲染

VS Code 官方 Lists And Trees 文档将 List 定义为虚拟渲染引擎：只有视口内元素进入 DOM，滚动时动态加入或移除节点。文档明确指出，该机制用于让列表扩展到很大的数据量，并给出了 `100k` 元素仍可处理的说明。

这说明商业化实现应从组件能力层面解决大列表问题，而不是等列表达到某个任意数量后再切换为另一套 DOM。

官方来源：

- [VS Code Wiki：Lists And Trees](https://github.com/microsoft/vscode/wiki/Lists-And-Trees)

### 7. JupyterLab：File Browser 局部模糊过滤

JupyterLab File Browser 的官方设置和源码显示：

- `useFuzzyFilter` 默认开启；
- `filterDirectories` 默认开启；
- 可以配置默认显示过滤栏；
- 可以在目录导航后清空过滤内容；
- 模型逐项应用过滤函数，并保存匹配位置供名称高亮。

这进一步支持左侧资源区内建局部过滤，而不是把所有查找都强制送往全局弹窗。

官方来源：

- [JupyterLab File Browser 设置 Schema](https://github.com/jupyterlab/jupyterlab/blob/main/packages/filebrowser-extension/schema/browser.json)
- [JupyterLab `filebrowser/src/model.ts`](https://github.com/jupyterlab/jupyterlab/blob/main/packages/filebrowser/src/model.ts)

### 8. JupyterLab：键盘浏览

JupyterLab `DirListing` 源码支持：

- `Enter` 打开所选项目；
- `ArrowUp / ArrowDown` 移动选择；
- 输入字符后按名称前缀选中；
- 焦点移动时确保当前项目滚入视口。

这些行为说明，无论左栏过滤还是 Quick Open，都必须具备完整键盘路径，不能只实现鼠标点击。

官方来源：

- [JupyterLab `filebrowser/src/listing.ts`](https://github.com/jupyterlab/jupyterlab/blob/main/packages/filebrowser/src/listing.ts)

### 9. JupyterLab：Command Palette 不是资源 Quick Open

JupyterLab 官方文档将 Command Palette 定义为搜索和执行应用命令的键盘入口。它不等同于 VS Code 的全局文件 Quick Open。

JupyterLab 也提供 Recent Menu 和 Reopen Closed Document，但本次没有找到官方证据表明它将“最近资源 + 全量文件模糊搜索”统一为资源 Quick Open。

因此， 的资源快速打开应主要参考 VS Code，而不是把 JupyterLab Command Palette 直接当作同类设计。

官方来源：

- [JupyterLab Commands：Command Palette](https://jupyterlab.readthedocs.io/en/stable/user/commands.html#command-palette)
- [JupyterLab Commands：Recent Menu](https://jupyterlab.readthedocs.io/en/stable/user/commands.html#recent-menu)

### 10. JupyterLab：File Browser 不适合作为长列表性能基线

JupyterLab 当前 `DirListing.onUpdateRequest` 会让列表节点数量与 item 数量一致：节点不足时持续创建并 append，节点过多时移除。这不是视口虚拟化。

JupyterLab 官方仓库的性能问题也记录了包含 60,000 个文件的目录会造成界面无响应和显著内存增长。该 issue 不能替代性能基准，但与源码行为一致，说明不能照搬 JupyterLab File Browser 的渲染方式。

官方来源：

- [JupyterLab `filebrowser/src/listing.ts`](https://github.com/jupyterlab/jupyterlab/blob/main/packages/filebrowser/src/listing.ts)
- [JupyterLab Issue #8700：FileBrowser large directory performance](https://github.com/jupyterlab/jupyterlab/issues/8700)

## 对 Schema Editor  的具体建议

### 左侧资源区

保留现有分组浏览，不增加文件夹、收藏夹、标签树等第二套组织系统。

建议增加：

- 一个固定的“搜索资源”输入框；
- 名称 fuzzy match 与字符高亮；
- 搜索结果数，例如 `Tables 8/420`；
- 搜索期间自动展示所有有命中的分组；
- 清空搜索后恢复用户原来的分组折叠状态；
- `/` 聚焦搜索，`Esc` 清空，`Up/Down` 移动，`Enter` 打开；
- 空结果时给出明确提示，而不是保留空白分组。

“全部 / Tables / Records / Enums”筛选 chips 暂不作为第一版必需项。只有当实际数据和可用性测试证明类型范围仍造成噪声时再加入。

### Quick Open

新增 `Cmd/Ctrl + P` 资源快速打开：

- 不依赖左侧资源区是否展开；
- 空查询显示最近打开的资源；
- 输入后查询全部 Table、Record、Enum；
- 每项显示名称、类型图标或短标签，以及必要的所属信息；
- 使用 fuzzy score 排序并高亮命中字符；
- `Up/Down` 移动，`Enter` 打开，`Esc` 关闭；
- 打开资源后更新最近使用顺序；
- 同名资源必须依靠类型与上下文消歧。

不要在第一版中加入收藏、固定、标签管理、复杂查询语法或多层筛选面板。这些能力会增加状态和管理成本，与“快速打开”的目标相冲突。

### 字段查找

字段不与 Table、Record、Enum 永久混在默认结果中，但保留独立模式：

- `Cmd/Ctrl + P` 默认查找资源；
- Quick Open 内输入 `@`，切换为“当前资源字段”；或提供等价独立快捷键；
- 字段结果显示字段名、类型、角色和约束摘要；
- 暂不做跨整个工作区的字段搜索，等实际使用证明有需求再增加独立 provider。

这种模式比彻底排除字段更可扩展，也避免大量 `Id`、`Name`、`Type` 污染默认资源结果。

### 数据与匹配实现

建议将资源发现能力建立在独立数据索引上，而不是查询 DOM：

- 维护规范化名称、显示名称、资源类型和稳定 ID；
- scorer 对 label、可选别名和上下文分别评分；
- 缓存规范化文本和重复查询分数；
- 输入事件进行轻量合并或取消过期异步结果；
- UI 只渲染排序后的结果窗口；
- 资源重命名或 Schema 更新时增量更新索引。

不要只依赖 hash 判断资源相同；稳定 ID 或规范化原字符串仍应参与最终确认。匹配索引用于定位候选，真实资源标识用于消歧。

### 长列表与虚拟化

正式实现应优先选用支持以下能力的单一列表组件：

- 虚拟滚动；
- 稳定 item key；
- 焦点与键盘 roving tabindex；
- 选中项滚入视口；
- 动态过滤后保持合理焦点；
- 屏幕阅读器所需的列表语义；
- reduced motion 兼容。

不能写成：

```text
if resource_count > 200:
    enable_virtualization()
```

固定 `200` 条阈值没有官方依据，也没有当前项目的性能测量支撑。更合理的决策是：

1. 若组件原生支持虚拟化，生产实现从第一天就使用同一渲染路径；
2. 若现有组件不支持，先建立包含 100、1,000、10,000 项的交互基准；
3. 根据首屏渲染、输入到结果延迟、滚动帧率、DOM 节点数和内存数据决定是否必须替换组件；
4. 不在运行时用任意条数切换两套完全不同的列表实现。

## 建议的  第一阶段范围

第一阶段只验证发现模型，不扩展 Schema 编辑能力：

1. 左栏 fuzzy 过滤、命中高亮、结果计数和键盘操作；
2. `Cmd/Ctrl + P` Quick Open；
3. 空查询 Recent，输入后全量 fuzzy 排序；
4. 类型图标或短标签与同名消歧；
5. `@` 当前资源字段模式；
6. 桌面、中屏、移动端焦点与关闭行为；
7. 使用模拟大数据验证 100、1,000、10,000 项；
8. 不加入收藏、标签、复杂筛选、跨工作区字段搜索。

## 最终判断

此前提出的双层查找方向是正确的，但以下三点需要纠正：

- 不使用手写的“精确 / 前缀 / 包含”三档匹配代替 fuzzy scorer；
- 不武断地永久排除字段搜索，而是将它设计为独立 provider 或模式；
- 不采用固定 `200` 条作为虚拟化开关。

Schema Editor  应以 VS Code Explorer + Quick Open 作为资源发现基线，JupyterLab 仅用于补充侧栏过滤和文件列表键盘交互参考，不能作为长列表渲染性能参考。
