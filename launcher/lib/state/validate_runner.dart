import 'package:flutter/foundation.dart';

import '../services/protocol/protocol.dart';
import '../services/worker_service.dart';

/// 只读校验运行器（native-flutter-workbench 任务 5.4 的前置：把 `validate` 接进桌面）。
///
/// 闸门结论完全来自内核 `validate` 回包：界面只渲染 `ok` 与 `issues`，
/// 不在 Dart 侧重复判类型/主键/ref；校验本身不写任何文件。
/// 有写任务在跑时不发请求——校验与导出抢同一把工作区锁只会互相拖慢。
class ValidateRunner extends ChangeNotifier {
  ValidateRunner({required this.worker, required this.workspaceRoot});

  final KernelGateway worker;
  final String workspaceRoot;

  bool busy = false;
  ValidateResult? last;
  String? error;
  int? elapsedMs;

  /// 单表范围（null/空 = 全库）；与导出的表过滤各自独立，不互相猜。
  String? scopeTable;

  Future<ValidateResult?> run({String? table}) async {
    if (busy || workspaceRoot.isEmpty) return null;
    final scope = (table ?? scopeTable ?? '').trim();
    busy = true;
    error = null;
    notifyListeners();
    final started = DateTime.now();
    try {
      final payload = await worker.query(
        Methods.validate,
        params: {if (scope.isNotEmpty) 'table': scope},
        workspaceRoot: workspaceRoot,
      );
      if (payload is! Map<String, Object?>) {
        error = '校验返回了意外形状：${payload.runtimeType}';
        last = null;
        return null;
      }
      last = ValidateResult.fromJson(payload);
      elapsedMs = DateTime.now().difference(started).inMilliseconds;
      return last;
    } on WorkerRequestException catch (e) {
      error = '${e.code}：${e.message}';
      last = null;
      return null;
    } on Object catch (e) {
      error = '校验失败：$e';
      last = null;
      return null;
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  void clear() {
    last = null;
    error = null;
    elapsedMs = null;
    notifyListeners();
  }

  /// 一句话摘要：内核说通过才通过；失败原因原样带出，不折叠成「出错了」。
  String get summaryLabel {
    if (busy) return '校验中…';
    if (error != null) return error!;
    final found = last;
    if (found == null) return '未校验';
    final timing = elapsedMs == null ? '' : ' · ${elapsedMs}ms';
    final scope = (scopeTable ?? '').trim();
    final where = scope.isEmpty ? '全库' : '表 $scope';
    return found.ok
        ? '校验通过（$where，问题 0 个$timing）'
        : '校验未通过（$where，问题 ${found.issues.length} 个$timing）';
  }
}
