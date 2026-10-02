// 后端进程托管
// spawn（注入 AUTOSTORY_PORT/AUTOSTORY_ROOT/AUTOSTORY_APP_TOKEN）→ 2s 监视循环
// （崩溃最多重启 3 次）→ /api/health 健康轮询（600s 上限）→ kill 于应用退出
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const MAX_RESTARTS = 3;
const HEALTH_TIMEOUT = 600_000;

let child = null;
let shuttingDown = false;
let restarts = 0;
let backendDead = false;
let superviseTimer = null;
let respawning = false;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function logShell(root, msg) {
  const logPath = path.join(root, "logs", "shell.log");
  try {
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    fs.appendFileSync(logPath, `[${Date.now()}] ${msg}\n`);
  } catch {
    /* 日志失败不影响主流程 */
  }
}

function tailBackendLog(root) {
  const MAX_BYTES = 4000;
  const logPath = path.join(root, "logs", "backend.log");
  let bytes;
  try {
    bytes = fs.readFileSync(logPath);
  } catch {
    return "（读取 logs/backend.log 失败）";
  }
  // 日志混有 GBK 字节（cmd/Python 中文输出），严格 UTF-8 解码会整体失败，必须无损解码
  const content = bytes.toString("utf8");
  return `最近日志：\n${content.length > MAX_BYTES ? content.slice(-MAX_BYTES) : content}`;
}

function spawnBackend(root, port, token) {
  return new Promise((resolve, reject) => {
    const logs = path.join(root, "logs");
    fs.mkdirSync(logs, { recursive: true });
    const logPath = path.join(logs, "backend.log");
    const out = fs.openSync(logPath, "a");

    const exe = path.join(root, "backend", "autostory-backend.exe");
    logShell(
      root,
      `spawn: exe=${exe} exists=${fs.existsSync(exe)} cwd=${root} port=${port} token_prefix=${token.slice(0, 8)}`,
    );
    const env = {
      ...process.env,
      AUTOSTORY_PORT: String(port),
      AUTOSTORY_ROOT: root,
    };
    if (token) env.AUTOSTORY_APP_TOKEN = token;

    const c = spawn(exe, [], {
      cwd: root,
      env,
      windowsHide: true,
      stdio: ["ignore", out, out],
    });
    c.on("spawn", () => resolve(c));
    c.on("error", (e) => {
      logShell(root, `spawn FAILED: msg=${e.message}`);
      reject(new Error(`启动后端失败: ${e.message}`));
    });
  });
}

function supervise(root, port, token) {
  superviseTimer = setInterval(async () => {
    if (shuttingDown || respawning) return;
    if (!child) return;
    const code = child.exitCode; // null = 仍在运行
    if (code === null && child.signalCode === null) return;

    logShell(root, `backend exited: code=${code ?? child.signalCode} restarts=${restarts}`);
    respawning = true;
    child = null;
    const old = restarts;
    restarts = old + 1;
    if (old >= MAX_RESTARTS) {
      backendDead = true;
      respawning = false;
      return;
    }
    try {
      child = await spawnBackend(root, port, token);
    } catch (e) {
      backendDead = true;
      logShell(root, `respawn failed: ${e.message}`);
    }
    respawning = false;
  }, 2000);
}

async function waitHealthy(root, port, token) {
  const url = `http://127.0.0.1:${port}/api/health`;
  const start = Date.now();
  for (;;) {
    if (Date.now() - start >= HEALTH_TIMEOUT) {
      throw new Error("后端启动超时：600 秒内未完成 startup");
    }
    if (backendDead) {
      throw new Error(
        `后端进程反复崩溃退出（重试 ${MAX_RESTARTS} 次后放弃）。\n${tailBackendLog(root)}`,
      );
    }
    try {
      // 健康检查固定打 127.0.0.1，任何情况下都不该走系统代理（Node fetch 默认不走代理）
      const resp = await fetch(url, {
        headers: token ? { "X-App-Token": token } : {},
        signal: AbortSignal.timeout(2000),
      });
      if (resp.ok) return;
    } catch {
      /* 未就绪，1s 后重试 */
    }
    await sleep(1000);
  }
}

async function spawnAndWaitHealthy(root, port, token) {
  shuttingDown = false;
  restarts = 0;
  backendDead = false;
  child = await spawnBackend(root, port, token);
  supervise(root, port, token);
  await waitHealthy(root, port, token);
}

function killBackend() {
  shuttingDown = true;
  if (superviseTimer) {
    clearInterval(superviseTimer);
    superviseTimer = null;
  }
  if (child) {
    try {
      child.kill();
    } catch {
      /* 进程可能已退出 */
    }
    child = null;
  }
}

module.exports = { spawnAndWaitHealthy, killBackend };
