import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.chaquopy)
}

// The Python engine is not copied into this project: it is taken from the repo root at build time, so the app
// and the command line always run the same code. Shipped (non-personal) config goes along as the pe_shipped package.
val engineRoot = rootProject.projectDir.parentFile
val enginePy = layout.buildDirectory.dir("generated/enginePy")
val syncEngine by tasks.registering(Sync::class) {
    from(engineRoot) {
        include("main.py", "pe/**/*.py", "pe/**/*.html")
        exclude("pe/tui.py")                    // the terminal shell needs prompt_toolkit and a tty
    }
    from(File(engineRoot, "config")) {
        include("settings.yaml", "asset_classes.yaml", "real_assets.yaml", "corporate_actions.yaml", "holdings.example.yaml")
        into("pe_shipped")
    }
    into(enginePy)
    doLast {
        File(enginePy.get().asFile, "pe_shipped/__init__.py").writeText("# Shipped config files, copied from config/ at build time.\n")
    }
}

// Release key lives outside the repo. Path: -PkeystoreProperties=... or $PE_KEYSTORE_PROPERTIES, default ~/pe-android-signing/keystore.properties.
// When the file is missing the release build falls back to the debug key, so the project still builds for anyone.
val keystorePropsFile = File(
    providers.gradleProperty("keystoreProperties").orNull
        ?: System.getenv("PE_KEYSTORE_PROPERTIES")
        ?: "${System.getProperty("user.home")}/pe-android-signing/keystore.properties"
)
val keystoreProps = Properties().apply {
    if (keystorePropsFile.isFile) keystorePropsFile.inputStream().use { load(it) }
}

android {
    namespace = "app.portfolioengine"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.portfolioengine"
        minSdk = 26
        targetSdk = 36
        versionCode = 3
        versionName = "1.0.0-beta3"
        ndk {
            // arm64 for phones, x86_64 for the emulator. -Pabi=arm64-v8a builds a phone-only (smaller) APK.
            abiFilters += (providers.gradleProperty("abi").orNull?.split(",") ?: listOf("arm64-v8a", "x86_64"))
        }
        vectorDrawables { useSupportLibrary = true }
    }

    signingConfigs {
        if (keystoreProps.containsKey("storeFile")) {
            create("release") {
                storeFile = File(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
            }
        }
    }

    buildTypes {
        release {
            // R8 has not been tested against Chaquopy yet, so no shrinking for now.
            isMinifyEnabled = false
            isShrinkResources = false
            isDebuggable = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true }
    packaging {
        resources.excludes += setOf("/META-INF/{AL2.0,LGPL2.1}")
    }
    testOptions { unitTests.isReturnDefaultValues = true }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        freeCompilerArgs.addAll(
            "-opt-in=androidx.compose.material3.ExperimentalMaterial3Api",
            "-opt-in=androidx.compose.foundation.layout.ExperimentalLayoutApi",
        )
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        pip {
            // Versions with prebuilt Android wheels on Chaquopy's index; the engine's tests pass on these.
            install("numpy==1.26.2")
            install("pandas==2.1.3")
            install("pyyaml")
            install("python-dateutil")
            install("requests")
            install("openpyxl")
            // casparser (CAS PDFs) is left out: it needs pydantic-core and PyMuPDF, which have no Android wheels.
            // The engine reports CAS import as unavailable on ImportError.
        }
        // The engine reads site_template.html and the shipped YAML through normal file paths.
        extractPackages("pe", "pe_shipped")
    }
    sourceSets {
        getByName("main") {
            srcDir(enginePy)
        }
    }
}

tasks.matching { it.name.startsWith("merge") && it.name.endsWith("PythonSources") }.configureEach {
    dependsOn(syncEngine)
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.work.runtime)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons)
    implementation(libs.kotlinx.coroutines.android)
    debugImplementation(libs.compose.ui.tooling)

    testImplementation(libs.junit)
    testImplementation(libs.org.json)
}
