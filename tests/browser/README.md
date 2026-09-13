# Browser checks

从仓库根目录运行（Python 3.10+，Node 22；先装 requirements-test.txt）：

```bash
npm --prefix tests/browser ci --ignore-scripts --no-audit --no-fund
cd tests/browser
npx playwright install chromium
cd ../..
node tests/browser/smoke.cjs
```

Linux CI 使用 `npx playwright install --with-deps chromium` 安装浏览器系统依赖；配置依据 [Playwright CI 文档](https://playwright.dev/docs/ci)。CI 使用顺序运行的独立 mock 服务。

可指定 `PYTHON_BIN` 与 `BROWSER_EXECUTABLE` 使用现有 Python/Chrome。脚本创建空白浏览器上下文，不复用个人资料；以随机端口启动 scripts/mock_server.py，等待 ready，结束关闭浏览器与子进程并清理临时数据库。截图和结果在 `.scratch/browser-report/`。

自动化覆盖 B01–B08 的核心交互，额外模拟 B09 composition 事件并验证 B10 键盘对话框与桌面截图。B07 会在生成中强制结束 mock 服务，使用同一临时数据库和端口重启，再验证旧操作标为 interrupted、页面提示中断以及用户手动重试成功。合成 composition 不等于真实中文输入法测试；B09 的原生输入法和 B10 的人工键盘走查见 [人工验收表](MANUAL_ACCEPTANCE.md)。

同目录 package-lock.json 锁定 Playwright 依赖。测试不会读取用户数据库或真实 settings，不会调用模型服务。
