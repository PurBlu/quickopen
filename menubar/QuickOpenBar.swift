import AppKit
import Foundation

// 秒开门 · macOS 菜单栏小工具
// 零第三方依赖，只用 AppKit / Foundation，编译后常驻内存约 10 MB。
// 只连本机 127.0.0.1 的服务，不承担开门协议，也不保存任何凭据。

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private let port = ProcessInfo.processInfo.environment["QO_PORT"] ?? "8787"
    private var base: String { "http://127.0.0.1:\(port)" }
    private var statusItem: NSStatusItem!
    private var timer: Timer?

    private let menu = NSMenu()
    private let stateItem = NSMenuItem(title: "正在连接…", action: nil, keyEquivalent: "")
    private let sessionItem = NSMenuItem(title: "会话：—", action: nil, keyEquivalent: "")
    private let resourceItem = NSMenuItem(title: "资源：—", action: nil, keyEquivalent: "")
    private let statItem = NSMenuItem(title: "统计：—", action: nil, keyEquivalent: "")
    private let defaultOpenItem = NSMenuItem(title: "一键开门（默认门）", action: #selector(openDefaultDoor), keyEquivalent: "o")
    private let doorsItem = NSMenuItem(title: "开指定门", action: nil, keyEquivalent: "")
    private let defaultDoorItem = NSMenuItem(title: "设为默认门", action: nil, keyEquivalent: "")
    private let panelItem = NSMenuItem(title: "打开控制面板…", action: #selector(openPanel), keyEquivalent: "p")
    private let restartItem = NSMenuItem(title: "重启后台服务", action: #selector(restartService), keyEquivalent: "r")
    private let quitItem = NSMenuItem(title: "退出菜单栏（服务继续运行）", action: #selector(quit), keyEquivalent: "q")

    private let doorsMenu = NSMenu()
    private let defaultsMenu = NSMenu()
    private var keys: [[String: Any]] = []
    private var defaultKeyId = ""
    private var lastKeySignature = ""

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let image = NSImage(systemSymbolName: "lock.open", accessibilityDescription: "秒开门") {
            image.isTemplate = true
            statusItem.button?.image = image
        } else {
            statusItem.button?.title = "门"
        }
        statusItem.button?.toolTip = "秒开门"

        for item in [stateItem, sessionItem, resourceItem, statItem] { item.isEnabled = false }
        for item in [defaultOpenItem, panelItem, restartItem, quitItem] { item.target = self }

        doorsMenu.delegate = self
        defaultsMenu.delegate = self
        doorsItem.submenu = doorsMenu
        defaultDoorItem.submenu = defaultsMenu
        rebuildDoorMenus()

        menu.addItem(stateItem)
        menu.addItem(sessionItem)
        menu.addItem(resourceItem)
        menu.addItem(statItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(defaultOpenItem)
        menu.addItem(doorsItem)
        menu.addItem(defaultDoorItem)
        menu.addItem(panelItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(restartItem)
        menu.addItem(quitItem)
        menu.delegate = self
        statusItem.menu = menu

        refresh()
        timer = Timer.scheduledTimer(timeInterval: 20, target: self,
                                     selector: #selector(refresh), userInfo: nil, repeats: true)
    }

    // MARK: - 钥匙菜单

    private func rebuildDoorMenus() {
        doorsMenu.removeAllItems()
        defaultsMenu.removeAllItems()
        if keys.isEmpty {
            let none = NSMenuItem(title: "尚未登录或无可用钥匙", action: nil, keyEquivalent: "")
            none.isEnabled = false
            doorsMenu.addItem(none)
            let none2 = NSMenuItem(title: "请先在控制面板登录", action: nil, keyEquivalent: "")
            none2.isEnabled = false
            defaultsMenu.addItem(none2)
            doorsItem.isEnabled = false
            defaultDoorItem.isEnabled = false
            return
        }
        doorsItem.isEnabled = true
        defaultDoorItem.isEnabled = true
        for k in keys {
            let id = k["id"] as? String ?? ""
            let name = k["name"] as? String ?? "未命名门"
            let isDefault = id == defaultKeyId

            let open = NSMenuItem(title: isDefault ? "\(name)  （默认）" : name,
                                  action: #selector(openSpecificDoor(_:)), keyEquivalent: "")
            open.target = self
            open.representedObject = id
            open.toolTip = "立即打开：\(name)"
            doorsMenu.addItem(open)

            let pick = NSMenuItem(title: name, action: #selector(setDefaultDoor(_:)), keyEquivalent: "")
            pick.target = self
            pick.representedObject = id
            pick.state = isDefault ? .on : .off
            defaultsMenu.addItem(pick)
        }
        doorsItem.title = "开指定门（\(keys.count) 把）"
    }

    private func request(_ path: String, method: String = "GET", payload: [String: Any]? = nil,
                         completion: @escaping (Data?) -> Void) {
        guard let url = URL(string: base + path) else { completion(nil); return }
        var req = URLRequest(url: url, timeoutInterval: 6)
        req.httpMethod = method
        if method == "POST" {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let obj = payload ?? [:]
            req.httpBody = try? JSONSerialization.data(withJSONObject: obj, options: [])
        }
        URLSession.shared.dataTask(with: req) { data, _, _ in
            DispatchQueue.main.async { completion(data) }
        }.resume()
    }

    private func showTransient(_ title: String, on item: NSMenuItem, restore: @escaping () -> String) {
        item.title = title
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { [weak item] in
            item?.title = restore()
        }
    }

    @objc func refresh() {
        request("/api/status") { [weak self] data in
            guard let self = self else { return }
            guard let data = data,
                  let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                self.stateItem.title = "服务：离线（Mac mini 未运行）"
                self.sessionItem.title = "会话：—"
                self.resourceItem.title = "资源：—"
                self.statItem.title = "统计：—"
                self.statusItem.button?.toolTip = "后台服务未响应"
                self.defaultOpenItem.isEnabled = false
                self.doorsItem.isEnabled = false
                return
            }
            let logged = j["logged_in"] as? Bool ?? false
            let invalid = j["session_invalid"] as? Bool ?? false
            self.stateItem.title = "服务：● 在线  v\(j["version"] as? String ?? "?")"
            if !logged {
                self.sessionItem.title = "会话：未登录，请在控制面板登录"
            } else if invalid {
                self.sessionItem.title = "会话：⚠ 已失效，请重新登录"
            } else {
                let last = j["last_ok_at"] as? Double ?? 0
                let ago = Int(Date().timeIntervalSince1970 - last)
                self.sessionItem.title = "会话：● 正常（\(self.duration(ago))前成功）"
            }
            let rss = j["rss_mb"] as? Double ?? 0
            let cpu = j["cpu_pct"] as? Double ?? 0
            let threads = j["threads"] as? Int ?? 0
            let up = j["uptime_s"] as? Int ?? 0
            self.resourceItem.title = String(format: "资源：内存 %.1f MB · CPU %.2f%% · %d 线程 · 已运行 %@",
                                             rss, cpu, threads, self.duration(up))
            let stats = j["stats"] as? [String: Any] ?? [:]
            let okCount = stats["open_ok"] as? Int ?? 0
            let failCount = stats["open_fail"] as? Int ?? 0
            self.statItem.title = "统计：成功 \(okCount) · 失败 \(failCount)"

            self.keys = j["keys"] as? [[String: Any]] ?? []
            self.defaultKeyId = j["default_key_id"] as? String ?? ""
            let signature = self.keys.map { ($0["id"] as? String ?? "") + "|" + ($0["name"] as? String ?? "") }
                .joined(separator: ",") + "#" + self.defaultKeyId
            if signature != self.lastKeySignature {
                self.lastKeySignature = signature
                self.rebuildDoorMenus()
            }
            self.defaultOpenItem.isEnabled = logged && !invalid && !self.keys.isEmpty
            self.statusItem.button?.toolTip = "秒开门 · 服务在线 · \(self.keys.count) 把钥匙"
        }
    }

    private func duration(_ seconds: Int) -> String {
        let s = max(0, seconds)
        if s < 60 { return "\(s)秒" }
        if s < 3600 { return "\(s / 60)分钟" }
        if s < 86400 { return "\(s / 3600)小时" }
        return "\(s / 86400)天"
    }

    private func handleOpenResult(_ data: Data?, on item: NSMenuItem, restore: @escaping () -> String) {
        var text = "开门失败"
        if let data = data,
           let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if j["ok"] as? Bool == true {
                text = "✓ 已开门 \(j["ms"] as? Int ?? 0)ms"
            } else if let m = j["message"] as? String {
                text = "✕ " + m
            }
        }
        showTransient(text, on: item, restore: restore)
        refresh()
    }

    @objc func openDefaultDoor() {
        let original = "一键开门（默认门）"
        defaultOpenItem.isEnabled = false
        defaultOpenItem.title = "正在开门…"
        request("/api/open", method: "POST") { [weak self] data in
            guard let self = self else { return }
            self.handleOpenResult(data, on: self.defaultOpenItem) { original }
            self.defaultOpenItem.isEnabled = true
        }
    }

    @objc func openSpecificDoor(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String, !id.isEmpty else { return }
        let originalTitle = sender.title
        let name = (keys.first { ($0["id"] as? String) == id })?["name"] as? String ?? "门"
        sender.isEnabled = false
        sender.title = "正在打开 \(name)…"
        request("/api/open", method: "POST", payload: ["key_id": id]) { [weak self, weak sender] data in
            guard let self = self, let sender = sender else { return }
            self.handleOpenResult(data, on: self.doorsItem, restore: { "开指定门（\(self.keys.count) 把）" })
            sender.isEnabled = true
            sender.title = originalTitle
        }
    }

    @objc func setDefaultDoor(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String, !id.isEmpty else { return }
        request("/api/set-default", method: "POST", payload: ["key_id": id]) { [weak self] data in
            guard let self = self else { return }
            if let data = data,
               let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               j["ok"] as? Bool == true {
                self.defaultKeyId = id
                self.lastKeySignature = ""
                self.showTransient("✓ 已设为默认门", on: self.defaultDoorItem, restore: { "设为默认门" })
            }
            self.refresh()
        }
    }

    @objc func openPanel() {
        if let url = URL(string: base) { NSWorkspace.shared.open(url) }
    }

    @objc func restartService() {
        let uid = getuid()
        let task = Process()
        task.launchPath = "/bin/launchctl"
        task.arguments = ["kickstart", "-k", "gui/\(uid)/cn.quickopen.door"]
        try? task.run()
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in self?.refresh() }
    }

    @objc func quit() { NSApp.terminate(nil) }

    func menuWillOpen(_ menu: NSMenu) {
        if menu === self.menu { refresh() }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
