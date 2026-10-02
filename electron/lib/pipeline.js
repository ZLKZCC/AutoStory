// 环境准备管线：python → pytorch → ffmpeg → 后端服务（manifest.json 断点续装）
const fs = require("node:fs");
const path = require("node:path");

const { download, downloadWithFallback, extractZip, gunzipTo } = require("./download");
const { detectVariant } = require("./gpu");
const pip = require("./pip");
const { spawnAndWaitHealthy } = require("./backend");
const { ITEM_PYTHON, ITEM_PYTORCH, ITEM_FFMPEG, ITEM_BACKEND, scale } = require("./env-state");

const PYTHON_VERSION = "3.12.10";

function loadManifest(runtime) {
  try {
    return JSON.parse(fs.readFileSync(path.join(runtime, "manifest.json"), "utf8"));
  } catch {
    return { python: false, torch: false, variant: "", ffmpeg: false };
  }
}

function saveManifest(runtime, manifest) {
  try {
    fs.mkdirSync(runtime, { recursive: true });
    fs.writeFileSync(
      path.join(runtime, "manifest.json"),
      JSON.stringify(manifest, null, 2),
    );
  } catch {
    /* 保存失败只是丢失断点，不影响本次安装 */
  }
}

function pthTag() {
  const [, minor] = PYTHON_VERSION.split(".");
  return `3${minor}`;
}

async function installPython(state, pythonDir, downloads) {
  const tag = pthTag();
  const file = `python-${PYTHON_VERSION}-embed-amd64.zip`;
  const urls = [
    `https://mirrors.huaweicloud.com/python/${PYTHON_VERSION}/${file}`,
    `https://www.python.org/ftp/python/${PYTHON_VERSION}/${file}`,
  ];
  const zip = path.join(downloads, file);
  await downloadWithFallback(urls, zip, (d, t) =>
    state.reportBytes(ITEM_PYTHON, d, t, 0, 50),
  );

  const extractDir = path.join(downloads, "python_extract");
  extractZip(zip, extractDir);
  const pth = path.join(extractDir, `python${tag}._pth`);
  fs.writeFileSync(pth, `python${tag}.zip\n.\nLib\\site-packages\nimport site\n`);
  if (fs.existsSync(pythonDir)) {
    fs.rmSync(pythonDir, { recursive: true, force: true });
  }
  fs.renameSync(extractDir, pythonDir);
  fs.rmSync(zip, { force: true });

  state.report(ITEM_PYTHON, 65, "");
  const getPip = path.join(downloads, "get-pip.py");
  await download(pip.GET_PIP_URL, getPip, (d, t) =>
    state.reportBytes(ITEM_PYTHON, d, t, 65, 80),
  );
  await pip.bootstrapPip(path.join(pythonDir, "python.exe"), getPip, (p, s) =>
    state.report(ITEM_PYTHON, scale(p, 80, 95), s),
  );
  fs.rmSync(getPip, { force: true });
}

async function checkDiskSpace(runtime, variant) {
  const needGb = variant === "cpu" ? 3.0 : 8.0;
  let free = 0;
  try {
    const st = await fs.promises.statfs(runtime);
    free = Number(st.bavail) * Number(st.bsize);
  } catch (e) {
    throw new Error(`读取磁盘剩余空间失败: ${e.message}`);
  }
  const freeGb = free / 1024 ** 3;
  if (freeGb < needGb) {
    throw new Error(
      `磁盘空间不足: 安装 PyTorch(${variant}) 约需 ${needGb.toFixed(0)}GB, 当前剩余 ${freeGb.toFixed(1)}GB, 请清理后重试`,
    );
  }
}

async function downloadWheel(state, urls, dest, lo, hi) {
  const part = dest.replace(/\.whl$/, ".part");
  await downloadWithFallback(urls, part, (d, t) => state.reportBytes(ITEM_PYTORCH, d, t, lo, hi));
  fs.renameSync(part, dest);
}

async function installTorchWheels(state, runtime, downloads, variant) {
  const wheels = path.join(downloads, "wheels");
  fs.mkdirSync(wheels, { recursive: true });

  const torchFile = `torch-${pip.TORCH_VERSION}+${variant}-cp312-cp312-win_amd64.whl`;
  const audioFile = `torchaudio-${pip.TORCHAUDIO_VERSION}+${variant}-cp312-cp312-win_amd64.whl`;
  const wheelUrls = (file) => {
    const encoded = file.replaceAll("+", "%2B");
    return [
      `https://mirror.sjtu.edu.cn/pytorch-wheels/${variant}/${encoded}`,
      `https://mirrors.aliyun.com/pytorch-wheels/${variant}/${encoded}`,
    ];
  };

  const torchPath = path.join(wheels, torchFile);
  if (!fs.existsSync(torchPath)) {
    await downloadWheel(state, wheelUrls(torchFile), torchPath, 0, 88);
  }
  const audioPath = path.join(wheels, audioFile);
  if (!fs.existsSync(audioPath)) {
    await downloadWheel(state, wheelUrls(audioFile), audioPath, 88, 90);
  }

  const pythonExe = path.join(runtime, "python", "python.exe");
  try {
    await pip.installTorchFromWheels(pythonExe, wheels, variant, (p, s) =>
      state.report(ITEM_PYTORCH, p, s),
    );
    fs.rmSync(wheels, { recursive: true, force: true });
  } catch (e) {
    throw e;
  }
}

async function installFfmpegNpmmirror(state, runtime, downloads) {
  const part = path.join(downloads, "ffmpeg-win32-x64.gz.part");
  try {
    await download(
      "https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.0/ffmpeg-win32-x64.gz",
      part,
      (d, t) => state.reportBytes(ITEM_FFMPEG, d, t, 0, 90),
    );
  } catch (e) {
    fs.rmSync(part, { force: true });
    throw e;
  }

  const binDir = path.join(runtime, "ffmpeg", "bin");
  fs.mkdirSync(binDir, { recursive: true });
  const exe = path.join(binDir, "ffmpeg.exe");
  await gunzipTo(part, exe);

  // 解出来的 exe 必须能跑（防下载损坏），对应 Rust 侧 ffmpeg -version 校验
  const { execFile } = require("node:child_process");
  const runnable = await new Promise((resolve) => {
    execFile(exe, ["-version"], { windowsHide: true, timeout: 15000 }, (err, stdout) =>
      resolve(!err && String(stdout).includes("ffmpeg")),
    );
  });
  fs.rmSync(part, { force: true });
  if (!runnable) {
    fs.rmSync(exe, { force: true });
    throw new Error("ffmpeg.exe 无法运行");
  }
  state.report(ITEM_FFMPEG, 95, "");
}

async function installFfmpegZip(state, runtime, downloads) {
  const urls = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
  ];
  const zip = path.join(downloads, "ffmpeg.zip");
  await downloadWithFallback(urls, zip, (d, t) =>
    state.reportBytes(ITEM_FFMPEG, d, t, 0, 85),
  );

  const extractDir = path.join(downloads, "ffmpeg_extract");
  extractZip(zip, extractDir);
  const inner = findDirWith(extractDir, ["bin", "ffmpeg.exe"]);
  if (!inner) throw new Error("压缩包结构异常：未找到 bin/ffmpeg.exe");
  const dest = path.join(runtime, "ffmpeg");
  if (fs.existsSync(dest)) {
    fs.rmSync(dest, { recursive: true, force: true });
  }
  fs.renameSync(inner, dest);
  fs.rmSync(extractDir, { recursive: true, force: true });
  fs.rmSync(zip, { force: true });
}

function findDirWith(root, rel) {
  const probe = (dir) => rel.every((part) => fs.existsSync(path.join(dir, ...part)));
  if (probe(root)) return root;
  let found = null;
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (entry.isDirectory() && probe(path.join(root, entry.name))) {
      found = path.join(root, entry.name);
      break;
    }
  }
  return found;
}

async function installFfmpeg(state, runtime, downloads) {
  try {
    await installFfmpegNpmmirror(state, runtime, downloads);
  } catch (e) {
    state.report(ITEM_FFMPEG, 2, "");
    try {
      await installFfmpegZip(state, runtime, downloads);
    } catch (e2) {
      throw new Error(`npmmirror 源失败: ${e.message}\n完整包源失败: ${e2.message}`);
    }
  }
}

async function runPipeline(state, root, rc) {
  const runtime = path.join(root, "runtime");
  const downloads = path.join(runtime, "_downloads");
  fs.mkdirSync(downloads, { recursive: true });

  const pythonDir = path.join(runtime, "python");
  const pythonExe = path.join(pythonDir, "python.exe");
  const manifest = loadManifest(runtime);

  state.setRunning(ITEM_PYTHON);
  if (!fs.existsSync(pythonExe)) {
    await installPython(state, pythonDir, downloads);
    manifest.python = true;
    saveManifest(runtime, manifest);
  }
  state.finish(ITEM_PYTHON);

  state.setRunning(ITEM_PYTORCH);
  const variant = detectVariant();
  const torchOk = fs.existsSync(
    path.join(pythonDir, "Lib", "site-packages", "torch"),
  );
  const variantOk = manifest.torch && manifest.variant === variant;
  if (!torchOk || !variantOk) {
    await checkDiskSpace(runtime, variant);
    await installTorchWheels(state, runtime, downloads, variant);
    manifest.torch = true;
    manifest.variant = variant;
    saveManifest(runtime, manifest);
  } else {
    state.report(ITEM_PYTORCH, 100, "");
  }
  state.finish(ITEM_PYTORCH);

  state.setRunning(ITEM_FFMPEG);
  const ffmpegExe = path.join(runtime, "ffmpeg", "bin", "ffmpeg.exe");
  if (!fs.existsSync(ffmpegExe)) {
    await installFfmpeg(state, runtime, downloads);
    manifest.ffmpeg = true;
    saveManifest(runtime, manifest);
  }
  state.finish(ITEM_FFMPEG);

  state.setRunning(ITEM_BACKEND);
  await spawnAndWaitHealthy(root, rc.port, rc.token);
  state.finish(ITEM_BACKEND);
}

function startPipeline(state, root, rc) {
  return runPipeline(state, root, rc).catch((e) => {
    // 把错误落到所有未完成项上，由启动页展示
    state.cascadeError(e instanceof Error ? e.message : String(e));
  });
}

module.exports = { startPipeline };
