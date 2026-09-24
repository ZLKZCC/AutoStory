/*
 * 占位数据统一包装 —— 供各域文件共享
 *
 * 模拟异步返回；替换真实请求后此函数可删除。
 */
export const ok = <T>(data: T, delay = 120): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(data), delay));
