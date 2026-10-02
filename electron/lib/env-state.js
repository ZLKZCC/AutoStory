// 启动页轮询的环境准备进度快照
const ITEM_PYTHON = "python";
const ITEM_PYTORCH = "pytorch";
const ITEM_FFMPEG = "ffmpeg";
const ITEM_BACKEND = "服务";

const SPEED_UNITS = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"];

function formatBytesPerSec(bps) {
  let v = bps;
  let unit = 0;
  while (v >= 1024 && unit < SPEED_UNITS.length - 1) {
    v /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? Math.round(v) : v.toFixed(1)} ${SPEED_UNITS[unit]}`;
}

function scale(progress, lo, hi) {
  return lo + Math.trunc(((hi - lo) * progress) / 100);
}

class EnvState {
  constructor() {
    this.items = [ITEM_PYTHON, ITEM_PYTORCH, ITEM_FFMPEG, ITEM_BACKEND].map((name) => ({
      name,
      progress: 0,
      speed: "",
      status: "pending",
      error: null,
      speedAnchor: null,
    }));
  }

  _update(name, fn) {
    const item = this.items.find((i) => i.name === name);
    if (item) fn(item);
  }

  markAllDone() {
    for (const item of this.items) {
      item.status = "done";
      item.progress = 100;
    }
  }

  setRunning(name) {
    this._update(name, (i) => (i.status = "running"));
  }

  finish(name) {
    this._update(name, (i) => {
      i.status = "done";
      i.progress = 100;
      i.speed = "";
      i.error = null;
    });
  }

  report(name, progress, speed) {
    this._update(name, (i) => {
      i.progress = progress;
      if (speed) i.speed = speed;
    });
  }

  // 对应 report_bytes：按已下载/总量换算进度，800ms 采样一次速度
  reportBytes(name, downloaded, total, lo, hi) {
    const now = Date.now();
    this._update(name, (i) => {
      if (total > 0) {
        const ratio = Math.min(100, Math.max(0, (downloaded / total) * 100));
        i.progress = scale(Math.trunc(ratio), lo, hi);
      }
      if (i.speedAnchor) {
        const { bytes, at } = i.speedAnchor;
        const elapsed = now - at;
        if (elapsed >= 800 && downloaded > bytes) {
          i.speed = formatBytesPerSec((downloaded - bytes) / (elapsed / 1000));
          i.speedAnchor = { bytes: downloaded, at: now };
        }
      } else {
        i.speedAnchor = { bytes: downloaded, at: now };
      }
    });
  }

  cascadeError(msg) {
    for (const item of this.items) {
      if (item.status === "pending" || item.status === "running") {
        item.status = "error";
        item.error = msg;
        item.speed = "";
      }
    }
  }

  // 渲染层可见的快照字段
  snapshot() {
    return this.items.map(({ name, progress, speed, status, error }) => ({
      name,
      progress,
      speed,
      status,
      error,
    }));
  }
}

const envState = new EnvState();

module.exports = { envState, EnvState, ITEM_PYTHON, ITEM_PYTORCH, ITEM_FFMPEG, ITEM_BACKEND, scale };
