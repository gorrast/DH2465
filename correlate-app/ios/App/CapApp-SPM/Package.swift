// swift-tools-version: 5.9
import PackageDescription

// DO NOT MODIFY THIS FILE - managed by Capacitor CLI commands
let package = Package(
    name: "CapApp-SPM",
    platforms: [.iOS(.v15)],
    products: [
        .library(
            name: "CapApp-SPM",
            targets: ["CapApp-SPM"])
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", exact: "8.5.2"),
        .package(name: "CapacitorCommunityBackgroundGeolocation", path: "../../../node_modules/@capacitor-community/background-geolocation"),
        .package(name: "CapacitorApp", path: "../../../node_modules/@capacitor/app"),
        .package(name: "EbarooniCapacitorCalendar", path: "../../../node_modules/@ebarooni/capacitor-calendar"),
        .package(name: "CapacitorHealth", path: "../../../node_modules/capacitor-health")
    ],
    targets: [
        .target(
            name: "CapApp-SPM",
            dependencies: [
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm"),
                .product(name: "CapacitorCommunityBackgroundGeolocation", package: "CapacitorCommunityBackgroundGeolocation"),
                .product(name: "CapacitorApp", package: "CapacitorApp"),
                .product(name: "EbarooniCapacitorCalendar", package: "EbarooniCapacitorCalendar"),
                .product(name: "CapacitorHealth", package: "CapacitorHealth")
            ]
        )
    ]
)
