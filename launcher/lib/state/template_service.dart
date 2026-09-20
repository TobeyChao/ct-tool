import 'package:flutter/foundation.dart';

import '../services/protocol/protocol.dart';
import '../services/worker_service.dart';

/// Excel 模板的显式预检与生成（native-flutter-workbench 任务 3.6）。
///
/// 只有 `template.plan` 放行（canGenerate）才允许 `template.generate`；
/// 两者都不碰 YAML 保存的结论，也不能被保存顺手触发——生成是独立操作。
class TemplateService extends ChangeNotifier {
  TemplateService({required this.worker, required this.workspaceRoot});

  final KernelGateway worker;
  final String workspaceRoot;

  String? table;
  TemplatePlanResult? plan;
  TemplateGenerateResult? generated;
  bool busy = false;
  String? error;
  int _generation = 0;

  bool get hasPlan => plan != null;

  /// 预检结论决定是否可生成：内核说不行就不给点。
  bool get canGenerate => plan != null && plan!.canGenerate && !busy;

  List<Issue> get problems => plan?.problems ?? const [];

  List<Issue> get warnings => [
    ...(plan?.warnings ?? const []),
    ...(generated?.warnings ?? const []),
  ];

  void select(String? name) {
    if (table == name) return;
    table = name;
    plan = null;
    generated = null;
    error = null;
    notifyListeners();
  }

  Future<TemplatePlanResult?> runPlan(String name) async {
    final generation = ++_generation;
    table = name;
    busy = true;
    error = null;
    plan = null;
    generated = null;
    notifyListeners();
    try {
      return await _planInto(name, generation);
    } on WorkerRequestException catch (e) {
      if (!_isCurrent(generation)) return null;
      error = '${e.code}：${e.message}';
      return null;
    } on Object catch (e) {
      if (!_isCurrent(generation)) return null;
      error = '模板预检失败：$e';
      return null;
    } finally {
      if (_isCurrent(generation)) {
        busy = false;
        notifyListeners();
      }
    }
  }

  Future<TemplatePlanResult?> _planInto(String name, int generation) async {
    final payload = await worker.query(
      Methods.templatePlan,
      params: {'table': name},
      workspaceRoot: workspaceRoot,
    );
    if (!_isCurrent(generation)) return null;
    final result = TemplatePlanResult.fromJson(_map(payload));
    plan = result;
    return result;
  }

  /// 显式生成：预检阻塞时绝不发送；失败也不改判已完成的 YAML 保存。
  Future<TemplateGenerateResult?> runGenerate() async {
    final found = plan;
    final name = table;
    if (found == null || !found.canGenerate || name == null || busy) {
      return null;
    }
    final generation = ++_generation;
    busy = true;
    error = null;
    notifyListeners();
    try {
      final payload = await worker.query(
        Methods.templateGenerate,
        params: {'table': name},
        workspaceRoot: workspaceRoot,
      );
      if (!_isCurrent(generation)) return null;
      final result = TemplateGenerateResult.fromJson(_map(payload));
      generated = result;
      // 生成会改变模板状态：立刻再问一次内核，界面不留在旧结论上。
      await _planInto(name, generation);
      return result;
    } on WorkerRequestException catch (e) {
      if (!_isCurrent(generation)) return null;
      error = '${e.code}：${e.message}';
      return null;
    } on Object catch (e) {
      if (!_isCurrent(generation)) return null;
      error = '模板生成失败：$e';
      return null;
    } finally {
      if (_isCurrent(generation)) {
        busy = false;
        notifyListeners();
      }
    }
  }

  bool _isCurrent(int generation) => generation == _generation;

  static Map<String, Object?> _map(Object? payload) =>
      payload is Map<String, Object?>
      ? payload
      : throw StateError('payload 形状异常');
}
