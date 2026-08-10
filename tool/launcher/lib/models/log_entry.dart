enum LogLevel { info, warn, error }

class LogEntry {
  LogEntry(this.level, this.message) : time = DateTime.now();

  final DateTime time;
  final LogLevel level;
  final String message;

  String get timestamp {
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(time.hour)}:${two(time.minute)}:${two(time.second)}';
  }
}
