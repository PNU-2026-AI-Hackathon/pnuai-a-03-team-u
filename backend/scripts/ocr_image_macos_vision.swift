import Foundation
import ImageIO
import Vision

if CommandLine.arguments.count != 2 {
    FileHandle.standardError.write(Data("usage: swift ocr_image_macos_vision.swift <image-path>\n".utf8))
    exit(2)
}

let originalURL = URL(fileURLWithPath: CommandLine.arguments[1])
let imageURL: URL

if originalURL.path.canBeConverted(to: .ascii) {
    imageURL = originalURL
} else {
    let tempURL = FileManager.default.temporaryDirectory
        .appendingPathComponent("codex-vision-ocr-\(UUID().uuidString)")
        .appendingPathExtension(originalURL.pathExtension.isEmpty ? "jpg" : originalURL.pathExtension)
    do {
        try FileManager.default.copyItem(at: originalURL, to: tempURL)
        imageURL = tempURL
    } catch {
        FileHandle.standardError.write(Data("failed to prepare temporary image: \(error.localizedDescription)\n".utf8))
        exit(1)
    }
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

if #available(macOS 11.0, *) {
    let supportedLanguages = (try? request.supportedRecognitionLanguages()) ?? []
    let preferredLanguages = ["ko-KR", "ko", "en-US"]
    let languages = preferredLanguages.filter { supportedLanguages.contains($0) }
    if !languages.isEmpty {
        request.recognitionLanguages = languages
    }
}

guard let imageSource = CGImageSourceCreateWithURL(imageURL as CFURL, nil),
      let cgImage = CGImageSourceCreateImageAtIndex(imageSource, 0, nil) else {
    FileHandle.standardError.write(Data("failed to decode image\n".utf8))
    exit(1)
}

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])

do {
    try handler.perform([request])
    let observations = request.results ?? []
    let lines = observations.compactMap { observation in
        observation.topCandidates(1).first?.string
    }
    print(lines.joined(separator: "\n"))
} catch {
    FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
    exit(1)
}
