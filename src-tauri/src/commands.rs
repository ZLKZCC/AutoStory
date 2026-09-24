use std::process::Command;
use std::sync::Arc;

use serde::Serialize;

use crate::env_setup::{EnvState, PrepareItem};
use crate::util::no_window;

#[derive(Serialize)]
pub struct EnvSnapshot {
    pub items: Vec<PrepareItem>,
}

#[tauri::command]
pub fn prepare_environment(state: tauri::State<'_, Arc<EnvState>>) -> EnvSnapshot {
    EnvSnapshot {
        items: state.snapshot(),
    }
}

#[tauri::command]
pub fn open_url(url: String) {
    if !url.starts_with("https://") {
        return;
    }
    let mut cmd = Command::new("cmd");
    cmd.args(["/C", "start", "", &url]);
    no_window(&mut cmd);
    let _ = cmd.spawn();
}
