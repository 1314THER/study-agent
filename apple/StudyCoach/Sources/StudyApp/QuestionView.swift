import SwiftUI
import UniformTypeIdentifiers
import StudyCore
#if os(iOS)
import PencilKit
import UIKit
#endif

struct QuestionView: View {
    @Environment(StudyModel.self) private var model
    let question: Question
    @State private var answer = ""
    @State private var showAnswer = false
    @State private var importing = false
    @State private var drawing = false
    @State private var camera = false
    @State private var assetID: String?
    @State private var drawingData = Data()
    @State private var uploading = false
    @State private var assetsReady = false
    var body: some View {
        GeometryReader { geometry in
            if geometry.size.width > 820 {
                HStack(spacing: 0) { statement; Divider(); workspace.frame(width: max(340, geometry.size.width * 0.42)) }
            } else { ScrollView { VStack(spacing: 0) { statement.frame(minHeight: 420); workspace } } }
        }
        .navigationTitle("练习")
        .toolbar { Toggle(isOn: $showAnswer) { Label("查看解析", systemImage: "text.book.closed") } }
        .task {
            answer = model.draft(question.id)
            drawingData = (try? model.cache?.drawing(questionID: question.id)) ?? Data()
            await model.cacheResources(question)
            assetsReady = true
        }
        .onChange(of: answer) { _, value in model.saveDraft(question.id, text: value) }
        .onChange(of: drawingData) { _, value in model.saveDraft(question.id, text: answer, drawing: value) }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.image, .pdf]) { result in
            if case .success(let url) = result { importFile(url) }
        }
        .onDrop(of: [UTType.fileURL], isTargeted: nil) { providers in
            guard let provider = providers.first else { return false }
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                guard let url else { return }
                Task { @MainActor in importFile(url) }
            }
            return true
        }
        #if os(iOS)
        .sheet(isPresented: $drawing) {
            DrawingSheet(data: $drawingData) { image in
                model.saveDraft(question.id, text: answer, drawing: drawingData)
                Task { await attach(image, filename: "handwriting.png", type: "image/png") }
            }
        }
        .sheet(isPresented: $camera) {
            CameraCapture { data in camera = false; Task { await attach(data, filename: "camera.jpg", type: "image/jpeg") } }
        }
        #endif
    }
    var statement: some View {
        MathView(question: question, showAnswer: showAnswer, assets: model.cache?.assetDirectory)
            .id(question.id + String(assetsReady))
            .accessibilityLabel("题目与解析")
    }
    var workspace: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("写下你的思路").font(.title2.bold())
                Text("先尝试，再对照每一步。离开页面后，草稿仍会保留。").font(.callout).foregroundStyle(.secondary)
                TextEditor(text: $answer).frame(minHeight: 180).padding(8).overlay(RoundedRectangle(cornerRadius: 8).stroke(.secondary.opacity(0.25)))
                HStack {
                    Button { importing = true } label: { Label("上传作答", systemImage: "paperclip") }
                    #if os(iOS)
                    Button { drawing = true } label: { Label("手写", systemImage: "pencil.tip") }
                    if UIImagePickerController.isSourceTypeAvailable(.camera) { Button { camera = true } label: { Label("拍照", systemImage: "camera") } }
                    #endif
                }.disabled(uploading)
                if uploading { ProgressView("正在上传") }
                if assetID != nil { Label("已附加作答文件", systemImage: "checkmark.circle").foregroundStyle(.green) }
                Button("批改作答") {
                    var args: [String: JSONValue] = ["question_id": .string(question.id), "question_revision": .number(Double(question.revision)), "student_answer": .string(answer)]
                    if let assetID { args["asset_id"] = .string(assetID) }
                    Task { await model.submit(kind: "grade", args: args, channel: "grade:" + question.id) }
                }.buttonStyle(.borderedProminent).disabled((answer.isEmpty && assetID == nil) || uploading || model.offline)
                Button("请老师带我做") { Task { await model.submit(kind: "teach_start", args: ["question_id": .string(question.id)], channel: "teach:" + question.id) } }.disabled(model.offline)
                ForEach(model.jobs.filter { $0.args["question_id"].string == question.id }.prefix(3)) { job in
                    VStack(alignment: .leading, spacing: 8) {
                        Label(job.stage, systemImage: job.status == "done" ? "checkmark.circle" : "clock")
                        if !job.terminal { ProgressView(value: Double(job.progress), total: 100) }
                        if let result = job.result, job.kind == "grade" {
                            Text(result["result"]["feedback"].string).textSelection(.enabled)
                            if !result["result"]["step_results"].array.isEmpty {
                                ForEach(Array(result["result"]["step_results"].array.enumerated()), id: \.offset) { _, step in
                                    Text(step["feedback"].string.isEmpty ? step["comment"].string : step["feedback"].string).font(.callout)
                                }
                            }
                        }
                        if let id = job.result?["session_id"].string, !id.isEmpty {
                            NavigationLink("继续教学") { TeachingDetail(sessionID: id) }
                        }
                    }.padding(.vertical, 10)
                }
            }.padding(24)
        }
    }
    func importFile(_ url: URL) {
        Task {
            let access = url.startAccessingSecurityScopedResource()
            defer { if access { url.stopAccessingSecurityScopedResource() } }
            do {
                let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                guard size <= 32 * 1024 * 1024 else { model.message = "附件须在 32 MB 内"; return }
                let data = try Data(contentsOf: url)
                await attach(data, filename: url.lastPathComponent, type: UTType(filenameExtension: url.pathExtension)?.preferredMIMEType ?? "application/octet-stream")
            } catch { model.message = "无法读取这个文件。请重新选择。" }
        }
    }
    func attach(_ data: Data, filename: String, type: String) async {
        uploading = true; defer { uploading = false }
        do {
            assetID = try await model.upload(data, filename: filename, mediaType: type)
            if filename.hasSuffix(".pdf"), let assetID {
                await model.submit(kind: "parse_file", args: ["asset_id": .string(assetID)], channel: "parse:" + assetID)
                model.message = "PDF 已进入后台识别。识别结果可在后台任务中查看。"
            }
        } catch { model.message = error.localizedDescription }
    }
}

#if os(iOS)
struct DrawingCanvas: UIViewRepresentable {
    let canvas: PKCanvasView
    func makeUIView(context: Context) -> PKCanvasView { canvas }
    func updateUIView(_ uiView: PKCanvasView, context: Context) {}
}

struct DrawingSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Binding var data: Data
    var onUpload: (Data) -> Void
    @State private var canvas = PKCanvasView()
    @State private var toolPicker = PKToolPicker()
    var body: some View {
        NavigationStack {
            DrawingCanvas(canvas: canvas).background(.white).navigationTitle("手写作答")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("保存草稿") { data = canvas.drawing.dataRepresentation(); dismiss() } }
                    ToolbarItem(placement: .confirmationAction) { Button("用于批改") {
                        data = canvas.drawing.dataRepresentation()
                        let bounds = canvas.drawing.bounds.insetBy(dx: -20, dy: -20)
                        guard !bounds.isEmpty, !bounds.isInfinite else { return }
                        let scale = min(2, 2400 / bounds.width, 3200 / bounds.height)
                        let size = CGSize(width: bounds.width * scale, height: bounds.height * scale)
                        let ink = canvas.drawing.image(from: bounds, scale: scale)
                        let format = UIGraphicsImageRendererFormat(); format.opaque = true; format.scale = 1
                        let flattened = UIGraphicsImageRenderer(size: size, format: format).image { context in
                            UIColor.white.setFill(); context.fill(CGRect(origin: .zero, size: size))
                            ink.draw(in: CGRect(origin: .zero, size: size))
                        }
                        guard let image = flattened.pngData() else { return }
                        onUpload(image); dismiss()
                    } }
                }
                .onAppear {
                    canvas.drawingPolicy = .anyInput; canvas.backgroundColor = .white
                    canvas.overrideUserInterfaceStyle = .light
                    canvas.tool = PKInkingTool(.pen, color: .black, width: 3)
                    if let drawing = try? PKDrawing(data: data) { canvas.drawing = drawing }
                    toolPicker.addObserver(canvas); toolPicker.setVisible(true, forFirstResponder: canvas); canvas.becomeFirstResponder()
                }
                .onDisappear { data = canvas.drawing.dataRepresentation(); toolPicker.removeObserver(canvas) }
        }
    }
}

struct CameraCapture: UIViewControllerRepresentable {
    @Environment(\.dismiss) private var dismiss
    var completion: (Data) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController(); picker.sourceType = .camera; picker.delegate = context.coordinator; return picker
    }
    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}
    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        var parent: CameraCapture
        init(_ parent: CameraCapture) { self.parent = parent }
        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            if let image = info[.originalImage] as? UIImage, let data = image.jpegData(compressionQuality: 0.85) { parent.completion(data) }
            parent.dismiss()
        }
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { parent.dismiss() }
    }
}
#endif
