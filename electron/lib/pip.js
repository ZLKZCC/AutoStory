// get-pip 引导与 torch wheel 安装（stdout 进度解析）
const { spawn } = require("node:child_process");

const TORCH_VERSION = "2.5.1";
const TORCHAUDIO_VERSION = "2.5.1";
const GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py";

function runPip(pythonExe, args, phase, report) {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonExe, args, {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.on("error", (e) => reject(new Error(`启动 pip 失败: ${e.message}`)));

    const recent = [];
    let downloadsSeen = 0;
    let buf = "";
    const dec = new TextDecoder("utf-8");
    child.stdout.on("data", (chunk) => {
      // pip 用 \r 刷新进度条，逐行扫描时把进度条行（含 % 或 /s）从错误摘要里剔除
      buf += dec.decode(chunk, { stream: true });
      const parts = buf.split(/\r|\n/);
      buf = parts.pop() ?? "";
      for (const raw of parts) {
        const line = raw.trim();
        if (!line) continue;
        const isBar = line.includes("%") || line.includes("/s");
        if (!isBar) {
          recent.push(line);
          if (recent.length > 6) recent.shift();
        }
        if (phase === "wheels") {
          if (line.startsWith("Processing") || line.startsWith("Downloading")) {
            report(92, "");
          } else if (line.startsWith("Installing collected packages")) {
            report(95, "");
          }
        } else {
          if (line.startsWith("Downloading")) {
            downloadsSeen += 1;
            report(Math.min(80, Math.min(18, downloadsSeen) * 4), "");
          } else if (line.startsWith("Installing collected packages")) {
            report(90, "");
          }
        }
      }
    });
    child.stderr.resume(); // 只排空，与 Rust 侧 drain 线程一致

    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`pip 安装失败:\n${recent.join("\n")}`));
      } else {
        report(100, "");
        resolve();
      }
    });
  });
}

function bootstrapPip(pythonExe, getPipPy, report) {
  return runPip(pythonExe, [getPipPy, "--no-warn-script-location"], "requirements", report);
}

function installTorchFromWheels(pythonExe, wheelsDir, variant, report) {
  const args = [
    "-m",
    "pip",
    "install",
    "--no-warn-script-location",
    "--disable-pip-version-check",
    `torch==${TORCH_VERSION}+${variant}`,
    `torchaudio==${TORCHAUDIO_VERSION}+${variant}`,
    `--find-links=${wheelsDir}`,
    "--index-url=https://mirrors.aliyun.com/pypi/simple/",
  ];
  return runPip(pythonExe, args, "wheels", report);
}

module.exports = { TORCH_VERSION, TORCHAUDIO_VERSION, GET_PIP_URL, bootstrapPip, installTorchFromWheels };
