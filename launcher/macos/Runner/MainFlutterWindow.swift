import Cocoa
import FlutterMacOS
import LaunchAtLogin
import macos_window_utils

class MainFlutterWindow: NSWindow {
  // Bounds are supplied by Flutter layout, in logical pixels from its top-left.
  var titlebarControlBounds: [String: NSRect] = [:]
  var titlebarEventTarget: NSViewController?
  private var forwardingTitlebarMouseSequence = false

  // Route before NSWindow interprets a titlebar click. Forward the entire mouse
  // sequence, including the second down/up, directly to Flutter. No zoom veto
  // or native accessory hit-test overlay is needed.
  override func sendEvent(_ event: NSEvent) {
    guard let target = titlebarEventTarget, event.window === self else {
      super.sendEvent(event)
      return
    }
    switch event.type {
    case .leftMouseDown:
      forwardingTitlebarMouseSequence = false
      let viewPoint = target.view.convert(event.locationInWindow, from: nil)
      let flutterPoint = NSPoint(
        x: viewPoint.x - target.view.bounds.minX,
        y: target.view.isFlipped
          ? viewPoint.y - target.view.bounds.minY
          : target.view.bounds.maxY - viewPoint.y
      )
      let onWindowButton = [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton]
        .compactMap { standardWindowButton($0) }
        .contains { !$0.isHidden && $0.bounds.contains($0.convert(event.locationInWindow, from: nil)) }
      if !onWindowButton && titlebarControlBounds.values.contains(where: { $0.contains(flutterPoint) }) {
        forwardingTitlebarMouseSequence = true
        if !isKeyWindow { makeKey() }
        target.mouseDown(with: event)
        return
      }
    case .leftMouseDragged:
      if forwardingTitlebarMouseSequence {
        target.mouseDragged(with: event)
        return
      }
    case .leftMouseUp:
      if forwardingTitlebarMouseSequence {
        forwardingTitlebarMouseSequence = false
        target.mouseUp(with: event)
        return
      }
    default:
      break
    }
    super.sendEvent(event)
  }

  override func awakeFromNib() {
    // macos_window_utils 接入（部署目标 Monterey，按包文档要求在原生侧
    // 包装 contentViewController 并显式交出窗口引用；Dart 侧 initialize()
    // 因此只做 reset 复用，不会重设默认样式或误抓其他窗口）。
    let macOSWindowUtilsViewController = MacOSWindowUtilsViewController()
    let flutterViewController = macOSWindowUtilsViewController.flutterViewController
    let windowFrame = self.frame
    self.contentViewController = macOSWindowUtilsViewController
    self.titlebarEventTarget = flutterViewController
    FlutterMethodChannel(
      name: "ct/titlebar_controls",
      binaryMessenger: flutterViewController.engine.binaryMessenger
    ).setMethodCallHandler { [weak self] call, result in
      #if DEBUG
      // Integration tests exercise the real FlutterViewController via NSEvent;
      // this entry point is absent from the Release application.
      if call.method == "testMouseClick", let self = self,
         let args = call.arguments as? [String: Any],
         let x = args["x"] as? Double, let y = args["y"] as? Double,
         let count = args["count"] as? Int, let target = self.titlebarEventTarget {
        let localPoint = NSPoint(
          x: target.view.bounds.minX + x,
          y: target.view.isFlipped ? target.view.bounds.minY + y : target.view.bounds.maxY - y
        )
        let point = target.view.convert(localPoint, to: nil)
        for type in [NSEvent.EventType.leftMouseDown, .leftMouseUp] {
          let event = NSEvent.mouseEvent(
            with: type, location: point, modifierFlags: [],
            timestamp: ProcessInfo.processInfo.systemUptime,
            windowNumber: self.windowNumber, context: nil, eventNumber: 1,
            clickCount: count, pressure: 0
          )!
          self.sendEvent(event)
        }
        result(nil)
        return
      }
      #endif
      guard let self = self, let arguments = call.arguments as? [String: Any],
            let id = arguments["id"] as? String else {
        result(FlutterError(code: "invalidBounds", message: "Missing control id", details: nil))
        return
      }
      switch call.method {
      case "update":
        guard let x = arguments["x"] as? Double, let y = arguments["y"] as? Double,
              let width = arguments["width"] as? Double, let height = arguments["height"] as? Double else {
          result(FlutterError(code: "invalidBounds", message: "Missing control bounds", details: nil))
          return
        }
        self.titlebarControlBounds[id] = NSRect(x: x, y: y, width: width, height: height)
        result(nil)
      case "remove":
        self.titlebarControlBounds.removeValue(forKey: id)
        result(nil)
      default:
        result(FlutterMethodNotImplemented)
      }
    }
    self.setFrame(windowFrame, display: true)
    MainFlutterWindowManipulator.start(mainFlutterWindow: self)
    // 空工具栏默认自画基线；顶栏底线由 Flutter 自绘，关掉原生分隔线避免双线。
    self.titlebarSeparatorStyle = .none

    // 开机自启通道（对齐 FlClash：LaunchAtLogin / SMAppService 系统登录项）
    FlutterMethodChannel(
      name: "launch_at_startup",
      binaryMessenger: flutterViewController.engine.binaryMessenger
    )
    .setMethodCallHandler { (call: FlutterMethodCall, result: @escaping FlutterResult) in
      switch call.method {
      case "launchAtStartupIsEnabled":
        result(LaunchAtLogin.isEnabled)
      case "launchAtStartupSetEnabled":
        if let arguments = call.arguments as? [String: Any] {
          LaunchAtLogin.isEnabled = arguments["setEnabledValue"] as! Bool
        }
        result(nil)
      default:
        result(FlutterMethodNotImplemented)
      }
    }

    // 空工具栏与 unifiedCompact 样式改由 macos_window_utils 在 Dart 侧配置
    //（见 main.dart：window_manager 应用 hidden 标题栏之后再 addToolbar）。

    RegisterGeneratedPlugins(registry: flutterViewController)

    super.awakeFromNib()
  }

  // 对齐 FlClash：启动时先藏窗口，等 Dart 就绪后再显示，
  // 避免 debug 启动时的黑屏与窗体大小变化瞬间。
  override public func order(_ place: NSWindow.OrderingMode, relativeTo otherWin: Int) {
    super.order(place, relativeTo: otherWin)
    hiddenWindowAtLaunch()
  }
}
