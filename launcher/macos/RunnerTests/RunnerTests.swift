import Cocoa
import FlutterMacOS
import XCTest
@testable import ct_launcher

private class RecordingController: NSViewController {
  var events: [NSEvent.EventType] = []
  override func loadView() { view = NSView(frame: NSRect(x: 0, y: 0, width: 800, height: 600)) }
  override func mouseDown(with event: NSEvent) { events.append(event.type) }
  override func mouseDragged(with event: NSEvent) { events.append(event.type) }
  override func mouseUp(with event: NSEvent) { events.append(event.type) }
}

private class RecordingWindow: MainFlutterWindow {
  var zoomRequests = 0
  override func zoom(_ sender: Any?) { zoomRequests += 1 }
}

class RunnerTests: XCTestCase {
  func testTitlebarButtonMouseSequencesBypassAppKitZoom() {
    let window = RecordingWindow(
      contentRect: NSRect(x: 0, y: 0, width: 800, height: 600),
      styleMask: [.titled, .resizable, .fullSizeContentView], backing: .buffered, defer: false
    )
    window.titleVisibility = .hidden
    window.titlebarAppearsTransparent = true
    window.toolbar = NSToolbar(identifier: "TestToolbar")
    window.toolbarStyle = .unifiedCompact
    let target = RecordingController()
    window.contentViewController = target
    window.titlebarEventTarget = target
    window.titlebarControlBounds["sidebar"] = NSRect(x: 92, y: 0, width: 32, height: 40)

    func send(_ type: NSEvent.EventType, _ count: Int, _ timestamp: TimeInterval,
              x: CGFloat = 108, y: CGFloat = 20) {
      let point = target.view.convert(NSPoint(x: x, y: target.view.bounds.maxY - y), to: nil)
      window.sendEvent(NSEvent.mouseEvent(
        with: type, location: point, modifierFlags: [], timestamp: timestamp,
        windowNumber: window.windowNumber, context: nil, eventNumber: 1,
        clickCount: count, pressure: 0
      )!)
    }
    let initialFrame = window.frame
    // Both clickCount values and the slower 240ms interval must be forwarded.
    for (count, time) in [(1, 1.0), (2, 1.04), (1, 2.0), (2, 2.24)] {
      send(.leftMouseDown, count, time)
      send(.leftMouseUp, count, time + 0.01)
    }
    XCTAssertEqual(target.events, Array(repeating: [.leftMouseDown, .leftMouseUp], count: 4).flatMap { $0 })
    XCTAssertEqual(window.zoomRequests, 0)
    XCTAssertEqual(window.frame, initialFrame)

    // Moving outside while held remains the same Flutter pointer sequence,
    // even if layout removes the registered rectangle before mouseUp.
    send(.leftMouseDown, 1, 3)
    window.titlebarControlBounds.removeAll()
    send(.leftMouseDragged, 1, 3.1, x: 470, y: 80)
    send(.leftMouseUp, 1, 3.2, x: 470, y: 80)
    XCTAssertEqual(Array(target.events.suffix(3)), [.leftMouseDown, .leftMouseDragged, .leftMouseUp])
    XCTAssertEqual(window.zoomRequests, 0)
  }
}
