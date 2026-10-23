import SwiftUI
import WebKit
import StudyCore

final class LocalScheme: NSObject, WKURLSchemeHandler {
    let root: URL
    let assets: URL?
    init(root: URL, assets: URL?) { self.root = root.resolvingSymlinksInPath(); self.assets = assets?.resolvingSymlinksInPath() }
    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let url = urlSchemeTask.request.url, url.host == "app" else { urlSchemeTask.didFailWithError(APIError.invalidResponse); return }
        let assetRequest = url.path.hasPrefix("/api/v1/assets/") || url.path.hasPrefix("/question-assets/")
        let base = assetRequest ? assets : root
        let path = assetRequest ? url.lastPathComponent : String(url.path.dropFirst())
        guard let base else { urlSchemeTask.didFailWithError(APIError.invalidResponse); return }
        let target = base.appendingPathComponent(path).resolvingSymlinksInPath()
        guard target.path.hasPrefix(base.path + "/"), let data = try? Data(contentsOf: target) else { urlSchemeTask.didFailWithError(APIError.invalidResponse); return }
        let mime = ["html": "text/html", "js": "text/javascript", "css": "text/css", "woff2": "font/woff2", "woff": "font/woff", "png": "image/png", "jpg": "image/jpeg"][target.pathExtension] ?? (assetRequest ? "image/png" : "application/octet-stream")
        urlSchemeTask.didReceive(URLResponse(url: url, mimeType: mime, expectedContentLength: data.count, textEncodingName: mime.hasPrefix("text") ? "utf-8" : nil))
        urlSchemeTask.didReceive(data); urlSchemeTask.didFinish()
    }
    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}
}

final class MathCoordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    var payload: [String: Any] = [:]
    var ready = false
    weak var webView: WKWebView?
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) { ready = true; render() }
    func render() {
        guard ready else { return }
        Task { @MainActor [weak self] in
            guard let self else { return }
            _ = try? await webView?.callAsyncJavaScript("window.render(payload)", arguments: ["payload": payload], in: nil, contentWorld: .page)
        }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let url = navigationAction.request.url
        decisionHandler(url?.scheme == "study" && url?.host == "app" ? .allow : .cancel)
    }
}

struct MathView {
    var question: Question
    var showAnswer: Bool
    var assets: URL?
    func makeCoordinator() -> MathCoordinator { MathCoordinator() }
    func create(_ coordinator: MathCoordinator) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.setURLSchemeHandler(LocalScheme(root: WebResources.root, assets: assets), forURLScheme: "study")
        config.userContentController.add(coordinator, name: "ready")
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = coordinator; coordinator.webView = view
        update(coordinator)
        view.load(URLRequest(url: URL(string: "study://app/index.html")!))
        return view
    }
    func update(_ coordinator: MathCoordinator) {
        let answer = (try? JSONSerialization.jsonObject(with: JSONEncoder().encode(question.answer_json))) ?? [:]
        coordinator.payload = ["content": question.content, "answer_json": answer, "showAnswer": showAnswer]
        coordinator.render()
    }
}

#if os(macOS)
extension MathView: NSViewRepresentable {
    func makeNSView(context: Context) -> WKWebView { create(context.coordinator) }
    func updateNSView(_ nsView: WKWebView, context: Context) { update(context.coordinator) }
}
#else
extension MathView: UIViewRepresentable {
    func makeUIView(context: Context) -> WKWebView { create(context.coordinator) }
    func updateUIView(_ uiView: WKWebView, context: Context) { update(context.coordinator) }
}
#endif
