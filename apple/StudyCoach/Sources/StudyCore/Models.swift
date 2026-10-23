import Foundation

public enum JSONValue: Codable, Sendable, Hashable {
    case object([String: JSONValue]), array([JSONValue]), string(String), number(Double), bool(Bool), null
    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .object(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
    public subscript(_ key: String) -> JSONValue { if case .object(let d) = self { return d[key] ?? .null }; return .null }
    public var string: String { if case .string(let s) = self { return s }; return "" }
    public var int: Int { if case .number(let n) = self { return Int(n) }; return 0 }
    public var bool: Bool { if case .bool(let b) = self { return b }; return false }
    public var array: [JSONValue] { if case .array(let a) = self { return a }; return [] }
    public var object: [String: JSONValue] { if case .object(let d) = self { return d }; return [:] }
    public var pretty: String { let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]; guard let data = try? encoder.encode(self) else { return "" }; return String(decoding: data, as: UTF8.self) }
}

public struct User: Codable, Sendable, Identifiable, Equatable {
    public var id: String
    public var username: String
    public var email: String?
    public var role: String
    public var api_key_configured: Bool
}

public struct Credentials: Codable, Sendable {
    public var access_token: String
    public var refresh_token: String
    public var device_session_id: String
    public var user: User
}

public struct Question: Codable, Sendable, Identifiable, Hashable {
    public var id: String
    public var content: String
    public var answer_json: JSONValue
    public var revision: Int
    public var owner_user_id: String?
    public var active: Bool
    public static func == (lhs: Self, rhs: Self) -> Bool { lhs.id == rhs.id && lhs.revision == rhs.revision }
    public func hash(into hasher: inout Hasher) { hasher.combine(id); hasher.combine(revision) }
    public init(id: String, content: String, answer_json: JSONValue = .object([:]), revision: Int = 1, owner_user_id: String? = nil, active: Bool = true) {
        self.id = id; self.content = content; self.answer_json = answer_json; self.revision = revision; self.owner_user_id = owner_user_id; self.active = active
    }
}

public struct Page<T: Codable & Sendable>: Codable, Sendable {
    public var items: [T]
    public var total: Int
    public var offset: Int
    public var limit: Int
}

public struct Items<T: Codable & Sendable>: Codable, Sendable { public var items: [T] }

public struct Job: Codable, Sendable, Identifiable {
    public var id: String
    public var kind: String
    public var status: String
    public var stage: String
    public var progress: Int
    public var result: JSONValue?
    public var error: JSONValue?
    public var args: JSONValue
    public var request_id: String
    public var terminal: Bool { ["done", "error", "interrupted", "cancelled"].contains(status) }
}

public struct Draft: Codable, Sendable {
    public var text: String
    public var drawingFile: String?
    public var updatedAt: Date
    public init(text: String = "", drawingFile: String? = nil, updatedAt: Date = .now) {
        self.text = text; self.drawingFile = drawingFile; self.updatedAt = updatedAt
    }
}

public enum WebResources {
    public static var root: URL { Bundle.module.url(forResource: "Web", withExtension: nil)! }
}
