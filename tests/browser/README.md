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

自动化覆盖 B01–B08 的核心交互；B09 还验证 5,200 字中文剪贴板粘贴、合成 composition 事件、反向 Shift 连续选择、跨段文字选择与提案范围；B10 验证 Writing Map Enter、话题卡 Enter/Space、Escape 对话框焦点恢复和桌面截图；B11 验证未等待 autosave 的当前编辑与指定历史版本下载，并确认导出不创建版本或改变当前稿；B12 从设置页下载整库备份，上传预检后恢复到新目录，并确认当前 Draft 没有变化；B13 验证写前候选不生成正文、键盘选择、完整编辑、确认快照和确认后写作；B14 验证保留原文的冲突拒绝、取消保留、工作单提案拒绝后重开和接受后完成；B15 验证材料依据卡、素材定位、用户确认、接受前正文不变与接受后检查过期；B16 验证“原定路径”与当前“稿件检查”分离、逐段定位、问题提案、拒绝重开和接受后过期；B17 验证旧话题库确认迁移、未收藏候选不持久化、收藏/检索/备注、清空浏览器存储后重载，以及选题与任务关联和重开。B07 会在生成中强制结束 mock 服务，使用同一临时数据库和端口重启，再验证旧操作标为 interrupted、页面提示中断以及用户手动重试成功。自动化 composition 不等于真实中文输入法测试；B09–B17 的人工走查见 [人工验收表](MANUAL_ACCEPTANCE.md)。

同目录 package-lock.json 锁定 Playwright 依赖。测试不会读取用户数据库或真实 settings，不会调用模型服务。
