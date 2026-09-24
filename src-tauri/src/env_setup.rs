use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Instant;

use serde::{Deserialize, Serialize};

use crate::backend_proc;
use crate::downloader::{download, download_with_fallback, extract_zip};
use crate::gpu::{detect_variant, TorchVariant};
use crate::pip;
use crate::runtime_config;
use crate::util::no_window;

pub const ITEM_PYTHON: &str = "python";
pub const ITEM_PYTORCH: &str = "pytorch";
pub const ITEM_FFMPEG: &str = "ffmpeg";
pub const ITEM_BACKEND: &str = "服务";

const PYTHON_VERSION: &str = "3.12.10";

#[derive(Clone, Serialize)]
pub struct PrepareItem {
    pub name: String,
    pub progress: u8,
    pub speed: String,
    pub status: String,
    pub error: Option<String>,
}

struct ItemInner {
    name: String,
    progress: u8,
    speed: String,
    status: String,
    error: Option<String>,
    speed_anchor: Option<(u64, Instant)>,
}

impl ItemInner {
    fn new(name: &str) -> Self {
        Self {
            name: name.to_string(),
            progress: 0,
            speed: String::new(),
            status: "pending".into(),
            error: None,
            speed_anchor: None,
        }
    }
}

pub struct EnvState {
    items: Mutex<Vec<ItemInner>>,
}

static SHARED: OnceLock<Arc<EnvState>> = OnceLock::new();

impl EnvState {
    pub fn shared() -> Arc<Self> {
        SHARED
            .get_or_init(|| {
                Arc::new(EnvState {
                    items: Mutex::new(vec![
                        ItemInner::new(ITEM_PYTHON),
                        ItemInner::new(ITEM_PYTORCH),
                        ItemInner::new(ITEM_FFMPEG),
                        ItemInner::new(ITEM_BACKEND),
                    ]),
                })
            })
            .clone()
    }

    pub fn mark_debug_ready(&self) {
        let mut items = self.items.lock().unwrap();
        for item in items.iter_mut() {
            item.status = "done".into();
            item.progress = 100;
        }
    }

    pub fn snapshot(&self) -> Vec<PrepareItem> {
        self.items
            .lock()
            .unwrap()
            .iter()
            .map(|i| PrepareItem {
                name: i.name.clone(),
                progress: i.progress,
                speed: i.speed.clone(),
                status: i.status.clone(),
                error: i.error.clone(),
            })
            .collect()
    }

    fn update<F: FnOnce(&mut ItemInner)>(&self, name: &str, f: F) {
        let mut items = self.items.lock().unwrap();
        if let Some(item) = items.iter_mut().find(|i| i.name == name) {
            f(item);
        }
    }

    fn set_running(&self, name: &str) {
        self.update(name, |i| i.status = "running".into());
    }

    fn finish(&self, name: &str) {
        self.update(name, |i| {
            i.status = "done".into();
            i.progress = 100;
            i.speed.clear();
            i.error = None;
        });
    }

    fn report(&self, name: &str, progress: u8, speed: &str) {
        self.update(name, |i| {
            i.progress = progress;
            if !speed.is_empty() {
                i.speed = speed.to_string();
            }
        });
    }

    fn report_bytes(&self, name: &str, downloaded: u64, total: u64, lo: u8, hi: u8) {
        let now = Instant::now();
        self.update(name, move |i| {
            if total > 0 {
                let ratio = ((downloaded as f64 / total as f64) * 100.0).clamp(0.0, 100.0);
                i.progress = scale(ratio as u8, lo, hi);
            }
            match i.speed_anchor {
                Some((bytes, at)) => {
                    let elapsed = now.duration_since(at).as_millis();
                    if elapsed >= 800 && downloaded > bytes {
                        let bps = (downloaded - bytes) as f64 / (elapsed as f64 / 1000.0);
                        i.speed = format_bytes_per_sec(bps);
                        i.speed_anchor = Some((downloaded, now));
                    }
                }
                None => i.speed_anchor = Some((downloaded, now)),
            }
        });
    }

    fn cascade_error(&self, msg: &str) {
        let mut items = self.items.lock().unwrap();
        for item in items.iter_mut() {
            if item.status == "pending" || item.status == "running" {
                item.status = "error".into();
                item.error = Some(msg.to_string());
                item.speed.clear();
            }
        }
    }
}

pub fn start_pipeline(state: Arc<EnvState>, root: PathBuf) {
    std::thread::spawn(move || {
        if let Err(e) = run_pipeline(&state, &root) {
            state.cascade_error(&e);
        }
    });
}

fn run_pipeline(state: &EnvState, root: &Path) -> Result<(), String> {
    let runtime = root.join("runtime");
    let downloads = runtime.join("_downloads");
    fs::create_dir_all(&downloads).map_err(|e| format!("创建 runtime 目录失败: {e}"))?;

    let python_dir = runtime.join("python");
    let python_exe = python_dir.join("python.exe");
    let mut manifest = Manifest::load(&runtime);

    state.set_running(ITEM_PYTHON);
    if !python_exe.exists() {
        install_python(state, &python_dir, &downloads)?;
        manifest.python = true;
        manifest.save(&runtime);
    }
    state.finish(ITEM_PYTHON);

    state.set_running(ITEM_PYTORCH);
    let variant = detect_variant();
    let torch_ok = python_dir.join("Lib").join("site-packages").join("torch").exists();
    let variant_ok = manifest.torch && manifest.variant == variant.name();
    if !torch_ok || !variant_ok {
        check_disk_space(&runtime, variant)?;
        install_torch_wheels(state, &runtime, &downloads, variant)?;
        manifest.torch = true;
        manifest.variant = variant.name().to_string();
        manifest.save(&runtime);
    } else {
        state.report(ITEM_PYTORCH, 100, "");
    }
    state.finish(ITEM_PYTORCH);

    state.set_running(ITEM_FFMPEG);
    let ffmpeg_exe = runtime.join("ffmpeg").join("bin").join("ffmpeg.exe");
    if !ffmpeg_exe.exists() {
        install_ffmpeg(state, &runtime, &downloads)?;
        manifest.ffmpeg = true;
        manifest.save(&runtime);
    }
    state.finish(ITEM_FFMPEG);

    state.set_running(ITEM_BACKEND);
    let rc = runtime_config::current();
    backend_proc::spawn_and_wait_healthy(root, rc.port, &rc.token)?;
    state.finish(ITEM_BACKEND);
    Ok(())
}

fn install_python(state: &EnvState, python_dir: &Path, downloads: &Path) -> Result<(), String> {
    let tag = pth_tag();
    let file = format!("python-{PYTHON_VERSION}-embed-amd64.zip");
    let urls = vec![
        format!("https://mirrors.huaweicloud.com/python/{PYTHON_VERSION}/{file}"),
        format!("https://www.python.org/ftp/python/{PYTHON_VERSION}/{file}"),
    ];
    let zip = downloads.join(&file);
    download_with_fallback(&urls, &zip, &|d, t| state.report_bytes(ITEM_PYTHON, d, t, 0, 50))?;

    let extract_dir = downloads.join("python_extract");
    extract_zip(&zip, &extract_dir)?;
    let pth = extract_dir.join(format!("python{tag}._pth"));
    fs::write(&pth, format!("python{tag}.zip\n.\nLib\\site-packages\nimport site\n"))
        .map_err(|e| format!("改写 ._pth 失败: {e}"))?;
    if python_dir.exists() {
        fs::remove_dir_all(python_dir).map_err(|e| format!("清理旧 Python 目录失败: {e}"))?;
    }
    fs::rename(&extract_dir, python_dir).map_err(|e| format!("就位 Python 目录失败: {e}"))?;
    let _ = fs::remove_file(&zip);

    state.report(ITEM_PYTHON, 65, "");
    let get_pip = downloads.join("get-pip.py");
    download(pip::GET_PIP_URL, &get_pip, &|d, t| {
        state.report_bytes(ITEM_PYTHON, d, t, 65, 80)
    })?;
    pip::bootstrap_pip(&python_dir.join("python.exe"), &get_pip, &|p, s| {
        state.report(ITEM_PYTHON, scale(p, 80, 95), s)
    })?;
    let _ = fs::remove_file(&get_pip);
    Ok(())
}

fn check_disk_space(runtime: &Path, variant: TorchVariant) -> Result<(), String> {
    let need_gb: f64 = if variant == TorchVariant::Cpu { 3.0 } else { 8.0 };
    let free = fs2::available_space(runtime)
        .map_err(|e| format!("读取磁盘剩余空间失败: {e}"))?;
    let free_gb = free as f64 / 1024.0 / 1024.0 / 1024.0;
    if free_gb < need_gb {
        Err(format!(
            "磁盘空间不足: 安装 PyTorch({}) 约需 {need_gb:.0}GB, 当前剩余 {free_gb:.1}GB, 请清理后重试",
            variant.name()
        ))
    } else {
        Ok(())
    }
}

fn install_torch_wheels(
    state: &EnvState,
    runtime: &Path,
    downloads: &Path,
    variant: TorchVariant,
) -> Result<(), String> {
    let name = variant.name();
    let wheels = downloads.join("wheels");
    fs::create_dir_all(&wheels).map_err(|e| format!("创建 wheels 目录失败: {e}"))?;

    let torch_file = format!("torch-{}+{name}-cp312-cp312-win_amd64.whl", pip::TORCH_VERSION);
    let audio_file = format!(
        "torchaudio-{}+{name}-cp312-cp312-win_amd64.whl",
        pip::TORCHAUDIO_VERSION
    );
    let wheel_urls = |file: &str| {
        let encoded = file.replace('+', "%2B");
        vec![
            format!("https://mirror.sjtu.edu.cn/pytorch-wheels/{name}/{encoded}"),
            format!("https://mirrors.aliyun.com/pytorch-wheels/{name}/{encoded}"),
        ]
    };

    let torch_path = wheels.join(&torch_file);
    if !torch_path.exists() {
        download_wheel(state, &wheel_urls(&torch_file), &torch_path, 0, 88)?;
    }
    let audio_path = wheels.join(&audio_file);
    if !audio_path.exists() {
        download_wheel(state, &wheel_urls(&audio_file), &audio_path, 88, 90)?;
    }

    let python_exe = runtime.join("python").join("python.exe");
    let result = pip::install_torch_from_wheels(&python_exe, &wheels, variant, &|p, s| {
        state.report(ITEM_PYTORCH, p, s)
    });
    if result.is_ok() {
        let _ = fs::remove_dir_all(&wheels);
    }
    result
}

fn download_wheel(state: &EnvState, urls: &[String], dest: &Path, lo: u8, hi: u8) -> Result<(), String> {
    let part = dest.with_extension("part");
    let r = download_with_fallback(urls, &part, &|d, t| state.report_bytes(ITEM_PYTORCH, d, t, lo, hi));
    match r {
        Ok(()) => fs::rename(&part, dest).map_err(|e| format!("就位 wheel 失败: {e}")),
        Err(e) => Err(format!("下载 wheel 失败: {e}")),
    }
}

fn install_ffmpeg(state: &EnvState, runtime: &Path, downloads: &Path) -> Result<(), String> {
    if let Err(e) = install_ffmpeg_npmmirror(state, runtime, downloads) {
        state.report(ITEM_FFMPEG, 2, "");
        return install_ffmpeg_zip(state, runtime, downloads)
            .map_err(|e2| format!("npmmirror 源失败: {e}\n完整包源失败: {e2}"));
    }
    Ok(())
}

fn install_ffmpeg_npmmirror(state: &EnvState, runtime: &Path, downloads: &Path) -> Result<(), String> {
    let part = downloads.join("ffmpeg-win32-x64.gz.part");
    if let Err(e) = download(
        "https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.0/ffmpeg-win32-x64.gz",
        &part,
        &|d, t| state.report_bytes(ITEM_FFMPEG, d, t, 0, 90),
    ) {
        let _ = fs::remove_file(&part);
        return Err(e);
    }

    let bin_dir = runtime.join("ffmpeg").join("bin");
    fs::create_dir_all(&bin_dir).map_err(|e| format!("创建 ffmpeg 目录失败: {e}"))?;
    let exe = bin_dir.join("ffmpeg.exe");
    let input = fs::File::open(&part).map_err(|e| format!("打开压缩文件失败: {e}"))?;
    let mut decoder = flate2::read::GzDecoder::new(input);
    let mut output = fs::File::create(&exe).map_err(|e| format!("创建 ffmpeg.exe 失败: {e}"))?;
    io::copy(&mut decoder, &mut output).map_err(|e| format!("解压 ffmpeg 失败: {e}"))?;
    drop(output);

    let mut cmd = Command::new(&exe);
    cmd.arg("-version");
    no_window(&mut cmd);
    let runnable = cmd.output().map(|o| o.status.success()).unwrap_or(false);
    let _ = fs::remove_file(&part);
    if !runnable {
        let _ = fs::remove_file(&exe);
        return Err("ffmpeg.exe 无法运行".into());
    }
    state.report(ITEM_FFMPEG, 95, "");
    Ok(())
}

fn install_ffmpeg_zip(state: &EnvState, runtime: &Path, downloads: &Path) -> Result<(), String> {
    let urls = vec![
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip".to_string(),
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
            .to_string(),
    ];
    let zip = downloads.join("ffmpeg.zip");
    download_with_fallback(&urls, &zip, &|d, t| state.report_bytes(ITEM_FFMPEG, d, t, 0, 85))?;

    let extract_dir = downloads.join("ffmpeg_extract");
    extract_zip(&zip, &extract_dir)?;
    let inner = find_dir_with(&extract_dir, &["bin", "ffmpeg.exe"])
        .ok_or("压缩包结构异常：未找到 bin/ffmpeg.exe")?;
    let dest = runtime.join("ffmpeg");
    if dest.exists() {
        fs::remove_dir_all(&dest).map_err(|e| format!("清理旧 ffmpeg 目录失败: {e}"))?;
    }
    fs::rename(&inner, &dest).map_err(|e| format!("就位 ffmpeg 目录失败: {e}"))?;
    let _ = fs::remove_dir_all(&extract_dir);
    let _ = fs::remove_file(&zip);
    Ok(())
}

fn find_dir_with(root: &Path, rel: &[&str]) -> Option<PathBuf> {
    let probe = |dir: &Path| {
        let mut p = dir.to_path_buf();
        for part in rel {
            p = p.join(part);
        }
        p.exists()
    };
    if probe(root) {
        return Some(root.to_path_buf());
    }
    for entry in fs::read_dir(root).ok()? {
        let entry = entry.ok()?;
        if entry.path().is_dir() && probe(&entry.path()) {
            return Some(entry.path());
        }
    }
    None
}

#[derive(Serialize, Deserialize, Default)]
#[serde(default)]
struct Manifest {
    python: bool,
    torch: bool,
    variant: String,
    ffmpeg: bool,
}

impl Manifest {
    fn load(runtime: &Path) -> Self {
        fs::read_to_string(runtime.join("manifest.json"))
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default()
    }

    fn save(&self, runtime: &Path) {
        if let Ok(json) = serde_json::to_string_pretty(self) {
            let _ = fs::write(runtime.join("manifest.json"), json);
        }
    }
}

fn pth_tag() -> String {
    let mut it = PYTHON_VERSION.split('.');
    let major = it.next().unwrap_or("3");
    let minor = it.next().unwrap_or("12");
    format!("{major}{minor}")
}

fn scale(progress: u8, lo: u8, hi: u8) -> u8 {
    lo + ((hi - lo) as u16 * progress as u16 / 100) as u8
}

fn format_bytes_per_sec(bps: f64) -> String {
    const UNITS: [&str; 5] = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"];
    let mut v = bps;
    let mut unit = 0;
    while v >= 1024.0 && unit < UNITS.len() - 1 {
        v /= 1024.0;
        unit += 1;
    }
    if unit == 0 {
        format!("{v:.0} {}", UNITS[unit])
    } else {
        format!("{v:.1} {}", UNITS[unit])
    }
}
