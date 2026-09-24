use std::net::TcpListener;
use std::sync::OnceLock;

use uuid::Uuid;

pub struct RuntimeConfig {
    pub port: u16,
    pub token: String,
}

static CONFIG: OnceLock<RuntimeConfig> = OnceLock::new();

pub fn init() -> &'static RuntimeConfig {
    CONFIG.get_or_init(|| RuntimeConfig {
        port: if cfg!(debug_assertions) { 8080 } else { free_port() },
        token: if cfg!(debug_assertions) { String::new() } else { Uuid::new_v4().to_string() },
    })
}

pub fn current() -> &'static RuntimeConfig {
    CONFIG.get().expect("runtime config 未初始化（须先在 setup 中调用 init）")
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .expect("申请空闲端口失败")
        .local_addr()
        .expect("读取端口失败")
        .port()
}
