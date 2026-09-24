#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend_proc;
mod commands;
mod downloader;
mod env_setup;
mod gpu;
mod pip;
mod runtime_config;
mod util;

use tauri::Manager;

fn deverbatim(p: std::path::PathBuf) -> std::path::PathBuf {
    let s = p.to_string_lossy();
    if let Some(rest) = s.strip_prefix(r"\\?\UNC\") {
        return std::path::PathBuf::from(format!(r"\\{rest}"));
    }
    if let Some(rest) = s.strip_prefix(r"\\?\") {
        return std::path::PathBuf::from(rest.to_string());
    }
    p
}

fn main() {
    let rc = runtime_config::init();

    tauri::Builder::default()
        .setup(move |app| {
            let state = env_setup::EnvState::shared();
            app.manage(state.clone());

            let init_script = format!(
                "window.__AUTOSTORY_PORT__ = {};\nwindow.__AUTOSTORY_TOKEN__ = {};",
                rc.port,
                serde_json::to_string(&rc.token).expect("令牌序列化失败")
            );

            let main = tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title("AutoStory")
            .inner_size(1280.0, 800.0)
            .min_inner_size(960.0, 600.0)
            .center()
            .resizable(true)
            .initialization_script(&init_script)
            // wry 默认下载行为是 SetHandled 后静默存进系统"下载"目录，用户无感知；
            // 弹系统"另存为"对话框，取消则中止本次下载
            .on_download(|_webview, event| {
                use tauri::webview::DownloadEvent;
                match event {
                    DownloadEvent::Requested { destination, .. } => {
                        let suggested = destination
                            .file_name()
                            .map(|n| n.to_string_lossy().to_string())
                            .unwrap_or_else(|| "有声书.mp3".into());
                        let picked = rfd::FileDialog::new()
                            .add_filter("MP3 音频", &["mp3"])
                            .set_file_name(&suggested)
                            .save_file();
                        match picked {
                            Some(p) => {
                                *destination = p;
                                true
                            }
                            None => false,
                        }
                    }
                    DownloadEvent::Finished { .. } => true,
                    _ => false,
                }
            })
            .build()
            .expect("创建主窗口失败");

            #[cfg(windows)]
            {
                use webview2_com_sys::Microsoft::Web::WebView2::Win32::ICoreWebView2Settings3;
                use windows_core::Interface;

                let release = !cfg!(debug_assertions);
                let _ = main.with_webview(move |webview| unsafe {
                    if let Ok(core) = webview.controller().CoreWebView2() {
                        if let Ok(settings) = core.Settings() {
                            let _ = settings.SetAreDefaultContextMenusEnabled(false);
                            if release {
                                let _ = settings.SetAreDevToolsEnabled(false);
                                if let Ok(s3) = settings.cast::<ICoreWebView2Settings3>() {
                                    let _ = s3.SetAreBrowserAcceleratorKeysEnabled(false);
                                }
                            }
                        }
                    }
                });
            }

            if cfg!(debug_assertions) {
                state.mark_debug_ready();
                println!("[dev] 请手动启动后端：cd backend && python main.py");
            } else {
                let root = app.path().resource_dir().expect("读取资源目录失败");
                // resource_dir 返回 \\?\ verbatim 前缀路径，Python sqlite3 无法打开，剥掉再传
                let root = deverbatim(root);
                env_setup::start_pipeline(state, root);
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::prepare_environment,
            commands::open_url,
        ])
        .build(tauri::generate_context!())
        .expect("Tauri 构建失败")
        .run(|_app, event| {
            if let tauri::RunEvent::Exit = event {
                backend_proc::kill();
            }
        });
}
