## ADDED Requirements

### Requirement: Semantic per-language i18n fingerprint
工具 SHALL 为每张含 i18n 字段的 Table 和每个 secondary language 计算确定性的语义 fingerprint。输入 SHALL 包含当前有效 source key 集合、每个有效 key 的存在性、`text` 与 `confirmed`、primary/target language、启用语言配置、data fingerprint 和 merge policy version。派生 `source`、派生 `status`、orphan 条目、JSON 空白与 key 排列 SHALL NOT 改变导出 fingerprint。

#### Scenario: Confirmed translation changes output fingerprint
- **WHEN** `Item/en` 的有效条目 `text` 改变或 `confirmed` 从 false 变为 true
- **THEN** Item/en i18n fingerprint 改变并使对应语言 JSON、i18n bytes 与 Bundle 失效

#### Scenario: Derived metadata does not rebuild output
- **WHEN** 仅 lang 文件的派生 `source`、`status`、orphan 条目、缩进或 key 排列改变，而当前有效 key 的 text/confirmed 语义不变
- **THEN** i18n fingerprint 保持不变，工具不重建语言产物

#### Scenario: Translation file appears or disappears
- **WHEN** 一个曾产生已确认译文的 Table/lang 文件删除，或缺失文件中新建了有效已确认译文
- **THEN** 语义 fingerprint 改变，导出按当前文件状态生成主语言 fallback 或新译文，不复用旧 i18n bytes

### Requirement: Compute i18n fingerprint after canonical sync
当 Table 的 data fingerprint 改变时，export SHALL 先解析 Excel、刷新 source 并运行既有 sync 状态机，再从同步后的有效 key 与 lang 条目计算最终 i18n fingerprint；当 data fingerprint 未变化时，工具 MAY 从可信 source/cache key 集合与当前 lang 文件计算 fingerprint。成功 export 后保存的 fingerprint SHALL 对应实际写出的 JSON/i18n bytes，不能因本次 sync 自身写文件而立即过期。

#### Scenario: Source change invalidates confirmation before hashing
- **WHEN** 主语言原文改变且旧译文此前 confirmed=true
- **THEN** sync 先把译文变为 stale/confirmed=false，随后计算的 fingerprint 与 fallback 输出一致

#### Scenario: Corrupt translation file never reuses old bytes
- **WHEN** 当前 Table/lang JSON 无法解析或结构不合法
- **THEN** export 报告具体文件和条目错误，不提交新 fingerprint，也不以旧缓存 bytes 假装成功

### Requirement: Language-scoped incremental export
翻译语义变化 SHALL 只失效对应 Table 和 language 的 JSON、i18n bytes 与 language Bundle。主语言 data、FBS、Accessor 和其他 secondary language 产物 SHALL 在各自 fingerprint 匹配时复用；新增或删除 secondary language SHALL 被视为语言产物集合变化，即使 Excel 未改变也必须生成或清理对应产物。

#### Scenario: Only English translation changes
- **WHEN** Item/en 有效译文变化，zh 主语言与 ja 译文未变
- **THEN** export 更新 Item_en JSON、Item/en i18n bytes 和 en Bundle，不重写 zh/ja Bundle、FBS 或 Accessor

#### Scenario: Add a secondary language without Excel change
- **WHEN** global config 新增 `ja` 且所有 Excel/Schema 未变化
- **THEN** 所有含 i18n 字段的 Table 进入 ja 语言导出路径并生成缺失 fallback/skeleton 对应的 ja JSON 与 Bundle

#### Scenario: Filter one language
- **WHEN** 用户执行 `ct export --lang en` 且只有 en fingerprint 改变
- **THEN** 工具只比较和发布 en 语言产物状态，不改写其他语言的成功 fingerprint 或产物
