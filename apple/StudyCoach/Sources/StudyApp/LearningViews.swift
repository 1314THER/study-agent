import SwiftUI
import StudyCore

struct TeachingList: View {
    @Environment(StudyModel.self) private var model
    var body: some View {
        NavigationStack {
            List {
                if model.teaching.isEmpty { ContentUnavailableView("开始一次分步学习", systemImage: "bubble.left.and.bubble.right", description: Text("在题目中选择“请老师带我做”，教学记录会保存在这里。")) }
                ForEach(model.teaching, id: \.self) { session in
                    NavigationLink { TeachingDetail(sessionID: session["session_id"].string) } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(session["question"].string).lineLimit(2)
                            Text("第 \(session["current_step"].int + 1) 步，共 \(session["total_steps"].int) 步").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }.navigationTitle("教学").refreshable { await model.reload() }
        }
    }
}

struct TeachingDetail: View {
    @Environment(StudyModel.self) private var model
    let sessionID: String
    @State private var state: JSONValue = .null
    @State private var input = ""
    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(state["question"].string).font(.headline)
                    ForEach(Array(state["messages"].array.enumerated()), id: \.offset) { _, item in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(item["role"].string == "student" ? "我的回答" : "老师").font(.caption).foregroundStyle(.secondary)
                            Text(item["content"].string).textSelection(.enabled)
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(16)
                            .background(item["role"].string == "student" ? Color.blue.opacity(0.08) : Color.secondary.opacity(0.07), in: RoundedRectangle(cornerRadius: 12))
                    }
                    if !state["step_introduced"].bool, state["current_step"].int < state["steps"].array.count {
                        Text(state["steps"].array[state["current_step"].int]["step_prompt"].string).font(.headline)
                    }
                    if state["current_step"].int >= state["total_steps"].int && state != .null {
                        Label("本次教学已完成", systemImage: "checkmark.circle").foregroundStyle(.green)
                        Button("保存学习结果") { submit("teach_finish") }
                    }
                }.padding(22).frame(maxWidth: 800)
            }
            Divider()
            HStack(alignment: .bottom) {
                TextField("写下你的思路", text: $input, axis: .vertical).textFieldStyle(.roundedBorder).lineLimit(1...6)
                Button("发送") { submit("teach_chat") }.buttonStyle(.borderedProminent).disabled(input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || working)
                Button("跳过此步") { submit("teach_chat", message: "跳过") }.disabled(working)
            }.padding()
            if working { ProgressView("老师正在思考，离开页面后仍会继续。").padding(.bottom) }
        }
        .navigationTitle("分步教学")
        .task { await load() }
        .onChange(of: model.jobs.filter { $0.args["session_id"].string == sessionID }.map(\.status)) { _, _ in Task { await load() } }
    }
    var working: Bool { model.jobs.contains { $0.args["session_id"].string == sessionID && !$0.terminal } }
    func load() async {
        if let cached = model.teaching.first(where: { $0["session_id"].string == sessionID }) { state = cached }
        do { if let api = model.client { state = try await api.send("/api/v1/teaching/" + sessionID) } }
        catch { model.message = error.localizedDescription }
    }
    func submit(_ kind: String, message: String? = nil) {
        let args: [String: JSONValue] = ["session_id": .string(sessionID), "expected_revision": .number(Double(state["revision"].int)), "message": .string(message ?? input)]
        Task { await model.submit(kind: kind, args: args, channel: "teaching:" + sessionID); input = "" }
    }
}

struct ProgressViewPage: View {
    @Environment(StudyModel.self) private var model
    var body: some View {
        NavigationStack {
            List {
                Section("我的练习") {
                    LabeledContent("累计作答", value: String(model.progress["attempt_count"].int))
                    LabeledContent("回答正确", value: String(model.progress["correct_count"].int))
                    LabeledContent("需要复习", value: String(model.progress["review_count"].int))
                }
                Section("最近的作答") {
                    ForEach(Array(model.progress["recent_attempts"].array.enumerated()), id: \.offset) { _, attempt in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(attempt["question_content"].string).font(.headline).lineLimit(3)
                            Text(attempt["student_answer"].string).lineLimit(3)
                            Text(attempt["result"]["feedback"].string).font(.callout).foregroundStyle(.secondary)
                        }.padding(.vertical, 6)
                    }
                }
                if !model.progress["mastery"].array.isEmpty {
                    Section("套路与分类掌握") {
                        ForEach(model.progress["mastery"].array, id: \.self) { record in
                            let data = record["data"]
                            LabeledContent(record["display_name"].string, value: data["state"].string.isEmpty ? "\(data["percent"].int)%" : (["never":"未开始", "first_pass":"第一轮完成", "second_pass":"第二轮完成", "third_pass":"已掌握", "again_wrong":"需要巩固"][data["state"].string] ?? "学习中"))
                        }
                    }
                }
            }.navigationTitle("学习进度").refreshable { await model.reload() }
        }
    }
}

struct JobList: View {
    @Environment(StudyModel.self) private var model
    var body: some View {
        List {
            ForEach(model.jobs) { job in
                VStack(alignment: .leading, spacing: 8) {
                    Text(title(job.kind)).font(.headline)
                    Text(job.stage).foregroundStyle(.secondary)
                    if !job.terminal { ProgressView(value: Double(job.progress), total: 100) }
                    if let result = job.result, job.kind == "parse_file" {
                        ForEach(Array(result["questions"].array.enumerated()), id: \.offset) { _, question in
                            let content = question["question"].string.isEmpty ? question["content"].string : question["question"].string
                            Text(content)
                            Button("解题并加入题库") { Task { await model.submit(kind: "solve", args: ["question": .string(content)], channel: "import:" + content) } }
                        }
                    }
                }.padding(.vertical, 10)
            }
            if model.jobs.isEmpty { ContentUnavailableView("暂无后台任务", systemImage: "clock", description: Text("解题、批改和文件识别的进度会显示在这里。")) }
        }.navigationTitle("后台任务").refreshable { await model.reload() }
    }
    func title(_ kind: String) -> String {
        ["solve": "解题", "grade": "批改", "ocr": "识别作答", "parse_file": "识别题目", "teach_start": "开始教学", "teach_chat": "教学对话", "teach_ack": "继续教学", "teach_finish": "保存教学"][kind] ?? kind
    }
}

struct AccountView: View {
    @Environment(StudyModel.self) private var model
    @State private var apiKey = ""
    @State private var devices: [JSONValue] = []
    @State private var confirmLogout = false
    var body: some View {
        NavigationStack {
            Form {
                Section("账号") {
                    Text(model.user?.username ?? "未登录")
                    if let email = model.user?.email { Text(email).foregroundStyle(.secondary) }
                    Text(model.server).font(.caption).textSelection(.enabled)
                }
                Section("DeepSeek API Key") {
                    SecureField("输入新密钥", text: $apiKey)
                    Button("保存密钥") {
                        Task {
                            do {
                                let _: JSONValue = try await model.client?.send("/api/v1/auth/api-key", method: "PUT", body: .object(["api_key": .string(apiKey)])) ?? .null
                                apiKey = ""; model.message = "API Key 已保存。"
                            } catch { model.message = error.localizedDescription }
                        }
                    }.disabled(apiKey.isEmpty)
                }
                Section("登录设备") {
                    ForEach(devices, id: \.self) { device in
                        HStack {
                            Text(device["device_name"].string)
                            Spacer()
                            Button("撤销", role: .destructive) {
                                Task {
                                    do {
                                        let _: JSONValue = try await model.client?.send("/api/v1/auth/devices/" + device["id"].string, method: "DELETE") ?? .null
                                        await loadDevices()
                                    } catch { model.message = error.localizedDescription }
                                }
                            }
                        }
                    }
                }
                Section {
                    Button("退出账号", role: .destructive) { confirmLogout = true }
                    Button("仅退出此设备", role: .destructive) { confirmLogout = true }
                        .help("离线时可移除此设备的凭证和缓存；服务器会话到期前仍需联网撤销。")
                }
            }.formStyle(.grouped).navigationTitle("账号").task { await loadDevices() }
                .confirmationDialog(model.cache?.hasDrafts() == true ? "退出会移除此设备的缓存和未提交草稿。" : "退出会移除此设备的缓存。", isPresented: $confirmLogout, titleVisibility: .visible) {
                    Button("退出并撤销会话", role: .destructive) { Task { await model.logout() } }
                    Button("仅移除此设备的数据", role: .destructive) { Task { await model.logout(localOnly: true) } }
                    Button("取消", role: .cancel) {}
                }
        }
    }
    func loadDevices() async {
        do { let result: Items<JSONValue>? = try await model.client?.send("/api/v1/auth/devices"); devices = result?.items ?? [] }
        catch { /* Cached learning remains available without account networking. */ }
    }
}
