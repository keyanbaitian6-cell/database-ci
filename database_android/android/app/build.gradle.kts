plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// A second installation of the same app, selected only for an explicit clone build.
// Keep the Kotlin namespace/classes and all Flutter behavior shared with the original.
val databaseClone = providers.environmentVariable("DATABASE_ANDROID_CLONE").getOrElse("original")
require(databaseClone == "original" || databaseClone == "pscube") {
    "DATABASE_ANDROID_CLONE must be original or pscube"
}
val databaseApplicationId = if (databaseClone == "pscube") {
    "com.keyan.database_android.pscube"
} else {
    "com.keyan.database_android"
}
val databaseAppLabel = if (databaseClone == "pscube") "database P’s CUBE" else "database"

android {
    namespace = "com.keyan.database_android"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = databaseApplicationId
        manifestPlaceholders["databaseAppLabel"] = databaseAppLabel
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }
}

dependencies {
    // The Flutter ML Kit plugin declares non-Latin recognizers as compileOnly.
    // Japanese OCR is required by this app, so package it into the APK.
    implementation("com.google.mlkit:text-recognition-japanese:16.0.1")
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
