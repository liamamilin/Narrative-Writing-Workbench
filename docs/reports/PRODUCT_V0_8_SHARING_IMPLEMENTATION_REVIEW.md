# Product V0.8 文章分享实施评审

日期：2026-09-23。状态：评审完成，工程实现见 [实施报告](PRODUCT_V0_8_SHARING_IMPLEMENTATION_REPORT.md)。

## 理解与规格决定

用户需要在当前文章页得到一个分享卡片和链接；链接打开精心设计的独立文章阅读页。入口放在正文工具栏“版本”之后，因为它作用于当前文章，并与导出、版本同属文章级操作。

Product V0 将 publishing integration 列为范围外；本次用户明确授权形成 V0.8 窄扩展。它不是内容平台：没有账户、评论、协作、推荐、关注、第三方代发布或搜索收录。

分享采用不可变快照。直接公开 Draft 会让读者看到作者尚未确认的后续编辑，也会让撤销和审计变得含糊，因此创建时复制标题与正文，并保存 Draft revision。更新分享会换新 token、使旧链接失效。

## 技术方案

- 继续使用 FastAPI、SQLite 和无构建 SPA，不引入前端框架。
- 数据库升至 v8，新增 `article_shares` 和 task 索引；进入严格备份与关系检查。
- Service 负责 revision 校验、字段上限、token、快照和撤销；API 只做路由与 HTML 响应。
- 公开 HTML 使用服务器端转义和字段白名单，不复用内部 Task JSON。
- 前端用 Canvas 从公开白名单绘制 1080×1440 PNG 卡片，避免增加图片生成依赖。
- 链接使用当前浏览器 origin；localhost 显示跨设备限制。

## 路由与界面

```text
Workspace toolbar 分享 → 分享 dialog
GET/POST/DELETE /tasks/:id/share → 管理当前分享
GET /s/:token → 独立阅读页
GET /s/:token/meta → 公开白名单数据
```

Dialog 展示署名、摘要、快照状态、链接、卡片预览、复制、系统分享、保存卡片和停止分享。公开页使用窄正文栏、中文衬线正文、清晰标题层级和移动端安全间距。

## 数据与安全

- token 由 24 bytes 随机数据生成，至少 192 bit。
- 公开页默认 noindex/no-referrer，禁止 iframe 嵌入和 MIME 猜测。
- 删除 Task 的既有事务先删除分享，Project 复用同一路径。
- 公开内容不含 Source、instruction、config、Review、Version、operation、模型设置和 API Key。
- 当前项目没有生产认证；链接本身是访问凭证。该限制会在 UI 和实施报告中明确。

## 测试计划

1. 创建、幂等读取、revision 冲突、替换 token、撤销和 404。
2. 编辑后快照不变；公开 HTML/JSON 隐私字段扫描。
3. Task/Project 删除清理及事务回滚。
4. v7→v8 迁移、v8 备份、v3–v7 兼容恢复和孤儿拒绝。
5. 工作台分享按钮、autosave、链接复制、卡片下载、更新和撤销。
6. 全量 pytest、JavaScript 语法及浏览器回归。

## 风险

- 本地地址不能被手机直接访问；功能只生成正确的 origin 相对链接，不假装完成公网部署。
- Web Share 和剪贴板能力因浏览器/安全上下文不同，需要复制与下载回退。
- Canvas 字体由浏览器环境决定；卡片以排版稳定和信息可读为先，不依赖远程字体。
