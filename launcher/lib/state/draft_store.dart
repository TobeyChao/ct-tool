import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import '../services/protocol/protocol.dart';

/// 用户目录草稿的信封（任务 3.5）：带格式版本、工作区身份、原始基线、
/// 完整命令与撤销游标。缺任一项都视为不可靠，不静默套用。
class DraftEnvelope {
  const DraftEnvelope({
    required this.formatVersion,
    required this.workspaceKey,
    required this.baseline,
    required this.commands,
    required this.cursor,
    required this.savedAt,
  });

  static const currentFormat = 1;

  final int formatVersion;
  final String workspaceKey;
  final String baseline;
  final List<SchemaCommand> commands;
  final int cursor;
  final DateTime savedAt;

  Map<String, Object?> toJson() => {
    'formatVersion': formatVersion,
    'workspaceKey': workspaceKey,
    'baseline': baseline,
    'cursor': cursor,
    'savedAt': savedAt.toIso8601String(),
    'commands': commands.map((c) => c.toJson()).toList(),
  };

  /// 解析失败一律抛 [DraftFormatException]：宁可保留文件让用户看，也不猜。
  static DraftEnvelope fromJson(Map<String, Object?> json) {
    final version = json['formatVersion'];
    if (version is! int) throw const DraftFormatException('缺少 formatVersion');
    if (version > currentFormat) {
      throw DraftFormatException('草稿格式版本 $version 高于当前支持版本 $currentFormat');
    }
    final key = json['workspaceKey'];
    final baseline = json['baseline'];
    final cursor = json['cursor'];
    final commands = json['commands'];
    if (key is! String || key.isEmpty) {
      throw const DraftFormatException('缺少 workspaceKey');
    }
    if (baseline is! String) {
      throw const DraftFormatException('缺少 baseline（Schema 基线）');
    }
    if (cursor is! int || cursor < 0) {
      throw const DraftFormatException('缺少可用 cursor');
    }
    if (commands is! List) {
      throw const DraftFormatException('缺少 commands 列表');
    }
    return DraftEnvelope(
      formatVersion: version,
      workspaceKey: key,
      baseline: baseline,
      cursor: cursor,
      commands: [
        for (final item in commands)
          if (item is Map<String, Object?>) SchemaCommand.fromJson(item),
      ],
      savedAt:
          DateTime.tryParse('${json['savedAt']}') ??
          DateTime.fromMillisecondsSinceEpoch(0),
    );
  }
}

class DraftFormatException implements Exception {
  const DraftFormatException(this.reason);

  final String reason;

  @override
  String toString() => '草稿格式不可靠：$reason';
}

/// 读取结果：界面据此决定恢复、提示冲突还是保留待查看。
enum DraftOutcome { none, restored, conflict, damaged }

class DraftLoad {
  const DraftLoad(
    this.outcome, {
    this.envelope,
    this.reason,
    this.path,
    this.leftoverTemp = false,
  });

  final DraftOutcome outcome;
  final DraftEnvelope? envelope;
  final String? reason;
  final String? path;

  /// 是否清掉了上一轮中断留下的 `.tmp`（写穿前的临时件）。
  final bool leftoverTemp;

  bool get hasDraft => envelope != null && envelope!.commands.isNotEmpty;
}

/// 草稿使用的文件访问边界，可由其他存储适配器提供同样的文件操作。
class DraftFileAccess {
  const DraftFileAccess();

  bool exists(File file) => file.existsSync();
  Future<String> read(File file) => file.readAsString();
  Future<void> write(File file, String contents) async {
    await file.writeAsString(contents, flush: true);
  }

  Future<void> rename(File file, String target) async {
    await file.rename(target);
  }

  Future<void> delete(File file) async {
    await file.delete();
  }
}

/// 按工作区隔离的用户目录草稿存储：临时文件 + rename 原子落盘。
class DraftStore {
  DraftStore({this.rootOverride, this.fileAccess = const DraftFileAccess()});

  final Directory? rootOverride;
  final DraftFileAccess fileAccess;

  static const dirName = 'ct/drafts';

  Future<Directory> directory() async {
    final root = rootOverride ?? await getApplicationSupportDirectory();
    final dir = Directory(
      rootOverride == null ? '${root.path}/$dirName' : '${root.path}/drafts',
    );
    if (!dir.existsSync()) await dir.create(recursive: true);
    return dir;
  }

  /// 工作区身份 → 文件名：自己做 FNV-1a（32 位），跨进程稳定、跨平台一致；
  /// Object.hash 不保证跨运行稳定，那样重启后就找不到自己写的草稿。
  static String fileName(String workspaceKey) {
    final key = _normalize(workspaceKey);
    final tail = '$key/v1';
    return 'draft-${_fnv1a(key)}${_fnv1a(tail)}.json';
  }

  static String _fnv1a(String input) {
    var hash = 2166136261;
    for (final unit in utf8.encode(input)) {
      hash = ((hash ^ unit) * 16777619) & 0xffffffff;
    }
    return hash.toRadixString(16).padLeft(8, '0');
  }

  static String _normalize(String key) =>
      key.replaceAll(r'\', '/').toLowerCase();
  Future<File> fileFor(String workspaceKey) async =>
      File('${(await directory()).path}/${fileName(workspaceKey)}');

  // Admission tails only cover identity resolution, not file I/O. Register
  // synchronously so a later store cannot overtake an unresolved earlier call.
  // Once admitted, operations on different real files run independently.
  static final _admissions = <String, Future<void>>{};
  static final _fileTails = <String, Future<void>>{};

  Future<T> _enqueue<T>(
    String workspaceKey,
    Future<T> Function(File) operation, {
    T Function(Object)? onDirectoryError,
  }) {
    final name = fileName(workspaceKey);
    final admitted = Completer<void>();
    final predecessor = _admissions[name];
    _admissions[name] = admitted.future;
    final target = Future<File>.sync(() => fileFor(workspaceKey));

    Future<T> schedule() async {
      File? file;
      String? identity;
      Object? failure;
      StackTrace? failureStack;
      try {
        final requested = await target;
        // Resolve aliases (including symlinked roots) before choosing a queue.
        final realDirectory = requested.parent.resolveSymbolicLinksSync();
        identity = '$realDirectory/${requested.uri.pathSegments.last}';
        file = requested;
      } on Object catch (error, stack) {
        failure = error;
        failureStack = stack;
      }
      // Even failed resolution must retain its admission position: releasing
      // it early would let the next call skip an older unresolved operation.
      if (predecessor != null) await predecessor;
      late final Future<T> result;
      try {
        if (failure != null) {
          if (onDirectoryError != null) return onDirectoryError(failure);
          Error.throwWithStackTrace(failure, failureStack!);
        }
        final resolved = file!;
        final queueKey = identity!;
        final previous = _fileTails[queueKey] ?? Future<void>.value();
        result = previous.then((_) => operation(resolved));
        // The caller receives result's original failure. Only the internal
        // tail settles successfully so subsequent operations can continue.
        final settled = result.then<void>(
          (_) {},
          onError: (Object error, StackTrace stack) {},
        );
        _fileTails[queueKey] = settled;
        unawaited(
          settled.then((_) {
            if (identical(_fileTails[queueKey], settled)) {
              _fileTails.remove(queueKey);
            }
          }),
        );
      } finally {
        admitted.complete();
        if (identical(_admissions[name], admitted.future)) {
          _admissions.remove(name);
        }
      }
      return result;
    }

    return schedule();
  }

  /// 原子写入：先写 `.tmp` 并 flush，再 rename 覆盖正式件；任何失败都抛给调用方，
  /// 由界面持续警告——半截内容永远不会成为正式信封。
  Future<void> save(DraftEnvelope envelope) async {
    // Encoding before the first await also snapshots nested mutable payloads
    // and the full command list; queued writes never inspect the live envelope.
    final contents = const JsonEncoder.withIndent(
      '  ',
    ).convert(envelope.toJson());
    return _enqueue(envelope.workspaceKey, (file) async {
      final tmp = File('${file.path}.tmp');
      await fileAccess.write(tmp, contents);
      await fileAccess.rename(tmp, file.path);
    });
  }

  /// 空草稿即删除文件；删不掉也不影响内存编辑。
  Future<void> clear(String workspaceKey) =>
      _enqueue(workspaceKey, (file) async {
        if (fileAccess.exists(file)) await fileAccess.delete(file);
      });

  Future<DraftLoad> load({
    required String workspaceKey,
    required String baseline,
  }) => _enqueue(
    workspaceKey,
    (file) => _loadFile(file, workspaceKey: workspaceKey, baseline: baseline),
    // 保持既有目录失败反馈，调用方据此显示「未持久化」警告。
    onDirectoryError: (e) => DraftLoad(DraftOutcome.none, reason: '草稿目录不可用：$e'),
  );

  Future<DraftLoad> _loadFile(
    File file, {
    required String workspaceKey,
    required String baseline,
  }) async {
    // 进入队列后才清理遗留临时件，不会误删正在写入的 `.tmp`。
    // 正式信封永远不读临时件，清理时仍如实报告。
    final tmp = File('${file.path}.tmp');
    final leftover = fileAccess.exists(tmp);
    if (leftover) {
      try {
        await fileAccess.delete(tmp);
      } on FileSystemException {
        // 清不掉也不影响读取，交给下一次保存覆盖
      }
    }
    if (!fileAccess.exists(file)) {
      return DraftLoad(
        DraftOutcome.none,
        path: file.path,
        leftoverTemp: leftover,
      );
    }
    Map<String, Object?> json;
    try {
      json = jsonDecode(await fileAccess.read(file))! as Map<String, Object?>;
    } on Object catch (e) {
      return DraftLoad(
        DraftOutcome.damaged,
        reason: '$e',
        path: file.path,
        leftoverTemp: leftover,
      );
    }
    final DraftEnvelope envelope;
    try {
      envelope = DraftEnvelope.fromJson(json);
    } on DraftFormatException catch (e) {
      return DraftLoad(
        DraftOutcome.damaged,
        reason: e.reason,
        path: file.path,
        leftoverTemp: leftover,
      );
    }
    if (envelope.workspaceKey != workspaceKey) {
      return DraftLoad(
        DraftOutcome.damaged,
        reason: '草稿归属的工作区与文件名不一致',
        path: file.path,
        leftoverTemp: leftover,
      );
    }
    if (envelope.baseline != baseline) {
      return DraftLoad(
        DraftOutcome.conflict,
        envelope: envelope,
        reason: '基线已变（草稿 ${envelope.baseline}，当前 $baseline）',
        path: file.path,
        leftoverTemp: leftover,
      );
    }
    return DraftLoad(
      DraftOutcome.restored,
      envelope: envelope,
      path: file.path,
      leftoverTemp: leftover,
    );
  }

  /// 不可靠的草稿保留供查看：改名留档，不静默清空。
  Future<String?> preserve(String workspaceKey) =>
      _enqueue(workspaceKey, (file) async {
        if (!fileAccess.exists(file)) return null;
        final kept =
            '${file.path}.damaged-${DateTime.now().millisecondsSinceEpoch}';
        await fileAccess.rename(file, kept);
        return kept;
      });
}
