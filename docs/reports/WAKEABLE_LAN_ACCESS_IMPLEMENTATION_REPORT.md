# 可唤醒 URL 与局域网访问实现报告

日期：2026-09-26

## 目标

保留 Workbench 工作进程 30 分钟无请求自动退出的资源回收行为，同时让原来的启动 URL 在过期后仍可再次访问；启动同一实例时，允许同一无线网络中的手机访问。

## 实现

- 新增 `workbench/wake.py`：标准库 `ThreadingHTTPServer` 监听公开端口，工作进程在本机随机端口运行。
- 首次请求或工作进程已退出时，代理按需启动 `python -m workbench.server`，等待 `/settings` 就绪后转发原请求。
- 代理只转发必要 HTTP 方法并过滤 hop-by-hop 头；普通响应补齐长度，SSE 响应保持流式转发；`HEAD` 不发送响应体。
- `scripts/launch_workbench.sh` 默认让代理监听 `0.0.0.0`，检测 `en0`/`en1` 的局域网地址并打印手机 URL。设置 `WORKBENCH_HOST=127.0.0.1` 可关闭局域网监听。
- `scripts/launch_workbench.sh stop` 停止公开入口，入口退出时也会回收当前工作进程。

## 使用

```bash
./scripts/launch_workbench.sh
# 本机：http://127.0.0.1:8600
# 手机：终端打印的 http://<局域网IP>:8600
```

手机和电脑需要处于同一无线网络。当前产品没有账号和访问控制，局域网地址上的文章和工作台操作对同一网络中持有地址的设备可见；不可信网络应使用本机-only 模式或后续增加访问控制。

## 验证

- `python3 -m py_compile workbench/wake.py workbench/server.py`
- `bash -n scripts/launch_workbench.sh`
- 短超时集成演练：首次请求成功，工作进程空闲退出后同一 URL 再次请求成功；SIGTERM 停止代理和子进程无挂起。
- 完整 Python 回归测试沿用现有产品测试套件，结果记录在开发进展日志。
