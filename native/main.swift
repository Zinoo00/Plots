// Plots — the Mac app for Plots, progress tracking for Claude Code projects.
//
// The window chrome is the Mac's own: an NSSplitViewController sidebar with a workspace switcher at the top, the
// views and the fix batches (SwiftUI); a unified NSToolbar (≡ and ✦ over the sidebar, appearance, search, Export)
// and the menus. On macOS 26 AppKit draws these in Liquid Glass with a floating sidebar; on macOS 27 the same code
// gets the edge-to-edge sidebar, the uniform toolbar and the new window corners without a rebuild.
// The dashboard is the engine's own page, served by `plots serve` on 127.0.0.1:4317 (started here if needed,
// from the engine inside this app), so it always shows what the `plots` CLI writes.
// Chat is where the sidebar is, like Xcode's coding assistant: ✦ swaps the views for the Chat
// panel, the same page with ?panel=chat in a second web view, and ≡ swaps them back; the page stays beside it and
// tells the panel what it shows, which goes with a message. With notes=project the workspace's Claude project
// answers (its coordinator, or a thread it hands the message to); otherwise a fork of the Claude Code session
// that works on the workspace does (see plots.py). Build with native/build.sh.

import Cocoa
import SwiftUI
import WebKit

let port = Int(ProcessInfo.processInfo.environment["PLOTS_PORT"] ?? "") ?? 4317
let baseURL = URL(string: "http://127.0.0.1:\(port)/")!
// `Plots --selftest <folder>`: loads the page, writes a report and a snapshot of the page, quits
let selftestDir: URL? = {
    let a = CommandLine.arguments
    if let i = a.firstIndex(of: "--selftest"), i + 1 < a.count { return URL(fileURLWithPath: a[i + 1]) }
    return nil
}()
// `--appearance light|dark|auto` (self-test only): use this appearance without saving it
let selftestAppearance: String? = {
    let a = CommandLine.arguments
    if let i = a.firstIndex(of: "--appearance"), i + 1 < a.count { return a[i + 1] }
    return nil
}()

// a small log for troubleshooting: ~/Library/Logs/Plots.log
func log(_ msg: String) {
    let url = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Plots.log")
    let line = "\(ISO8601DateFormatter().string(from: Date())) \(selftestDir == nil ? "" : "[selftest] ")\(msg)\n"
    if let h = try? FileHandle(forWritingTo: url) { h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); try? h.close() }
    else { try? line.data(using: .utf8)!.write(to: url) }
}

// The engine (plots.py and the page): the source folder the app was built from while it is there, so an update
// to the engine or the page needs no rebuild (the server restarts itself when plots.py changes, and a rebuilt
// app is a new app to macOS, which asks again for folders it had allowed); otherwise the copy inside the app.
func engineDir() -> URL? {
    let fm = FileManager.default
    if let p = Bundle.main.object(forInfoDictionaryKey: "PlotsSource") as? String,
       fm.fileExists(atPath: (p as NSString).appendingPathComponent("plots.py")),
       fm.fileExists(atPath: (p as NSString).appendingPathComponent("app/index.html")) { return URL(fileURLWithPath: p) }
    if let r = Bundle.main.resourceURL?.appendingPathComponent("engine"),
       fm.fileExists(atPath: r.appendingPathComponent("plots.py").path) { return r }
    return nil
}

func jsString(_ s: String) -> String {
    let data = try? JSONSerialization.data(withJSONObject: [s])
    let arr = data.flatMap { String(data: $0, encoding: .utf8) } ?? "[\"\"]"
    return String(arr.dropFirst().dropLast())
}

// The page's window colour, so the area under the floating sidebar and the toolbar matches it in both appearances.
let pageLight = NSColor(srgbRed: 0xF4 / 255.0, green: 0xF4 / 255.0, blue: 0xF4 / 255.0, alpha: 1)
let pageDark = NSColor(srgbRed: 0x1E / 255.0, green: 0x1E / 255.0, blue: 0x1E / 255.0, alpha: 1)

let wsPalette: [String: Color] = [
    "blue": Color(red: 0.04, green: 0.52, blue: 1.0), "green": Color(red: 0.19, green: 0.78, blue: 0.35),
    "orange": Color(red: 1.0, green: 0.62, blue: 0.04), "purple": Color(red: 0.69, green: 0.32, blue: 0.87),
    "pink": Color(red: 1.0, green: 0.22, blue: 0.37), "teal": Color(red: 0.19, green: 0.69, blue: 0.78),
    "indigo": Color(red: 0.37, green: 0.36, blue: 0.90), "red": Color(red: 1.0, green: 0.27, blue: 0.23),
    "yellow": Color(red: 0.90, green: 0.72, blue: 0.0), "gray": Color(red: 0.56, green: 0.56, blue: 0.58),
]

// MARK: - What the page reports for the sidebar and the toolbar

struct BatchInfo: Identifiable, Equatable {
    let id: String
    let done: Int
    let total: Int
    let flight: Int
}

struct WorkspaceInfo: Identifiable, Equatable {
    let id: String
    let name: String
    let color: String
    let initials: String
    let done: Int
    let total: Int

    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? ""
        name = d["name"] as? String ?? "Workspace"
        color = d["color"] as? String ?? "blue"
        initials = d["initials"] as? String ?? "·"
        done = d["done"] as? Int ?? 0
        total = d["total"] as? Int ?? 0
    }
}

@MainActor
final class Chrome: ObservableObject {
    @Published var view = "overview"
    @Published var batch = "All"
    @Published var screens = 0
    @Published var waiting = 0
    @Published var batches: [BatchInfo] = []
    @Published var ws: WorkspaceInfo?
    @Published var workspaces: [WorkspaceInfo] = []
    var selectView: @MainActor (String) -> Void = { _ in }
    var selectBatch: @MainActor (String) -> Void = { _ in }
    var workspaceMenu: @MainActor (NSView) -> Void = { _ in }
    var search: @MainActor () -> Void = {}
}

// MARK: - Sidebar (SwiftUI in an NSSplitViewController sidebar item)

struct WorkspaceBadge: View {
    let ws: WorkspaceInfo
    var size: CGFloat = 28
    var body: some View {
        let c = wsPalette[ws.color] ?? .blue
        RoundedRectangle(cornerRadius: size * 0.29, style: .continuous)
            .fill(LinearGradient(colors: [c.mix(with: .white, by: 0.18), c], startPoint: .top, endPoint: .bottom))
            .overlay(Text(ws.initials).font(.system(size: size * 0.41, weight: .semibold)).foregroundStyle(.white))
            .overlay(RoundedRectangle(cornerRadius: size * 0.29, style: .continuous).strokeBorder(.black.opacity(0.1), lineWidth: 0.5))
            .frame(width: size, height: size)
    }
}

// An NSView to anchor an AppKit menu to a SwiftUI button.
final class AnchorBox { weak var view: NSView? }
struct MenuAnchor: NSViewRepresentable {
    let box: AnchorBox
    func makeNSView(context: Context) -> NSView { let v = NSView(); box.view = v; return v }
    func updateNSView(_ nsView: NSView, context: Context) { box.view = nsView }
}

struct WorkspaceSwitcher: View {
    @ObservedObject var chrome: Chrome
    @State private var hover = false
    private let anchor = AnchorBox()

    var body: some View {
        Button { if let v = anchor.view { chrome.workspaceMenu(v) } } label: {
            HStack(spacing: 9) {
                if let ws = chrome.ws { WorkspaceBadge(ws: ws) } else { WorkspaceBadge(ws: WorkspaceInfo(["initials": "·"])) }
                VStack(alignment: .leading, spacing: 1) {
                    Text(chrome.ws?.name ?? "Plots").font(.system(size: 13, weight: .semibold)).lineLimit(1)
                    Text(chrome.ws.map { $0.total > 0 ? "\($0.done) of \($0.total) done" : "Nothing tracked yet" } ?? " ")
                        .font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1).monospacedDigit()
                }
                Spacer(minLength: 4)
                Image(systemName: "chevron.up.chevron.down").font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            }
            .padding(.horizontal, 7).padding(.vertical, 6)
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.primary.opacity(hover ? 0.07 : 0)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .background(MenuAnchor(box: anchor))
        .onHover { hover = $0 }
        .help("Switch workspace")
        .accessibilityLabel("Workspace: \(chrome.ws?.name ?? "none")")
    }
}

struct Ring: View {
    let done: Int
    let flight: Int
    let total: Int
    var body: some View {
        let d = total > 0 ? Double(done) / Double(total) : 0
        let f = total > 0 ? Double(flight) / Double(total) : 0
        ZStack {
            Circle().stroke(Color.primary.opacity(0.14), lineWidth: 2.4)
            if f > 0 { Circle().trim(from: d, to: min(1, d + f)).stroke(Color.blue, lineWidth: 2.4) }
            if d > 0 { Circle().trim(from: 0, to: d).stroke(Color.green, lineWidth: 2.4) }
        }
        .rotationEffect(.degrees(-90))
        .frame(width: 14, height: 14)
    }
}

// A sidebar row drawn by us: the selection is a neutral tint, not the accent colour, and the icons stay gray.
struct NavRow<Trailing: View>: View {
    let title: String
    let icon: String
    let selected: Bool
    let action: () -> Void
    @ViewBuilder var trailing: () -> Trailing
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .font(.system(size: 13))
                    .foregroundStyle(selected ? Color.primary : Color.secondary)
                    .frame(width: 18)
                Text(title).lineLimit(1)
                Spacer(minLength: 4)
                trailing()
            }
            .padding(.horizontal, 6)
            .frame(minHeight: 26)
            .background(
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(Color.primary.opacity(selected ? 0.09 : hover ? 0.05 : 0))
            )
            .padding(.horizontal, -6)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .selectionDisabled()
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

struct SidebarView: View {
    @ObservedObject var chrome: Chrome

    var body: some View {
        List {
            Section {
                NavRow(title: "Overview", icon: "house", selected: chrome.view == "overview",
                       action: { chrome.selectView("overview") }) { EmptyView() }
                NavRow(title: "Screens", icon: "rectangle.split.3x1", selected: chrome.view == "screens",
                       action: { chrome.selectView("screens") }) {
                    Text("\(chrome.screens)").font(.system(size: 12)).monospacedDigit().foregroundStyle(.secondary)
                }
                NavRow(title: "Decisions", icon: "checkmark.bubble", selected: chrome.view == "decisions",
                       action: { chrome.selectView("decisions") }) {
                    if chrome.waiting > 0 {
                        Text("\(chrome.waiting)")
                            .font(.system(size: 11, weight: .bold)).monospacedDigit()
                            .foregroundStyle(Color(white: 0.11))
                            .padding(.horizontal, 6).frame(minWidth: 18, minHeight: 18)
                            .background(Capsule().fill(Color.orange))
                            .help("\(chrome.waiting) waiting on you")
                    }
                }
                NavRow(title: "Activity", icon: "clock", selected: chrome.view == "activity",
                       action: { chrome.selectView("activity") }) { EmptyView() }
            }

            if !chrome.batches.isEmpty {
                Section("Fix Batches") {
                    ForEach(chrome.batches) { b in
                        BatchRow(b: b, selected: chrome.batch == b.id) { chrome.selectBatch(b.id) }
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .top, spacing: 0) {
            WorkspaceSwitcher(chrome: chrome).padding(.horizontal, 10).padding(.top, 2).padding(.bottom, 4)
        }
    }
}

struct BatchRow: View {
    let b: BatchInfo
    let selected: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Ring(done: b.done, flight: b.flight, total: b.total)
                Text(b.id == "All" ? "All batches" : b.id).lineLimit(1)
                Spacer(minLength: 4)
                Text(b.total > 0 ? "\(b.done)/\(b.total)" : "Out of scope")
                    .font(.system(size: b.total > 0 ? 12 : 11)).monospacedDigit()
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 6)
            .frame(minHeight: 26)
            .background(
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(Color.primary.opacity(selected ? 0.09 : hover ? 0.05 : 0))
            )
            .padding(.horizontal, -6)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .selectionDisabled()
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

// MARK: - The page

final class ContentController: NSViewController {
    let web: WKWebView

    init(web: WKWebView) { self.web = web; super.init(nibName: nil, bundle: nil) }
    required init?(coder: NSCoder) { fatalError("not used") }

    override func loadView() {
        let v = NSView()
        web.translatesAutoresizingMaskIntoConstraints = false
        v.addSubview(web)
        NSLayoutConstraint.activate([
            web.leadingAnchor.constraint(equalTo: v.leadingAnchor),
            web.trailingAnchor.constraint(equalTo: v.trailingAnchor),
            web.topAnchor.constraint(equalTo: v.topAnchor),
            web.bottomAnchor.constraint(equalTo: v.bottomAnchor),
        ])
        view = v
    }
}

// The sidebar: the views and batches (SwiftUI), or the Chat panel (the page with ?panel=chat, transparent over
// the sidebar's glass), like Xcode's navigators and its coding assistant. ≡ and ✦ in the toolbar swap them.
final class SidebarController: NSViewController {
    let list: NSViewController
    let chat: WKWebView

    init(list: NSViewController, chat: WKWebView) {
        self.list = list
        self.chat = chat
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError("not used") }

    override func loadView() {
        let v = NSView()
        addChild(list)
        let lv = list.view
        lv.translatesAutoresizingMaskIntoConstraints = false
        chat.translatesAutoresizingMaskIntoConstraints = false
        v.addSubview(lv)
        v.addSubview(chat)
        NSLayoutConstraint.activate([
            lv.leadingAnchor.constraint(equalTo: v.leadingAnchor),
            lv.trailingAnchor.constraint(equalTo: v.trailingAnchor),
            lv.topAnchor.constraint(equalTo: v.topAnchor),
            lv.bottomAnchor.constraint(equalTo: v.bottomAnchor),
            // the panel starts under the toolbar; the list handles that itself
            chat.leadingAnchor.constraint(equalTo: v.leadingAnchor),
            chat.trailingAnchor.constraint(equalTo: v.trailingAnchor),
            chat.topAnchor.constraint(equalTo: v.safeAreaLayoutGuide.topAnchor),
            chat.bottomAnchor.constraint(equalTo: v.bottomAnchor),
        ])
        chat.isHidden = true
        view = v
    }

    var showsChat: Bool { isViewLoaded && !chat.isHidden }
    func show(chat on: Bool) {
        _ = view
        list.view.isHidden = on
        chat.isHidden = !on
    }
}

// ✦ for Chat: three lines and a four-pointed star (the page's "assist" icon), as a template image
func chatSymbol() -> NSImage {
    let img = NSImage(size: NSSize(width: 19, height: 14), flipped: true) { _ in
        let t = NSAffineTransform()
        t.translateX(by: -2.4, yBy: -4.6)
        t.concat()
        NSColor.black.set()
        let lines = NSBezierPath()
        lines.lineWidth = 1.6
        lines.lineCapStyle = .round
        for (y, len) in [(7.5, 5.0), (12.0, 4.0), (16.5, 5.0)] as [(CGFloat, CGFloat)] {
            lines.move(to: NSPoint(x: 3.5, y: y))
            lines.line(to: NSPoint(x: 3.5 + len, y: y))
        }
        lines.stroke()
        let star = NSBezierPath()
        star.move(to: NSPoint(x: 15.5, y: 5.5))
        star.curve(to: NSPoint(x: 20.7, y: 10.8), controlPoint1: NSPoint(x: 16.0, y: 8.8), controlPoint2: NSPoint(x: 17.5, y: 10.3))
        star.curve(to: NSPoint(x: 15.5, y: 16.1), controlPoint1: NSPoint(x: 17.5, y: 11.3), controlPoint2: NSPoint(x: 16.0, y: 12.8))
        star.curve(to: NSPoint(x: 10.3, y: 10.8), controlPoint1: NSPoint(x: 15.0, y: 12.8), controlPoint2: NSPoint(x: 13.5, y: 11.3))
        star.curve(to: NSPoint(x: 15.5, y: 5.5), controlPoint1: NSPoint(x: 13.5, y: 10.3), controlPoint2: NSPoint(x: 15.0, y: 8.8))
        star.close()
        star.fill()
        star.lineWidth = 0.8
        star.lineJoinStyle = .round
        star.stroke()
        return true
    }
    img.isTemplate = true
    img.accessibilityDescription = "Chat"
    return img
}

// Messages from the page and from the chat panel (window.webkit.messageHandlers.plots)
final class Bridge: NSObject, WKScriptMessageHandler {
    var handle: (([String: Any]) -> Void)?
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        if let body = message.body as? [String: Any] { handle?(body) }
    }
}

// MARK: - App

extension NSToolbarItem.Identifier {
    static let sidebarMode = NSToolbarItem.Identifier("plots.sidebarMode")     // ≡ views and batches · ✦ Chat
    static let appearance = NSToolbarItem.Identifier("plots.appearance")
    static let search = NSToolbarItem.Identifier("plots.search")
    static let export = NSToolbarItem.Identifier("plots.export")
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSToolbarDelegate, NSSearchFieldDelegate,
                         WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var split: NSSplitViewController!
    var content: ContentController!
    var web: WKWebView!
    let chrome = Chrome()
    let bridge = Bridge()
    var downloads: [ObjectIdentifier: URL] = [:]
    var retries = 0
    var appearanceMode = selftestAppearance ?? UserDefaults.standard.string(forKey: "appearance") ?? "auto"
    var currentWS = UserDefaults.standard.string(forKey: "workspace")
    // the Chat panel in the sidebar
    var chatWeb: WKWebView!
    let chatBridge = Bridge()
    var sidebarItem: NSSplitViewItem!
    var sidebarVC: SidebarController!
    weak var modeGroup: NSToolbarItemGroup?
    var sidebarMode = (selftestDir == nil ? UserDefaults.standard.string(forKey: "sidebarMode") : nil) == "chat" ? "chat" : "views"
    var serverUp = false
    var chatRequested = false
    var chatLoaded = false
    var chatRetries = 0
    var pendingChat: [String] = []          // what to run in the panel once it has loaded
    var lastSel: String? = nil              // what the page shows (screen:<id>, decision:<n>), for the panel
    var panelConv: String? = nil            // the conversation the panel shows
    var lastShown: Bool? = nil
    var applyingMode = false
    var chatAttention = 0
    var chatTip = ""
    var collapseObserver: NSKeyValueObservation?
    weak var searchItem: NSSearchToolbarItem?
    weak var appearanceItem: NSMenuToolbarItem?
    var appearanceMenus: [NSMenu] = []
    var appearanceObserver: NSKeyValueObservation?
    var workspacePaths: [String: String] = [:]

    func applicationDidFinishLaunching(_ notification: Notification) {
        applyAppearance(appearanceMode, tellPage: false)
        buildMenus()

        // the page
        let config = WKWebViewConfiguration()
        config.userContentController.add(bridge, name: "plots")
        config.websiteDataStore = .default()                 // keeps the page's drafts between launches
        config.applicationNameForUserAgent = "PlotsApp/8"           // 8: Chat is a panel in the sidebar
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = false
        web.allowsMagnification = false
        if #available(macOS 13.3, *) { web.isInspectable = true }
        bridge.handle = { [weak self] body in MainActor.assumeIsolated { self?.handle(body) } }

        // the Chat panel: the same page with ?panel=chat, drawn without a background over the sidebar's glass
        let chatConfig = WKWebViewConfiguration()
        chatConfig.userContentController.add(chatBridge, name: "plots")
        chatConfig.websiteDataStore = .default()
        chatConfig.applicationNameForUserAgent = "PlotsApp/8"
        chatWeb = WKWebView(frame: .zero, configuration: chatConfig)
        chatWeb.navigationDelegate = self
        chatWeb.uiDelegate = self
        chatWeb.allowsBackForwardNavigationGestures = false
        chatWeb.allowsMagnification = false
        if chatWeb.responds(to: NSSelectorFromString("_setDrawsBackground:")) || chatWeb.responds(to: NSSelectorFromString("setDrawsBackground:")) {
            chatWeb.setValue(false, forKey: "drawsBackground")
        }
        chatWeb.underPageBackgroundColor = .clear
        if #available(macOS 13.3, *) { chatWeb.isInspectable = true }
        chatBridge.handle = { [weak self] body in MainActor.assumeIsolated { self?.handleChat(body) } }

        // sidebar | content. The content sits beside the sidebar and below the toolbar, so AppKit moves and
        // resizes it together with the sidebar when it folds; nothing in the page has to chase the animation.
        chrome.selectView = { [weak self] v in self?.js("Plots.view(\(jsString(v)))") }
        chrome.selectBatch = { [weak self] b in self?.js("Plots.batch(\(jsString(b)))") }
        chrome.workspaceMenu = { [weak self] anchor in self?.showWorkspaceMenu(anchor) }
        chrome.search = { [weak self] in self?.focusSearch(nil) }
        let list = NSHostingController(rootView: SidebarView(chrome: chrome))
        list.sizingOptions = []
        sidebarVC = SidebarController(list: list, chat: chatWeb)
        let sidebar = NSSplitViewItem(sidebarWithViewController: sidebarVC)
        sidebar.canCollapse = true
        sidebarItem = sidebar
        setThickness()
        content = ContentController(web: web)
        let main = NSSplitViewItem(viewController: content)
        main.minimumThickness = 420             // the page stays usable beside a wide Chat panel
        main.automaticallyAdjustsSafeAreaInsets = false
        main.allowsFullHeightLayout = false
        main.titlebarSeparatorStyle = .none
        split = NSSplitViewController()
        split.addSplitViewItem(sidebar)
        split.addSplitViewItem(main)

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 900),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "Plots"
        window.titleVisibility = .hidden
        window.toolbarStyle = .unified
        window.tabbingMode = .disallowed
        window.isReleasedWhenClosed = false
        window.delegate = self
        let toolbar = NSToolbar(identifier: "PlotsToolbar")
        toolbar.delegate = self
        toolbar.displayMode = .iconOnly
        toolbar.allowsUserCustomization = false
        window.toolbar = toolbar
        window.contentViewController = split
        window.minSize = NSSize(width: 820, height: 560)
        if selftestDir != nil {
            window.setFrame(NSRect(x: 60, y: 60, width: 1440, height: 900), display: false)
        } else if !window.setFrameUsingName("PlotsWindow") {
            let vis = (NSScreen.main ?? NSScreen.screens[0]).visibleFrame
            window.setFrame(NSRect(x: 0, y: 0, width: min(1440, vis.width * 0.92), height: min(920, vis.height * 0.92)), display: false)
            window.center()
        }
        if selftestDir == nil { window.setFrameAutosaveName("PlotsWindow") }
        // the sidebar shows what it showed last time, at its width, open or hidden
        let wasCollapsed = selftestDir == nil && UserDefaults.standard.bool(forKey: "sidebarCollapsed")
        applySidebarMode(sidebarMode, focus: false, open: false)
        split.splitView.setPosition(savedWidth(), ofDividerAt: 0)
        if wasCollapsed { sidebar.isCollapsed = true }
        syncModeGroup()
        collapseObserver = sidebar.observe(\.isCollapsed, options: [.new]) { [weak self] _, _ in
            DispatchQueue.main.async { MainActor.assumeIsolated { self?.sidebarCollapsedChanged() } }
        }
        NotificationCenter.default.addObserver(forName: NSSplitView.didResizeSubviewsNotification, object: split.splitView,
                                               queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.sidebarResized() }
        }
        updatePageColors()
        appearanceObserver = NSApp.observe(\.effectiveAppearance) { [weak self] _, _ in
            DispatchQueue.main.async { MainActor.assumeIsolated { self?.updatePageColors() } }
        }

        web.loadHTMLString(statusPage("Starting Plots…"), baseURL: nil)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate()
        // once the window has its layout, the sidebar takes its width again
        DispatchQueue.main.async {
            MainActor.assumeIsolated {
                guard !self.sidebarItem.isCollapsed else { return }
                self.applyingMode = true
                self.split.splitView.setPosition(self.savedWidth(), ofDividerAt: 0)
                self.applyingMode = false
            }
        }
        log("launched, engine \(engineDir()?.path ?? "not found")")
        startServer { [weak self] ok in
            guard let self else { return }
            log(ok ? "server is up, loading \(baseURL)" : "server did not come up")
            if ok { self.serverUp = true; self.loadPage(); if self.sidebarMode == "chat" { self.loadChat() } }
            else { self.showServerError() }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { window.makeKeyAndOrderFront(nil) }
        return true
    }

    func pageURL() -> URL {
        guard let ws = currentWS, var c = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { return baseURL }
        c.queryItems = [URLQueryItem(name: "ws", value: ws)]
        return c.url ?? baseURL
    }

    func loadPage() { web.load(URLRequest(url: pageURL())) }

    // MARK: page messages

    func js(_ code: String) { web?.evaluateJavaScript("window.Plots && \(code)") }

    // Runs `code` (an async function body) with named arguments; done(nil) on success, done(message) on error.
    func callJS(_ code: String, _ args: [String: Any], _ done: @escaping @MainActor (String?) -> Void) {
        let body = "if (!window.Plots) throw new Error('The page isn’t ready yet.');\n" + code
        web.callAsyncJavaScript(body, arguments: args, in: nil, in: .page) { result in
            MainActor.assumeIsolated {
                switch result {
                case .success: done(nil)
                case .failure(let e):
                    let msg = (e as NSError).userInfo["WKJavaScriptExceptionMessage"] as? String ?? e.localizedDescription
                    done(msg.replacingOccurrences(of: "Error: ", with: ""))
                }
            }
        }
    }

    func handle(_ body: [String: Any]) {
        switch body["type"] as? String {
        case "chrome":
            chrome.view = body["view"] as? String ?? chrome.view
            chrome.batch = body["batch"] as? String ?? chrome.batch
            chrome.screens = body["screens"] as? Int ?? chrome.screens
            chrome.waiting = body["waiting"] as? Int ?? 0
            if let list = body["batches"] as? [[String: Any]] {
                let b = list.compactMap { d -> BatchInfo? in
                    guard let id = d["id"] as? String else { return nil }
                    return BatchInfo(id: id, done: d["done"] as? Int ?? 0, total: d["total"] as? Int ?? 0, flight: d["flight"] as? Int ?? 0)
                }
                if b != chrome.batches { chrome.batches = b }
            }
            if let w = body["ws"] as? [String: Any] {
                let info = WorkspaceInfo(w)
                if info != chrome.ws { chrome.ws = info }
                if !info.id.isEmpty && info.id != currentWS {
                    currentWS = info.id
                    if selftestDir == nil { UserDefaults.standard.set(info.id, forKey: "workspace") }
                }
                window.title = info.name
            } else if body["ws"] is NSNull {
                chrome.ws = nil
                window.title = "Plots"
            }
            if let ws = body["workspaces"] as? [[String: Any]] {
                let list = ws.map { WorkspaceInfo($0) }
                if list != chrome.workspaces { chrome.workspaces = list }
            }
            updateChat(body["chat"] as? [String: Any] ?? [:])
            // what the page shows goes with a chat message: the panel shows it as a chip
            let sel = body["sel"] as? String
            if sel != lastSel { lastSel = sel; chatJS("Plots.context(\(sel.map(jsString) ?? "null"))") }
            if let page = body["theme"] as? String, page != appearanceMode { js("Plots.theme(\(jsString(appearanceMode)))") }
        case "openChat":                    // a notice's View, a conversation in the search, an old #/chat link
            openChat(body["id"] as? String)
        case "newChat":
            newChat()
        case "toggleChat":
            toggleChatAction(nil)
        case "openNotes":                   // an older page's way of asking for the notes
            openChat(nil)
        case "newWorkspace":
            newWorkspace(nil)
        case "palette":
            if (body["open"] as? Bool) == false { endSearch(clearPage: false) }
        case "reveal":                      // a worktree's folder, from the Code card
            if let p = body["path"] as? String, FileManager.default.fileExists(atPath: p) {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: p)])
            }
        case "askFolders":                  // "Allow Access…" on the Code card; quietly, when a message goes to a fork
            askFolders(body)
        default:
            break
        }
    }

    func askFolders(_ body: [String: Any]) {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let paths = (body["folders"] as? [String] ?? []).map { $0.hasPrefix("/") ? $0 : home + "/" + $0 }
        if (body["quiet"] as? Bool) == true { touchFolders(paths) } else { requestFolderAccess(paths) }
    }

    // Messages from the Chat panel
    func handleChat(_ body: [String: Any]) {
        switch body["type"] as? String {
        case "navigate":                    // a screen or decision in the chat opens in the page beside it
            if let h = body["hash"] as? String { js("Plots.go(\(jsString(h)))") }
        case "panel":                       // the conversation it shows (the page's notices leave that one out)
            panelConv = body["conv"] as? String
            if chatShown { js("Plots.panelConv(\(panelConv.map(jsString) ?? "null"))") }
        case "askFolders":
            askFolders(body)
        default:
            break
        }
    }

    // ✦ in the toolbar and the Dock icon: a badge for what needs you in Chat (threads waiting on you, answers you
    // haven't read); the toolbar's only while the Chat panel isn't showing.
    func updateChat(_ c: [String: Any]) {
        let working = c["working"] as? Int ?? 0
        let waiting = c["waiting"] as? Int ?? 0
        let unread = c["unread"] as? Int ?? 0
        let attention = c["attention"] as? Int ?? (waiting + unread)
        let project = (c["mode"] as? String) == "project"
        var tip: [String] = []
        if waiting > 0 { tip.append("\(waiting) waiting on you") }
        if unread > 0 { tip.append("\(unread) new answer\(unread == 1 ? "" : "s")") }
        if working > 0 { tip.append("Claude is working on \(working)") }
        let idle = project ? "Chat with your Claude project" : "Ask Claude about the work"
        chatTip = (tip.isEmpty ? idle : tip.joined(separator: " · ")) + "  ⌘0"
        chatAttention = attention
        NSApp.dockTile.badgeLabel = attention > 0 ? "\(attention)" : nil
        updateChatBadge()
    }

    var badgeShown = -1
    func updateChatBadge() {
        guard let g = modeGroup else { return }
        let n = chatAttention > 0 && !chatShown ? chatAttention : 0
        if n != badgeShown { badgeShown = n; g.badge = n > 0 ? .count(n) : nil }
        if g.subitems.count == 2 { g.subitems[1].toolTip = chatTip.isEmpty ? "Chat  ⌘0" : chatTip }
    }

    // MARK: the sidebar: views and batches, or Chat

    // while the sidebar slides open (true) or shut (false), where it's going; nil while it stands still
    var sidebarMoving: Bool? = nil
    var moveToken = 0
    var moveStarted = false
    var afterMove: (() -> Void)? = nil      // the last thing asked for while it slid, done once it stops
    var sidebarOpen: Bool { sidebarMoving ?? !(sidebarItem?.isCollapsed ?? true) }
    var chatShown: Bool { sidebarMode == "chat" && sidebarOpen }

    // Keep one shared width for Views and Chat (the width dragged by the user), like Xcode's navigators, so
    // swapping ≡ and ✦ only changes the sidebar content without causing the page to reflow and flicker.
    func setThickness() {
        sidebarItem.minimumThickness = 240
        sidebarItem.maximumThickness = 560
    }

    // the sidebar's width (with the floating sidebar's inset): the one last dragged to, else 320
    func savedWidth() -> CGFloat {
        let w = selftestDir == nil ? CGFloat(UserDefaults.standard.double(forKey: "sidebarWidth")) : 0
        return w >= 248 && w <= 568 ? w : 320
    }

    // the sidebar's width as the window lays it out (the floating sidebar's inset included)
    var sidebarSpan: CGFloat { split.splitView.arrangedSubviews.first?.frame.width ?? sidebarVC.view.frame.width }

    // ≡ shows the views and batches, ✦ the Chat panel. A hidden sidebar slides open on it, the way ⌃⌘S shows it
    // (open: false leaves it hidden, as at launch).
    func applySidebarMode(_ mode: String, focus: Bool, open: Bool = true) {
        // Queue requests that arrive while the sidebar is mid-slide so rapid hide/show toggles stay consistent.
        if open && sidebarMoving != nil { afterMove = { [weak self] in self?.applySidebarMode(mode, focus: focus) }; return }
        let chat = mode == "chat"
        sidebarMode = chat ? "chat" : "views"
        if selftestDir == nil { UserDefaults.standard.set(sidebarMode, forKey: "sidebarMode") }
        sidebarVC.show(chat: chat)
        if chat { loadChat() }
        if sidebarItem.isCollapsed && open { revealSidebar(focus: focus); return }
        syncModeGroup()
        chatVisibilityChanged()
        if focus && !sidebarItem.isCollapsed { focusSidebar() }
    }

    func focusSidebar() {
        let chat = sidebarMode == "chat"
        window.makeFirstResponder(chat ? chatWeb : web)
        if chat { chatRun("Plots.focusChat()") }
    }

    // The sidebar slides open and shut one slide at a time (what comes meanwhile runs when it stops). While it
    // slides the page keeps its layout and moves along as one piece, then lays itself out once when it stops.
    func revealSidebar(focus: Bool) {
        guard sidebarItem.isCollapsed, sidebarMoving == nil else { return }
        sidebarMoving = true
        syncModeGroup()
        chatVisibilityChanged()
        moveSidebar(collapsed: false, focus: focus)
    }

    func concealSidebar() {
        guard !sidebarItem.isCollapsed, sidebarMoving == nil else { return }
        sidebarMoving = false
        syncModeGroup()
        chatVisibilityChanged()
        if let r = window.firstResponder as? NSView, r.isDescendant(of: sidebarVC.view) { window.makeFirstResponder(web) }
        moveSidebar(collapsed: true, focus: false)
    }

    func moveSidebar(collapsed: Bool, focus: Bool) {
        moveToken += 1
        moveStarted = false
        let token = moveToken
        applyingMode = true
        // the page holds its layout first; the slide starts once it has (or at once without the page)
        if web.url?.host == "127.0.0.1" {
            web.evaluateJavaScript("window.Plots && Plots.hold && Plots.hold(true); 1") { [weak self] _, _ in
                MainActor.assumeIsolated { self?.startMove(token, collapsed: collapsed, focus: focus) }
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak self] in
                MainActor.assumeIsolated { self?.startMove(token, collapsed: collapsed, focus: focus) }
            }
        } else {
            startMove(token, collapsed: collapsed, focus: focus)
        }
    }

    func startMove(_ token: Int, collapsed: Bool, focus: Bool) {
        guard token == moveToken, !moveStarted else { return }
        moveStarted = true
        NSAnimationContext.runAnimationGroup({ _ in
            self.sidebarItem.animator().isCollapsed = collapsed
        }, completionHandler: { [weak self] in
            MainActor.assumeIsolated { self?.sidebarDidMove(token, focus: focus) }
        })
        // in case the animation never reports back
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            MainActor.assumeIsolated { self?.sidebarDidMove(token, focus: focus) }
        }
    }

    func sidebarDidMove(_ token: Int, focus: Bool) {
        guard token == moveToken, let opened = sidebarMoving else { return }
        sidebarMoving = nil
        // it opens at the width it had; if that wasn't the sidebar's width, it takes it now, before the page lays out
        if opened && !sidebarItem.isCollapsed && abs(sidebarSpan - savedWidth()) > 1 {
            split.splitView.setPosition(savedWidth(), ofDividerAt: 0)
            split.splitView.layoutSubtreeIfNeeded()
        }
        applyingMode = false
        js("Plots.hold && Plots.hold(false)")
        syncModeGroup()
        chatVisibilityChanged()
        if opened && focus { focusSidebar() }
        if let next = afterMove { afterMove = nil; next() }
    }

    // ≡ or ✦ shows as chosen only while the sidebar is open (nothing stays selected once it's hidden). The
    // group lets each segment toggle (a one-of group always keeps one chosen), and this keeps at most one on.
    var shownSelection = [false, false]
    func syncModeGroup() {
        guard let g = modeGroup, g.subitems.count == 2 else { return }
        let want = sidebarOpen ? (sidebarMode == "chat" ? 1 : 0) : -1
        for k in 0..<2 where g.isSelected(at: k) != (k == want) { g.setSelected(k == want, at: k) }
        shownSelection = [want == 0, want == 1]
        updateChatBadge()
    }

    // the width you drag the sidebar to is kept
    func sidebarResized() {
        if sidebarItem.isCollapsed != lastCollapsed { sidebarCollapsedChanged() }
        guard !sidebarItem.isCollapsed, sidebarMoving == nil, !applyingMode, selftestDir == nil, sidebarVC.view.inLiveResize else { return }
        let w = sidebarSpan
        if w >= 248 && w <= 568 { UserDefaults.standard.set(Double(w), forKey: "sidebarWidth") }
    }

    // the sidebar was hidden or shown (⌃⌘S, the toolbar, dragging it closed)
    var lastCollapsed: Bool? = nil
    func sidebarCollapsedChanged() {
        let c = sidebarItem.isCollapsed
        if c != lastCollapsed {
            lastCollapsed = c
            if selftestDir == nil { UserDefaults.standard.set(c, forKey: "sidebarCollapsed") }
        }
        if sidebarMoving == nil { syncModeGroup() }
        chatVisibilityChanged()
    }

    // the panel marks answers read only while it shows; the page leaves the conversation it shows out of its notices
    func chatVisibilityChanged() {
        let shown = chatShown
        guard shown != lastShown else { return }
        lastShown = shown
        chatJS("Plots.visible(\(shown))")
        js("Plots.panelConv(\(shown ? (panelConv.map(jsString) ?? "null") : "null"))")
        updateChatBadge()
    }

    func chatURL() -> URL {
        guard var c = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { return baseURL }
        var q = [URLQueryItem(name: "panel", value: "chat")]
        if let ws = currentWS { q.insert(URLQueryItem(name: "ws", value: ws), at: 0) }
        c.queryItems = q
        return c.url ?? baseURL
    }

    func loadChat(force: Bool = false) {
        guard serverUp, force || !chatRequested else { return }
        chatRequested = true
        chatLoaded = false
        chatWeb.load(URLRequest(url: chatURL()))
    }

    func chatJS(_ code: String) { if chatLoaded { chatWeb.evaluateJavaScript("window.Plots && \(code)") } }
    // runs now if the panel has loaded, else once it has
    func chatRun(_ code: String) {
        if chatLoaded { chatJS(code) } else { pendingChat.append(code); loadChat() }
    }

    func chatDidLoad() {
        guard chatWeb.url?.host == "127.0.0.1" else { return }
        chatLoaded = true
        chatRetries = 0
        chatJS("Plots.theme(\(jsString(appearanceMode)))")
        chatJS("Plots.context(\(lastSel.map(jsString) ?? "null"))")
        lastShown = nil
        chatVisibilityChanged()
        let todo = pendingChat
        pendingChat = []
        todo.forEach { chatJS($0) }
    }

    func openChat(_ id: String?) {
        applySidebarMode("chat", focus: true)
        chatRun("Plots.chat(\(id.map(jsString) ?? "null"))")
    }

    func newChat() {
        applySidebarMode("chat", focus: true)
        chatRun("Plots.newChat()")
    }

    // A message to a fork reads the working session's folder and Claude Code's skills; when those are in a folder
    // macOS protects (Desktop, Documents, Downloads), the fork runs on Plots' permission. Reading them from the
    // app, once, brings up macOS's prompt with Plots' reason instead of a fork that silently waits for it.
    var touchedFolders: Set<String> = []
    func touchFolders(_ paths: [String]) {
        guard selftestDir == nil else { return }        // a self-test never brings up macOS's privacy prompt
        let todo = paths.filter { !touchedFolders.contains($0) }
        guard !todo.isEmpty else { return }
        touchedFolders.formUnion(todo)
        DispatchQueue.global(qos: .userInitiated).async {
            for f in todo { _ = try? FileManager.default.contentsOfDirectory(atPath: f) }
        }
    }

    // Reading a protected folder (Desktop, Documents, Downloads) from the app brings up macOS's prompt with
    // Plots' reason. If macOS answers at once, the choice was made before (Don't Allow): open the Files & Folders
    // settings instead, where it can be changed.
    func requestFolderAccess(_ paths: [String]) {
        guard selftestDir == nil, !paths.isEmpty else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            let start = Date()
            var denied = false
            for p in paths {
                do { _ = try FileManager.default.contentsOfDirectory(atPath: p) } catch { denied = true }
            }
            if denied && Date().timeIntervalSince(start) < 1 {
                DispatchQueue.main.async {
                    MainActor.assumeIsolated {
                        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders") {
                            NSWorkspace.shared.open(url)
                        }
                    }
                }
            }
        }
    }

    // MARK: server

    nonisolated func ping(_ done: @escaping @Sendable ([String: Any]?) -> Void) {
        var req = URLRequest(url: baseURL.appendingPathComponent("api/ping"))
        req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            guard (resp as? HTTPURLResponse)?.statusCode == 200, let data,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return done(nil) }
            done(obj)
        }.resume()
    }

    // `plots.py open --no-window` starts the server in the background (it keeps running after the app quits),
    // and replaces an older one if that is what answers.
    func startServer(_ done: @escaping (Bool) -> Void) {
        ping { info in
            let current = (info?["app"] as? String) == "plots" && ((info?["version"] as? Int) ?? 0) >= 6
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    if current { done(true); return }
                    self.launchServer()
                    self.waitForServer(tries: 80, done)
                }
            }
        }
    }

    func waitForServer(tries: Int, _ done: @escaping (Bool) -> Void) {
        ping { info in
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    if (info?["app"] as? String) == "plots" { done(true) }
                    else if tries <= 0 { done(false) }
                    else { DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { MainActor.assumeIsolated { self.waitForServer(tries: tries - 1, done) } } }
                }
            }
        }
    }

    func python() -> String? {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let pythons = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "\(home)/miniconda3/bin/python3",
                       "\(home)/anaconda3/bin/python3", "\(home)/miniforge3/bin/python3", "\(home)/.pyenv/shims/python3",
                       "/usr/bin/python3"]
        return pythons.first(where: { FileManager.default.isExecutableFile(atPath: $0) })
    }

    func launchServer() {
        guard let engine = engineDir() else { log("no engine in the app"); return }
        let script = engine.appendingPathComponent("plots.py").path
        let p = Process()
        if let py = python() {
            p.executableURL = URL(fileURLWithPath: py)
            p.arguments = [script, "open", "--no-window"]
        } else {
            p.executableURL = URL(fileURLWithPath: "/bin/zsh")
            p.arguments = ["-lc", "python3 \"\(script)\" open --no-window"]
        }
        p.environment = ProcessInfo.processInfo.environment
        p.currentDirectoryURL = engine
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        try? p.run()
    }

    func showServerError() {
        web.loadHTMLString(statusPage("Plots couldn’t start its server.",
                                      "Open Terminal and run <code>plots open</code>, or check <code>~/.plots/run/server.log</code>."),
                           baseURL: nil)
    }

    func statusPage(_ title: String, _ detail: String = "") -> String {
        """
        <!doctype html><meta charset="utf-8"><meta name="color-scheme" content="light dark">
        <style>html,body{height:100%;margin:0;background:transparent;font:13px -apple-system,system-ui;color:CanvasText}
        body{display:grid;place-items:center;text-align:center}div{max-width:420px;padding:24px;border-radius:14px}
        b{font-size:15px}p{color:GrayText;margin:8px 0 0}code{font:12px ui-monospace,monospace}</style>
        <div><b>\(title)</b>\(detail.isEmpty ? "" : "<p>\(detail)</p>")</div>
        """
    }

    // MARK: workspaces

    func badgeImage(_ ws: WorkspaceInfo, size: CGFloat = 16) -> NSImage {
        let renderer = ImageRenderer(content: WorkspaceBadge(ws: ws, size: size))
        renderer.scale = NSScreen.main?.backingScaleFactor ?? 2
        return renderer.nsImage ?? NSImage()
    }

    func showWorkspaceMenu(_ anchor: NSView) {
        let m = NSMenu()
        for w in chrome.workspaces {
            let it = NSMenuItem(title: w.name, action: #selector(pickWorkspace(_:)), keyEquivalent: "")
            it.target = self
            it.representedObject = w.id
            it.image = badgeImage(w)
            it.subtitle = w.total > 0 ? "\(w.done) of \(w.total) done" : "Nothing tracked yet"
            it.state = w.id == chrome.ws?.id ? .on : .off
            m.addItem(it)
        }
        if !chrome.workspaces.isEmpty { m.addItem(.separator()) }
        let add = NSMenuItem(title: "New Workspace…", action: #selector(newWorkspace(_:)), keyEquivalent: "")
        add.target = self
        add.image = NSImage(systemSymbolName: "plus", accessibilityDescription: nil)
        m.addItem(add)
        let show = NSMenuItem(title: "Show Data in Finder", action: #selector(showDataFile(_:)), keyEquivalent: "")
        show.target = self
        show.image = NSImage(systemSymbolName: "folder", accessibilityDescription: nil)
        m.addItem(show)
        m.popUp(positioning: nil, at: NSPoint(x: 0, y: -6), in: anchor)
    }

    @objc func pickWorkspace(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        switchWorkspace(id)
    }

    func switchWorkspace(_ id: String) {
        currentWS = id
        if selftestDir == nil { UserDefaults.standard.set(id, forKey: "workspace") }
        js("Plots.workspace(\(jsString(id)))")
        lastSel = nil
        panelConv = nil
        if chatLoaded { chatJS("Plots.workspace(\(jsString(id)))") } else if chatRequested { loadChat(force: true) }
    }

    @objc func newWorkspace(_ sender: Any?) {
        let alert = NSAlert()
        alert.messageText = "New Workspace"
        alert.informativeText = "One workspace per project. Claude Code keeps it up to date with the plots command; run `plots init` in a project folder to do the same from Terminal."
        let name = NSTextField(string: "")
        name.placeholderString = "Name, for example Website Redesign"
        let folderLabel = NSTextField(labelWithString: "No project folder chosen")
        folderLabel.textColor = .secondaryLabelColor
        folderLabel.lineBreakMode = .byTruncatingMiddle
        var folder: URL? = nil
        let choose = NSButton(title: "Choose Project Folder…", target: nil, action: nil)
        let chooser = ButtonAction {
            let panel = NSOpenPanel()
            panel.canChooseDirectories = true
            panel.canChooseFiles = false
            panel.prompt = "Choose"
            panel.message = "The folder Claude Code works in for this project"
            if panel.runModal() == .OK, let u = panel.url {
                folder = u
                folderLabel.stringValue = u.path
                if name.stringValue.isEmpty { name.stringValue = u.lastPathComponent }
            }
        }
        choose.target = chooser
        choose.action = #selector(ButtonAction.fire)
        let stack = NSStackView(views: [name, choose, folderLabel])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 8
        stack.frame = NSRect(x: 0, y: 0, width: 320, height: 86)
        name.widthAnchor.constraint(equalToConstant: 320).isActive = true
        folderLabel.widthAnchor.constraint(equalToConstant: 320).isActive = true
        alert.accessoryView = stack
        alert.addButton(withTitle: "Create")
        alert.addButton(withTitle: "Cancel")
        alert.window.initialFirstResponder = name
        alert.beginSheetModal(for: window) { [weak self] resp in
            withExtendedLifetime(chooser) {}
            guard resp == .alertFirstButtonReturn, let self else { return }
            let n = name.stringValue.trimmingCharacters(in: .whitespaces)
            guard !n.isEmpty else { return }
            var body: [String: Any] = ["name": n]
            if let f = folder { body["root"] = f.path }
            self.post("api/workspaces", body) { obj, err in
                if let id = (obj?["workspace"] as? [String: Any])?["id"] as? String {
                    self.js("Plots.workspaces()")
                    self.switchWorkspace(id)
                } else {
                    let a = NSAlert()
                    a.messageText = "Couldn’t create the workspace."
                    a.informativeText = err ?? "Is Plots’s server running?"
                    a.beginSheetModal(for: self.window)
                }
            }
        }
    }

    func post(_ path: String, _ body: [String: Any], _ done: @escaping @MainActor ([String: Any]?, String?) -> Void) {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = "POST"
        req.setValue("1", forHTTPHeaderField: "X-Plots")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req) { data, resp, err in
            let obj = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200
            let message = ok ? nil : (obj?["error"] as? String ?? err?.localizedDescription ?? "Request failed")
            DispatchQueue.main.async { MainActor.assumeIsolated { done(ok ? obj : nil, message) } }
        }.resume()
    }

    func get(_ path: String, _ done: @escaping @MainActor ([String: Any]?) -> Void) {
        URLSession.shared.dataTask(with: baseURL.appendingPathComponent(path)) { data, _, _ in
            let obj = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            DispatchQueue.main.async { MainActor.assumeIsolated { done(obj) } }
        }.resume()
    }

    // MARK: toolbar

    func toolbarDefaultItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [.sidebarMode, .sidebarTrackingSeparator, .flexibleSpace, .appearance, .search, .export]
    }

    func toolbarAllowedItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        toolbarDefaultItemIdentifiers(toolbar) + [.space]
    }

    func toolbar(_ toolbar: NSToolbar, itemForItemIdentifier id: NSToolbarItem.Identifier,
                 willBeInsertedIntoToolbar flag: Bool) -> NSToolbarItem? {
        switch id {
        case .sidebarMode:
            // ≡ and ✦ over the sidebar, like Xcode's navigator and its coding assistant; clicking the one that's
            // showing hides or shows the sidebar
            let views = NSImage(systemSymbolName: "list.bullet", accessibilityDescription: "Views and batches") ?? NSImage()
            let group = NSToolbarItemGroup(itemIdentifier: id, images: [views, chatSymbol()], selectionMode: .selectAny,
                                           labels: ["Views", "Chat"], target: self, action: #selector(sidebarModeAction(_:)))
            group.label = "Sidebar"
            group.paletteLabel = "Sidebar"
            group.controlRepresentation = .expanded
            if group.subitems.count == 2 {
                group.subitems[0].toolTip = "Views and batches"
                group.subitems[1].toolTip = chatTip.isEmpty ? "Chat  ⌘0" : chatTip
            }
            modeGroup = group
            badgeShown = -1
            syncModeGroup()
            return group
        case .appearance:
            let item = NSMenuToolbarItem(itemIdentifier: id)
            item.label = "Appearance"
            item.paletteLabel = "Appearance"
            item.toolTip = "Appearance: Automatic, Light or Dark"
            item.image = NSImage(systemSymbolName: appearanceSymbol(), accessibilityDescription: "Appearance")
            item.showsIndicator = false
            item.menu = appearanceMenu()
            appearanceItem = item
            return item
        case .search:
            let item = NSSearchToolbarItem(itemIdentifier: id)
            item.label = "Search"
            item.searchField.placeholderString = "Search"
            item.searchField.delegate = self
            item.searchField.sendsSearchStringImmediately = true
            item.preferredWidthForSearchField = 220
            item.resignsFirstResponderWithCancel = true
            item.toolTip = "Search screens, decisions and commands  ⌘K"
            searchItem = item
            return item
        case .export:
            let item = NSToolbarItem(itemIdentifier: id)
            item.label = "Export"
            item.paletteLabel = "Export to Excel"
            item.title = "Export"
            item.image = NSImage(systemSymbolName: "square.and.arrow.down", accessibilityDescription: "Export")
            item.toolTip = "Download the tracker as an Excel file"
            item.target = self
            item.action = #selector(exportAction(_:))
            return item
        default:
            return nil
        }
    }

    // MARK: search field → the page's palette

    func controlTextDidChange(_ obj: Notification) {
        guard let field = searchItem?.searchField else { return }
        js("Plots.palette(\(jsString(field.stringValue)))")
    }

    func control(_ control: NSControl, textView: NSTextView, doCommandBy selector: Selector) -> Bool {
        switch selector {
        case #selector(NSResponder.moveDown(_:)): js("Plots.paletteKey('ArrowDown')"); return true
        case #selector(NSResponder.moveUp(_:)): js("Plots.paletteKey('ArrowUp')"); return true
        case #selector(NSResponder.insertNewline(_:)): js("Plots.paletteKey('Enter')"); endSearch(clearPage: false); return true
        case #selector(NSResponder.cancelOperation(_:)): endSearch(clearPage: true); return true
        default: return false
        }
    }

    func searchFieldDidStartSearching(_ sender: NSSearchField) { js("Plots.palette(\(jsString(sender.stringValue)))") }
    func searchFieldDidEndSearching(_ sender: NSSearchField) { js("Plots.paletteKey('Escape')") }

    func endSearch(clearPage: Bool) {
        if clearPage { js("Plots.paletteKey('Escape')") }
        guard let item = searchItem else { return }
        if !item.searchField.stringValue.isEmpty { item.searchField.stringValue = "" }
        item.endSearchInteraction()
        window.makeFirstResponder(web)
    }

    @objc func focusSearch(_ sender: Any?) {
        guard let item = searchItem else { js("Plots.search()"); return }
        item.beginSearchInteraction()
        js("Plots.palette(\(jsString(item.searchField.stringValue)))")
    }

    // MARK: actions

    // ≡ / ✦: with the sidebar hidden, it slides open on the one clicked; the other one swaps what it shows; the
    // one that's showing hides it
    @objc func sidebarModeAction(_ sender: Any?) {
        guard let g = modeGroup, g.subitems.count == 2 else { return }
        // the segment clicked is the one that changed (or the subitem that sent this)
        var i = (0..<2).first { g.isSelected(at: $0) != shownSelection[$0] } ?? -1
        if let it = sender as? NSToolbarItem, let k = g.subitems.firstIndex(where: { $0 === it }) { i = k }
        guard i == 0 || i == 1 else { syncModeGroup(); return }
        sidebarClicked(i == 1 ? "chat" : "views")
    }

    func sidebarClicked(_ want: String) {
        if sidebarMoving != nil { afterMove = { [weak self] in self?.sidebarClicked(want) }; return }
        if !sidebarItem.isCollapsed && want == sidebarMode { concealSidebar() } else { applySidebarMode(want, focus: true) }
    }

    // ⌃⌘S (View › Show or Hide Sidebar)
    @objc func toggleSidebarAction(_ sender: Any?) {
        if sidebarMoving != nil { afterMove = { [weak self] in self?.toggleSidebarAction(nil) }; return }
        if sidebarItem.isCollapsed { revealSidebar(focus: false) } else { concealSidebar() }
    }

    // ⌘0: Chat, or back to the views
    @objc func toggleChatAction(_ sender: Any?) {
        if sidebarMoving != nil { afterMove = { [weak self] in self?.toggleChatAction(nil) }; return }
        applySidebarMode(chatShown ? "views" : "chat", focus: true)
    }
    @objc func newChatAction(_ sender: Any?) { newChat() }

    @objc func exportAction(_ sender: Any?) { js("Plots.exportXlsx()") }
    @objc func showOverview(_ s: Any?) { js("Plots.view('overview')") }
    @objc func showScreens(_ s: Any?) { js("Plots.view('screens')") }
    @objc func showDecisions(_ s: Any?) { js("Plots.view('decisions')") }
    @objc func showActivity(_ s: Any?) { js("Plots.view('activity')") }
    @objc func reloadAction(_ s: Any?) {
        retries = 0
        loadPage()
        if chatRequested { loadChat(force: true) }
    }
    @objc func openReadme(_ s: Any?) {
        if let e = engineDir() {
            let readme = e.appendingPathComponent("README.md")
            if FileManager.default.fileExists(atPath: readme.path) { NSWorkspace.shared.open(readme); return }
        }
        NSWorkspace.shared.open(baseURL)
    }
    @objc func showDataFile(_ s: Any?) {
        get("api/workspaces") { obj in
            let list = obj?["workspaces"] as? [[String: Any]] ?? []
            let w = list.first { ($0["id"] as? String) == self.currentWS } ?? list.first
            if let p = w?["data"] as? String { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: p)]) }
        }
    }

    // Puts a `plots` command in ~/.local/bin that runs the engine inside this app.
    @objc func installCLI(_ s: Any?) {
        guard let engine = engineDir() else { return }
        let bin = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin")
        let target = bin.appendingPathComponent("plots")
        let alert = NSAlert()
        alert.messageText = "Install the plots command?"
        alert.informativeText = "Claude Code and Terminal use it to update and read your workspaces. It goes in \(target.path) and runs the engine inside this app."
        alert.addButton(withTitle: "Install")
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        let script = "#!/bin/sh\n# Plots CLI, installed by the Plots app\nexec python3 \"\(engine.appendingPathComponent("plots.py").path)\" \"$@\"\n"
        do {
            try FileManager.default.createDirectory(at: bin, withIntermediateDirectories: true)
            try script.write(to: target, atomically: true, encoding: .utf8)
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: target.path)
            let done = NSAlert()
            done.messageText = "Installed."
            done.informativeText = "Try `plots help` in Terminal. If it isn’t found, add ~/.local/bin to your PATH."
            done.runModal()
        } catch {
            NSAlert(error: error).runModal()
        }
    }

    // Copies the Claude Code plugin out of the app (so the path stays put across app updates) and installs it:
    // the plots skill, and the hooks that hand notes to the working session as soon as they arrive.
    @objc func installPlugin(_ s: Any?) {
        let fm = FileManager.default
        guard let src = Bundle.main.resourceURL?.appendingPathComponent("plugin"), fm.fileExists(atPath: src.path) else { return }
        let alert = NSAlert()
        alert.messageText = "Add Plots to Claude Code?"
        alert.informativeText = "Installs the Plots plugin: a skill for the plots command, and hooks that pass on to the working session what you send it from Chat, as soon as it arrives, even in the middle of a task. New Claude Code sessions pick it up."
        alert.addButton(withTitle: "Install")
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        let dest = fm.homeDirectoryForCurrentUser.appendingPathComponent(".plots/claude-plugin")
        do {
            try fm.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
            if fm.fileExists(atPath: dest.path) { try fm.removeItem(at: dest) }
            try fm.copyItem(at: src, to: dest)
        } catch { NSAlert(error: error).runModal(); return }
        let q = "'" + dest.path.replacingOccurrences(of: "'", with: "'\\''") + "'"
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        p.arguments = ["-lc", "(claude plugin marketplace add \(q) || claude plugin marketplace update plots) && claude plugin install plots@plots"]
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        p.terminationHandler = { proc in
            let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            let ok = proc.terminationStatus == 0
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    let a = NSAlert()
                    a.messageText = ok ? "Plots is in Claude Code." : "The plugin didn’t install."
                    a.informativeText = ok ? "Start a new Claude Code session to use it. In a project folder, /plots:init starts tracking the project."
                        : String(out.suffix(600)) + "\n\nYou can also run: claude plugin marketplace add ~/.plots/claude-plugin && claude plugin install plots@plots"
                    a.runModal()
                }
            }
        }
        do { try p.run() } catch { NSAlert(error: error).runModal() }
    }

    // MARK: appearance (Automatic follows the Mac)

    func appearanceSymbol() -> String {
        switch appearanceMode { case "light": return "sun.max"; case "dark": return "moon"; default: return "circle.lefthalf.filled" }
    }

    func appearanceMenu() -> NSMenu {
        let m = NSMenu(title: "Appearance")
        for (mode, title) in [("auto", "Automatic"), ("light", "Light"), ("dark", "Dark")] {
            let it = NSMenuItem(title: title, action: #selector(setAppearance(_:)), keyEquivalent: "")
            it.target = self
            it.representedObject = mode
            it.state = mode == appearanceMode ? .on : .off
            m.addItem(it)
        }
        appearanceMenus.append(m)
        return m
    }

    @objc func setAppearance(_ sender: NSMenuItem) {
        if let mode = sender.representedObject as? String { applyAppearance(mode, tellPage: true) }
    }

    // The page switches first, then the window, so both change in the same moment.
    func applyAppearance(_ mode: String, tellPage: Bool) {
        appearanceMode = ["light", "dark"].contains(mode) ? mode : "auto"
        if selftestDir == nil { UserDefaults.standard.set(appearanceMode, forKey: "appearance") }
        let apply: @MainActor () -> Void = { [weak self] in
            guard let self else { return }
            switch self.appearanceMode {
            case "light": NSApp.appearance = NSAppearance(named: .aqua)
            case "dark": NSApp.appearance = NSAppearance(named: .darkAqua)
            default: NSApp.appearance = nil
            }
            self.updatePageColors()
            for m in self.appearanceMenus { for it in m.items { it.state = (it.representedObject as? String) == self.appearanceMode ? .on : .off } }
            self.appearanceItem?.image = NSImage(systemSymbolName: self.appearanceSymbol(), accessibilityDescription: "Appearance")
        }
        if tellPage { chatJS("Plots.theme(\(jsString(appearanceMode)))") }
        if tellPage, let web, web.url?.host == "127.0.0.1" {
            web.evaluateJavaScript("window.Plots && Plots.theme(\(jsString(appearanceMode))); 1") { _, _ in MainActor.assumeIsolated { apply() } }
        } else {
            apply()
        }
    }

    // The colour around the page (under the toolbar and the floating sidebar) follows the appearance in effect.
    func updatePageColors() {
        let a = NSApp.appearance ?? NSApp.effectiveAppearance
        let dark = a.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
        let c = dark ? pageDark : pageLight
        window?.backgroundColor = c
        web?.underPageBackgroundColor = c
    }

    // MARK: menus

    func buildMenus() {
        let main = NSMenu()
        func item(_ title: String, _ action: Selector?, _ key: String = "", _ mods: NSEvent.ModifierFlags = [.command], target: AnyObject? = nil) -> NSMenuItem {
            let it = NSMenuItem(title: title, action: action, keyEquivalent: key)
            it.keyEquivalentModifierMask = mods
            it.target = target
            return it
        }
        @discardableResult
        func menu(_ title: String, _ items: [NSMenuItem]) -> NSMenu {
            let m = NSMenu(title: title)
            items.forEach { m.addItem($0) }
            let holder = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            holder.submenu = m
            main.addItem(holder)
            return m
        }
        let services = NSMenu(title: "Services")
        let servicesItem = NSMenuItem(title: "Services", action: nil, keyEquivalent: "")
        servicesItem.submenu = services
        menu("Plots", [
            item("About Plots", #selector(NSApplication.orderFrontStandardAboutPanel(_:))),
            .separator(),
            item("Install Command Line Tool…", #selector(installCLI(_:)), target: self),
            item("Install Claude Code Plugin…", #selector(installPlugin(_:)), target: self),
            .separator(), servicesItem, .separator(),
            item("Hide Plots", #selector(NSApplication.hide(_:)), "h"),
            item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
            item("Show All", #selector(NSApplication.unhideAllApplications(_:))),
            .separator(),
            item("Quit Plots", #selector(NSApplication.terminate(_:)), "q"),
        ])
        NSApp.servicesMenu = services
        menu("File", [
            item("New Workspace…", #selector(newWorkspace(_:)), "n", [.command, .shift], target: self),
            item("New Conversation", #selector(newChatAction(_:)), "n", target: self),
            item("Export to Excel…", #selector(exportAction(_:)), "e", [.command, .shift], target: self),
            item("Show Data in Finder", #selector(showDataFile(_:)), target: self),
            .separator(),
            item("Close Window", #selector(NSWindow.performClose(_:)), "w"),
        ])
        menu("Edit", [
            item("Undo", Selector(("undo:")), "z"),
            item("Redo", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("Cut", #selector(NSText.cut(_:)), "x"),
            item("Copy", #selector(NSText.copy(_:)), "c"),
            item("Paste", #selector(NSText.paste(_:)), "v"),
            item("Select All", #selector(NSText.selectAll(_:)), "a"),
            .separator(),
            item("Find…", #selector(focusSearch(_:)), "f", target: self),
        ])
        let appearance = NSMenuItem(title: "Appearance", action: nil, keyEquivalent: "")
        appearance.submenu = appearanceMenu()
        menu("View", [
            item("Overview", #selector(showOverview(_:)), "1", target: self),
            item("Screens", #selector(showScreens(_:)), "2", target: self),
            item("Decisions", #selector(showDecisions(_:)), "3", target: self),
            item("Activity", #selector(showActivity(_:)), "4", target: self),
            item("Chat", #selector(toggleChatAction(_:)), "0", target: self),
            .separator(),
            appearance,
            .separator(),
            item("Show or Hide Sidebar", #selector(toggleSidebarAction(_:)), "s", [.command, .control], target: self),
            item("Search…", #selector(focusSearch(_:)), "k", target: self),
            .separator(),
            item("Reload", #selector(reloadAction(_:)), "r", target: self),
        ])
        let windowMenu = menu("Window", [
            item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("Zoom", #selector(NSWindow.performZoom(_:))),
            .separator(),
            item("Bring All to Front", #selector(NSApplication.arrangeInFront(_:))),
        ])
        NSApp.windowsMenu = windowMenu
        NSApp.helpMenu = menu("Help", [item("Plots Help", #selector(openReadme(_:)), "?", target: self)])
        NSApp.mainMenu = main
    }

    // MARK: navigation, links and downloads

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction) async -> WKNavigationActionPolicy {
        guard let url = action.request.url else { return .allow }
        if action.shouldPerformDownload || url.path == "/api/export" { return .download }
        let local = url.host == "127.0.0.1" || url.host == "localhost"
        if (url.scheme == "http" || url.scheme == "https" || url.scheme == "mailto") && !local {
            NSWorkspace.shared.open(url)
            return .cancel
        }
        return .allow
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse) async -> WKNavigationResponsePolicy {
        response.canShowMIMEType ? .allow : .download
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String) async -> URL? {
        let fm = FileManager.default
        let dir = fm.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
        let name = suggestedFilename.isEmpty ? "Plots-progress.xlsx" : suggestedFilename
        var url = dir.appendingPathComponent(name)
        let stem = url.deletingPathExtension().lastPathComponent, ext = url.pathExtension
        var i = 2
        while fm.fileExists(atPath: url.path) {
            url = dir.appendingPathComponent(ext.isEmpty ? "\(stem) \(i)" : "\(stem) \(i).\(ext)")
            i += 1
        }
        downloads[ObjectIdentifier(download)] = url
        return url
    }

    func downloadDidFinish(_ download: WKDownload) {
        if let url = downloads.removeValue(forKey: ObjectIdentifier(download)) {
            NSWorkspace.shared.activateFileViewerSelecting([url])
        }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.removeValue(forKey: ObjectIdentifier(download))
        let alert = NSAlert()
        alert.messageText = "The Excel export didn’t finish."
        alert.informativeText = error.localizedDescription
        alert.beginSheetModal(for: window)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url, url.scheme == "http" || url.scheme == "https" || url.scheme == "mailto" {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    // window.prompt / confirm from the page (not used in the app, but answer them properly)
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo) async -> String? {
        let a = NSAlert()
        a.messageText = prompt
        let f = NSTextField(string: defaultText ?? "")
        f.frame = NSRect(x: 0, y: 0, width: 300, height: 24)
        a.accessoryView = f
        a.addButton(withTitle: "OK")
        a.addButton(withTitle: "Cancel")
        return a.runModal() == .alertFirstButtonReturn ? f.stringValue : nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if webView === chatWeb {
            log("loaded the chat panel \(webView.url?.absoluteString ?? "")")
            chatDidLoad()
            return
        }
        log("loaded \(webView.url?.absoluteString ?? "status page")")
        retries = 0
        guard webView.url?.host == "127.0.0.1" else { return }
        js("Plots.theme(\(jsString(appearanceMode)))")
        js("Plots.chrome()")
        lastShown = nil
        chatVisibilityChanged()
        // the Chat panel loads in the background once the page is up, so ✦ shows it at once
        if !chatRequested {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { MainActor.assumeIsolated { self.loadChat() } }
        }
        if selftestDir != nil {
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { MainActor.assumeIsolated { self.selftest() } }
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if webView === chatWeb {
            log("the chat panel didn't load: \(error.localizedDescription)")
            chatLoaded = false
            guard chatRetries < 5 else { return }
            chatRetries += 1
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { MainActor.assumeIsolated { self.loadChat(force: true) } }
            return
        }
        log("load failed: \(error.localizedDescription)")
        guard retries < 3 else { showServerError(); return }
        retries += 1
        startServer { [weak self] ok in
            guard let self else { return }
            if ok { self.loadPage() } else { self.showServerError() }
        }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        if webView === chatWeb { chatLoaded = false }
        webView.reload()
    }

    // MARK: self-test

    func selftest() {
        guard let dir = selftestDir else { return }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let probe = "JSON.stringify({ cls: document.documentElement.className, theme: document.documentElement.dataset.theme || 'auto', sbShown: getComputedStyle(document.querySelector('.sb')).display, contentPad: getComputedStyle(document.querySelector('.content')).padding, firstCard: (document.querySelector('.card') || {getBoundingClientRect(){return {}}}).getBoundingClientRect().top, bridge: (window.Plots ? 'ok' : 'none'), bg: getComputedStyle(document.body).backgroundColor, w: innerWidth, h: innerHeight })"
        web.evaluateJavaScript(probe) { result, error in
            MainActor.assumeIsolated {
                var report: [String: Any] = ["page": result as? String ?? "error: \(String(describing: error))"]
                report["window"] = NSStringFromRect(self.window.frame)
                report["webFrame"] = NSStringFromRect(self.web.convert(self.web.bounds, to: nil))
                report["title"] = self.window.title
                report["workspace"] = self.chrome.ws?.name ?? "none"
                report["workspaces"] = self.chrome.workspaces.map { "\($0.id) \($0.done)/\($0.total)" }
                report["sidebarBatches"] = self.chrome.batches.map { "\($0.id) \($0.done)/\($0.total)" }
                report["sidebarMode"] = self.sidebarMode
                report["sidebarWidth"] = self.sidebarVC.view.frame.width
                report["sidebarCollapsed"] = self.sidebarItem.isCollapsed
                report["modeGroup"] = self.modeGroup.map { "selected \($0.selectedIndex), \($0.subitems.count) items" } ?? "none"
                report["chatPanel"] = self.chatRequested ? (self.chatLoaded ? "loaded" : "loading") : "not requested"
                report["toolbarItems"] = self.window.toolbar?.items.map { $0.itemIdentifier.rawValue } ?? []
                report["appearance"] = self.window.effectiveAppearance.name.rawValue
                report["windowNumber"] = self.window.windowNumber
                if let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]) {
                    try? data.write(to: dir.appendingPathComponent("report.json"))
                }
                self.web.takeSnapshot(with: WKSnapshotConfiguration()) { image, _ in
                    MainActor.assumeIsolated {
                        if let image, let tiff = image.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                           let png = rep.representation(using: .png, properties: [:]) {
                            try? png.write(to: dir.appendingPathComponent("page.png"))
                        }
                        if CommandLine.arguments.contains("--open-chat") { self.selftestChat(dir) }
                        else if CommandLine.arguments.contains("--sidebar-test") { self.selftestSidebar(dir) }
                        // stay on screen a little so the window itself can be captured, then quit
                        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { NSApp.terminate(nil) }
                    }
                }
            }
        }
    }
}

extension AppDelegate: NSMenuItemValidation {
    // View › Chat has a checkmark while the Chat panel shows
    func validateMenuItem(_ item: NSMenuItem) -> Bool {
        if item.action == #selector(toggleChatAction(_:)) { item.state = chatShown ? .on : .off }
        return true
    }
}

extension AppDelegate {
    // `--open-chat` (self-test): opens Chat the way ⌘0 does, records what the panel and the toolbar show (chat.json,
    // chat.png: the panel by itself), then goes back to the views (views.json)
    func selftestChat(_ dir: URL) {
        toggleChatAction(nil)
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            MainActor.assumeIsolated {
                let probe = "JSON.stringify({ cls: document.documentElement.className, conv: (document.querySelector('.cp') || { dataset: {} }).dataset.conv || null, title: (document.querySelector('.cp-t span') || {}).textContent || null, ctx: (document.querySelector('.fld-ctx .tid') || {}).textContent || null, field: !!document.querySelector('#chat-msg'), focus: (document.activeElement || {}).id || null, bodyBg: getComputedStyle(document.body).backgroundColor, theme: document.documentElement.dataset.theme || 'auto', w: innerWidth, h: innerHeight })"
                self.chatWeb.evaluateJavaScript(probe) { result, error in
                    MainActor.assumeIsolated {
                        let r: [String: Any] = [
                            "panel": result as? String ?? "error: \(String(describing: error))",
                            "mode": self.sidebarMode,
                            "shown": self.chatShown,
                            "sidebarWidth": self.sidebarVC.view.frame.width,
                            "chatFrame": NSStringFromRect(self.chatWeb.convert(self.chatWeb.bounds, to: nil)),
                            "groupSelected": self.modeGroup?.selectedIndex ?? -1,
                            "badge": self.modeGroup?.badge.map { String(describing: $0) } ?? "none",
                            "dock": NSApp.dockTile.badgeLabel ?? "",
                            "tip": self.chatTip,
                            "sel": self.lastSel ?? "none",
                            "panelConv": self.panelConv ?? "none",
                            "chatFocused": self.window.firstResponder === self.chatWeb,
                        ]
                        if let data = try? JSONSerialization.data(withJSONObject: r, options: [.prettyPrinted, .sortedKeys]) {
                            try? data.write(to: dir.appendingPathComponent("chat.json"))
                        }
                        self.chatWeb.takeSnapshot(with: WKSnapshotConfiguration()) { image, _ in
                            MainActor.assumeIsolated {
                                if let image, let tiff = image.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                                   let png = rep.representation(using: .png, properties: [:]) {
                                    try? png.write(to: dir.appendingPathComponent("chat.png"))
                                }
                                // stay in Chat a while so the window can be captured, then back to the views
                                DispatchQueue.main.asyncAfter(deadline: .now() + 8) {
                                    MainActor.assumeIsolated {
                                        self.toggleChatAction(nil)
                                        DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                                            MainActor.assumeIsolated {
                                                let v: [String: Any] = ["mode": self.sidebarMode, "shown": self.chatShown,
                                                                        "sidebarWidth": self.sidebarVC.view.frame.width,
                                                                        "badge": self.modeGroup?.badge.map { String(describing: $0) } ?? "none"]
                                                if let data = try? JSONSerialization.data(withJSONObject: v, options: [.prettyPrinted, .sortedKeys]) {
                                                    try? data.write(to: dir.appendingPathComponent("views.json"))
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

extension AppDelegate {
    // `--sidebar-test` (self-test): clicks ✦, ✦ again (hide), ≡ (show the views), ≡ again (hide), ✦ (show Chat) the
    // way the toolbar does, and records after each step whether the sidebar shows and what the toolbar selects
    // (sidebar.json)
    func sidebarProbe(_ step: String) -> [String: Any] {
        let sv = sidebarVC.view
        var chain: [String] = []
        var v: NSView? = sv
        while let x = v, chain.count < 7 {
            let t = x.layer?.transform
            chain.append("\(type(of: x)) hidden=\(x.isHidden) alpha=\(x.alphaValue) frame=\(NSStringFromRect(x.frame)) layerOpacity=\(x.layer.map { String($0.opacity) } ?? "-") tx=\(t.map { "\($0.m41),\($0.m42)" } ?? "-")")
            v = x.superview
        }
        let g = modeGroup
        return [
            "step": step,
            "collapsed": sidebarItem.isCollapsed,
            "mode": sidebarMode,
            "selected": g.map { g in (0..<g.subitems.count).map { g.isSelected(at: $0) } } ?? [],
            "sidebarInWindow": NSStringFromRect(sv.convert(sv.bounds, to: nil)),
            "visibleRect": NSStringFromRect(sv.visibleRect),
            "hiddenOrAncestor": sv.isHiddenOrHasHiddenAncestor,
            "listHidden": sidebarVC.list.view.isHidden,
            "listInWindow": NSStringFromRect(sidebarVC.list.view.convert(sidebarVC.list.view.bounds, to: nil)),
            "chatHidden": chatWeb.isHidden,
            "pageX": web.convert(web.bounds, to: nil).minX,
            "min": sidebarItem.minimumThickness,
            "max": sidebarItem.maximumThickness,
            "subview0": split.splitView.subviews.first.map { "\(NSStringFromRect($0.frame)) hidden=\($0.isHidden) collapsed=\(split.splitView.isSubviewCollapsed($0))" } ?? "-",
            "chain": chain,
        ]
    }

    func selftestSidebar(_ dir: URL) {
        let steps = SidebarTestSteps()
        steps.list.append(sidebarProbe("start"))
        sidebarTestStep(0, steps, dir)
    }

    func sidebarTestStep(_ k: Int, _ steps: SidebarTestSteps, _ dir: URL) {
        // (what is checked, the segment clicked, how long until the next click); the last ones click right after
        // hiding to test rapid hide/show transitions
        let plan: [(String, Int, Double)] = [("chat", 1, 1.4), ("hidden", 1, 1.4), ("views", 0, 1.4), ("hidden-again", 0, 1.4),
                                             ("chat-from-hidden", 1, 1.4), ("views-swap", 0, 1.4), ("hide-quick", 0, 0.15),
                                             ("chat-right-after", 1, 1.6), ("hide-quick-2", 1, 0.15), ("views-right-after", 0, 1.6)]
        guard k < plan.count else {
            if let data = try? JSONSerialization.data(withJSONObject: steps.list, options: [.prettyPrinted, .sortedKeys]) {
                try? data.write(to: dir.appendingPathComponent("sidebar.json"))
            }
            return
        }
        let (name, i, wait) = plan[k]
        if let g = modeGroup { g.setSelected(!g.isSelected(at: i), at: i) }     // a click toggles the segment,
        sidebarModeAction(modeGroup)                                            // then the group sends its action
        DispatchQueue.main.asyncAfter(deadline: .now() + wait) {
            MainActor.assumeIsolated {
                var p = self.sidebarProbe(name)
                // whether the page holds its layout (it does while the sidebar slides)
                self.web.evaluateJavaScript("document.documentElement.style.width || 'free'") { r, _ in
                    MainActor.assumeIsolated {
                        p["pageHeld"] = r as? String ?? "?"
                        steps.list.append(p)
                        self.sidebarTestStep(k + 1, steps, dir)
                    }
                }
            }
        }
    }
}

final class SidebarTestSteps { var list: [[String: Any]] = [] }

// Target-action for a closure (the New Workspace sheet's folder button)
final class ButtonAction: NSObject {
    let body: () -> Void
    init(_ body: @escaping () -> Void) { self.body = body }
    @objc func fire() { body() }
}

MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.regular)
    app.run()
}
