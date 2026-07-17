allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

// file_picker (y otros plugins) generan tareas Kotlin apuntando a JVM 21
// mientras las tareas Java del resto del proyecto apuntan a JVM 17 —
// Gradle falla por "Inconsistent JVM Target Compatibility" si no se
// homogeneiza aquí explícitamente para todos los subproyectos. Se fija
// jvmTarget directamente en las tareas KotlinCompile (no via jvmToolchain,
// que ya viene fijado por el propio plugin de Kotlin y no admite cambios).
subprojects {
    tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>().configureEach {
        compilerOptions.jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
