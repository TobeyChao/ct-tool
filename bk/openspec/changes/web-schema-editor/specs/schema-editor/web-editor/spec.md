## Purpose

web 端结构化 schema 编辑器主体：把表格管理的 schema 编辑从 YAML 明文文本框升级为结构化界面（表 CRUD、字段结构化编辑、校验与保存），策划全程不接触 YAML。

## ADDED Requirements

### Requirement: 表格管理页签（表 CRUD）

面板 SHALL 在「表格管理」页签展示 schema 表列表（表名 + excel 文件 + 字段数/i18n 数 + 状态徽章），支持新增表、编辑表、删除表。删除 SHALL 弹出确认模态（提示将删除 schema 定义与 Excel 模板、不可恢复、已导出产物与翻译文件不受影响），确认后删除并刷新列表。列表为空时 SHALL 显示空态（「暂无表」+ 新增表引导按钮），不显示空白。

#### Scenario: 删除表带确认
- **WHEN** 策划在表列表点击删除并确认
- **THEN** 该表从列表移除，schema 文件与 Excel 模板被删除，列表显示空态（若已无表）

#### Scenario: 取消删除
- **WHEN** 策划在确认模态点击取消
- **THEN** 表保留，列表不变

#### Scenario: 空列表
- **WHEN** 工作区没有任何 schema 表
- **THEN** 列表区域显示「暂无表」与「新增表」引导按钮

### Requirement: 结构化字段编辑（9 种类型）

字段编辑器 SHALL 以结构化行展示字段（字段名 + 类型控件 + 状态 tags + 操作按钮），支持 9 种类型（int32/int64/float/double/bool/string/enum/struct/vector）的类型选择、字段新增、删除、上移/下移、重命名。主键字段（固定名 Id，类型仅 int32/int64）与 code 字段（固定名 CodeName，string）SHALL 锁定显示「🔒 主键」/「🔒 CodeName」，无改名/删除入口，删除主键行被拦截并提示「主键字段不可删除」。

#### Scenario: 新增并排序字段
- **WHEN** 策划点击「+ 添加字段」插入新字段行，并可上移/下移调整顺序
- **THEN** 字段行即时出现且顺序按操作改变，保存后 YAML 字段顺序一致

#### Scenario: 主键与 code 字段锁定
- **WHEN** 策划尝试删除或重命名 Id / CodeName 字段
- **THEN** 操作被拦截：Id 显示「主键字段不可删除」，CodeName 无改名入口

#### Scenario: 修改字段类型
- **WHEN** 策划通过类型控件切换字段类型（如 int32 → string）
- **THEN** 字段行类型即时更新，相关约束（如 i18n 可用性）联动变化

### Requirement: 保存与后端对接

保存 Schema SHALL 将结构化字段数组序列化后提交既有 `POST/PUT /api/schemas`（后端 `_build_schema` 的 pydantic 校验兜底），成功关闭模态并刷新列表，失败在模态顶部显示后端校验错误。整个编辑过程 SHALL 不出现 YAML 明文编辑框。

#### Scenario: 保存成功
- **WHEN** 策划完成字段编辑并点击保存 Schema 且前端校验通过
- **THEN** 字段数组提交后端，schema 文件按结构化内容写入，模态关闭、列表刷新

#### Scenario: 后端校验兜底
- **WHEN** 前端绕过校验提交非法结构（如 enum 无 values）
- **THEN** 后端 pydantic 校验报错，错误文本显示在模态顶部错误条，模态不关闭

### Requirement: 前端即时校验

字段编辑器 SHALL 在保存前做即时校验并显示错误：字段名必填（空名显示「未命名字段」占位并可再次点击进入编辑）、字段名与现有字段重名（「与字段 X 重复」）、主键删除保护；保存时全量校验，存在错误时模态顶部显示「存在 N 处校验问题（…），请修复后再保存」。重新打开模态时错误态复位。

#### Scenario: 空名与重名即时提示
- **WHEN** 策划提交空字段名或将字段改为与已有字段同名
- **THEN** 该行标红并显示行内错误提示，保存被阻止并汇总错误

#### Scenario: 错误态复位
- **WHEN** 关闭后重新打开编辑模态
- **THEN** 上次的校验错误态全部清除
