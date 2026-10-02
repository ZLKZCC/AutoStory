// 启动参数生成
// dev：端口 8080、无 token；release：空闲端口 + 随机 token
const net = require("node:net");
const crypto = require("node:crypto");

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
    srv.on("error", reject);
  });
}

async function runtimeConfig(isDev) {
  return {
    port: isDev ? 8080 : await freePort(),
    token: isDev ? "" : crypto.randomUUID(),
  };
}

module.exports = { runtimeConfig };
