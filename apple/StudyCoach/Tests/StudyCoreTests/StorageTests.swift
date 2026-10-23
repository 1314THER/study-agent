import XCTest
@testable import StudyCore

final class StorageTests: XCTestCase {
    func testDraftAndDownloadedQuestionsSurviveReopen() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let server = URL(string: "https://study.example")!
        let q = Question(id: UUID().uuidString, content: "计算 $1+1$")
        do {
            let store = try SQLiteStore(root: root, server: server, userID: "alice")
            try store.save([q], kind: "questions", key: "all")
            try store.saveDraft(questionID: q.id, text: "先看条件", drawing: Data([1,2,3]))
        }
        let reopened = try SQLiteStore(root: root, server: server, userID: "alice")
        XCTAssertEqual(try reopened.read([Question].self, kind: "questions", key: "all"), [q])
        XCTAssertEqual(try reopened.read(Draft.self, kind: "draft", key: q.id)?.text, "先看条件")
        XCTAssertEqual(try reopened.drawing(questionID: q.id), Data([1,2,3]))
        XCTAssertTrue(reopened.hasDrafts())
    }
    func testAccountsAndServersNeverShareCaches() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let server = URL(string: "https://study.example")!
        let a = try SQLiteStore(root: root, server: server, userID: "alice")
        let b = try SQLiteStore(root: root, server: server, userID: "bob")
        let otherServer = try SQLiteStore(root: root, server: URL(string: "https://other.example")!, userID: "alice")
        try a.saveDraft(questionID: "q", text: "private")
        XCTAssertNil(try b.read(Draft.self, kind: "draft", key: "q"))
        XCTAssertNil(try otherServer.read(Draft.self, kind: "draft", key: "q"))
        try a.erase()
        XCTAssertFalse(FileManager.default.fileExists(atPath: a.directory.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: b.directory.path))
    }
    func testBundledRendererWorksWithoutRemoteAssets() throws {
        let html = try String(contentsOf: WebResources.root.appendingPathComponent("index.html"), encoding: .utf8)
        XCTAssertTrue(html.contains("trust:false"))
        XCTAssertFalse(html.contains("https://cdn"))
        for file in ["geometry.js", "vendor/katex/katex.min.js", "vendor/jsxgraph-1.11.1/distrib/jsxgraphcore.js", "vendor/three-0.180.0/build/three.module.min.js"] {
            XCTAssertTrue(FileManager.default.fileExists(atPath: WebResources.root.appendingPathComponent(file).path))
        }
    }
}
