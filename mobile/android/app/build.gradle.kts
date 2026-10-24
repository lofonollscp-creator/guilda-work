import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Firma de release (Ola 0.1): las credenciales NO van al repositorio. En local
// se leen de android/key.properties; en el CI, de las variables de entorno
// GUILDA_KEYSTORE_FILE / GUILDA_KEYSTORE_PASSWORD / GUILDA_KEY_ALIAS /
// GUILDA_KEY_PASSWORD (secretos del CI). Sin ninguna de las dos, el release
// sigue firmándose con la clave de debug para poder probar en local.
val keyProps = Properties().apply {
    val f = rootProject.file("key.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
fun firma(clave: String, entorno: String): String? =
    System.getenv(entorno) ?: keyProps.getProperty(clave)
val almacen = firma("storeFile", "GUILDA_KEYSTORE_FILE")

android {
    namespace = "cat.guilda.guilda_work_mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "cat.guilda.guilda_work_mobile"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (almacen != null) {
            create("release") {
                storeFile = file(almacen)
                storePassword = firma("storePassword", "GUILDA_KEYSTORE_PASSWORD")
                keyAlias = firma("keyAlias", "GUILDA_KEY_ALIAS")
                keyPassword = firma("keyPassword", "GUILDA_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (almacen != null) signingConfigs.getByName("release")
                            else signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
