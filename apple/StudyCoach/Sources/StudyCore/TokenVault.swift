import Foundation
import Security

public protocol TokenVault: Sendable {
    func load() throws -> Credentials?
    func save(_ credentials: Credentials) throws
    func clear() throws
}

public struct KeychainVault: TokenVault {
    private let service: String
    public init(server: URL) { service = "chat.150.studycoach." + server.absoluteString }
    private var query: [String: Any] {
        var q: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                               kSecAttrService as String: service, kSecAttrAccount as String: "device-session"]
        #if os(macOS)
        q[kSecUseDataProtectionKeychain as String] = true
        #endif
        return q
    }
    public func load() throws -> Credentials? {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let code = SecItemCopyMatching(q as CFDictionary, &item)
        if code == errSecItemNotFound { return nil }
        guard code == errSecSuccess, let data = item as? Data else { throw VaultError.status(code) }
        return try JSONDecoder().decode(Credentials.self, from: data)
    }
    public func save(_ credentials: Credentials) throws {
        let data = try JSONEncoder().encode(credentials)
        let updated = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if updated == errSecSuccess { return }
        guard updated == errSecItemNotFound else { throw VaultError.status(updated) }
        var q = query
        q[kSecValueData as String] = data
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let code = SecItemAdd(q as CFDictionary, nil)
        guard code == errSecSuccess else { throw VaultError.status(code) }
    }
    public func clear() throws {
        let code = SecItemDelete(query as CFDictionary)
        guard code == errSecSuccess || code == errSecItemNotFound else { throw VaultError.status(code) }
    }
}

public enum VaultError: LocalizedError {
    case status(OSStatus)
    public var errorDescription: String? {
        switch self {
        case .status(let code):
            if code == -34018 { return "此构建缺少钥匙串签名权限。请在 Xcode 中选择开发团队并签名后运行。" }
            let detail = SecCopyErrorMessageString(code, nil) as String? ?? "系统钥匙串不可用"
            return "无法保存登录凭证（\(code)）：\(detail)"
        }
    }
}
