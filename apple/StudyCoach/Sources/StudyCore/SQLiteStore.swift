import Foundation
import CryptoKit
import SQLite3

public final class SQLiteStore: @unchecked Sendable {
    public let directory: URL
    public let assetDirectory: URL
    private var db: OpaquePointer?
    private let lock = NSRecursiveLock()
    private let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    public init(root: URL, server: URL, userID: String) throws {
        let scope = SHA256.hash(data: Data((server.absoluteString + ":" + userID).utf8)).map { String(format: "%02x", $0) }.joined()
        directory = root.appendingPathComponent(scope, isDirectory: true)
        assetDirectory = directory.appendingPathComponent("assets", isDirectory: true)
        try FileManager.default.createDirectory(at: assetDirectory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        guard sqlite3_open(directory.appendingPathComponent("cache.sqlite3").path, &db) == SQLITE_OK else { throw StorageError.database }
        try execute("PRAGMA journal_mode=WAL")
        try execute("CREATE TABLE IF NOT EXISTS cache (kind TEXT NOT NULL, key TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(kind,key))")
        try execute("PRAGMA user_version=1")
    }

    deinit { sqlite3_close(db) }

    private func execute(_ sql: String) throws {
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else { throw StorageError.database }
    }

    public func save<T: Encodable>(_ value: T, kind: String, key: String) throws {
        lock.lock(); defer { lock.unlock() }
        let data = try JSONEncoder().encode(value)
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, "INSERT INTO cache VALUES (?,?,?) ON CONFLICT(kind,key) DO UPDATE SET data=excluded.data", -1, &stmt, nil) == SQLITE_OK else { throw StorageError.database }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, kind, -1, transient); sqlite3_bind_text(stmt, 2, key, -1, transient)
        _ = data.withUnsafeBytes { sqlite3_bind_blob(stmt, 3, $0.baseAddress, Int32(data.count), transient) }
        guard sqlite3_step(stmt) == SQLITE_DONE else { throw StorageError.database }
    }

    public func read<T: Decodable>(_ type: T.Type, kind: String, key: String) throws -> T? {
        lock.lock(); defer { lock.unlock() }
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, "SELECT data FROM cache WHERE kind=? AND key=?", -1, &stmt, nil) == SQLITE_OK else { throw StorageError.database }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, kind, -1, transient); sqlite3_bind_text(stmt, 2, key, -1, transient)
        guard sqlite3_step(stmt) == SQLITE_ROW else { return nil }
        let data = Data(bytes: sqlite3_column_blob(stmt, 0), count: Int(sqlite3_column_bytes(stmt, 0)))
        return try JSONDecoder().decode(type, from: data)
    }

    public func saveDraft(questionID: String, text: String, drawing: Data? = nil) throws {
        lock.lock(); defer { lock.unlock() }
        var draft = try read(Draft.self, kind: "draft", key: questionID) ?? Draft()
        draft.text = text; draft.updatedAt = .now
        if let drawing {
            let name = UUID().uuidString + ".drawing"
            try drawing.write(to: directory.appendingPathComponent(name), options: .atomic)
            if let old = draft.drawingFile { try? FileManager.default.removeItem(at: directory.appendingPathComponent(old)) }
            draft.drawingFile = name
        }
        try save(draft, kind: "draft", key: questionID)
    }

    public func drawing(questionID: String) throws -> Data? {
        guard let name = try read(Draft.self, kind: "draft", key: questionID)?.drawingFile else { return nil }
        return try Data(contentsOf: directory.appendingPathComponent(name))
    }

    public func hasDrafts() -> Bool {
        lock.lock(); defer { lock.unlock() }
        var statement: OpaquePointer?
        sqlite3_prepare_v2(db, "SELECT 1 FROM cache WHERE kind='draft' LIMIT 1", -1, &statement, nil)
        defer { sqlite3_finalize(statement) }
        return sqlite3_step(statement) == SQLITE_ROW
    }

    public func remove(kind: String, key: String) throws {
        lock.lock(); defer { lock.unlock() }
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, "DELETE FROM cache WHERE kind=? AND key=?", -1, &stmt, nil) == SQLITE_OK else { throw StorageError.database }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, kind, -1, transient); sqlite3_bind_text(stmt, 2, key, -1, transient)
        guard sqlite3_step(stmt) == SQLITE_DONE else { throw StorageError.database }
    }

    public func erase() throws {
        lock.lock(); defer { lock.unlock() }
        try execute("DELETE FROM cache")
        sqlite3_close(db); db = nil
        try FileManager.default.removeItem(at: directory)
    }
}

public enum StorageError: Error { case database }
