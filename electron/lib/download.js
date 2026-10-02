// 流式下载（进度回调）+ 多源回退 + zip/gzip 解压
const fs = require("node:fs");
const zlib = require("node:zlib");
const { pipeline } = require("node:stream/promises");
const { Readable } = require("node:stream");
const AdmZip = require("adm-zip");

async function download(url, dest, report) {
  let resp;
  try {
    resp = await fetch(url, { redirect: "follow" });
  } catch (e) {
    throw new Error(`请求失败 ${url}: ${e.message}`);
  }
  if (!resp.ok) {
    throw new Error(`下载失败 ${url}: HTTP ${resp.status}`);
  }
  const total = Number(resp.headers.get("content-length") ?? 0);
  let downloaded = 0;
  const out = fs.createWriteStream(dest);
  const src = Readable.fromWeb(resp.body);
  src.on("data", (chunk) => {
    downloaded += chunk.length;
    report(downloaded, total);
  });
  await pipeline(src, out);
}

async function downloadWithFallback(urls, dest, report) {
  let lastErr = "";
  for (const url of urls) {
    try {
      await download(url, dest, report);
      return;
    } catch (e) {
      try {
        fs.rmSync(dest, { force: true });
      } catch {
        /* 清理失败不阻塞下一源 */
      }
      lastErr = e.message ?? String(e);
    }
  }
  throw new Error(lastErr || "无可用下载源");
}

function extractZip(zipPath, outDir) {
  try {
    new AdmZip(zipPath).extractAllTo(outDir, true);
  } catch (e) {
    throw new Error(`解压失败 ${zipPath}: ${e.message}`);
  }
}

function gunzipTo(srcGz, destOut) {
  return pipeline(
    fs.createReadStream(srcGz),
    zlib.createGunzip(),
    fs.createWriteStream(destOut),
  );
}

module.exports = { download, downloadWithFallback, extractZip, gunzipTo };
