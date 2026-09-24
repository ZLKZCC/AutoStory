use std::path::PathBuf;

fn main() {
    tauri_build::build();

    let out_dir = PathBuf::from(std::env::var("OUT_DIR").unwrap_or_default());
    let Some(profile_dir) = out_dir.ancestors().nth(3) else {
        return;
    };
    let backend = profile_dir.join("backend");
    let data = profile_dir.join("data");
    let backend_removed = std::fs::remove_dir_all(&backend).is_ok();
    let data_removed = std::fs::remove_dir_all(&data).is_ok();
    println!(
        "cargo:warning=build.rs cleanup at {:?}: backend_removed={} data_removed={}",
        profile_dir, backend_removed, data_removed
    );
}
