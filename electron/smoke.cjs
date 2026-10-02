// 冒烟脚本：通过 CDP 截图并验证 Electron 壳的 preload 注入与 IPC 桥
const fs = require("node:fs");

const PORT = process.argv[2] ?? "9223";
const OUT = process.argv[3] ?? "electron-smoke.png";

async function main() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const page = list.find((t) => t.type === "page");
  if (!page) throw new Error("找不到页面 target");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = rej;
  });

  let seq = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  };
  const send = (method, params = {}) =>
    new Promise((res) => {
      const id = ++seq;
      pending.set(id, res);
      ws.send(JSON.stringify({ id, method, params }));
    });

  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.result?.exceptionDetails) return { exception: r.result.exceptionDetails.text };
    return r.result?.result?.value;
  };

  const checks = {
    bootPort: await evaluate("window.autostoryBoot?.port"),
    bootTokenEmpty: await evaluate("window.autostoryBoot?.token === ''"),
    hasBridge: await evaluate("!!window.autostoryBridge"),
    isMaximized: await evaluate("window.autostoryBridge.isMaximized()"),
    bootItems: await evaluate(
      "window.autostoryBridge.envSnapshot().then(s => JSON.stringify(s.items.map(i => [i.name, i.status])))",
    ),
  };
  console.log(JSON.stringify(checks, null, 2));

  await send("Page.enable");
  const shot = await send("Page.captureScreenshot", { format: "png" });
  fs.writeFileSync(OUT, Buffer.from(shot.result.data, "base64"));
  console.log("screenshot ->", OUT);
  ws.close();
}

main().catch((e) => {
  console.error("SMOKE FAILED:", e.message);
  process.exit(1);
});
