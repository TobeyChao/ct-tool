/// 模拟数据（MOCK）——仅供 native-flutter-workbench 1.2-1.4 界面样板使用。
///
/// 严禁作为业务验收依据；接入真实 worker（任务 2.x-4.x）后本目录整体删除。
library;

import '../workbench_models.dart';

/// 样板场景：覆盖 1.4 要求的空态、错误、长文本、忙碌与冲突状态。
enum MockScenario { normal, empty, loadError, longText, busy, conflict }

extension MockScenarioLabel on MockScenario {
  String get label => switch (this) {
    MockScenario.normal => '正常',
    MockScenario.empty => '空工作区',
    MockScenario.loadError => '加载失败',
    MockScenario.longText => '长文本',
    MockScenario.busy => '导出忙碌',
    MockScenario.conflict => '候选冲突',
  };
}

// 模型类型已上移到中性契约（workbench_models.dart），这里只保留样板用的别名；
// 接入真实 worker 后本文件整体删除。
/// 类别名与 `.label` 文案的唯一定义在 workbench_models.dart，避免两份扩展竞争。
typedef MockResourceKind = WorkbenchResourceKind;

typedef MockField = WorkbenchField;
typedef MockResource = WorkbenchResource;
typedef MockTaskStatus = WorkbenchTaskStatus;
typedef MockTask = WorkbenchTask;

/// 界面样板数据：字段与 [WorkbenchData] 契约同名，便于与真实来源互换。
class MockWorkspaceData extends StaticWorkbenchData {
  const MockWorkspaceData({
    required super.workspaceName,
    required super.workspacePath,
    super.schemaRevision = 41,
    super.resources = const [],
    super.tasks = const [],
    super.draftCount = 0,
    super.busy = false,
    super.candidateExpired = false,
    super.loadError,
  });
}

MockWorkspaceData mockWorkspaceFor(MockScenario scenario) {
  return switch (scenario) {
    MockScenario.normal => _normal(),
    MockScenario.empty => const MockWorkspaceData(
      workspaceName: 'gd',
      workspacePath: 'D:/game/gd',
      schemaRevision: 3,
    ),
    MockScenario.loadError => const MockWorkspaceData(
      workspaceName: 'gd',
      workspacePath: 'D:/game/gd',
      loadError:
          '读取 schemas/hero.yaml 失败：mapping values are not allowed here\n'
          '  in "schemas/hero.yaml", line 18, column 7\n'
          '工作区其余 6 个资源正常，可修复后重试。',
      tasks: [
        MockTask(
          id: 9,
          title: '加载工作区资源',
          status: MockTaskStatus.failed,
          detail: 'schemas/hero.yaml 第 18 行语法错误',
          duration: '0.04s',
        ),
      ],
    ),
    MockScenario.longText => _longText(),
    MockScenario.busy => _busy(),
    MockScenario.conflict => _conflict(),
  };
}

MockWorkspaceData _normal() {
  const hero = MockResource(
    name: 'hero',
    kind: MockResourceKind.table,
    path: 'schemas/hero.yaml',
    dirty: true,
    fields: [
      MockField(
        name: 'id',
        type: 'int',
        role: '主键',
        constraints: '必填·唯一',
        description: '英雄唯一 ID',
      ),
      MockField(
        name: 'name',
        type: 'string',
        description: '显示名称（中文）',
        localized: true,
      ),
      MockField(
        name: 'rarity',
        type: 'ref<Enum<quality>>',
        constraints: '必填',
        description: '品质，引用枚举 quality',
      ),
      MockField(
        name: 'base_hp',
        type: 'int',
        defaultValue: '100',
        description: '基础生命',
      ),
      MockField(
        name: 'base_atk',
        type: 'int',
        defaultValue: '10',
        description: '基础攻击',
      ),
      MockField(
        name: 'skills',
        type: 'vector<ref<Record<hero_skill>>>',
        description: '技能列表',
      ),
      MockField(
        name: 'unlock_level',
        type: 'int',
        defaultValue: '1',
        description: '解锁等级',
      ),
      MockField(
        name: 'story',
        type: 'string',
        description: '角色背景故事，支持多语言',
        localized: true,
      ),
    ],
    previewColumns: ['id', 'name', 'rarity', 'base_hp'],
    previewRows: [
      ['1001', '阿岚', 'epic', '560'],
      ['1002', '凯尔', 'rare', '480'],
      ['1003', 'Mira', 'legendary', '720'],
    ],
  );
  const item = MockResource(
    name: 'item',
    kind: MockResourceKind.table,
    path: 'schemas/item.yaml',
    fields: [
      MockField(name: 'id', type: 'int', role: '主键', constraints: '必填·唯一'),
      MockField(name: 'name', type: 'string', localized: true),
      MockField(name: 'icon', type: 'string', description: '图标资源路径'),
      MockField(name: 'price', type: 'int', defaultValue: '0'),
      MockField(name: 'stack_limit', type: 'int', defaultValue: '99'),
    ],
    previewColumns: ['id', 'name', 'price'],
    previewRows: [
      ['2001', '治疗药水', '50'],
      ['2002', '铁剑', '320'],
    ],
  );
  const monster = MockResource(
    name: 'monster',
    kind: MockResourceKind.table,
    path: 'schemas/monster.yaml',
    fields: [
      MockField(name: 'id', type: 'int', role: '主键', constraints: '必填·唯一'),
      MockField(name: 'name', type: 'string', localized: true),
      MockField(name: 'level', type: 'int', defaultValue: '1'),
      MockField(name: 'drop', type: 'ref<Record<drop_rule>>'),
    ],
  );
  const heroSkill = MockResource(
    name: 'hero_skill',
    kind: MockResourceKind.record,
    path: 'schemas/hero_skill.yaml',
    fields: [
      MockField(
        name: 'skill_id',
        type: 'int',
        role: '主键',
        constraints: '必填·唯一',
      ),
      MockField(name: 'damage', type: 'int', defaultValue: '0'),
      MockField(name: 'cooldown', type: 'float', defaultValue: '0'),
      MockField(name: 'effect', type: 'string', localized: true),
    ],
  );
  const dropRule = MockResource(
    name: 'drop_rule',
    kind: MockResourceKind.record,
    path: 'schemas/drop_rule.yaml',
    fields: [
      MockField(name: 'item', type: 'ref<Table<item>>', constraints: '必填'),
      MockField(name: 'chance', type: 'float', defaultValue: '1'),
      MockField(name: 'count_range', type: 'vector<int>'),
    ],
  );
  const quality = MockResource(
    name: 'quality',
    kind: MockResourceKind.enumType,
    path: 'schemas/quality.yaml',
    dirty: true,
    fields: [
      MockField(
        name: 'common',
        type: 'item',
        constraints: 'ordinal 0',
        description: '普通',
      ),
      MockField(
        name: 'rare',
        type: 'item',
        constraints: 'ordinal 1',
        description: '稀有',
      ),
      MockField(
        name: 'epic',
        type: 'item',
        constraints: 'ordinal 2',
        description: '史诗',
      ),
      MockField(
        name: 'legendary',
        type: 'item',
        constraints: 'ordinal 3',
        description: '传说',
      ),
    ],
  );
  const damageType = MockResource(
    name: 'skill_damage_type',
    kind: MockResourceKind.enumType,
    path: 'schemas/skill_damage_type.yaml',
    fields: [
      MockField(name: 'physical', type: 'item', constraints: 'ordinal 0'),
      MockField(name: 'magical', type: 'item', constraints: 'ordinal 1'),
      MockField(name: 'true_damage', type: 'item', constraints: 'ordinal 2'),
    ],
  );
  return const MockWorkspaceData(
    workspaceName: 'gd',
    workspacePath: 'D:/game/gd',
    schemaRevision: 41,
    draftCount: 3,
    resources: [hero, item, monster, heroSkill, dropRule, quality, damageType],
    tasks: [
      MockTask(
        id: 8,
        title: 'i18n sync（en, ja）',
        status: MockTaskStatus.queued,
        detail: '等待导出完成后开始',
        duration: '—',
      ),
      MockTask(
        id: 7,
        title: '导出 hero, item → json/fbs/cs/lua',
        status: MockTaskStatus.success,
        detail: '4 类产物已发布 · 缓存命中 2/7',
        duration: '2.31s',
      ),
      MockTask(
        id: 6,
        title: '模板预检 hero',
        status: MockTaskStatus.success,
        detail: '列路径无需迁移',
        duration: '0.18s',
      ),
      MockTask(
        id: 5,
        title: '导出 monster → 全部目标',
        status: MockTaskStatus.failed,
        detail: 'monster.xlsx 第 42 行：rarity 引用了不存在的枚举值 elite',
        duration: '1.02s',
      ),
    ],
  );
}

MockWorkspaceData _busy() {
  final base = _normal();
  return MockWorkspaceData(
    workspaceName: base.workspaceName,
    workspacePath: base.workspacePath,
    schemaRevision: base.schemaRevision,
    resources: base.resources,
    draftCount: 2,
    busy: true,
    tasks: [
      const MockTask(
        id: 9,
        title: '导出 7 张表 → json/fbs/cs/lua',
        status: MockTaskStatus.running,
        progress: 0.42,
        detail: '正在构建 fbs：monster（3/7）',
        duration: '1.8s',
      ),
      ...base.tasks,
    ],
  );
}

MockWorkspaceData _conflict() {
  final base = _normal();
  return MockWorkspaceData(
    workspaceName: base.workspaceName,
    workspacePath: base.workspacePath,
    schemaRevision: base.schemaRevision,
    resources: base.resources,
    draftCount: 3,
    candidateExpired: true,
    tasks: base.tasks,
  );
}

MockWorkspaceData _longText() {
  const heroLong = MockResource(
    name: '英雄配置表_超长名称_hero_config_with_a_very_long_english_suffix_v2',
    kind: MockResourceKind.table,
    path: 'schemas/非常深的目录层级/再深一层/hero_config_with_a_very_long_name.yaml',
    dirty: true,
    fields: [
      MockField(
        name: 'id',
        type: 'int',
        role: '主键',
        constraints: '必填·唯一',
        description: '英雄唯一 ID',
      ),
      MockField(
        name: 'name',
        type: 'string',
        localized: true,
        description:
            '这是一个用来验证长文本省略与换行行为的字段描述，需要足够长才能覆盖属性区和表格单元格的截断场景，'
            'English mixed content to make it even longer than usual for overflow checks.',
      ),
      MockField(
        name: 'skill_bindings',
        type:
            'vector<ref<Record<hero_skill_binding_with_extremely_long_name>>>',
        description: '超长类型表达式截断验证',
      ),
      MockField(
        name: 'drop_table_override_reference_id',
        type:
            'ref<Table<drop_table_with_an_extremely_long_table_name_for_testing>>',
        constraints: '必填·跨表引用',
        defaultValue: '999999999999',
      ),
    ],
    previewColumns: ['id', 'name'],
    previewRows: [
      ['1001', '这是一个非常非常长的本地化文本内容，用来验证预览表格的单元格省略与横向滚动是否正常工作'],
      [
        '1002',
        'AnExtremelyLongEnglishLocalizedStringWithoutAnySpacesToTestEllipsisBehaviorInCells',
      ],
    ],
  );
  const enumLong = MockResource(
    name: 'quality_with_unusually_long_enum_name_for_layout_testing',
    kind: MockResourceKind.enumType,
    path: 'schemas/quality_with_unusually_long_enum_name.yaml',
    fields: [
      MockField(name: 'common', type: 'item', constraints: 'ordinal 0'),
      MockField(
        name: 'ridiculously_long_enum_item_name_that_should_be_truncated',
        type: 'item',
        constraints: 'ordinal 1',
      ),
    ],
  );
  return const MockWorkspaceData(
    workspaceName: 'gd-超长线',
    workspacePath:
        'D:/项目/游戏工作区/这是一个非常长的工作区目录名称_for_a_really_long_workspace_path/gd',
    draftCount: 1,
    resources: [heroLong, enumLong],
    tasks: [
      MockTask(
        id: 3,
        title:
            '导出 英雄配置表_超长名称_hero_config_with_a_very_long_english_suffix_v2 → json/fbs/cs/lua（含全部语言）',
        status: MockTaskStatus.failed,
        detail:
            '第 1024 行：skill_bindings 引用的 Record hero_skill_binding_with_extremely_long_name 在工作区中不存在，请检查 schema 后再导出',
        duration: '12.40s',
      ),
    ],
  );
}
