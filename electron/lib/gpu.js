// nvidia-smi 探测 CUDA 版本，决定 PyTorch wheel 变体
const { spawnSync } = require("node:child_process");

function detectVariant() {
  const r = spawnSync("nvidia-smi", [], { windowsHide: true });
  if (r.error || r.status !== 0) return "cpu";
  const text = r.stdout.toString("utf8");
  const idx = text.indexOf("CUDA Version:");
  if (idx < 0) return "cpu";
  const ver = (text.slice(idx + "CUDA Version:".length).match(/^[\d.]*/) ?? [""])[0];
  const major = Number.parseInt(ver.split(".")[0], 10);
  const minor = Number.parseInt(ver.split(".")[1] ?? "0", 10) || 0;
  if (Number.isNaN(major)) return "cpu";
  if (major > 12 || (major === 12 && minor >= 4)) return "cu124";
  if (major === 12 && minor >= 1) return "cu121";
  return "cpu";
}

module.exports = { detectVariant };
