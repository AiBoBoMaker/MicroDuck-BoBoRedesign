plugins {
    id("com.android.application")
    id("kotlin-android")
    id("com.chaquo.python")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.microduck.console_apk"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.microduck.console_apk"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = maxOf(flutter.minSdkVersion, 28)
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

flutter {
    source = "../.."
}

val consoleAssets = layout.buildDirectory.dir("generated/consoleAssets")

val packConsole by tasks.registering(Zip::class) {
    archiveFileName.set("console-runtime.zip")
    destinationDirectory.set(consoleAssets)
    // android/ → console-apk/ → microduck-hd1910/firmware/console
    from(rootProject.file("../../firmware/console")) {
        include("*.py", "*.json", "static/**")
        exclude("**/__pycache__/**", "logs/**", "verification/**", "updates/**")
    }
}

android {
    sourceSets.getByName("main").assets.srcDir(consoleAssets)
}

tasks.configureEach {
    if (name.startsWith("merge") && name.endsWith("Assets")) {
        dependsOn(packConsole)
    }
}

chaquopy {
    defaultConfig {
        version = "3.10"
        pip {
            install("paramiko==2.12.0")
        }
    }
}
