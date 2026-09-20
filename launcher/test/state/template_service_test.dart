import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/template_service.dart';
import 'package:flutter_test/flutter_test.dart';

/// 模板预检/生成（任务 3.6）：生成必须由预检放行，阻塞问题原样交给界面。
class _Call {
  _Call(this.method, this.params);
  final String method;
  final Map<String, Object?> params;
}

class _FakeGateway implements KernelGateway {
  _FakeGateway({this.canGenerate = true, this.failWith});

  final bool canGenerate;
  final String? failWith;
  final List<_Call> calls = [];

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-tpl';

  List<_Call> of(String method) =>
      calls.where((c) => c.method == method).toList();

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    calls.add(_Call(method, params));
    if (failWith == method) {
      throw WorkerRequestException(
        ErrorBody(code: 'busy', message: '工作区被写任务占用'),
      );
    }
    return switch (method) {
      Methods.templatePlan => {
        'canGenerate': canGenerate,
        'actions': const ['重建表头（样式与 stable column path）', '按稳定列路径迁移数据'],
        'warnings': canGenerate
            ? const [
                {'code': 'template', 'message': 'Enum 下拉超过 255 字符，已降级'},
              ]
            : const <Object?>[],
        'problems': canGenerate
            ? const <Object?>[]
            : [
                {
                  'code': 'template',
                  'message': 'Item 的 Excel 缺少布局 manifest，无法安全迁移',
                  'resource': 'table:Item',
                },
              ],
      },
      Methods.templateGenerate => {
        'migratedRows': 7,
        'warnings': const <Object?>[],
      },
      _ => throw StateError('未预期方法 $method'),
    };
  }
}

void main() {
  late _FakeGateway gateway;
  late TemplateService service;

  setUp(() {
    gateway = _FakeGateway();
    service = TemplateService(worker: gateway, workspaceRoot: 'E:/ws/gd');
  });

  tearDown(() => service.dispose());

  test('未预检时不能生成，也不发任何请求', () async {
    expect(service.canGenerate, isFalse);
    expect(await service.runGenerate(), isNull);
    expect(gateway.calls, isEmpty);
  });

  test('预检带表名与 workspaceRoot，动作与告警原样保留', () async {
    final plan = await service.runPlan('Item');
    expect(plan, isNotNull);
    final call = gateway.of(Methods.templatePlan).single;
    expect(call.params, {'table': 'Item'});
    expect(call.params.containsKey('resource'), isFalse);
    expect(service.canGenerate, isTrue);
    expect(plan!.actions, hasLength(2));
    expect(plan.warnings.single.message, contains('255'));
    expect(service.problems, isEmpty);
  });

  test('生成成功后立刻再预检一次，界面不留旧结论', () async {
    await service.runPlan('Item');
    gateway.calls.clear();
    final done = await service.runGenerate();
    expect(done?.migratedRows, 7);
    expect(gateway.of(Methods.templateGenerate).single.params, {
      'table': 'Item',
    });
    expect(gateway.of(Methods.templatePlan), isNotEmpty, reason: '生成后必须刷新模板状态');
    expect(service.generated?.migratedRows, 7);
  });

  test('预检阻塞时生成按钮不可用，请求也发不出去', () async {
    gateway = _FakeGateway(canGenerate: false);
    service = TemplateService(worker: gateway, workspaceRoot: 'E:/ws/gd');
    final plan = await service.runPlan('Item');
    expect(plan!.canGenerate, isFalse);
    expect(service.canGenerate, isFalse);
    expect(service.problems.single.resource, 'table:Item');
    gateway.calls.clear();
    expect(await service.runGenerate(), isNull);
    expect(gateway.of(Methods.templateGenerate), isEmpty);
  });

  test('内核拒绝时交出错误码，不改判成成功', () async {
    gateway = _FakeGateway(failWith: Methods.templateGenerate);
    service = TemplateService(worker: gateway, workspaceRoot: 'E:/ws/gd');
    await service.runPlan('Item');
    expect(await service.runGenerate(), isNull);
    expect(service.error, contains('busy'));
    expect(service.generated, isNull);
  });

  test('预检失败也只报预检失败，不假装可生成', () async {
    gateway = _FakeGateway(failWith: Methods.templatePlan);
    service = TemplateService(worker: gateway, workspaceRoot: 'E:/ws/gd');
    expect(await service.runPlan('Item'), isNull);
    expect(service.error, isNotNull);
    expect(service.canGenerate, isFalse);
    expect(service.plan, isNull);
  });

  test('切换选中资源会清掉上一个表的预检结果', () async {
    await service.runPlan('Item');
    service.select('Quest');
    expect(service.plan, isNull);
    expect(service.canGenerate, isFalse);
    expect(service.generated, isNull);
  });
}
