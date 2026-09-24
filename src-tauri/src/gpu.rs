use std::process::Command;

use crate::util::no_window;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum TorchVariant {
    Cu124,
    Cu121,
    Cpu,
}

impl TorchVariant {
    pub fn name(&self) -> &'static str {
        match self {
            TorchVariant::Cu124 => "cu124",
            TorchVariant::Cu121 => "cu121",
            TorchVariant::Cpu => "cpu",
        }
    }
}

pub fn detect_variant() -> TorchVariant {
    match nvidia_cuda_version() {
        Some((major, minor)) if major > 12 || (major == 12 && minor >= 4) => TorchVariant::Cu124,
        Some((12, minor)) if minor >= 1 => TorchVariant::Cu121,
        _ => TorchVariant::Cpu,
    }
}

fn nvidia_cuda_version() -> Option<(u32, u32)> {
    let mut cmd = Command::new("nvidia-smi");
    no_window(&mut cmd);
    let out = cmd.output().ok()?;
    if !out.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&out.stdout);
    let idx = text.find("CUDA Version:")?;
    let rest = text[idx + "CUDA Version:".len()..].trim_start();
    let ver: String = rest
        .chars()
        .take_while(|c| c.is_ascii_digit() || *c == '.')
        .collect();
    let mut parts = ver.split('.');
    let major = parts.next()?.parse().ok()?;
    let minor = parts.next().unwrap_or("0").parse().unwrap_or(0);
    Some((major, minor))
}
