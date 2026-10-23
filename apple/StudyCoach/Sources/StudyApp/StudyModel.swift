import SwiftUI
import StudyCore
#if os(iOS)
import UIKit
#endif

@MainActor @Observable
final class StudyModel {
    var server = UserDefaults.standard.string(forKey: "study-server") ?? "https://150.chat"
    var client: APIClient?
    var user: User?
    var cache: SQLiteStore?
    var questions: [Question] = []
    var wrongQuestions: [Question] = []
    var wrongTotal = 0
    var total = 0
    var jobs: [Job] = []
    var teaching: [JSONValue] = []
    var progress: JSONValue = .null
    var message: String?
    var offline = false
    var busy = false
    var registrationEnabled = false
    var results: [String: JSONValue] = [:]
    var polling: [String: Task<Void, Never>] = [:]

    private var root: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("StudyCoach", isDirectory: true)
    }
    var deviceName: String {
        #if os(macOS)
        return Host.current().localizedName ?? "Mac"
        #else
        return UIDevice.current.name
        #endif
    }

    func connect() throws -> APIClient {
        guard let url = URL(string: server.trimmingCharacters(in: .whitespacesAndNewlines)) else { throw APIError.insecureServer }
        let api = try APIClient(baseURL: url, vault: KeychainVault(server: url))
        client = api
        UserDefaults.standard.set(url.absoluteString, forKey: "study-server")
        return api
    }

    func restore() async {
        do {
            let api = try connect()
            guard let saved = await api.savedUser() else { return }
            try openCache(for: saved)
            await reload()
        } catch { message = error.localizedDescription }
    }

    func configureRegistration() async {
        do {
            let api = try connect()
            let config: JSONValue = try await api.send("/auth/config", authenticated: false)
            registrationEnabled = config["registration_enabled"].bool
        } catch { registrationEnabled = false; message = error.localizedDescription }
    }

    func openCache(for user: User) throws {
        guard let url = URL(string: server) else { throw APIError.insecureServer }
        let store = try SQLiteStore(root: root, server: url, userID: user.id)
        self.user = user; cache = store
        questions = try store.read([Question].self, kind: "questions", key: "all") ?? []
        wrongQuestions = try store.read([Question].self, kind: "questions", key: "wrong") ?? []
        jobs = try store.read([Job].self, kind: "jobs", key: "all") ?? []
        teaching = try store.read([JSONValue].self, kind: "teaching", key: "all") ?? []
        progress = try store.read(JSONValue.self, kind: "progress", key: "all") ?? .null
    }

    func login(identifier: String, password: String) async {
        busy = true; defer { busy = false }
        do {
            let api = try connect()
            let user = try await api.login(login: identifier, password: password, deviceName: deviceName)
            try openCache(for: user); await reload()
        } catch { message = error.localizedDescription }
    }

    func sendCode(email: String) async {
        do {
            let api = try client ?? connect()
            let _: JSONValue = try await api.send("/api/v1/auth/email-code", method: "POST", body: .object(["email": .string(email)]), authenticated: false)
            message = "验证码已申请发送，请检查收件箱与垃圾邮件。"
        } catch { message = error.localizedDescription }
    }

    func register(username: String, email: String, password: String, code: String, key: String) async {
        busy = true; defer { busy = false }
        do {
            let api = try client ?? connect()
            let user = try await api.register(fields: ["username": .string(username), "email": .string(email), "password": .string(password), "code": .string(code), "api_key": .string(key), "device_name": .string(deviceName)])
            try openCache(for: user); await reload()
        } catch { message = error.localizedDescription }
    }

    func loadQuestions(query: String = "", wrong: Bool = false, more: Bool = false) async {
        guard let api = client else { return }
        do {
            let offset = more ? (wrong ? wrongQuestions.count : questions.count) : 0
            var components = URLComponents()
            components.path = "/api/v1/questions"
            components.queryItems = [.init(name: "q", value: query), .init(name: "wrong", value: String(wrong)), .init(name: "offset", value: String(offset)), .init(name: "limit", value: "50")]
            let page: Page<Question> = try await api.send(components.string!)
            if wrong {
                wrongQuestions = more ? wrongQuestions + page.items : page.items
                wrongTotal = page.total
                if query.isEmpty { try cache?.save(wrongQuestions, kind: "questions", key: "wrong") }
            } else {
                questions = more ? questions + page.items : page.items
                total = page.total
            }
            offline = false
            if !wrong && query.isEmpty { try cache?.save(questions, kind: "questions", key: "all") }
            for question in page.items { try cache?.save(question, kind: "question", key: question.id) }
        } catch { offline = true; message = "连接暂不可用，已下载的题目和草稿仍可使用。" }
    }

    func reload() async {
        guard user != nil, let api = client else { return }
        await loadQuestions()
        await loadQuestions(wrong: true)
        do {
            progress = try await api.send("/api/v1/progress")
            let history: Items<Job> = try await api.send("/api/v1/jobs")
            let sessions: Items<JSONValue> = try await api.send("/api/v1/teaching")
            jobs = history.items; teaching = sessions.items
            try cache?.save(jobs, kind: "jobs", key: "all")
            try cache?.save(teaching, kind: "teaching", key: "all")
            try cache?.save(progress, kind: "progress", key: "all")
            for job in jobs where !job.terminal { watch(job) }
        } catch { offline = true }
    }

    func submit(kind: String, args: [String: JSONValue], channel: String) async {
        guard let api = client else { return }
        do {
            let body = JSONValue.object(["kind": .string(kind), "args": .object(args)])
            // Persist the request ID BEFORE networking. An ambiguous timeout can
            // safely retry the same action without starting another AI call.
            let encoded = body.pretty
            let previous = try cache?.read(JSONValue.self, kind: "pending", key: channel)
            let requestID = previous?["fingerprint"].string == encoded ? previous!["request_id"].string : UUID().uuidString
            try cache?.save(JSONValue.object(["fingerprint": .string(encoded), "request_id": .string(requestID)]), kind: "pending", key: channel)
            let job: Job = try await api.send("/api/v1/jobs", method: "POST", body: .object(["kind": .string(kind), "args": .object(args), "request_id": .string(requestID)]))
            try cache?.save(channel, kind: "job-channel", key: job.id)
            jobs.removeAll { $0.id == job.id }; jobs.insert(job, at: 0)
            try cache?.save(jobs, kind: "jobs", key: "all")
            watch(job)
        } catch { message = error.localizedDescription }
    }

    func watch(_ job: Job) {
        guard polling[job.id] == nil, let api = client else { return }
        polling[job.id] = Task { [weak self] in
            defer { self?.polling[job.id] = nil }
            while !Task.isCancelled {
                do {
                    let current: Job = try await api.send("/api/v1/jobs/" + job.id)
                    guard let self, !Task.isCancelled, self.user != nil else { return }
                    if let index = self.jobs.firstIndex(where: { $0.id == current.id }) { self.jobs[index] = current }
                    try self.cache?.save(self.jobs, kind: "jobs", key: "all")
                    if current.terminal {
                        if let channel = try self.cache?.read(String.self, kind: "job-channel", key: current.id) {
                            try self.cache?.remove(kind: "pending", key: channel)
                            try self.cache?.remove(kind: "job-channel", key: current.id)
                        }
                        if let result = current.result {
                            self.results[current.args["question_id"].string] = result
                            if current.kind == "parse_file" { self.results["import"] = result }
                        }
                        if current.status != "done" { self.message = current.error?["detail"].string ?? current.stage }
                        await self.reload()
                        return
                    }
                    try await Task.sleep(for: .seconds(2))
                } catch is CancellationError { return }
                catch { self?.offline = true; return }
            }
        }
    }

    func draft(_ id: String) -> String { (try? cache?.read(Draft.self, kind: "draft", key: id))?.text ?? "" }
    func saveDraft(_ id: String, text: String, drawing: Data? = nil) {
        do { try cache?.saveDraft(questionID: id, text: text, drawing: drawing) }
        catch { message = "草稿未能保存，请检查设备存储空间。" }
    }

    func upload(_ data: Data, filename: String, mediaType: String) async throws -> String {
        guard let api = client else { throw APIError.notSignedIn }
        let result = try await api.upload(data: data, filename: filename, mediaType: mediaType)
        return result["id"].string
    }

    func cacheResources(_ question: Question) async {
        guard let api = client, let cache else { return }
        for ref in question.answer_json["asset_refs"].array.map(\.string) where !ref.isEmpty {
            let file = cache.assetDirectory.appendingPathComponent(ref)
            if FileManager.default.fileExists(atPath: file.path) { continue }
            do {
                let path = UUID(uuidString: ref) == nil ? "/api/v1/legacy-assets/" + ref : "/api/v1/assets/" + ref
                let data = try await api.download(path)
                try data.write(to: file, options: .atomic)
            } catch { /* Missing image is shown by the renderer; text stays usable. */ }
        }
    }

    func logout(localOnly: Bool = false) async {
        do {
            if localOnly { try await client?.clearLocalCredentials() }
            else { try await client?.signOut() }
            for task in polling.values { task.cancel() }
            polling.removeAll()
            try cache?.erase()
            cache = nil; user = nil; questions = []; wrongQuestions = []; jobs = []; teaching = []; results = [:]; progress = .null
        } catch { message = "退出未完成。请恢复网络后重试，或选择仅退出此设备。" }
    }
}
