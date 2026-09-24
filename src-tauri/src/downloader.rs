use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use std::time::Duration;

pub fn download(url: &str, dest: &Path, report: &dyn Fn(u64, u64)) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .connect_timeout(Duration::from_secs(20))
        .build()
        .map_err(|e| format!("构建 HTTP 客户端失败: {e}"))?;
    let mut resp = client
        .get(url)
        .send()
        .map_err(|e| format!("请求失败 {url}: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("下载失败 {url}: HTTP {}", resp.status()));
    }
    let total = resp
        .headers()
        .get(reqwest::header::CONTENT_LENGTH)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse::<u64>().ok())
        .unwrap_or(0);
    let mut file =
        File::create(dest).map_err(|e| format!("创建文件失败 {}: {e}", dest.display()))?;
    let mut buf = vec![0u8; 64 * 1024];
    let mut downloaded: u64 = 0;
    loop {
        let n = resp
            .read(&mut buf)
            .map_err(|e| format!("读取响应失败 {url}: {e}"))?;
        if n == 0 {
            break;
        }
        file.write_all(&buf[..n])
            .map_err(|e| format!("写入失败 {}: {e}", dest.display()))?;
        downloaded += n as u64;
        report(downloaded, total);
    }
    Ok(())
}

pub fn download_with_fallback(
    urls: &[String],
    dest: &Path,
    report: &dyn Fn(u64, u64),
) -> Result<(), String> {
    let mut last_err = String::new();
    for url in urls {
        match download(url, dest, report) {
            Ok(()) => return Ok(()),
            Err(e) => {
                let _ = std::fs::remove_file(dest);
                last_err = e;
            }
        }
    }
    Err(if last_err.is_empty() {
        "无可用下载源".into()
    } else {
        last_err
    })
}

pub fn extract_zip(zip_path: &Path, out_dir: &Path) -> Result<(), String> {
    let file = File::open(zip_path)
        .map_err(|e| format!("打开压缩包失败 {}: {e}", zip_path.display()))?;
    let mut archive = zip::ZipArchive::new(file)
        .map_err(|e| format!("读取压缩包失败 {}: {e}", zip_path.display()))?;
    archive
        .extract(out_dir)
        .map_err(|e| format!("解压失败 {}: {e}", zip_path.display()))
}
