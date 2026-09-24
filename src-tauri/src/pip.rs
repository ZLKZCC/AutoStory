use std::collections::VecDeque;
use std::io::{BufReader, Read};
use std::path::Path;
use std::process::{Command, Stdio};

use crate::gpu::TorchVariant;
use crate::util::no_window;

pub const TORCH_VERSION: &str = "2.5.1";
pub const TORCHAUDIO_VERSION: &str = "2.5.1";
pub const GET_PIP_URL: &str = "https://bootstrap.pypa.io/get-pip.py";

enum Phase {
    Wheels,
    Requirements,
}

pub fn bootstrap_pip(python_exe: &Path, get_pip_py: &Path, report: &dyn Fn(u8, &str)) -> Result<(), String> {
    let args = vec![
        get_pip_py.to_string_lossy().into_owned(),
        "--no-warn-script-location".into(),
    ];
    run_pip(python_exe, &args, Phase::Requirements, report)
}

pub fn install_torch_from_wheels(
    python_exe: &Path,
    wheels_dir: &Path,
    variant: TorchVariant,
    report: &dyn Fn(u8, &str),
) -> Result<(), String> {
    let name = variant.name();
    let args: Vec<String> = [
        "-m".to_string(),
        "pip".to_string(),
        "install".to_string(),
        "--no-warn-script-location".into(),
        "--disable-pip-version-check".into(),
        format!("torch=={TORCH_VERSION}+{name}"),
        format!("torchaudio=={TORCHAUDIO_VERSION}+{name}"),
        format!("--find-links={}", wheels_dir.display()),
        "--index-url=https://mirrors.aliyun.com/pypi/simple/".into(),
    ]
    .to_vec();
    run_pip(python_exe, &args, Phase::Wheels, report)
}

fn run_pip(python_exe: &Path, args: &[String], phase: Phase, report: &dyn Fn(u8, &str)) -> Result<(), String> {
    let mut cmd = Command::new(python_exe);
    cmd.args(args).stdout(Stdio::piped()).stderr(Stdio::piped());
    no_window(&mut cmd);
    let mut child = cmd.spawn().map_err(|e| format!("启动 pip 失败: {e}"))?;

    let stderr_handle = child.stderr.take();
    let _drain = std::thread::spawn(move || {
        if let Some(mut e) = stderr_handle {
            let mut sink = Vec::new();
            let _ = e.read_to_end(&mut sink);
        }
    });

    let mut recent: VecDeque<String> = VecDeque::new();
    let mut downloads_seen: u32 = 0;
    if let Some(stdout) = child.stdout.take() {
        let mut reader = BufReader::new(stdout);
        let mut segment: Vec<u8> = Vec::new();
        let mut chunk = [0u8; 4096];
        loop {
            let n = match reader.read(&mut chunk) {
                Ok(0) | Err(_) => break,
                Ok(n) => n,
            };
            for &b in &chunk[..n] {
                if b == b'\r' || b == b'\n' {
                    if !segment.is_empty() {
                        let line = String::from_utf8_lossy(&segment).trim().to_string();
                        if !line.is_empty() {
                            let is_bar = line.contains('%') || line.contains("/s");
                            if !is_bar {
                                if recent.len() == 6 {
                                    recent.pop_front();
                                }
                                recent.push_back(line.clone());
                            }
                            match phase {
                                Phase::Wheels => {
                                    if line.starts_with("Processing") || line.starts_with("Downloading") {
                                        report(92, "");
                                    } else if line.starts_with("Installing collected packages") {
                                        report(95, "");
                                    }
                                }
                                Phase::Requirements => {
                                    if line.starts_with("Downloading") {
                                        downloads_seen += 1;
                                        report((downloads_seen.min(18) * 4).min(80) as u8, "");
                                    } else if line.starts_with("Installing collected packages") {
                                        report(90, "");
                                    }
                                }
                            }
                        }
                        segment.clear();
                    }
                } else {
                    segment.push(b);
                }
            }
        }
    }

    let status = child.wait().map_err(|e| format!("等待 pip 退出失败: {e}"))?;
    let _ = _drain.join();
    if !status.success() {
        let tail: Vec<String> = recent.into_iter().collect();
        return Err(format!("pip 安装失败:\n{}", tail.join("\n")));
    }
    report(100, "");
    Ok(())
}
