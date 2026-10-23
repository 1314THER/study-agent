import Foundation

public enum APIError: LocalizedError {
    case insecureServer, notSignedIn, response(Int, String), invalidResponse
    public var errorDescription: String? {
        switch self {
        case .insecureServer: return "服务器须使用 HTTPS；本机调试可使用 localhost。"
        case .notSignedIn: return "登录已过期，请重新登录。"
        case .response(_, let message): return message
        case .invalidResponse: return "服务器返回格式无效。"
        }
    }
}

public actor APIClient {
    public let baseURL: URL
    private let session: URLSession
    private let vault: any TokenVault
    private var credentials: Credentials?
    private var refreshing: Task<Credentials, Error>?

    public init(baseURL: URL, vault: any TokenVault, session: URLSession = .init(configuration: .ephemeral)) throws {
        guard baseURL.scheme == "https" || (baseURL.scheme == "http" && ["localhost", "127.0.0.1", "[::1]", "::1"].contains(baseURL.host ?? "")),
              baseURL.user == nil, baseURL.password == nil, baseURL.query == nil, baseURL.fragment == nil,
              baseURL.path.isEmpty || baseURL.path == "/" else { throw APIError.insecureServer }
        self.baseURL = baseURL; self.vault = vault; self.session = session
        credentials = try vault.load()
    }

    public func savedUser() -> User? { credentials?.user }
    public func deviceID() -> String? { credentials?.device_session_id }

    public func login(login: String, password: String, deviceName: String) async throws -> User {
        let result: Credentials = try await send("/api/v1/auth/login", method: "POST", body: .object([
            "login": .string(login), "password": .string(password), "device_name": .string(deviceName)]), authenticated: false)
        try vault.save(result); credentials = result
        return result.user
    }

    public func register(fields: [String: JSONValue]) async throws -> User {
        let result: Credentials = try await send("/api/v1/auth/register", method: "POST", body: .object(fields), authenticated: false)
        try vault.save(result); credentials = result
        return result.user
    }

    public func signOut() async throws {
        if let id = credentials?.device_session_id {
            let _: JSONValue = try await send("/api/v1/auth/devices/" + id, method: "DELETE")
        }
        try clearLocalCredentials()
    }

    public func clearLocalCredentials() throws {
        refreshing?.cancel(); refreshing = nil
        try vault.clear(); credentials = nil
    }

    private func refresh() async throws {
        if let task = refreshing { credentials = try await task.value; return }
        guard let old = credentials else { throw APIError.notSignedIn }
        let task = Task<Credentials, Error> {
            try await self.send("/api/v1/auth/refresh", method: "POST", body: .object(["refresh_token": .string(old.refresh_token)]), authenticated: false)
        }
        refreshing = task
        defer { refreshing = nil }
        let result = try await task.value
        try vault.save(result); credentials = result
    }

    private func request(_ path: String, method: String, body: Data?, contentType: String?, authenticated: Bool, retry: Bool = true) async throws -> Data {
        guard path.hasPrefix("/"), !path.hasPrefix("//"), let url = URL(string: path, relativeTo: baseURL)?.absoluteURL,
              url.host == baseURL.host, url.scheme == baseURL.scheme else { throw APIError.invalidResponse }
        var request = URLRequest(url: url)
        request.httpMethod = method; request.httpBody = body; request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let contentType { request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        if authenticated {
            guard let token = credentials?.access_token else { throw APIError.notSignedIn }
            request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        if http.statusCode == 401 && authenticated && retry {
            // A concurrent request may already have replaced this access token.
            if request.value(forHTTPHeaderField: "Authorization") == "Bearer " + (credentials?.access_token ?? "") {
                try await refresh()
            }
            return try await self.request(path, method: method, body: body, contentType: contentType, authenticated: authenticated, retry: false)
        }
        guard (200..<300).contains(http.statusCode) else {
            let detail = (try? JSONDecoder().decode(JSONValue.self, from: data))?["detail"].string ?? ""
            throw APIError.response(http.statusCode, detail.isEmpty ? "请求未完成，请稍后重试。" : detail)
        }
        return data
    }

    public func send<T: Decodable>(_ path: String, method: String = "GET", body: JSONValue? = nil, authenticated: Bool = true) async throws -> T {
        let data = try await request(path, method: method, body: try body.map { try JSONEncoder().encode($0) }, contentType: body == nil ? nil : "application/json", authenticated: authenticated)
        return try JSONDecoder().decode(T.self, from: data)
    }

    public func download(_ path: String) async throws -> Data {
        try await request(path, method: "GET", body: nil, contentType: nil, authenticated: true)
    }

    public func upload(data: Data, filename: String, mediaType: String) async throws -> JSONValue {
        guard data.count <= 32 * 1024 * 1024 else { throw APIError.response(413, "附件须在 32 MB 内") }
        let boundary = UUID().uuidString
        let safeName = filename.replacingOccurrences(of: "\"", with: "").replacingOccurrences(of: "\r", with: "").replacingOccurrences(of: "\n", with: "")
        var body = Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(safeName)\"\r\nContent-Type: \(mediaType)\r\n\r\n".utf8)
        body.append(data); body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        let result = try await request("/api/v1/assets", method: "POST", body: body, contentType: "multipart/form-data; boundary=" + boundary, authenticated: true)
        return try JSONDecoder().decode(JSONValue.self, from: result)
    }
}
