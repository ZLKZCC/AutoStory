use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::util::no_window;

static BACKEND_CHILD: Mutex<Option<Child>> = Mutex::new(None);
static SHUTTING_DOWN: AtomicBool = AtomicBool::new(false);
static RESTARTS: AtomicU32 = AtomicU32::new(0);
static BACKEND_DEAD: AtomicBool = AtomicBool::new(false);

const MAX_RESTARTS: u32 = 3;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(600);

fn log_shell(root: &Path, msg: &str) {
    let path = root.join("logs").join("shell.log");
    if let Ok(mut f) = fs::OpenOptions::new().create(true).append(true).open(&path) {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis())
            .unwrap_or(0);
        let _ = writeln!(f, "[{ts}] {msg}");
    }
}

pub fn spawn_and_wait_healthy(root: &Path, port: u16, token: &str) -> Result<(), String> {
    log_shell(root, &format!("wait_healthy start: root={:?} port={} token_prefix={}", root, port, &token[..token.len().min(8)]));
    RESTARTS.store(0, Ordering::SeqCst);
    BACKEND_DEAD.store(false, Ordering::SeqCst);
    let child = spawn_backend(root, port, token)?;
    *BACKEND_CHILD.lock().unwrap() = Some(child);
    supervise(root.to_path_buf(), port, token.to_string());
    wait_healthy(root, port, token)
}

fn spawn_backend(root: &Path, port: u16, token: &str) -> Result<Child, String> {
    let logs = root.join("logs");
    fs::create_dir_all(&logs).map_err(|e| format!("创建日志目录失败: {e}"))?;
    let log_path = logs.join("backend.log");
    let stdout = File::options()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|e| format!("打开日志文件失败 {}: {e}", log_path.display()))?;
    let stderr = stdout
        .try_clone()
        .map_err(|e| format!("复制日志句柄失败: {e}"))?;

    let backend_exe = root.join("backend").join("autostory-backend.exe");
    log_shell(root, &format!("spawn: exe={:?} exists={} cwd={:?} port={} token_prefix={}", backend_exe, backend_exe.exists(), root, port, &token[..token.len().min(8)]));
    let mut cmd = Command::new(&backend_exe);
    cmd.current_dir(root)
        .env("AUTOSTORY_PORT", port.to_string())
        .env("AUTOSTORY_ROOT", root)
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    if !token.is_empty() {
        cmd.env("AUTOSTORY_APP_TOKEN", token);
    }
    no_window(&mut cmd);
    match cmd.spawn() {
        Ok(child) => Ok(child),
        Err(e) => {
            log_shell(root, &format!("spawn FAILED: kind={:?} msg={}", e.kind(), e));
            Err(format!("启动后端失败: {e}"))
        }
    }
}

fn supervise(root: PathBuf, port: u16, token: String) {
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_secs(2));
        if SHUTTING_DOWN.load(Ordering::SeqCst) {
            return;
        }
        let exited_code: Option<Option<i32>> = {
            let mut guard = BACKEND_CHILD.lock().unwrap();
            match guard.as_mut() {
                None => return,
                Some(child) => match child.try_wait() {
                    Ok(Some(status)) => Some(status.code()),
                    Ok(None) => None,
                    Err(e) => {
                        log_shell(&root, &format!("try_wait err: {e}"));
                        None
                    }
                },
            }
        };
        if let Some(code) = exited_code {
            log_shell(&root, &format!("backend exited: code={code:?} restarts={}", RESTARTS.load(Ordering::SeqCst)));
        }
        if exited_code.is_some() {
            if RESTARTS.fetch_add(1, Ordering::SeqCst) >= MAX_RESTARTS {
                BACKEND_DEAD.store(true, Ordering::SeqCst);
                return;
            }
            *BACKEND_CHILD.lock().unwrap() = None;
            match spawn_backend(&root, port, &token) {
                Ok(child) => *BACKEND_CHILD.lock().unwrap() = Some(child),
                Err(_) => {
                    BACKEND_DEAD.store(true, Ordering::SeqCst);
                    return;
                }
            }
        }
    });
}

fn wait_healthy(root: &Path, port: u16, token: &str) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        // 健康检查固定打 127.0.0.1，任何情况下都不该走系统代理
        .no_proxy()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| format!("构建 HTTP 客户端失败: {e}"))?;
    let url = format!("http://127.0.0.1:{port}/api/health");
    let start = Instant::now();
    loop {
        if start.elapsed() >= HEALTH_TIMEOUT {
            return Err("后端启动超时：600 秒内未完成 startup".into());
        }
        if BACKEND_DEAD.load(Ordering::SeqCst) {
            return Err(format!(
                "后端进程反复崩溃退出（重试 {MAX_RESTARTS} 次后放弃）。\n{}",
                tail_backend_log(root)
            ));
        }
        let mut req = client.get(&url);
        if !token.is_empty() {
            req = req.header("X-App-Token", token);
        }
        if let Ok(resp) = req.send() {
            if resp.status().is_success() {
                return Ok(());
            }
        }
        std::thread::sleep(Duration::from_secs(1));
    }
}

pub fn kill() {
    SHUTTING_DOWN.store(true, Ordering::SeqCst);
    if let Some(mut child) = BACKEND_CHILD.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn tail_backend_log(root: &Path) -> String {
    const MAX_BYTES: usize = 4000;
    let path = root.join("logs").join("backend.log");
    // 日志混有 GBK 字节（cmd/Python 中文输出），严格 UTF-8 解码会整体失败，必须无损解码
    let bytes = match fs::read(&path) {
        Ok(b) => b,
        Err(e) => return format!("（读取 logs/backend.log 失败: {e}）"),
    };
    let content = String::from_utf8_lossy(&bytes);
    let mut start = content.len().saturating_sub(MAX_BYTES);
    while !content.is_char_boundary(start) {
        start += 1;
    }
    format!("最近日志：\n{}", &content[start..])
}
