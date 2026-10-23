import SwiftUI
import StudyCore
#if os(iOS)
import UIKit
#endif

@main
struct StudyCoachApp: App {
    @State private var model = StudyModel()
    var body: some Scene {
        #if os(macOS)
        mainWindow.defaultSize(width: 1160, height: 800)
            .commands {
                CommandGroup(after: .newItem) { Button("刷新学习记录") { Task { await model.reload() } }.keyboardShortcut("r") }
            }
        Settings { AccountView().environment(model).frame(width: 560, height: 520) }
        #else
        mainWindow
        #endif
    }
    var mainWindow: some Scene {
        WindowGroup {
            RootView().environment(model)
                .task { if model.user == nil { await model.restore() } }
        }
    }
}

struct RootView: View {
    @Environment(StudyModel.self) private var model
    @Environment(\.scenePhase) private var phase
    @State private var section = "题库"
    var body: some View {
        Group {
            if model.user == nil { LoginView() }
            else {
                #if os(iOS)
                if UIDevice.current.userInterfaceIdiom == .phone {
                    TabView {
                        LibraryView().tabItem { Label("题库", systemImage: "books.vertical") }
                        LibraryView(wrong: true).tabItem { Label("复习", systemImage: "arrow.counterclockwise") }
                        TeachingList().tabItem { Label("教学", systemImage: "bubble.left.and.bubble.right") }
                        ProgressViewPage().tabItem { Label("进度", systemImage: "chart.bar") }
                        AccountView().tabItem { Label("账号", systemImage: "person.crop.circle") }
                    }
                } else { desktop }
                #else
                desktop
                #endif
            }
        }
        .tint(.blue)
        .alert("学习教练台", isPresented: Binding(get: { model.message != nil }, set: { if !$0 { model.message = nil } })) {
            Button("知道了") { model.message = nil }
        } message: { Text(model.message ?? "") }
        .onChange(of: phase) { _, value in if value == .active && model.user != nil { Task { await model.reload() } } }
    }
    var desktop: some View {
        NavigationSplitView {
            List(selection: $section) {
                Label("题库", systemImage: "books.vertical").tag("题库")
                Label("错题复习", systemImage: "arrow.counterclockwise").tag("复习")
                Label("教学", systemImage: "bubble.left.and.bubble.right").tag("教学")
                Label("学习进度", systemImage: "chart.bar").tag("进度")
                Label("后台任务", systemImage: "clock").tag("任务")
                Label("账号", systemImage: "person.crop.circle").tag("账号")
            }
            .navigationTitle("学习教练台")
            .navigationSplitViewColumnWidth(min: 180, ideal: 220)
        } detail: {
            switch section {
            case "复习": LibraryView(wrong: true)
            case "教学": TeachingList()
            case "进度": ProgressViewPage()
            case "任务": JobList()
            case "账号": AccountView()
            default: LibraryView()
            }
        }
        #if os(macOS)
        .frame(minWidth: 820, minHeight: 560)
        #endif
    }
}

struct LoginView: View {
    @Environment(StudyModel.self) private var model
    @State private var identifier = ""
    @State private var password = ""
    @State private var confirm = ""
    @State private var registering = false
    @State private var username = ""
    @State private var code = ""
    @State private var key = ""
    @State private var resendAt = Date.distantPast
    var body: some View {
        @Bindable var model = model
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Image(systemName: "function").font(.system(size: 44, weight: .medium)).foregroundStyle(.blue).accessibilityHidden(true)
                Text("成为数学高手").font(.largeTitle.bold())
                Text("从一道题开始，找到下一步。 ").foregroundStyle(.secondary)
                Picker("入口", selection: $registering) { Text("账号登录").tag(false); Text("创建账号").tag(true) }.pickerStyle(.segmented)
                if registering {
                    TextField("用户名", text: $username).textContentType(.username)
                    TextField("邮箱", text: $identifier).textContentType(.emailAddress)
                    HStack {
                        TextField("6 位验证码", text: $code).textContentType(.oneTimeCode)
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            let seconds = max(0, Int(resendAt.timeIntervalSince(context.date)))
                            Button(seconds > 0 ? "\(seconds) 秒后重发" : "发送验证码") {
                                resendAt = .now.addingTimeInterval(60)
                                Task { await model.sendCode(email: identifier) }
                            }.disabled(seconds > 0 || !model.registrationEnabled || identifier.isEmpty)
                        }
                    }
                } else { TextField("用户名 / 邮箱", text: $identifier).textContentType(.username) }
                SecureField(registering ? "设置密码（至少 12 位）" : "密码", text: $password)
                if registering {
                    SecureField("确认密码", text: $confirm)
                    SecureField("DeepSeek API Key", text: $key)
                    Link("如何获取 DeepSeek API Key", destination: URL(string: "https://platform.deepseek.com/api_keys")!)
                    if !model.registrationEnabled { Text("此服务器尚未开放邮箱注册，请使用已有账号登录。").font(.callout).foregroundStyle(.secondary) }
                }
                Button {
                    Task {
                        if registering {
                            guard password == confirm else { model.message = "两次输入的密码不一致。"; return }
                            await model.register(username: username, email: identifier, password: password, code: code, key: key)
                        } else { await model.login(identifier: identifier, password: password) }
                        password = ""; confirm = ""; key = ""
                    }
                } label: {
                    HStack { Spacer(); if model.busy { ProgressView() }; Text(registering ? "创建学习空间" : "登录"); Spacer() }.padding(.vertical, 8)
                }.buttonStyle(.borderedProminent).disabled(model.busy || identifier.isEmpty || password.isEmpty || (registering && !model.registrationEnabled))
                DisclosureGroup("服务器地址") {
                    TextField("https://你的服务器", text: $model.server)
                    Button("检查连接") { Task { await model.configureRegistration() } }
                }.font(.callout)
            }
            .textFieldStyle(.roundedBorder).padding(32).frame(maxWidth: 460)
            .frame(maxWidth: .infinity)
        }
        .task { await model.configureRegistration() }
    }
}

struct LibraryView: View {
    @Environment(StudyModel.self) private var model
    var wrong = false
    @State private var query = ""
    @State private var newQuestion = ""
    @State private var showingNew = false
    var items: [Question] { wrong ? model.wrongQuestions : model.questions }
    var body: some View {
        NavigationStack {
            List {
                if model.offline { Label("离线浏览 · 草稿保存在此设备", systemImage: "wifi.slash").foregroundStyle(.secondary) }
                if items.isEmpty {
                    ContentUnavailableView(wrong ? "还没有错题" : "还没有题目", systemImage: "book.closed", description: Text(wrong ? "完成练习后，需要复习的题目会出现在这里。" : "刷新公共题库，或添加你想练习的题目。"))
                }
                ForEach(items) { question in
                    NavigationLink(value: question) {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(question.content).lineLimit(3)
                            Text(question.owner_user_id == nil ? "公共题库" : "我的题目").font(.caption).foregroundStyle(.secondary)
                        }.padding(.vertical, 8)
                    }
                }
                if items.count < (wrong ? model.wrongTotal : model.total) { Button("加载更多") { Task { await model.loadQuestions(query: query, wrong: wrong, more: true) } } }
            }
            .navigationTitle(wrong ? "错题复习" : "题库")
            .searchable(text: $query, prompt: "搜索题目")
            .task(id: query + String(wrong)) {
                try? await Task.sleep(for: .milliseconds(250))
                if !Task.isCancelled { await model.loadQuestions(query: query, wrong: wrong) }
            }
            .refreshable { await model.loadQuestions(query: query, wrong: wrong) }
            .navigationDestination(for: Question.self) { QuestionView(question: $0) }
            .toolbar {
                ToolbarItem { Button { showingNew = true } label: { Label("添加题目", systemImage: "plus") } }
                ToolbarItem { NavigationLink { JobList() } label: { Label("后台任务", systemImage: "clock") } }
            }
            .sheet(isPresented: $showingNew) {
                VStack(alignment: .leading, spacing: 16) {
                    Text("添加题目").font(.title2.bold())
                    TextEditor(text: $newQuestion).frame(minHeight: 200)
                    HStack {
                        Button("取消") { showingNew = false }
                        Spacer()
                        Button("解题并保存") {
                            let text = newQuestion; showingNew = false; newQuestion = ""
                            Task { await model.submit(kind: "solve", args: ["question": .string(text)], channel: "solve:" + text) }
                        }.buttonStyle(.borderedProminent).disabled(newQuestion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }.padding(24).frame(minWidth: 320, minHeight: 300)
            }
        }
    }
}
