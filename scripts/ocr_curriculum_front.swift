// Read-only local OCR for scanned textbook front matter. No cloud API.
import Foundation
import PDFKit
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 3, let pdf = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    fatalError("Usage: swift ocr_curriculum_front.swift book.pdf output.json")
}
var output: [[String: Any]] = []
for index in 1..<min(pdf.pageCount, 13) {
    guard let page = pdf.page(at: index) else { continue }
    let image = page.thumbnail(of: NSSize(width: 1500, height: 2100), for: .mediaBox)
    var rect = NSRect(origin: .zero, size: image.size)
    guard let cg = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else { continue }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: cg).perform([request])
    let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    output.append(["pdf_page": index + 1, "text": lines.joined(separator: "\n")])
}
let data = try JSONSerialization.data(withJSONObject: output, options: [.prettyPrinted, .sortedKeys, .fragmentsAllowed])
try data.write(to: URL(fileURLWithPath: args[2]))
print(URL(fileURLWithPath: args[1]).lastPathComponent, "OCR pages:", output.count)
