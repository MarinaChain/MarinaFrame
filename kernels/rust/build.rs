use std::{env, path::PathBuf, process::Command};

fn run(command: &mut Command) {
    assert!(
        command.status().expect("start CMake").success(),
        "CMake failed"
    );
}

fn main() {
    let source = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap()).join("..");
    let build = PathBuf::from(env::var_os("OUT_DIR").unwrap()).join("native");
    run(Command::new("cmake")
        .arg("-S")
        .arg(&source)
        .arg("-B")
        .arg(&build)
        .arg("-DBUILD_TESTING=OFF")
        .arg("-DCMAKE_BUILD_TYPE=Release"));
    run(Command::new("cmake").arg("--build").arg(&build).args([
        "--config",
        "Release",
        "--target",
        "mf_kernels_static",
    ]));
    println!("cargo:rustc-link-search=native={}", build.display());
    println!(
        "cargo:rustc-link-search=native={}",
        build.join("Release").display()
    );
    println!("cargo:rustc-link-lib=static=mf_kernels_static");
    for file in ["CMakeLists.txt", "src/volume.c", "include/mf_kernels.h"] {
        println!("cargo:rerun-if-changed={}", source.join(file).display());
    }
}
