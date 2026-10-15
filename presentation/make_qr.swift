import AppKit
import CoreImage
import Vision

guard CommandLine.arguments.count == 3 else {
    fatalError("Usage: swift make_qr.swift URL OUTPUT.png")
}
let url = CommandLine.arguments[1]
let filter = CIFilter(name: "CIQRCodeGenerator")!
filter.setValue(Data(url.utf8), forKey: "inputMessage")
filter.setValue("M", forKey: "inputCorrectionLevel")
let code = filter.outputImage!
let side = code.extent.width + 8
let background = CIImage(color: CIColor.white).cropped(to: CGRect(x: 0, y: 0, width: side, height: side))
let bordered = code.transformed(by: CGAffineTransform(translationX: 4, y: 4)).composited(over: background)
let scaled = bordered.transformed(by: CGAffineTransform(scaleX: 32, y: 32))
let cg = CIContext().createCGImage(scaled, from: scaled.extent)!
let png = NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:])!
try png.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
let request = VNDetectBarcodesRequest()
request.symbologies = [.qr]
try VNImageRequestHandler(data: png).perform([request])
guard request.results?.contains(where: { $0.payloadStringValue == url }) == true else {
    fatalError("QR verification failed")
}
print("QR verified: \(url)")
