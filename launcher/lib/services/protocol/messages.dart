/// stdio worker 协议 v1 消息信封（与 native/crates/ct-protocol 同源）。
///
/// 语义权威文档：native/docs/protocol/v1.md；
/// golden samples：native/docs/protocol/examples/*.ndjson。
library;

/// 消息类型标签（线格式 `type` 字段）。
enum MessageType { hello, request, progress, log, issue, result, error }

/// 信封消息基类。
sealed class Message {
  const Message();

  factory Message.fromJson(Map<String, Object?> json) {
    final type = json['type'];
    return switch (type) {
      'hello' => Hello.fromJson(json),
      'request' => Request.fromJson(json),
      'progress' => ProgressEvent.fromJson(json),
      'log' => LogEvent.fromJson(json),
      'issue' => IssueEvent.fromJson(json),
      'result' => ResultMessage.fromJson(json),
      'error' => ErrorMessage.fromJson(json),
      _ => throw FormatException('未知消息类型: $type'),
    };
  }

  Map<String, Object?> toJson();
}

/// 握手消息：连接建立后双向各一条，先客户端后 worker。
final class Hello extends Message {
  const Hello({
    required this.protocolVersion,
    required this.coreVersion,
    required this.capabilities,
  });

  factory Hello.fromJson(Map<String, Object?> json) => Hello(
    protocolVersion: json['protocolVersion']! as int,
    coreVersion: json['coreVersion']! as String,
    capabilities: (json['capabilities']! as List).cast<String>(),
  );

  final int protocolVersion;
  final String coreVersion;
  final List<String> capabilities;

  @override
  Map<String, Object?> toJson() => {
    'type': 'hello',
    'protocolVersion': protocolVersion,
    'coreVersion': coreVersion,
    'capabilities': capabilities,
  };
}

/// 客户端请求。requestId 连接内唯一；重复会被 worker 拒绝。
final class Request extends Message {
  const Request({
    required this.requestId,
    required this.method,
    required this.workspaceRoot,
    this.params = const {},
  });

  factory Request.fromJson(Map<String, Object?> json) => Request(
    requestId: json['requestId']! as int,
    method: json['method']! as String,
    workspaceRoot: json['workspaceRoot']! as String,
    params: (json['params'] as Map<String, Object?>?) ?? const {},
  );

  final int requestId;
  final String method;
  final String workspaceRoot;
  final Map<String, Object?> params;

  @override
  Map<String, Object?> toJson() => {
    'type': 'request',
    'requestId': requestId,
    'method': method,
    'workspaceRoot': workspaceRoot,
    'params': params,
  };
}

/// 阶段进度事件（可合并）。
final class ProgressEvent extends Message {
  const ProgressEvent({
    required this.requestId,
    required this.workspaceId,
    required this.seq,
    required this.stage,
    required this.done,
    required this.total,
  });

  factory ProgressEvent.fromJson(Map<String, Object?> json) => ProgressEvent(
    requestId: json['requestId']! as int,
    workspaceId: json['workspaceId']! as String,
    seq: json['seq']! as int,
    stage: json['stage']! as String,
    done: json['done']! as int,
    total: json['total']! as int,
  );

  final int requestId;
  final String workspaceId;
  final int seq;
  final String stage;
  final int done;
  final int total;

  @override
  Map<String, Object?> toJson() => {
    'type': 'progress',
    'requestId': requestId,
    'workspaceId': workspaceId,
    'seq': seq,
    'stage': stage,
    'done': done,
    'total': total,
  };
}

/// 实时日志事件（历史查询走 logs.list）。
final class LogEvent extends Message {
  const LogEvent({
    required this.requestId,
    required this.workspaceId,
    required this.seq,
    required this.module,
    required this.level,
    required this.message,
  });

  factory LogEvent.fromJson(Map<String, Object?> json) => LogEvent(
    requestId: json['requestId']! as int,
    workspaceId: json['workspaceId']! as String,
    seq: json['seq']! as int,
    module: json['module']! as String,
    level: json['level']! as String,
    message: json['message']! as String,
  );

  final int requestId;
  final String workspaceId;
  final int seq;
  final String module;
  final String level;
  final String message;

  @override
  Map<String, Object?> toJson() => {
    'type': 'log',
    'requestId': requestId,
    'workspaceId': workspaceId,
    'seq': seq,
    'module': module,
    'level': level,
    'message': message,
  };
}

/// 结构化问题事件。
final class IssueEvent extends Message {
  const IssueEvent({
    required this.requestId,
    required this.workspaceId,
    required this.seq,
    required this.issue,
  });

  factory IssueEvent.fromJson(Map<String, Object?> json) => IssueEvent(
    requestId: json['requestId']! as int,
    workspaceId: json['workspaceId']! as String,
    seq: json['seq']! as int,
    issue: Issue.fromJson(json['issue']! as Map<String, Object?>),
  );

  final int requestId;
  final String workspaceId;
  final int seq;
  final Issue issue;

  @override
  Map<String, Object?> toJson() => {
    'type': 'issue',
    'requestId': requestId,
    'workspaceId': workspaceId,
    'seq': seq,
    'issue': issue.toJson(),
  };
}

/// 成功终态；任务取消以 payload.outcome == 'cancelled' 表示。
final class ResultMessage extends Message {
  const ResultMessage({
    required this.requestId,
    required this.workspaceId,
    required this.seq,
    required this.payload,
  });

  factory ResultMessage.fromJson(Map<String, Object?> json) => ResultMessage(
    requestId: json['requestId']! as int,
    workspaceId: json['workspaceId']! as String,
    seq: json['seq']! as int,
    payload: json['payload'],
  );

  final int requestId;
  final String workspaceId;
  final int seq;
  final Object? payload;

  @override
  Map<String, Object?> toJson() => {
    'type': 'result',
    'requestId': requestId,
    'workspaceId': workspaceId,
    'seq': seq,
    'payload': payload,
  };
}

/// 失败终态 / 连接级错误。
///
/// 仅当入站消息无法解析出 requestId 时 requestId/workspaceId/seq 为 null。
final class ErrorMessage extends Message {
  const ErrorMessage({
    this.requestId,
    this.workspaceId,
    this.seq,
    required this.error,
  });

  factory ErrorMessage.fromJson(Map<String, Object?> json) => ErrorMessage(
    requestId: json['requestId'] as int?,
    workspaceId: json['workspaceId'] as String?,
    seq: json['seq'] as int?,
    error: ErrorBody.fromJson(json['error']! as Map<String, Object?>),
  );

  final int? requestId;
  final String? workspaceId;
  final int? seq;
  final ErrorBody error;

  @override
  Map<String, Object?> toJson() => {
    'type': 'error',
    if (requestId != null) 'requestId': requestId,
    if (workspaceId != null) 'workspaceId': workspaceId,
    if (seq != null) 'seq': seq,
    'error': error.toJson(),
  };
}

/// 结构化错误载体；code 见 [ProtocolErrorCodes]。
///
/// [issues] 是业务失败定位明细（无明细时线格式省略该键）。
final class ErrorBody {
  const ErrorBody({
    required this.code,
    required this.message,
    this.issues = const [],
  });

  factory ErrorBody.fromJson(Map<String, Object?> json) => ErrorBody(
    code: json['code']! as String,
    message: json['message']! as String,
    issues: ((json['issues'] as List?) ?? const [])
        .map((e) => Issue.fromJson(e! as Map<String, Object?>))
        .toList(),
  );

  final String code;
  final String message;
  final List<Issue> issues;

  Map<String, Object?> toJson() => {
    'code': code,
    'message': message,
    if (issues.isNotEmpty) 'issues': issues.map((e) => e.toJson()).toList(),
  };
}

/// 结构化问题定位：据此跳转资源/字段/Excel 行，不解析人类日志。
final class Issue {
  const Issue({
    required this.code,
    required this.message,
    this.resource,
    this.fieldPath,
    this.excelRow,
    this.file,
  });

  factory Issue.fromJson(Map<String, Object?> json) => Issue(
    code: json['code']! as String,
    message: json['message']! as String,
    resource: json['resource'] as String?,
    fieldPath: json['fieldPath'] as String?,
    excelRow: json['excelRow'] as int?,
    file: json['file'] as String?,
  );

  final String code;
  final String message;
  final String? resource;
  final String? fieldPath;

  /// 原始 Excel 行号；非 Excel 来源缺省。
  final int? excelRow;
  final String? file;

  Map<String, Object?> toJson() => {
    'code': code,
    'message': message,
    if (resource != null) 'resource': resource,
    if (fieldPath != null) 'fieldPath': fieldPath,
    if (excelRow != null) 'excelRow': excelRow,
    if (file != null) 'file': file,
  };
}

/// 协议级错误码（与 ct_protocol::error::ErrorCode 一致）。
abstract final class ProtocolErrorCodes {
  static const protocolMismatch = 'protocol-mismatch';
  static const malformedMessage = 'malformed-message';
  static const messageTooLarge = 'message-too-large';
  static const unknownMethod = 'unknown-method';
  static const duplicateRequestId = 'duplicate-request-id';
  static const stalePage = 'stale-page';
  static const busy = 'busy';
  static const recoveryNeeded = 'recovery-needed';
  static const internal = 'internal';
}
