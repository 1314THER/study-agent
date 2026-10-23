import XCTest
@testable import StudyCore

final class MemoryVault: TokenVault, @unchecked Sendable {
    let lock = NSLock()
    var value: Credentials?
    func load() throws -> Credentials? { lock.lock(); defer { lock.unlock() }; return value }
    func save(_ credentials: Credentials) throws { lock.lock(); defer { lock.unlock() }; value = credentials }
    func clear() throws { lock.lock(); defer { lock.unlock() }; value = nil }
}

final class StubProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (code, data) = try Self.handler!(request)
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: ["Content-Type":"application/json"])!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}

final class APITests: XCTestCase {
    let user: [String: Any] = ["id":"alice", "username":"Alice", "role":"user", "api_key_configured":true]
    func response(_ access: String, refresh: String = "refresh-1") throws -> Data {
        try JSONSerialization.data(withJSONObject: ["access_token":access, "refresh_token":refresh, "device_session_id":"device-1", "user":user])
    }
    override func tearDown() { StubProtocol.handler = nil; super.tearDown() }
    func client(vault: MemoryVault) throws -> APIClient {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [StubProtocol.self]
        return try APIClient(baseURL: URL(string:"https://study.example")!, vault:vault, session:URLSession(configuration:config))
    }
    func testLoginAndAutomaticSingleRefresh() async throws {
        let vault = MemoryVault()
        let lock = NSLock(); var refreshes = 0
        StubProtocol.handler = { request in
            if request.url!.path.hasSuffix("/login") { return (200, try self.response("expired")) }
            if request.url!.path.hasSuffix("/refresh") {
                lock.lock(); refreshes += 1; lock.unlock()
                return (200, try self.response("new-access",refresh:"refresh-2"))
            }
            if request.value(forHTTPHeaderField:"Authorization") == "Bearer expired" { return (401,Data("{}".utf8)) }
            return (200,Data("{\"ok\":true}".utf8))
        }
        let api = try client(vault:vault)
        _ = try await api.login(login:"alice", password:"password", deviceName:"iPad")
        async let a: JSONValue = api.send("/api/v1/progress")
        async let b: JSONValue = api.send("/api/v1/questions")
        let (first,second) = try await (a,b)
        XCTAssertTrue(first["ok"].bool); XCTAssertTrue(second["ok"].bool)
        XCTAssertEqual(refreshes,1); XCTAssertEqual(try vault.load()?.refresh_token,"refresh-2")
    }
    func testServerValidationAndCredentialsClearedOnLogout() async throws {
        let vault = MemoryVault()
        XCTAssertThrowsError(try APIClient(baseURL:URL(string:"http://public.example")!,vault:vault))
        XCTAssertThrowsError(try APIClient(baseURL:URL(string:"https://user:password@study.example")!,vault:vault))
        _ = try APIClient(baseURL:URL(string:"http://127.0.0.1:8000")!,vault:vault)
        StubProtocol.handler = { request in
            if request.url!.path.hasSuffix("/login") { return (200,try self.response("access")) }
            return (200,Data("{}".utf8))
        }
        let api = try client(vault:vault)
        _ = try await api.login(login:"alice",password:"password",deviceName:"Mac")
        try await api.signOut()
        XCTAssertNil(try vault.load())
    }
}
