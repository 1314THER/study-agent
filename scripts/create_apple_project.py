"""Generate a dependency-free multiplatform Xcode project for the SwiftUI app."""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parent.parent / "apple/StudyCoach"


def ident(value): return hashlib.sha1(value.encode()).hexdigest()[:24].upper()


def main():
    project = ROOT / "StudyCoach.xcodeproj"
    project.mkdir(exist_ok=True)
    objects = []
    def obj(key, value):
        objects.append(ident(key) + " = { " + value + " };")
        return ident(key)
    files, builds = [], []
    for source in sorted((ROOT / "Sources/StudyApp").glob("*.swift")):
        ref = obj(str(source.name), f'isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = "Sources/StudyApp/{source.name}"; sourceTree = "<group>";')
        files.append(ref)
        builds.append(obj("build:" + source.name, f"isa = PBXBuildFile; fileRef = {ref};"))
    app = obj("app", 'isa = PBXFileReference; explicitFileType = wrapper.application; path = StudyCoach.app; sourceTree = BUILT_PRODUCTS_DIR;')
    group = obj("group", 'isa = PBXGroup; children = (' + ','.join(files + [app]) + '); sourceTree = "<group>";')
    pkg = obj("package", 'isa = XCLocalSwiftPackageReference; relativePath = .;')
    product = obj("core-product", f'isa = XCSwiftPackageProductDependency; package = {pkg}; productName = StudyCore;')
    product_build = obj("core-build", f'isa = PBXBuildFile; productRef = {product};')
    framework = obj("frameworks", f'isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = ({product_build}); runOnlyForDeploymentPostprocessing = 0;')
    sources = obj("sources", 'isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (' + ','.join(builds) + '); runOnlyForDeploymentPostprocessing = 0;')
    resources = obj("resources", 'isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0;')
    configs = []
    for config in ("Debug", "Release"):
        settings = '''PRODUCT_BUNDLE_IDENTIFIER = chat.150.StudyCoach; PRODUCT_NAME = StudyCoach;
            SWIFT_VERSION = 5.0; SDKROOT = auto; SUPPORTED_PLATFORMS = "iphoneos iphonesimulator macosx"; ALWAYS_SEARCH_USER_PATHS = NO;
            IPHONEOS_DEPLOYMENT_TARGET = 18.0; MACOSX_DEPLOYMENT_TARGET = 15.0;
            TARGETED_DEVICE_FAMILY = "1,2"; SUPPORTS_MACCATALYST = NO;
            CODE_SIGN_STYLE = Automatic; GENERATE_INFOPLIST_FILE = YES;
            INFOPLIST_KEY_CFBundleDisplayName = "学习教练台"; INFOPLIST_KEY_LSApplicationCategoryType = "public.app-category.education";
            INFOPLIST_KEY_NSCameraUsageDescription = "拍摄题目与手写作答，用于识别和批改。";
            INFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;
            INFOPLIST_KEY_UILaunchScreen_Generation = YES;
            INFOPLIST_KEY_UISupportedInterfaceOrientations = "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";
            INFOPLIST_KEY_NSAppTransportSecurity_NSAllowsLocalNetworking = YES;
            ENABLE_APP_SANDBOX = YES; ENABLE_HARDENED_RUNTIME = YES;
            ENABLE_OUTGOING_NETWORK_CONNECTIONS = YES; ENABLE_USER_SELECTED_FILES = readwrite;
            CURRENT_PROJECT_VERSION = 1; MARKETING_VERSION = 0.1.0;'''
        if config == "Debug": settings += ' SWIFT_OPTIMIZATION_LEVEL = "-Onone"; DEBUG_INFORMATION_FORMAT = dwarf; ONLY_ACTIVE_ARCH = YES;'
        configs.append(obj("config:" + config, f'isa = XCBuildConfiguration; buildSettings = {{{settings}}}; name = {config};'))
    config_list = obj("configs", 'isa = XCConfigurationList; buildConfigurations = (' + ','.join(configs) + '); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;')
    target = obj("target", f'isa = PBXNativeTarget; buildConfigurationList = {config_list}; buildPhases = ({sources},{framework},{resources}); buildRules = (); dependencies = (); name = StudyCoach; productName = StudyCoach; productReference = {app}; productType = "com.apple.product-type.application"; packageProductDependencies = ({product});')
    root = obj("project", f'isa = PBXProject; attributes = {{BuildIndependentTargetsInParallel = YES; LastUpgradeCheck = 2600;}}; buildConfigurationList = {config_list}; compatibilityVersion = "Xcode 15.0"; developmentRegion = zh-Hans; hasScannedForEncodings = 0; knownRegions = (en,Base,"zh-Hans"); mainGroup = {group}; projectDirPath = ""; projectRoot = ""; targets = ({target}); packageReferences = ({pkg});')
    (project / "project.pbxproj").write_text('// !$*UTF8*$!\n{ archiveVersion = 1; classes = {}; objectVersion = 60; objects = {\n' + '\n'.join(objects) + '\n}; rootObject = ' + root + ';}\n')
    schemes = project / "xcshareddata/xcschemes"; schemes.mkdir(parents=True, exist_ok=True)
    (schemes / "StudyCoach.xcscheme").write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="2600" version="1.3"><BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{target}" BuildableName="StudyCoach.app" BlueprintName="StudyCoach" ReferencedContainer="container:StudyCoach.xcodeproj"/></BuildActionEntry></BuildActionEntries></BuildAction><LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES"><BuildableProductRunnable runnableDebuggingMode="0"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{target}" BuildableName="StudyCoach.app" BlueprintName="StudyCoach" ReferencedContainer="container:StudyCoach.xcodeproj"/></BuildableProductRunnable></LaunchAction><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/></Scheme>''')


if __name__ == "__main__": main()
