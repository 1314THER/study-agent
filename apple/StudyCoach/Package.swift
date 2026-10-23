// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "StudyCoach",
    platforms: [.iOS(.v18), .macOS(.v15)],
    products: [.library(name: "StudyCore", targets: ["StudyCore"]), .executable(name: "StudyCoach", targets: ["StudyApp"])],
    targets: [
        .target(name: "StudyCore", resources: [.copy("Resources/Web")], linkerSettings: [.linkedLibrary("sqlite3")]),
        .executableTarget(name: "StudyApp", dependencies: ["StudyCore"]),
        .testTarget(name: "StudyCoreTests", dependencies: ["StudyCore"])
    ],
    swiftLanguageModes: [.v5]
)
