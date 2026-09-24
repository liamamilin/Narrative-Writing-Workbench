/* Narrative Writing Workbench — V0 SPA (no build step) */
"use strict";

/* ------------------------------------------------------------------ util */
const $ = (sel, el = document) => el.querySelector(sel);
const esc = s => (s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function api(method, path, body) {
  let r;
  try {
    r = await fetch(path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (_) {
    // Browser-level fetch failure: the backend itself is unreachable
    // (idle auto-shutdown, crash, wrong port) — NOT the LLM provider.
    throw { code: "BACKEND_DOWN",
      message: "连不上本机 Workbench 服务（它可能因空闲自动退出了）。请先在终端运行 python -m workbench.server，再刷新页面重试。",
      retryable: true, backendDown: true };
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = data.error || { code: "NETWORK", message: r.statusText, retryable: false };
    throw e;
  }
  return data;
}

async function downloadExport(path) {
  let r;
  try { r = await fetch(path); }
  catch (_) {
    throw { code: "BACKEND_DOWN", message: "连不上本机 Workbench 服务。", retryable: true };
  }
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw data.error || { code: "NETWORK", message: r.statusText, retryable: false };
  }
  const disposition = r.headers.get("Content-Disposition") || "";
  const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const plain = disposition.match(/filename="([^"]+)"/i);
  let filename = plain?.[1] || "稿件.md";
  if (utf8) {
    try { filename = decodeURIComponent(utf8[1]); } catch (_) { /* use safe fallback */ }
  }
  const url = URL.createObjectURL(await r.blob());
  const link = document.createElement("a");
  link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return filename;
}

function defaultShareExcerpt(content) {
  const paragraph = (content || "").split(/\n\s*\n/).find(part => part.trim()) || "";
  const compact = paragraph.replace(/\s+/g, " ").trim();
  return compact.length <= 180 ? compact : compact.slice(0, 179).trimEnd() + "…";
}

function absoluteShareUrl(share) {
  return new URL(share.path, window.location.href).href;
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(value); return; } catch (_) { /* fallback */ }
  }
  const input = document.createElement("textarea");
  input.value = value; input.readOnly = true; input.style.position = "fixed";
  input.style.opacity = "0"; document.body.appendChild(input); input.select();
  const copied = document.execCommand("copy"); input.remove();
  if (!copied) throw new Error("浏览器未允许复制，请手动复制链接。");
}

function canvasLines(ctx, text, maxWidth, maxLines) {
  const lines = []; let line = "";
  for (const char of Array.from(text || "")) {
    const next = line + char;
    if (line && ctx.measureText(next).width > maxWidth) {
      lines.push(line); line = char;
      if (lines.length === maxLines) break;
    } else line = next;
  }
  if (lines.length < maxLines && line) lines.push(line);
  if (lines.length === maxLines && Array.from(text || "").join("") !== lines.join("")) {
    let last = lines[maxLines - 1];
    while (last && ctx.measureText(last + "…").width > maxWidth) last = last.slice(0, -1);
    lines[maxLines - 1] = last + "…";
  }
  return lines;
}

async function downloadShareCard({ title, excerpt, author, url }) {
  const canvas = document.createElement("canvas");
  canvas.width = 1080; canvas.height = 1440;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createLinearGradient(0, 0, 1080, 1440);
  gradient.addColorStop(0, "#fffdf8"); gradient.addColorStop(1, "#eee4d4");
  ctx.fillStyle = gradient; ctx.fillRect(0, 0, 1080, 1440);
  ctx.strokeStyle = "#d2c4b0"; ctx.lineWidth = 2; ctx.strokeRect(58, 58, 964, 1324);
  ctx.fillStyle = "#b84634"; ctx.font = '34px -apple-system,"PingFang SC",sans-serif';
  ctx.fillText("纸墨写作台 · 文章", 120, 166);
  ctx.fillStyle = "#2c2822"; ctx.font = '700 72px "Songti SC","Noto Serif CJK SC",serif';
  let y = 300;
  canvasLines(ctx, title || "未命名文章", 840, 4).forEach(line => { ctx.fillText(line, 120, y); y += 108; });
  ctx.fillStyle = "#b84634"; ctx.fillRect(120, y + 12, 84, 4); y += 92;
  ctx.fillStyle = "#655e55"; ctx.font = '38px "Songti SC","Noto Serif CJK SC",serif';
  canvasLines(ctx, excerpt || "", 840, 5).forEach(line => { ctx.fillText(line, 120, y); y += 66; });
  ctx.fillStyle = "#82786b"; ctx.font = '30px -apple-system,"PingFang SC",sans-serif';
  if (author) ctx.fillText(author, 120, 1248);
  let host = ""; try { host = new URL(url).host; } catch (_) { host = url; }
  ctx.fillText(host, 120, 1308);
  ctx.strokeStyle = "#b84634"; ctx.lineWidth = 3; ctx.strokeRect(886, 1220, 76, 76);
  ctx.fillStyle = "#b84634"; ctx.font = '40px "Songti SC",serif'; ctx.fillText("墨", 904, 1274);
  const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("浏览器无法生成分享卡片。");
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl; link.download = `${(title || "文章").replace(/[\\/:*?"<>|]/g, "-").slice(0, 60)}-分享卡片.png`;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

async function openTaskShare() {
  if (!WS.draft) return;
  const taskId = WS.tid;
  await flushAutosave({ checkpoint: false });
  let current = (await api("GET", `/tasks/${encodeURIComponent(taskId)}/share`)).share;
  if (WS.tid !== taskId) return;
  const previousFocus = document.activeElement;
  const dialog = document.createElement("dialog");
  dialog.className = "product-dialog share-dialog";
  document.body.appendChild(dialog);
  const close = () => {
    if (dialog.open) dialog.close();
    dialog.remove();
    if (previousFocus?.isConnected) previousFocus.focus();
  };
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });

  const previewMarkup = (title, excerpt, author, url = "") => `
    <aside class="share-card-preview" aria-label="分享卡片预览">
      <div><div class="share-card-kicker">纸墨写作台 · 文章</div>
        <div class="share-card-title">${esc(title || "未命名文章")}</div>
        <div class="share-card-excerpt">${esc(excerpt || "从正文中选一句摘要，让读者知道这篇文章写什么。")}</div></div>
      <div class="share-card-foot"><span>${esc(author || "文章分享")}${url ? `<br>${esc(new URL(url).host)}` : ""}</span><span class="share-card-seal">墨</span></div>
    </aside>`;

  const render = () => {
    const share = current;
    const title = share?.title || WS.task.title || "未命名文章";
    const excerpt = share?.excerpt || defaultShareExcerpt(WS.draft.working_content);
    const author = share?.author || "";
    const url = share ? absoluteShareUrl(share) : "";
    const localOnly = ["localhost", "127.0.0.1", "::1"].includes(location.hostname);
    const canReplace = Boolean(share?.stale);
    dialog.innerHTML = `<div class="share-dialog-body">
      <div class="share-dialog-head"><div><h2>${share ? "分享这篇文章" : "生成文章分享"}</h2>
        <p>${share ? "链接打开的是发布时的独立快照，之后修改正文不会悄悄改变它。" : "生成一个只包含标题、正文和署名信息的独立阅读页。"}</p></div>
        <button type="button" class="dialog-close" aria-label="关闭">关闭</button></div>
      <div class="share-dialog-grid"><div class="share-fields">
        ${share?.stale ? `<div class="share-note warn">正文已有新修改。当前链接仍保留旧快照；更新后旧链接会立即失效。</div>` :
          `<div class="share-note">素材、写作目标、检查记录、版本历史和模型配置不会出现在分享页。</div>`}
        <label for="share-author">作者署名（可选）</label>
        <input id="share-author" maxlength="80" value="${esc(author)}" ${share && !canReplace ? "disabled" : ""} placeholder="例如：林墨">
        <label for="share-excerpt">文章摘要（可选）</label>
        <textarea id="share-excerpt" maxlength="240" ${share && !canReplace ? "disabled" : ""} placeholder="默认取正文第一段">${esc(excerpt)}</textarea>
        ${share ? `<label for="share-link">分享链接</label><div class="share-link-row">
          <input id="share-link" readonly value="${esc(url)}"><button type="button" id="share-copy">复制链接</button>
          <a class="action-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">打开文章</a></div>` : ""}
        ${localOnly ? `<div class="share-local-warning">当前地址只在这台电脑上可访问。若要发给别人，请先把服务部署到可访问的域名，再生成链接。</div>` : ""}
        <div class="share-actions">
          ${!share ? `<button type="button" class="primary" id="share-create">生成链接</button>` : `
            <button type="button" id="share-native">系统分享</button>
            <button type="button" id="share-card">保存分享卡片</button>
            ${canReplace ? `<button type="button" class="primary" id="share-replace">更新分享</button>` : ""}
            <button type="button" class="danger" id="share-revoke">停止分享</button>`}
        </div>
      </div><div id="share-preview">${previewMarkup(title, excerpt, author, url)}</div></div>
    </div>`;
    dialog.querySelector(".dialog-close").onclick = close;
    const authorInput = dialog.querySelector("#share-author");
    const excerptInput = dialog.querySelector("#share-excerpt");
    const refreshPreview = () => {
      dialog.querySelector("#share-preview").innerHTML = previewMarkup(
        title, excerptInput.value.trim(), authorInput.value.trim(), url);
    };
    authorInput.oninput = refreshPreview; excerptInput.oninput = refreshPreview;
    const create = async replace => {
      if (replace) {
        const confirmed = await confirmDialog(
          "更新分享快照", "更新后，旧链接会立即失效。已经收到旧链接的人将无法继续打开它。", "更新并使旧链接失效", "取消");
        if (!confirmed || WS.tid !== taskId) return;
      }
      const button = dialog.querySelector(replace ? "#share-replace" : "#share-create");
      button.disabled = true;
      try {
        await flushAutosave({ checkpoint: false });
        const result = await api("POST", `/tasks/${encodeURIComponent(taskId)}/share`, {
          expected_revision: WS.draft.revision,
          author: authorInput.value.trim(), excerpt: excerptInput.value.trim(), replace,
        });
        current = result.share; render();
        toast(replace ? "分享已更新，旧链接已失效。" : "分享链接已生成。");
      } catch (error) {
        toast(error.message || "分享生成失败。", true);
        if (button.isConnected) button.disabled = false;
      }
    };
    const createButton = dialog.querySelector("#share-create");
    if (createButton) createButton.onclick = () => create(false);
    const replaceButton = dialog.querySelector("#share-replace");
    if (replaceButton) replaceButton.onclick = () => create(true);
    const copyButton = dialog.querySelector("#share-copy");
    if (copyButton) copyButton.onclick = async () => {
      try { await copyText(url); toast("分享链接已复制。"); }
      catch (error) { toast(error.message, true); }
    };
    const nativeButton = dialog.querySelector("#share-native");
    if (nativeButton) nativeButton.onclick = async () => {
      try {
        if (navigator.share) await navigator.share({ title: share.title, text: share.excerpt, url });
        else { await copyText(url); toast("当前浏览器不支持系统分享，链接已复制。"); }
      } catch (error) { if (error.name !== "AbortError") toast("系统分享没有完成。", true); }
    };
    const cardButton = dialog.querySelector("#share-card");
    if (cardButton) cardButton.onclick = async () => {
      cardButton.disabled = true;
      try {
        await downloadShareCard({ title: share.title, excerpt: share.excerpt, author: share.author, url });
        toast("分享卡片已保存。");
      } catch (error) { toast(error.message || "卡片保存失败。", true); }
      finally { if (cardButton.isConnected) cardButton.disabled = false; }
    };
    const revokeButton = dialog.querySelector("#share-revoke");
    if (revokeButton) revokeButton.onclick = async () => {
      const confirmed = await confirmDialog("停止分享", "停止后，这个链接将立即无法访问。", "停止分享", "取消");
      if (!confirmed || WS.tid !== taskId) return;
      revokeButton.disabled = true;
      try {
        await api("DELETE", `/tasks/${encodeURIComponent(taskId)}/share`);
        close(); toast("分享已停止，原链接已失效。");
      } catch (error) { toast(error.message || "停止分享失败。", true); revokeButton.disabled = false; }
    };
  };
  render(); dialog.showModal();
}

async function uploadBackup(path, file) {
  let r;
  try {
    r = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/zip" }, body: file,
    });
  } catch (_) {
    throw { code: "BACKEND_DOWN", message: "连不上本机 Workbench 服务。", retryable: true };
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw data.error || { code: "NETWORK", message: r.statusText, retryable: false };
  return data;
}

let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (err ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = ""), err ? 6000 : 3000);
}

function openDialog({ title, message, confirmLabel = "确定", cancelLabel = "取消", inputLabel = "" }) {
  return new Promise(resolve => {
    const previousFocus = document.activeElement;
    const dialog = document.createElement("dialog");
    dialog.className = "product-dialog";
    dialog.innerHTML = `<form method="dialog">
      <h2>${esc(title)}</h2>
      <p>${esc(message)}</p>
      ${inputLabel ? `<label for="dialog-input">${esc(inputLabel)}</label>
        <input id="dialog-input" autocomplete="off">` : ""}
      <div class="dialog-actions">
        <button value="cancel">${esc(cancelLabel)}</button>
        <button class="primary" value="confirm">${esc(confirmLabel)}</button>
      </div>
    </form>`;
    document.body.appendChild(dialog);
    const finish = value => {
      dialog.close();
      dialog.remove();
      if (previousFocus?.isConnected) previousFocus.focus();
      resolve(value);
    };
    dialog.addEventListener("cancel", e => { e.preventDefault(); finish(null); });
    dialog.querySelector("form").addEventListener("submit", e => {
      e.preventDefault();
      const submitter = e.submitter?.value;
      if (submitter && submitter !== "confirm") { finish(null); return; }
      const input = dialog.querySelector("input");
      finish(input ? input.value.trim() || null : true);
    });
    dialog.showModal();
    const input = dialog.querySelector("input");
    if (input) input.focus();
  });
}

const confirmDialog = (title, message, confirmLabel, cancelLabel) =>
  openDialog({ title, message, confirmLabel, cancelLabel });

/* ---------------------------------------------------------------- router */
const routes = [
  [/^#\/$/, "home"],
  [/^#\/quickwrite$/, "quickWrite"],
  [/^#\/revise$/, "reviseDraft"],
  [/^#\/tasks$/, "tasks"],
  [/^#\/tasks\/new\?project=([^&]+)$/, "newTask"],
  [/^#\/tasks\/new$/, "newTask"],
  [/^#\/tasks\/([^/]+)$/, "workspace"],
  [/^#\/tasks\/([^/]+)\/versions$/, "versions"],
  [/^#\/projects$/, "projects"],
  [/^#\/projects\/([^/]+)$/, "project"],
  [/^#\/guide$/, "guide"],
  [/^#\/settings$/, "settings"],
];

let routeSeq = 0;
let activeHash = location.hash || "#/";
async function route() {
  const seq = ++routeSeq;
  try { await saveGoalPanel(); }
  catch (_) { history.replaceState(null, "", activeHash); return; }
  // Hash navigation can replace the whole SPA tree. Capture the live editor
  // first and make a best-effort save before any screen is rendered.
  if ($("#editor") && WS.draft) {
    try { await flushAutosave({ checkpoint: false }); }
    catch (_) {
      history.replaceState(null, "", activeHash);
      return;
    }
  }
  if (seq !== routeSeq) return;
  const h = location.hash || "#/";
  for (const [re, name] of routes) {
    const m = h.match(re);
    if (m) {
      document.querySelectorAll("#topbar nav a").forEach(a =>
        a.classList.toggle("on", a.getAttribute("href") === h));
      Promise.resolve(SCREENS[name](...m.slice(1).map(decodeURIComponent)))
        .then(() => { if (seq === routeSeq) activeHash = h; })
        .catch(e => toast(e.message || "页面暂时无法打开。", true));
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", route);

/* ------------------------------------------------------------------ home */
function taskDisplayTitle(task) {
  return task.title || task.topic || (task.instruction || "").slice(0, 40) || "未命名任务";
}

function taskStatusLabel(status) {
  return ({
    draft: "草稿", generating: "生成中", ready: "待修改", failed: "失败", done: "已完成",
  }[status] || status || "未知状态");
}

function taskRow(task, { showUpdatedAt = false } = {}) {
  return `<div class="row-item task-row">
    <a class="grow" href="#/tasks/${encodeURIComponent(task.id)}">
      <b>${esc(taskDisplayTitle(task))}</b>
      <span class="muted small"> · ${esc(taskStatusLabel(task.status))}</span>
      ${showUpdatedAt ? `<span class="muted small task-updated">${esc(task.updated_at || "")}</span>` : ""}
    </a>
    <a class="small" href="#/tasks/${encodeURIComponent(task.id)}" data-tip="打开此任务">打开</a>
    <button type="button" class="task-delete small" data-delete-task="${esc(task.id)}"
      data-task-title="${esc(taskDisplayTitle(task))}" data-tip="删除任务及其正文、版本和运行记录">删除</button>
  </div>`;
}

function bindTaskDeleteButtons(refresh) {
  document.querySelectorAll("[data-delete-task]").forEach(button => {
    button.onclick = async () => {
      const taskId = button.dataset.deleteTask;
      const title = button.dataset.taskTitle || "未命名任务";
      const confirmed = await confirmDialog(
        "删除任务",
        `将永久删除《${title}》及其正文、版本、检查、运行记录和分享链接。项目素材会保留；关联选题会回到待写。`,
        "永久删除", "取消");
      if (!confirmed) return;
      button.disabled = true;
      try {
        await api("DELETE", `/tasks/${encodeURIComponent(taskId)}`);
        toast("任务已删除。");
        await refresh();
      } catch (e) {
        toast(e.message || "任务删除失败。", true);
        if (button.isConnected) button.disabled = false;
      }
    };
  });
}

function bindProjectDeleteButtons(refresh) {
  document.querySelectorAll("[data-delete-project]").forEach(button => {
    button.onclick = async () => {
      const pid = button.dataset.deleteProject;
      const name = button.dataset.projectName || "未命名项目";
      const confirmed = await confirmDialog(
        "删除项目",
        `将永久删除项目《${name}》及其全部任务、正文、版本、检查、运行记录、分享链接和素材。关联选题会回到待写。`,
        "永久删除", "取消");
      if (!confirmed) return;
      button.disabled = true;
      try {
        await api("DELETE", `/projects/${encodeURIComponent(pid)}`);
        toast("项目已删除。");
        await refresh();
      } catch (e) {
        toast(e.message || "项目删除失败。", true);
        if (button.isConnected) button.disabled = false;
      }
    };
  });
}

async function home() {
  const [tasks, projects] = await Promise.all([api("GET", "/tasks"), api("GET", "/projects")]);
  $("#app").innerHTML = `
    <div class="hero">
      <p class="slogan">发现值得写的，写成值得读的。</p>
      <h1>今天，想写什么？</h1>
      <div class="entries">
        <a class="entry" href="#/quickwrite" data-tip="只有一个话题也行:系统先找到值得说的角度再写">
          <b>从一个话题开始</b>
          <span class="muted">把一个念头，写成有推进的文章</span></a>
        <a class="entry" href="#/tasks/new" data-tip="粘贴笔记、素材、观点,生成初稿">
          <b>从素材写起</b>
          <span class="muted">让笔记、资料和意图成为初稿</span></a>
        <a class="entry" href="#/revise" data-tip="贴入你的旧稿,只做局部修改,不重写全文">
          <b>改一篇旧稿</b>
          <span class="muted">只修该修之处，不推倒重写</span></a>
      </div>
    </div>
    <div class="home-sections">
      <section><div class="sec-head"><h2>最近任务</h2>
          <a class="ghost small" href="#/tasks" data-tip="查看本机保存的全部任务">查看所有任务</a></div>
        <div class="home-list">${
        tasks.tasks.length ? tasks.tasks.slice(0, 8).map(t => taskRow(t)).join("")
        : `<p class="muted">还没有任务。从一个话题或一批素材开始。</p>`}
      </div></section>
      <section><div class="sec-head"><h2>项目</h2>
          <button class="ghost small" onclick="newProjectPrompt()" data-tip="项目用来把相关素材与任务归堆(可选)">＋ 新建</button></div>
        <div class="home-list">${
        projects.projects.length ? projects.projects.slice(0, 8).map(p => `
          <div class="row-item"><a class="grow" href="#/projects/${p.id}"><b>${esc(p.name)}</b></a>
          <a class="small" href="#/projects/${p.id}" data-tip="打开此项目">打开</a>
          <button type="button" class="project-delete small" data-delete-project="${p.id}"
            data-project-name="${esc(p.name)}" data-tip="删除项目及其全部任务与素材">删除</button></div>`).join("")
        : `<p class="muted">项目用于把相关素材与任务归堆(可选)。</p>`}
      </div></section>
    </div>`;
  bindTaskDeleteButtons(home);
  bindProjectDeleteButtons(home);
}

async function tasks() {
  const data = await api("GET", "/tasks");
  if (location.hash !== "#/tasks") return;
  const rows = data.tasks.map(t => taskRow(t, { showUpdatedAt: true })).join("");
  $("#app").innerHTML = `
    <div class="page-head task-list-head">
      <div>
        <p class="slogan">把写作继续下去</p>
        <h1>所有任务</h1>
        <p class="muted">按最近更新时间排列，共 ${data.tasks.length} 个任务。</p>
      </div>
      <a class="primary action-link" href="#/tasks/new">从素材写</a>
    </div>
    <section class="task-list card">
      ${rows || `<div class="task-empty">
        <p>还没有任务。</p>
        <p class="muted">从一个话题或一批素材开始，第一篇文章会出现在这里。</p>
        <a class="primary action-link" href="#/tasks/new">开始写作</a>
      </div>`}
    </section>`;
  bindTaskDeleteButtons(tasks);
}

async function newProjectPrompt() {
  const name = await openDialog({
    title: "新建项目", message: "项目用于归拢相关素材和写作任务。",
    inputLabel: "项目名称", confirmLabel: "创建项目",
  });
  if (!name) return;
  const p = await api("POST", "/projects", { name });
  location.hash = `#/projects/${p.id}`;
}

/* --------------------------------------------------------- quick write */
const QW_EXAMPLES = [
  "为什么越想摆脱一个人,反而越像他?",
  "为什么知道结局的故事仍然有悬念?",
  "为什么人会怀念已经结束的关系?",
  "为什么所有人都理性,合起来却是坏结果?",
];
let AUTOSTART = false;

/* Compose state stays local. The old topic library is read only for a
   one-time, server-confirmed migration into the SQLite idea box. */
const LIB_KEY = "qw_topic_lib_v1", COMPOSE_KEY = "qw_compose_v1";
const loadLib = () => {
  try { return JSON.parse(localStorage.getItem(LIB_KEY) || "[]") || []; }
  catch { return []; }
};
const loadCompose = () => {
  try { return JSON.parse(localStorage.getItem(COMPOSE_KEY) || "{}") || {}; }
  catch { return {}; }
};
const saveCompose = st => {
  try { localStorage.setItem(COMPOSE_KEY, JSON.stringify(st)); }
  catch { /* private mode: degrade to session-only */ }
};

function quickWrite() {
  const saved = loadCompose();
  $("#app").innerHTML = `
  <div class="qw-grid">
    <section class="card qw-col qw-right">
       <label for="qw-topic">你要谈的话题</label>
      <textarea id="qw-topic" rows="3"
                placeholder="在这里写下话题，或点选右侧任意一条">${esc(saved.topic || "")}</textarea>
      <p class="row qw-save-row"><button class="ghost small" id="qw-save-current"
        data-tip="把当前话题明确收藏到本机选题箱">☆ 收藏当前话题</button></p>
      <div class="chips" id="qw-ex">${QW_EXAMPLES.map(x =>
        `<button class="chip" data-tip="点击填入示例话题" data-v="${esc(x)}">${esc(x.slice(0, 18))}${x.length > 18 ? "…" : ""}</button>`).join("")}</div>
       <label for="qw-mode">写作模式</label>
      <select id="qw-mode" data-tip="深度叙事=先体验后领悟、延迟解释、克制收束(旗舰模式);清晰论述=观点清晰直给;小说=以故事呈现;自由写作=放松随笔">
         <option value="deep_narrative" selected>深度叙事（推荐）</option>
         <option value="clear_essay">清晰论述</option>
         <option value="fiction">小说</option>
         <option value="free_writing">自由写作</option>
      </select>
       <label for="qw-angle">切入角度</label>
      <select id="qw-angle" data-tip="自动发现=系统找最有意义、最能推进的切入角度;不满意可生成后换">
         <option value="auto" selected>自动发现</option>
         <option value="custom">我已有角度</option>
      </select>
      <textarea id="qw-custom" rows="2" placeholder="你的角度 — 系统会提炼，不会替换。" style="display:none"></textarea>
      <div class="qw-duo">
        <div data-tip="正文目标字数，模型会在 ±20% 内调节">
           <label class="muted small" for="qw-length">目标字数</label>
          <input id="qw-length" type="number" min="200" step="50" value="900"></div>
        <div data-tip="正文输出语言;auto = 跟随话题语言">
           <label class="muted small" for="qw-lang">语言</label>
          <select id="qw-lang"><option value="auto">跟随输入</option><option value="zh">中文</option><option value="en">英文</option></select></div>
      </div>
      <p class="row qw-cta">
        <button class="primary" id="qw-go" data-tip="先找意义，再写初稿；完成后进入工作台(⌘/Ctrl+Enter 同效)">开始写</button>
        <button id="qw-preview" data-tip="只寻找候选角度，不写正文">先看角度</button>
        <button onclick="location.hash='#/'">取消</button>
      </p>
      <p class="muted small">系统先找到值得说的角度与读者旅程，再动笔；写完进入同一工作台审阅修改。</p>
      <section id="qw-angle-stage" class="qw-angle-stage" hidden></section>
    </section>
    <section class="card qw-col qw-left">
      <h2 class="qw-title">找点灵感</h2>
      <p class="muted small qw-sub">按领域寻找可展开的话题；点选即填入左侧表单。</p>
      <label class="muted small" for="qw-tax-search">搜索领域</label>
      <input id="qw-tax-search" placeholder="例如：教育 / 职场 / AI"
             data-tip="输入即过滤领域 chips">
      <span class="muted small qw-fld-label">领域 <span class="muted">(点选一个，选中的会高亮)</span></span>
      <div class="tax-row" id="qw-tax-domains" data-tip="点选一个领域；不限 = 全领域漫游"></div>
      <label class="muted small" for="qw-tax-hint">方向提示（可选）</label>
      <input id="qw-tax-hint" placeholder="例如：关注外卖骑手 / 只看平台经济"
             data-tip="想聚焦时填；空着则按领域全面铺开">
      <p class="row">
         <button id="qw-topic-suggest" data-tip="已有话题时围绕它生成一批不同切面；为空时按领域生成一批">生成一批话题</button>
        <span class="muted small" id="qw-tax-sel"></span></p>
      <div class="qw-lib-head">
        <h3>本次生成 <span class="muted small" id="qw-lib-stats"></span></h3>
        <button class="ghost" id="qw-topic-clear" style="display:none"
                data-tip="只清空本次生成的候选">清空本次</button>
      </div>
      <div id="qw-lib"></div>
      <div id="qw-skel" style="display:none">
        <div class="qw-card qw-skel"></div><div class="qw-card qw-skel"></div>
        <div class="qw-card qw-skel"></div>
      </div>
      <div class="idea-head">
        <h3>选题箱 <span class="muted small" id="idea-stats"></span></h3>
      </div>
      <p class="muted small" id="idea-migration" hidden></p>
      <div class="idea-filters">
        <input id="idea-search" aria-label="搜索选题箱" placeholder="搜索话题、备注或领域">
        <select id="idea-status" aria-label="筛选选题状态">
          <option value="all">全部状态</option><option value="to_write">待写</option>
          <option value="written">已写</option><option value="archived">已归档</option>
        </select>
      </div>
      <div id="idea-box"><div class="qw-empty">正在读取本机选题箱…</div></div>
    </section>
  </div>`;
  if (saved.mode) $("#qw-mode").value = saved.mode;
  if (saved.angle) $("#qw-angle").value = saved.angle;
  if (saved.custom) $("#qw-custom").value = saved.custom;
  if (saved.angle === "custom") $("#qw-custom").style.display = "";
  if (saved.length) $("#qw-length").value = saved.length;
  if (saved.lang) $("#qw-lang").value = saved.lang;
  $("#qw-ex").onclick = e => {
    const b = e.target.closest(".chip"); if (!b) return;
    $("#qw-topic").value = b.dataset.v;
    TX.selectedIdeaId = null; TX.selectedGeneratedIndex = null;
    saveComposeNow(); invalidateAngles();
  };

  /* Generated suggestions are session-only. Saved ideas are explicit product
     records, fetched from SQLite and linked to a task only when writing starts. */
  const TX = { tax: null, domain: "", generated: [], ideas: [],
               selected: saved.topic || "", selectedIdeaId: null,
               selectedGeneratedIndex: null };
  const AF = { taskId: null, discoveryId: null, candidates: [], selected: null,
               signature: null };
  const composeState = () => ({
    topic: $("#qw-topic").value, mode: $("#qw-mode").value,
    angle: $("#qw-angle").value, custom: $("#qw-custom").value,
    length: $("#qw-length").value, lang: $("#qw-lang").value });
  const saveComposeNow = () => saveCompose(composeState());
  const composeSignature = () => JSON.stringify(composeState());
  const domainName = id => {
    const d = ((TX.tax || {}).domains || []).find(x => x.id === id);
    return d ? d.name : (id ? id : "不限领域");
  };
  const renderDomains = () => {
    const t = TX.tax; if (!t) return;
    const q = ($("#qw-tax-search").value || "").trim().toLowerCase();
    const hit = d => !q || d.name.toLowerCase().includes(q)
                  || d.id.toLowerCase().includes(q);
    $("#qw-tax-domains").innerHTML =
      [{ id: "", name: "不限" }, ...t.domains].filter(hit).map(d =>
        `<button class="chip${d.id === TX.domain ? " on" : ""}" data-v="${esc(d.id)}">${esc(d.name)}</button>`).join("");
    $("#qw-tax-sel").textContent =
      TX.domain ? `领域: ${esc(domainName(TX.domain))}` : "";
  };
  $("#qw-tax-search").oninput = renderDomains;
  $("#qw-tax-domains").onclick = e => {
    const b = e.target.closest(".chip"); if (!b) return;
    TX.domain = b.dataset.v;
    renderDomains();
  };
  const chooseTopic = (topic, ideaId = null, generatedIndex = null) => {
    TX.selected = topic;
    TX.selectedIdeaId = ideaId;
    TX.selectedGeneratedIndex = generatedIndex;
    $("#qw-topic").value = topic;
    saveComposeNow(); invalidateAngles();
    renderLib(); renderIdeas();
    $("#qw-topic").focus();
  };
  const renderLib = (freshTs = 0, freshDomain = "") => {
    const lib = TX.generated;
    $("#qw-topic-clear").style.display = lib.length ? "" : "none";
    const doms = [...new Set(lib.map(t => t.domainName))];
    $("#qw-lib-stats").textContent =
      lib.length ? `${lib.length} 条 · ${doms.length} 个领域` : "";
    if (!lib.length) {
      $("#qw-lib").innerHTML = `<div class="qw-empty">本次还没有生成候选。生成后可先挑选，
        确定想写时再收藏到选题箱。</div>`;
      return;
    }
    const prevOpen = new Set(
      [...document.querySelectorAll("#qw-lib details.qw-group")]
        .filter(d => d.open).map(d => d.dataset.d));
    const indexed = lib.map((t, i) => ({ t, i }));       // keep true lib index
    const lastTs = dn => Math.max(
      ...indexed.filter(x => x.t.domainName === dn).map(x => x.t.ts));
    doms.sort((a, b) => lastTs(b) - lastTs(a));          // newest domain first
    $("#qw-lib").innerHTML = doms.map(dn => {
      const items = indexed.filter(x => x.t.domainName === dn)
                           .sort((a, b) => b.t.ts - a.t.ts);   // newest on top
      const open = prevOpen.has(dn) || dn === freshDomain ||
                   !prevOpen.size;
      return `<details class="qw-group"${open ? " open" : ""} data-d="${esc(dn)}">
        <summary><b>${esc(dn)}</b><span class="qw-count">${items.length}</span>
          <span class="grow"></span>
          <button class="ghost qw-more" data-d="${esc(items[0].t.domain)}"
                  data-tip="该领域再来一批(避开全部已生成话题)">再来一批</button></summary>
        <div class="qw-cards">${items.map(({t, i}) => `
           <div class="qw-card${t.text === TX.selected && TX.selectedGeneratedIndex === i ? " sel" : ""}${t.ts >= freshTs ? " fresh" : ""}" data-i="${i}" role="button" tabindex="0" aria-label="选择话题：${esc(t.text)}">
            <b>${esc(t.text)}</b>
            <span class="sub">${esc(t.hook)}
              <button class="qw-save" data-i="${i}" title="收藏到选题箱">☆ 收藏</button>
              <button class="qw-del" data-i="${i}"
                       title="移除这条（${new Date(t.ts).toLocaleTimeString()}）">移除</button></span>
          </div>`).join("")}</div>
      </details>`;
    }).join("");
  };
  $("#qw-lib").onclick = e => {
    const save = e.target.closest(".qw-save");
    if (save) {
      e.stopPropagation(); saveGenerated(+save.dataset.i, save); return;
    }
    const del = e.target.closest(".qw-del");
    if (del) {
      const index = +del.dataset.i;
      TX.generated.splice(index, 1);
      if (TX.selectedGeneratedIndex === index) TX.selectedGeneratedIndex = null;
      else if (TX.selectedGeneratedIndex > index) TX.selectedGeneratedIndex -= 1;
      renderLib();
      return;
    }
    const more = e.target.closest(".qw-more");
    if (more) {
      e.preventDefault();          // keep the group open while re-rolling
      TX.domain = more.dataset.d;
      renderDomains();
      suggestTopics();
      return;
    }
    const card = e.target.closest(".qw-card"); if (!card) return;
    const index = +card.dataset.i;
    chooseTopic(TX.generated[index].text, null, index);
  };
  $("#qw-lib").onkeydown = e => {
    const card = e.target.closest(".qw-card");
    if (!card || e.target !== card || !["Enter", " "].includes(e.key)) return;
    e.preventDefault(); card.click();
  };
  const seedNow = () => ($("#qw-topic").value || "").trim();
  const refreshSuggestBtn = () => {
    $("#qw-topic-suggest").textContent =
      seedNow() ? "围绕它生成一批" : "生成一批话题";
  };
  const suggestTopics = async () => {
    const btn = $("#qw-topic-suggest");
    const seed = seedNow();
    btn.disabled = true;
    btn.innerHTML = seed
      ? '<span class="spin"></span> 正在围绕它生产 8 条切面…(约半分钟)'
      : '<span class="spin"></span> 正在生产 8 条话题…(约半分钟)';
    $("#qw-skel").style.display = "";
    try {
      const r = await api("POST", "/topics/suggest",
        { domain: TX.domain || null, count: 8,
          hint: ($("#qw-tax-hint").value || "").trim() || null,
          seed: seed || null,
          avoid: [...TX.generated.map(t => t.text), ...TX.ideas.map(t => t.topic)] });
      const now = Date.now(), dname = domainName(TX.domain);
      TX.generated = [...TX.generated, ...r.topics.map(t => ({
        domain: TX.domain, domainName: dname,
        text: t.text, hook: t.hook, ts: now }))];
      renderLib(now - 1, dname);
      const el = $("#qw-lib .qw-card.fresh");
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      toast(e.message || "生成失败,请重试。", true);
      btn.textContent = "↻ 重试";
      btn.disabled = false;
      return;
    } finally {
      $("#qw-skel").style.display = "none";
    }
    btn.disabled = false; refreshSuggestBtn();
  };
  $("#qw-topic-suggest").onclick = suggestTopics;
  $("#qw-topic-clear").onclick = () => {
    TX.generated = []; TX.selectedGeneratedIndex = null; renderLib();
  };
  const ideaStatusLabel = status => ({
    to_write: "待写", written: "已写", archived: "已归档",
  }[status] || status);
  const renderIdeas = () => {
    if (!$("#idea-box") || !$("#idea-stats")) return;
    const counts = TX.ideaCounts || { to_write: 0, written: 0, archived: 0 };
    $("#idea-stats").textContent =
      `${counts.to_write} 待写 · ${counts.written} 已写 · ${counts.archived} 归档`;
    if (!TX.ideas.length) {
      $("#idea-box").innerHTML = `<div class="qw-empty">当前筛选下没有选题。
        从本次生成中收藏，或收藏左侧正在编辑的话题。</div>`;
      return;
    }
    $("#idea-box").innerHTML = TX.ideas.map(idea => `
      <article class="idea-card${idea.id === TX.selectedIdeaId ? " sel" : ""}"
        data-idea-id="${esc(idea.id)}">
        <div class="idea-topic"><b>${esc(idea.topic)}</b>
          <span class="idea-status ${esc(idea.status)}">${esc(ideaStatusLabel(idea.status))}</span></div>
        ${idea.hook ? `<p class="muted small">${esc(idea.hook)}</p>` : ""}
        ${idea.domain_name ? `<p class="idea-domain">${esc(idea.domain_name)}</p>` : ""}
        <textarea class="idea-note" rows="2" maxlength="2000"
          aria-label="${esc(idea.topic)}的备注" placeholder="补充备注…">${esc(idea.note)}</textarea>
        <div class="idea-actions">
          ${idea.task_id
            ? `<button class="small" data-open-idea="${esc(idea.task_id)}">打开文章</button>`
            : `<button class="small" data-use-idea="${esc(idea.id)}">用于写作</button>`}
          <button class="ghost small" data-save-note="${esc(idea.id)}">保存备注</button>
          <select class="idea-status-select" data-idea-status="${esc(idea.id)}" aria-label="修改选题状态">
            ${(idea.task_id ? ["written", "archived"] : ["to_write", "archived"]).map(status =>
              `<option value="${status}"${status === idea.status ? " selected" : ""}>${ideaStatusLabel(status)}</option>`).join("")}
          </select>
        </div>
      </article>`).join("");
  };
  const refreshIdeas = async () => {
    const request = (TX.ideaRequestSeq || 0) + 1;
    TX.ideaRequestSeq = request;
    const q = encodeURIComponent(($("#idea-search")?.value || "").trim());
    const status = encodeURIComponent($("#idea-status")?.value || "all");
    try {
      const r = await api("GET", `/ideas?q=${q}&status=${status}&limit=200`);
      if (request !== TX.ideaRequestSeq || !$("#idea-box")) return;
      TX.ideas = r.ideas; TX.ideaCounts = r.counts; renderIdeas();
    } catch (e) {
      const box = $("#idea-box");
      if (request === TX.ideaRequestSeq && box)
        box.innerHTML = `<div class="qw-empty">${esc(e.message || "选题箱读取失败，请重试。")}</div>`;
    }
  };
  const saveIdea = async (payload, button) => {
    if (button) { button.disabled = true; button.textContent = "收藏中…"; }
    try {
      const r = await api("POST", "/ideas", payload);
      await refreshIdeas();
      toast(r.created ? "已收藏到本机选题箱。" : "选题箱里已有这条话题。");
      return r.idea;
    } catch (e) {
      toast(e.message || "收藏失败，请重试。", true); return null;
    } finally {
      if (button?.isConnected) { button.disabled = false; button.textContent = "☆ 收藏"; }
    }
  };
  const saveGenerated = async (index, button) => {
    const item = TX.generated[index]; if (!item) return;
    await saveIdea({ topic: item.text, hook: item.hook, domain: item.domain,
      domain_name: item.domainName, origin: "generated" }, button);
  };
  $("#qw-save-current").onclick = async e => {
    const topic = $("#qw-topic").value.trim();
    if (!topic) { toast("先写下要收藏的话题。", true); return; }
    const item = TX.selectedGeneratedIndex === null ? null : TX.generated[TX.selectedGeneratedIndex];
    const idea = await saveIdea(item && item.text === topic
      ? { topic, hook: item.hook, domain: item.domain, domain_name: item.domainName,
          origin: "generated" }
      : { topic, origin: "manual" }, e.currentTarget);
    if (idea) { TX.selectedIdeaId = idea.id; TX.selected = idea.topic; renderIdeas(); }
  };
  $("#idea-search").oninput = () => {
    clearTimeout(TX.searchTimer); TX.searchTimer = setTimeout(refreshIdeas, 180);
  };
  $("#idea-status").onchange = refreshIdeas;
  $("#idea-box").onclick = async e => {
    const open = e.target.closest("[data-open-idea]");
    if (open) { location.hash = `#/tasks/${open.dataset.openIdea}`; return; }
    const use = e.target.closest("[data-use-idea]");
    if (use) {
      const idea = TX.ideas.find(x => x.id === use.dataset.useIdea);
      if (idea) chooseTopic(idea.topic, idea.id, null);
      return;
    }
    const saveNote = e.target.closest("[data-save-note]");
    if (saveNote) {
      const card = saveNote.closest(".idea-card");
      saveNote.disabled = true;
      try {
        await api("PATCH", `/ideas/${saveNote.dataset.saveNote}`,
          { note: card.querySelector(".idea-note").value });
        await refreshIdeas(); toast("备注已保存。");
      } catch (err) { toast(err.message || "备注保存失败。", true); }
      return;
    }
  };
  $("#idea-box").onchange = async e => {
    const select = e.target.closest("[data-idea-status]"); if (!select) return;
    const prior = TX.ideas.find(x => x.id === select.dataset.ideaStatus)?.status;
    select.disabled = true;
    try {
      await api("PATCH", `/ideas/${select.dataset.ideaStatus}`, { status: select.value });
      await refreshIdeas();
    } catch (err) {
      select.value = prior || "to_write"; select.disabled = false;
      toast(err.message || "状态更新失败。", true);
    }
  };
  const migrateLegacy = async () => {
    const legacy = loadLib();
    if (!Array.isArray(legacy) || !legacy.length) return;
    const info = $("#idea-migration"); if (!info) return;
    info.hidden = false;
    if (legacy.length > 200) {
      info.textContent = "旧话题库超过 200 条，暂未迁移；原数据仍保留。"; return;
    }
    info.textContent = `正在迁移 ${legacy.length} 条旧话题…`;
    try {
      const r = await api("POST", "/ideas/import-legacy", { items: legacy });
      if (r.imported + r.existing !== r.received) throw new Error("迁移确认不完整");
      localStorage.removeItem(LIB_KEY);
      if (info.isConnected)
        info.textContent = `旧话题已迁移：新增 ${r.imported} 条，已有 ${r.existing} 条。`;
      await refreshIdeas();
    } catch (e) {
      if (info.isConnected)
        info.textContent = `旧话题迁移未完成，原数据仍保留。${e.message || "请稍后重试。"}`;
    }
  };
  renderLib();                 // empty-state guidance (no taxonomy needed)
  refreshSuggestBtn();         // now safe: defined above
  refreshIdeas().then(migrateLegacy);
  api("GET", "/taxonomy").then(t => {
    TX.tax = t; renderDomains();
  }).catch(() => {});
  $("#qw-angle").onchange = e => {
    $("#qw-custom").style.display = e.target.value === "custom" ? "" : "none";
    saveComposeNow(); invalidateAngles();
  };
  const invalidateAngles = () => {
    if (!AF.discoveryId || AF.signature === composeSignature()) return;
    AF.taskId = AF.discoveryId = AF.selected = null; AF.candidates = [];
    const stage = $("#qw-angle-stage");
    stage.hidden = false;
    stage.innerHTML = '<p class="muted small">写作设置已变化，请重新寻找候选角度。</p>';
  };
  $("#qw-topic").oninput = () => {
    TX.selectedIdeaId = null; TX.selectedGeneratedIndex = null;
    saveComposeNow(); refreshSuggestBtn(); invalidateAngles();
  };
  $("#qw-mode").onchange = () => { saveComposeNow(); invalidateAngles(); };
  $("#qw-custom").oninput = () => { saveComposeNow(); invalidateAngles(); };
  $("#qw-length").oninput = () => { saveComposeNow(); invalidateAngles(); };
  $("#qw-lang").onchange = () => { saveComposeNow(); invalidateAngles(); };
  $("#qw-topic").addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      $("#qw-go").click();
    }
  });
  const createQuickWriteTask = async (btn, busyText) => {
    const topic = $("#qw-topic").value.trim();
    if (!topic) { toast("先写下你想谈的话题。", true); return null; }
    btn.disabled = true;
    btn.innerHTML = `<span class="spin"></span> ${busyText}`;
    try {
      const t = await api("POST", "/tasks", {
        input_mode: "topic_only", topic,
        idea_id: TX.selectedIdeaId,
        title: topic.slice(0, 40),
        writing_mode: $("#qw-mode").value,
        angle_mode: $("#qw-angle").value,
        custom_angle: $("#qw-custom").value.trim(),
        config: { expected_language: $("#qw-lang").value,
                  target_length: parseInt($("#qw-length").value) || null },
      });
      const d = await api("GET", `/tasks/${t.id}`);
      if (d.factuality_warning && !(await confirmDialog(
          "这个话题可能依赖具体事实",
          "你可以使用通用知识继续，文章不会假装引用来源；也可以先进入任务添加素材。",
          "使用通用知识继续", "先添加素材"))) {
        location.hash = `#/tasks/${t.id}`;   // don't orphan the created task
        return null;
      }
      saveComposeNow();
      return t;
    } catch (e) {
      toast(e.message || "无法开始写作。", true);
      return null;
    } finally {
      btn.disabled = false;
    }
  };
  $("#qw-go").onclick = async () => {
    const btn = $("#qw-go");
    const t = await createQuickWriteTask(btn, "写作中…");
    btn.textContent = "开始写";
    if (!t) return;
    AUTOSTART = { tid: t.id, body: {} };
    location.hash = `#/tasks/${t.id}`;
  };

  const angleValue = (candidate, key) => esc(candidate[key] || "");
  const renderAngles = () => {
    const stage = $("#qw-angle-stage");
    stage.hidden = false;
    if (!AF.candidates.length) {
      stage.innerHTML = '<p class="muted small">这次没有可用候选，请再试一次。</p>';
      return;
    }
    const selected = AF.candidates.find(c => c.id === AF.selected) || AF.candidates[0];
    AF.selected = selected.id;
    stage.innerHTML = `
      <div class="qw-angle-head"><div><b>先选一个值得写的角度</b>
        <p class="muted small">选择后可直接修改完整角度，再确认写作。</p></div>
        <button class="small" id="qw-more-angles">再找一批</button></div>
      <div class="qw-angle-list" role="listbox" aria-label="候选角度">
        ${AF.candidates.map(c => `<button type="button" role="option"
          aria-selected="${c.id === selected.id}" class="qw-angle-card${c.id === selected.id ? " on" : ""}"
          data-angle-id="${esc(c.id)}"><b>${esc(c.label)}</b>
          <span><strong>机制</strong>${esc(c.mechanism)}</span>
          <span><strong>核心问题</strong>${esc(c.core_question)}</span>
          <span><strong>边界</strong>${esc(c.boundary)}</span>
          <span><strong>读者带走</strong>${esc(c.reader_end_state)}</span></button>`).join("")}
      </div>
      <details class="qw-angle-edit"><summary>编辑已选角度（可选）</summary>
        <label for="qa-label">主张</label><textarea id="qa-label" rows="2">${angleValue(selected, "label")}</textarea>
        <label for="qa-question">核心问题</label><textarea id="qa-question" rows="2">${angleValue(selected, "core_question")}</textarea>
        <label for="qa-meaning">深层含义</label><textarea id="qa-meaning" rows="2">${angleValue(selected, "deep_meaning")}</textarea>
        <label for="qa-boundary">适用边界</label><textarea id="qa-boundary" rows="2">${angleValue(selected, "boundary")}</textarea>
        <label for="qa-end">读者收获</label><textarea id="qa-end" rows="2">${angleValue(selected, "reader_end_state")}</textarea>
      </details>
      <p class="row qw-angle-actions"><button class="primary" id="qw-confirm-angle">确认并开始写</button>
        <button id="qw-back-form">返回修改设置</button></p>`;
    stage.querySelector(".qw-angle-list").onclick = e => {
      const card = e.target.closest("[data-angle-id]");
      if (!card || card.dataset.angleId === AF.selected) return;
      AF.selected = card.dataset.angleId; renderAngles();
    };
    $("#qw-back-form").onclick = () => {
      stage.hidden = true; $("#qw-topic").focus();
    };
    $("#qw-more-angles").onclick = () => findAngles(true);
    $("#qw-confirm-angle").onclick = confirmAngle;
  };

  const findAngles = async (reuseTask = false) => {
    const btn = reuseTask ? $("#qw-more-angles") : $("#qw-preview");
    const original = reuseTask ? "再找一批" : "先看角度";
    let taskId = AF.taskId;
    if (!reuseTask || !taskId || AF.signature !== composeSignature()) {
      const t = await createQuickWriteTask(btn, "正在找角度…");
      if (!t) { btn.textContent = original; return; }
      taskId = t.id; AF.taskId = taskId; AF.signature = composeSignature();
    }
    btn.disabled = true; btn.innerHTML = '<span class="spin"></span> 正在找角度…';
    try {
      const found = await api("POST", `/tasks/${taskId}/angle-options`, {});
      AF.discoveryId = found.discovery_id;
      AF.candidates = found.candidates;
      AF.selected = found.candidates[0]?.id || null;
      renderAngles();
      $("#qw-angle-stage").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      toast(e.message || "寻找角度失败，请重试。", true);
    } finally {
      const current = reuseTask ? $("#qw-more-angles") : $("#qw-preview");
      if (current) { current.disabled = false; current.textContent = original; }
    }
  };

  const confirmAngle = async () => {
    const btn = $("#qw-confirm-angle");
    const values = {
      label: $("#qa-label").value.trim(),
      core_question: $("#qa-question").value.trim(),
      deep_meaning: $("#qa-meaning").value.trim(),
      boundary: $("#qa-boundary").value.trim(),
      reader_end_state: $("#qa-end").value.trim(),
    };
    if (Object.values(values).some(v => !v)) {
      toast("请补全角度的主张、问题、含义、边界和读者收获。", true); return;
    }
    btn.disabled = true; btn.innerHTML = '<span class="spin"></span> 正在确认…';
    try {
      const confirmed = await api("POST", `/tasks/${AF.taskId}/confirm-angle`, {
        discovery_id: AF.discoveryId, candidate_id: AF.selected, edits: values,
      });
      AUTOSTART = { tid: AF.taskId,
                    body: { confirmed_meaning_id: confirmed.confirmed_meaning_id } };
      location.hash = `#/tasks/${AF.taskId}`;
    } catch (e) {
      toast(e.message || "角度确认失败，请重试。", true);
      btn.disabled = false; btn.textContent = "确认并开始写";
    }
  };
  $("#qw-preview").onclick = () => findAngles(false);
}

function reviseDraft() {
  newTask("", "draft_revision");
}

/* ------------------------------------------------------------- new task */
const TASK_TYPES = [
  ["fiction_scene", "小说场景", "写一个具体场景的小说片段（场景、动作、对话）"],
  ["narrative_analysis", "叙事分析", "分析故事的叙事机制：视角、信息释放、推进"],
  ["character_analysis", "人物分析", "剖析一个人物：行为、动机、矛盾"],
  ["essay", "观点文章", "观点性文章：论点要有推进与重量"],
  ["emotional_retelling", "情感复述", "带着情感重述一段事件或记忆"],
  ["free_writing", "自由写作", "放松随笔，结构约束最弱"],
];

function newTask(projectId = "", mode = "source_grounded") {
  let chosenType = TASK_TYPES[0][0];
  const rev = mode === "draft_revision";
  const composeKey = `compose:${mode}:${projectId}`;
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(composeKey) || "{}") || {}; } catch (_) {}
  const formIds = ["f-instruction", "f-material", "f-project", "f-immersion",
    "f-explicitness", "f-intensity", "f-length", "f-lang", "c-facts",
    "c-meaning", "c-avoid", "c-invent"];
  const rememberForm = () => {
    const fields = {};
    for (const id of formIds) {
      const el = $("#" + id);
      fields[id] = el.type === "checkbox" ? el.checked : el.value;
    }
    try { localStorage.setItem(composeKey, JSON.stringify({ chosenType, fields })); }
    catch (_) { /* Form remains usable if storage is unavailable. */ }
  };
  $("#app").innerHTML = `
  <div class="form">
    <h1>${rev ? "修改一篇旧稿" : "从素材开始写"}</h1>
    <div class="chips" id="types">${TASK_TYPES.map(([v, l, tip], i) =>
      `<button class="chip${i === 0 ? " on" : ""}" data-v="${v}" data-tip="${tip}">${l}</button>`).join("")}</div>
    <label for="f-instruction">${rev ? "你想改什么？" : "你希望这篇文字做到什么？"}</label>
    <textarea id="f-instruction" rows="3" placeholder="${rev ?
      "e.g. 结尾说教味太重,让最后一段只呈现画面。" : "e.g. 父亲不要直接表达支持。"}"></textarea>
    <label for="f-material">${rev ? "粘贴旧稿" : "写作应基于哪些素材？"}</label>
    <textarea id="f-material" rows="7" placeholder="${rev ?
      "粘贴你想修改的稿件…" : "粘贴笔记、场景或资料…"}"></textarea>
    <div class="row">
      <input id="f-file" type="file" accept=".txt,.md" class="grow" data-tip="从 .txt/.md 文件载入素材,内容会填入下方素材框">
      <select id="f-project" class="grow" aria-label="所属项目" data-tip="可选：把任务归入某个项目"><option value="">不加入项目</option></select>
    </div>
    <details class="compose-options"><summary>阅读感受与写作约束（可选）</summary>
    <label>阅读感受</label>
    <div class="trio">
      ${[["immersion", "高=偏场景呈现,让读者“身临其境”;低=偏概述与说明"],
         ["explicitness", "高=主题直说;低=意义藏在画面里,靠读者推断(推荐低)"],
         ["intensity", "情绪与冲突的强度:高=浓烈,低=克制留白"]]
        .map(([k, tip]) => `
        <div data-tip="${tip}"><span class="muted small">${({immersion:"沉浸度",explicitness:"直白程度",intensity:"情绪强度"})[k]}</span>
        <select id="f-${k}">${["low", "medium", "high"].map(v =>
          `<option value="${v}"${v === ({immersion:"high", explicitness:"low", intensity:"medium"})[k] ? " selected" : ""}>${({low:"低",medium:"中",high:"高"})[v]}</option>`).join("")}</select></div>`).join("")}
      <div data-tip="期望篇幅；实际字数可能有偏差">
        <label class="muted small" for="f-length">目标字数</label>
        <input id="f-length" type="number" min="100" step="50" value="800"></div>
      <div data-tip="正文输出语言;auto = 跟随你的素材/话题语言">
        <label class="muted small" for="f-lang">语言</label>
        <select id="f-lang"><option value="auto">跟随输入</option><option value="zh">中文</option><option value="en">英文</option></select></div>
    </div>
    <label>写作约束</label>
    <div class="checks">
      <label data-tip="修改时不得增删改素材中的事实"><input type="checkbox" id="c-facts" checked> 保留事实</label>
      <label data-tip="局部修改不得偷换文章的核心观点"><input type="checkbox" id="c-meaning" checked> 保留核心意义</label>
      <label data-tip="少做把意义说破的解释"><input type="checkbox" id="c-avoid" checked> 避免过度解释</label>
      <label data-tip="允许文学性细节，但不编造改变故事走向的重大事件"><input type="checkbox" id="c-invent" checked> 不编造重大事件</label>
    </div>
    </details>
    <p class="small muted">未提交的内容会保留在当前浏览器，返回此入口可继续填写。</p>
    <p class="row" style="margin-top:22px">
      <button class="primary" id="f-go" data-tip="保存输入并进入工作台">${rev ? "进入修改工作台" : "进入写作工作台"}</button>
      <button onclick="location.hash='#/'">取消</button>
    </p>
  </div>`;
  const form = $("#f-go").closest(".form");
  for (const id of formIds) {
    const el = $("#" + id), value = stored.fields?.[id];
    if (value === undefined || id === "f-project") continue;
    if (el.type === "checkbox") el.checked = Boolean(value);
    else el.value = value;
  }
  if (TASK_TYPES.some(([v]) => v === stored.chosenType)) chosenType = stored.chosenType;
  $("#types").querySelectorAll(".chip").forEach(x => x.classList.toggle("on", x.dataset.v === chosenType));
  form.addEventListener("input", rememberForm);
  form.addEventListener("change", rememberForm);
  $("#types").onclick = e => {
    const b = e.target.closest(".chip"); if (!b) return;
    chosenType = b.dataset.v;
    rememberForm();
    $("#types").querySelectorAll(".chip").forEach(x => x.classList.toggle("on", x === b));
  };
  (async () => {
    const ps = await api("GET", "/projects");
    if (!form.isConnected) return;
    $("#f-project").innerHTML += ps.projects.map(p =>
      `<option value="${p.id}"${p.id === projectId ? " selected" : ""}>${esc(p.name)}</option>`).join("");
    if (stored.fields?.["f-project"] && ps.projects.some(p => p.id === stored.fields["f-project"]))
      $("#f-project").value = stored.fields["f-project"];
  })().catch(e => toast(e.message || "项目列表暂时无法加载，仍可直接写作。", true));
  $("#f-file").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    const text = await f.text();
    if (!form.isConnected) return;
    $("#f-material").value = text;
    rememberForm();
  };
  $("#f-go").onclick = async () => {
    $("#f-go").disabled = true;
    try {
      const payload = {
        input_mode: mode,
        type: chosenType,
        project_id: $("#f-project").value || null,
        instruction: $("#f-instruction").value.trim(),
        material: $("#f-material").value.trim(),
        config: {
          expected_language: $("#f-lang").value,
          immersion: $("#f-immersion").value,
          explicitness: $("#f-explicitness").value,
          intensity: $("#f-intensity").value,
          target_length: parseInt($("#f-length").value) || null,
          locks: { facts: $("#c-facts").checked, core_meaning: $("#c-meaning").checked },
          constraints: {
            avoid_over_explanation: $("#c-avoid").checked,
            do_not_invent_major_events: $("#c-invent").checked,
          },
        },
      };
      const t = await api("POST", "/tasks", payload);
      try { localStorage.removeItem(composeKey); } catch (_) {}
      location.hash = `#/tasks/${t.id}`;
    } catch (e) { toast(e.message, true); $("#f-go").disabled = false; }
  };
  if (PREFILL) {
    const ex = PREFILL; PREFILL = null;
    chosenType = ex.type;
    $("#types").querySelectorAll(".chip").forEach(x =>
      x.classList.toggle("on", x.dataset.v === ex.type));
    $("#f-instruction").value = ex.instruction;
    $("#f-material").value = ex.material;
    for (const k of ["immersion", "explicitness", "intensity"])
      $("#f-" + k).value = ex.config[k];
    $("#f-length").value = ex.config.target_length;
    toast("示例已填入，进入写作工作台即可继续。");
  }
}

/* ------------------------------------------------------------- projects */
async function projects() {
  const ps = await api("GET", "/projects");
  $("#app").innerHTML = `<h1>项目</h1>
    <p><button class="primary" onclick="newProjectPrompt()" data-tip="新建一个项目">新建项目</button></p>` +
    (ps.projects.map(p => `<div class="card row">
      <a class="grow" href="#/projects/${p.id}"><b>${esc(p.name)}</b></a>
      <button type="button" class="project-delete small" data-delete-project="${p.id}"
        data-project-name="${esc(p.name)}" data-tip="删除项目及其全部任务与素材">删除</button></div>`).join("") ||
      '<p class="muted">还没有项目。</p>');
  bindProjectDeleteButtons(projects);
}

let projectCache = null;
async function project(pid) {
  const p = await api("GET", `/projects/${pid}`);
  projectCache = p;
  $("#app").innerHTML = `
    <h1>${esc(p.name)}</h1><p class="muted">${esc(p.description || "")}</p>
    <div class="row"><button class="primary" data-tip="为本项目新建写作任务" onclick="location.hash='#/tasks/new?project=${encodeURIComponent(pid)}'">新建写作任务</button></div>
    <div class="cols">
      <section class="card project-task-list"><h3>任务</h3>${p.tasks.map(t => taskRow(t)).join("")
        || '<p class="muted">还没有任务。</p>'}</section>
      <section class="card"><h3>素材</h3>
        <div id="src-list"></div>
        <label class="small muted" for="src-title" style="margin-top:10px">添加文字素材</label>
        <input id="src-title" data-tip="给这份素材起个名字" placeholder="素材标题">
        <textarea id="src-body" rows="4" aria-label="素材内容" placeholder="粘贴素材…"></textarea>
        <p><button id="src-add" data-tip="把素材存入本项目，供任务引用">添加素材</button></p></section>
    </div>
    <div class="task-danger-zone" style="margin-top:20px">
      <b class="small">删除项目</b>
      <p class="small muted">将永久删除本项目及其全部任务、正文、版本、检查、运行记录、分享链接和素材。关联选题会回到待写。</p>
      <button type="button" id="delete-project" class="danger"
        data-delete-project="${pid}" data-project-name="${esc(p.name)}">删除这个项目</button>
    </div>`;
  renderProjectSources(pid, p.sources, null);
  bindTaskDeleteButtons(() => project(pid));
  bindProjectDeleteButtons(() => { location.hash = "#/projects"; });
  $("#src-add").onclick = async () => {
    try {
      await api("POST", `/projects/${pid}/sources`, {
        title: $("#src-title").value || "未命名素材",
        type: "pasted_text", content: $("#src-body").value });
      project(pid);
    } catch (e) { toast(e.message, true); }
  };
}

function renderProjectSources(pid, sources, editId) {
  const box = $("#src-list");
  if (!sources.length) { box.innerHTML = '<p class="muted small">还没有素材。</p>'; return; }
  box.innerHTML = sources.map(s => {
    if (editId === s.id) {
      return `<div class="srcitem editing" data-source-id="${esc(s.id)}">
        <input class="src-edit-title small" value="${esc(s.title)}" placeholder="素材标题" aria-label="素材标题">
        <textarea class="src-edit-body" rows="6" aria-label="素材内容">${esc(s.content)}</textarea>
        <div class="srcitem-head"><span class="grow"></span>
          <button type="button" class="small" data-psave="${esc(s.id)}" data-tip="保存修改">保存</button>
          <button type="button" class="small" data-pcancel>取消</button></div></div>`;
    }
    return `<div class="srcitem" data-source-id="${esc(s.id)}">
      <div class="srcitem-head"><b class="small">${esc(s.title)}</b>
      <span class="muted small"> · ${esc(s.type)}</span>
      <span class="grow"></span>
      <button type="button" class="small" data-pedit="${esc(s.id)}" data-tip="修改这份素材">修改</button>
      <button type="button" class="small" data-pdel="${esc(s.id)}" data-tip="删除这份素材及其任务引用">删除</button></div>
      <div class="body">${esc(s.content)}</div></div>`;
  }).join("");
  bindProjectSourceButtons(pid);
}

function bindProjectSourceButtons(pid) {
  const refresh = () => renderProjectSources(pid, projectCache.sources, null);
  document.querySelectorAll("[data-pedit]").forEach(b => b.onclick = () => {
    renderProjectSources(pid, projectCache.sources, b.dataset.pedit);
    const ta = document.querySelector(".src-edit-body"); if (ta) ta.focus();
  });
  document.querySelectorAll("[data-pcancel]").forEach(b => b.onclick = refresh);
  document.querySelectorAll("[data-psave]").forEach(b => b.onclick = async () => {
    const sid = b.dataset.psave;
    const card = b.closest(".srcitem");
    b.disabled = true;
    try {
      await api("PATCH", `/sources/${encodeURIComponent(sid)}`, {
        title: card.querySelector(".src-edit-title").value,
        content: card.querySelector(".src-edit-body").value });
      await project(pid);
      toast("素材已修改。");
    } catch (e) { toast(e.message || "素材修改失败。", true); if (b.isConnected) b.disabled = false; }
  });
  document.querySelectorAll("[data-pdel]").forEach(b => b.onclick = async () => {
    const sid = b.dataset.pdel;
    const src = projectCache.sources.find(x => x.id === sid);
    const confirmed = await confirmDialog(
      "删除素材",
      `将永久删除素材《${src ? src.title : ""}》及其在所有任务中的引用。引用它的依据卡会失效。`,
      "永久删除", "取消");
    if (!confirmed) return;
    b.disabled = true;
    try {
      await api("DELETE", `/sources/${encodeURIComponent(sid)}`);
      await project(pid);
      toast("素材已删除。");
    } catch (e) { toast(e.message || "素材删除失败。", true); if (b.isConnected) b.disabled = false; }
  });
}

/* ------------------------------------------------------------- settings */
async function settings() {
  const [s, pr] = await Promise.all([api("GET", "/settings"), api("GET", "/settings/providers")]);
  if (location.hash !== "#/settings") return;
  const known = pr.providers.find(p => p.base_url && p.base_url === s.base_url);
  $("#app").innerHTML = `
  <div class="form" style="max-width:640px">
    <h1>设置</h1>
    <p class="muted small">配置保存在本机 <code>workbench/settings.json</code>(仅本地,保存后立即生效,无需重启)。
    密钥只写入本地文件,接口永远不会回传完整密钥。</p>
    <label for="s-engine">引擎模式</label>
    <select id="s-engine" data-tip="mock=离线秒级体验界面;real=调用真实 LLM harness">
      <option value="real"${s.engine === "real" ? " selected" : ""}>real(真实引擎)</option>
      <option value="mock"${s.engine === "mock" ? " selected" : ""}>mock(离线演示)</option>
    </select>
    <label for="s-provider">API 服务商</label>
    <select id="s-provider" data-tip="选本地 Ollama / LM Studio 无需密钥">
      ${pr.providers.map(p => `<option value="${p.id}"${known && known.id === p.id ? " selected" : ""}${p.id === "custom" && !known ? " selected" : ""}>${esc(p.name)}</option>`).join("")}
    </select>
    <label for="s-base">API 地址</label>
    <input id="s-base" data-tip="OpenAI 兼容端点;选上方服务商可自动填入" value="${esc(s.base_url)}" placeholder="https://…/v1 或 http://127.0.0.1:11434/v1">
    <label for="s-key">API 密钥</label>
    <input id="s-key" type="password" data-tip="仅保存在本机 settings.json,接口只回传掩码" placeholder="${s.has_key ? "已保存 " + esc(s.api_key_masked) + "(留空则不修改)" : "sk-…(本地 Ollama 可留空)"}">
    <label for="s-model">模型</label>
    <div class="row">
      <input id="s-model" class="grow" list="s-model-list" value="${esc(s.model)}" placeholder="选择或输入模型名" data-tip="下拉选常见模型;也可手填">
      <datalist id="s-model-list">${(known ? known.models : []).map(m => `<option value="${esc(m)}">`).join("")}</datalist>
      <button id="s-fetch" data-tip="向该地址请求模型清单(GET /models)，只列出已可用的模型，不会下载">刷新模型列表</button>
    </div>
    <p class="muted small" id="s-model-hint" style="margin:4px 0 0"></p>
    <div class="trio" style="margin-top:10px">
      <div><span class="muted small">超时(秒)</span>
        <input id="s-timeout" type="number" min="30" step="30" value="${s.timeout_seconds ?? ""}" placeholder="300" data-tip="单次 LLM 调用超时"></div>
      <div><span class="muted small">写作温度</span>
        <input id="s-temp" type="number" min="0" max="2" step="0.1" value="${s.writer_temperature ?? ""}" placeholder="0.7" data-tip="越高越发散,越低越克制(仅作用于正文写作)"></div>
    </div>
    <p class="row" style="margin-top:20px">
      <button class="primary" id="s-save" data-tip="保存并热切换引擎">保存</button>
      <button id="s-test" data-tip="用当前参数发一次最小请求，不保存">测试连接</button>
      <span id="s-result" class="small"></span>
    </p>
    <section class="card" style="margin-top:28px">
      <h2>本地数据</h2>
      <p class="muted small">备份包含已保存的项目、素材、正文和版本，不包含 settings.json、API 密钥、环境变量或日志。
      恢复会创建新的独立工作区，不会改写当前数据。</p>
      <p><button id="backup-download" data-tip="下载当前整个工作区的一致性快照">下载工作区备份</button></p>
      <label for="backup-file">预检并恢复备份</label>
      <input id="backup-file" type="file" accept=".zip,application/zip"
        data-tip="先校验包格式、hash、数据库完整性和引用关系">
      <p class="row">
        <button id="backup-inspect" disabled>预检备份</button>
        <button class="primary" id="backup-restore" disabled>恢复到新工作区</button>
      </p>
      <p id="backup-result" class="muted small" role="status"></p>
    </section>
  </div>`;

  const PROVIDERS = pr.providers;
  const viewProvider = $("#s-provider");
  const stillHere = () => $("#s-provider") === viewProvider;
  const showResult = html => { if (stillHere()) $("#s-result").innerHTML = html; };
  let fetchSeq = 0, modelEditSeq = 0;
  $("#s-model").oninput = () => { modelEditSeq++; };
  function hintModel(text) { if (stillHere()) $("#s-model-hint").textContent = text; }
  async function fetchModels(quiet = false) {
    const btn = $("#s-fetch"), my = ++fetchSeq, edit = modelEditSeq;
    const base = $("#s-base").value.trim(), key = $("#s-key").value.trim();
    const current = () => stillHere() && my === fetchSeq &&
      $("#s-base").value.trim() === base && $("#s-key").value.trim() === key;
    btn.disabled = true; btn.textContent = "刷新中…";
    try {
      const r = await api("POST", "/settings/models", { base_url: base, api_key: key });
      if (!current()) return;
      if (r.ok && r.models.length) {
        $("#s-model-list").innerHTML = r.models.map(m => `<option value="${esc(m)}">`).join("");
        if (!$("#s-model").value.trim() && edit === modelEditSeq) $("#s-model").value = r.models[0];
        hintModel(r.models.includes($("#s-model").value.trim()) ? "" :
          "清单未列出当前模型。手填名称会保留，可用「测试连接」确认。" );
        showResult(`<span class="muted">已载入 ${r.models.length} 个模型建议</span>`);
      } else {
        $("#s-model-list").innerHTML = "";
        hintModel("暂未获取模型清单，手填名称仍可保存。可用「测试连接」确认。" );
        showResult(`<span class="muted">${esc(r.error || "该端点未返回模型清单")}</span>`);
      }
    } catch (e) {
      if (!current()) return;
      hintModel(e.backendDown ? e.message : "模型清单请求失败，手填名称已保留。" );
      if (!quiet) showResult(`<span style="color:var(--warn)">${esc(e.message)}</span>`);
    } finally {
      if (stillHere() && my === fetchSeq) { btn.disabled = false; btn.textContent = "刷新模型列表"; }
    }
  }
  $("#s-provider").onchange = e => {
    const p = PROVIDERS.find(x => x.id === e.target.value);
    if (!p) return;
    fetchSeq++;
    $("#s-fetch").disabled = false; $("#s-fetch").textContent = "刷新模型列表";
    if (p.id !== "custom") $("#s-base").value = p.base_url;
    hintModel("");
    const list = $("#s-model-list");
    list.innerHTML = p.models
      .map(m => `<option value="${esc(m)}">`).join("");
    if (p.models.length && !$("#s-model").value.trim())
      $("#s-model").value = p.models[0];
    if (!p.needs_key) $("#s-key").placeholder = "本地服务无需密钥(留空即可)";
    else $("#s-key").placeholder = "sk-…";
    if (p.id !== "custom") fetchModels(true);    // auto-detect available models
  };
  $("#s-base").onchange = () => fetchModels(true);
  $("#s-fetch").onclick = () => fetchModels(false);
  if (s.base_url) fetchModels(true);             // initial auto-detect
  $("#s-save").onclick = async () => {
    const btn = $("#s-save"); btn.disabled = true;
    try {
      const r = await api("POST", "/settings", {
        engine: $("#s-engine").value,
        base_url: $("#s-base").value.trim(),
        api_key: $("#s-key").value.trim(),
        model: $("#s-model").value.trim(),
        timeout_seconds: parseFloat($("#s-timeout").value) || null,
        writer_temperature: (() => {
          const t = parseFloat($("#s-temp").value);
          return Number.isFinite(t) ? t : null;
        })(),
      });
      toast(`已保存,引擎已切换为 ${r.engine}。`);
      settings();
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; }
  };
  $("#s-test").onclick = async () => {
    const btn = $("#s-test"); btn.disabled = true; btn.innerHTML = '<span class="spin"></span> 测试中…';
    showResult("");
    try {
      const r = await api("POST", "/settings/test", {
        base_url: $("#s-base").value.trim(),
        api_key: $("#s-key").value.trim(),
        model: $("#s-model").value.trim(),
      });
      if (r.ok) showResult(`<span style="color:var(--accent)">连接成功（${r.latency_seconds}s）</span>`);
      else showResult(`<span style="color:var(--warn)">✗ ${esc(r.error)}</span>`);
    } catch (e) { showResult(`<span style="color:var(--warn)">✗ ${esc(e.message)}</span>`); }
    finally { btn.disabled = false; btn.textContent = "测试连接"; }
  };

  let backupFile = null, inspectedFile = null;
  const backupResult = (message, error = false) => {
    if (!stillHere()) return;
    const out = $("#backup-result");
    out.textContent = message;
    out.style.color = error ? "var(--warn)" : "";
  };
  $("#backup-download").onclick = async () => {
    const btn = $("#backup-download"); btn.disabled = true;
    try {
      const filename = await downloadExport("/backups/export");
      toast(`已下载 ${filename}`);
    } catch (e) { toast(e.message, true); }
    finally { if (stillHere()) btn.disabled = false; }
  };
  $("#backup-file").onchange = e => {
    backupFile = e.target.files[0] || null;
    inspectedFile = null;
    $("#backup-inspect").disabled = !backupFile;
    $("#backup-restore").disabled = true;
    backupResult(backupFile ? `已选择 ${backupFile.name}，请先预检。` : "");
  };
  $("#backup-inspect").onclick = async () => {
    if (!backupFile) return;
    const btn = $("#backup-inspect"); btn.disabled = true;
    inspectedFile = null; $("#backup-restore").disabled = true;
    backupResult("正在预检…");
    try {
      const r = await uploadBackup("/backups/inspect", backupFile);
      if (!stillHere()) return;
      inspectedFile = backupFile;
      $("#backup-restore").disabled = false;
      const c = r.table_counts;
      backupResult(`预检通过 · schema v${r.schema_version} · ${c.projects} 个项目 · ${c.tasks} 个任务 · ${c.drafts} 份正文 · ${c.versions} 个版本`);
    } catch (e) { backupResult(`预检失败：${e.message}`, true); }
    finally { if (stillHere()) btn.disabled = !backupFile; }
  };
  $("#backup-restore").onclick = async () => {
    if (!backupFile || inspectedFile !== backupFile) return;
    if (!(await confirmDialog("恢复工作区",
      "将在本机创建一个新的独立工作区。当前数据不会改变。",
      "创建恢复副本", "取消"))) return;
    const btn = $("#backup-restore"); btn.disabled = true;
    backupResult("正在创建独立副本…");
    try {
      const r = await uploadBackup("/backups/restore", backupFile);
      backupResult(`恢复完成。新工作区：${r.restored_directory}`);
      toast("已创建独立恢复副本。");
    } catch (e) { backupResult(`恢复失败：${e.message}`, true); }
    finally { if (stillHere()) btn.disabled = inspectedFile !== backupFile; }
  };
}

/* =============================================================== workspace */
const WS = {
  tid: null, task: null, draft: null, versions: [], sel: new Set(),
  selAnchor: null, editSourceId: null,
  panelTab: "goal", view: "draft", review: null, evidence: null, map: null, reader: null,
  proposals: [], preserved: [], saveTimer: null, savePromise: null, dirty: false, editRevision: 0,
};

async function workspace(tid) {
  if (location.hash !== `#/tasks/${tid}`) return;
  if (WS.tid !== tid) { WS.view = "draft"; WS.panelTab = "goal"; priorSuggestions.length = 0; }
  WS.tid = tid; WS.sel.clear(); WS.selAnchor = null; WS.editSourceId = null;
  WS.proposals = []; WS.preserved = []; WS.review = null; WS.evidence = null; WS.map = null; WS.reader = null;
  await reloadTask();
  if (location.hash !== `#/tasks/${tid}`) return;
  if (WS.task.operation?.status === "running" && !GENERATING) {
    resumeInProgressGeneration();
    return;
  }
  if (WS.task.input_mode === "draft_revision") WS.panelTab = "review";
  renderWorkspace();
  if (WS.task.operation?.status === "interrupted") {
    toast("服务重启导致上次运行中断，已保存正文保留。请手动重试。", true);
    const endpoints = {
      generate: ["generate", {}],
      regenerate: ["regenerate", { preserve_angle: true }],
      rediscover_angle: ["rediscover-angle", {}],
    };
    const retry = endpoints[WS.task.operation.kind];
    if (retry) genFailureCard(
      "服务已重启，本次运行中断。已保存正文保留，可从匹配的已完成步骤继续。",
      retry[0], retry[1], "生成已完成。");
  }
  if (AUTOSTART) {
    const start = typeof AUTOSTART === "string"
      ? { tid: AUTOSTART, body: {} } : AUTOSTART;
    if (start.tid === tid) {
      AUTOSTART = false;
      if (!WS.draft && WS.task.input_mode === "topic_only") generateDraft(start.body);
    } else AUTOSTART = false;   // navigated elsewhere first: drop, don't misfire
  }
}

async function reloadTask() {
  WS.task = await api("GET", `/tasks/${WS.tid}`);
  WS.draft = WS.task.draft;
  WS.review = WS.task.review;
  WS.evidence = WS.task.evidence_check;
  WS.dirty = false;
  WS.editRevision = 0;
  WS.versions = WS.draft ? WS.task.draft.versions : [];
  WS.proposals = (WS.task.pending_patches || [])
    .filter(p => p.after);   // restorable after reload/refactor
  const kept = await api("GET", `/tasks/${WS.tid}/preserved-spans`);
  WS.preserved = kept.spans || [];
  WS.meaning = null;
  if (WS.task.input_mode === "topic_only") {
    try { WS.meaning = await api("GET", `/tasks/${WS.tid}/meaning`); }
    catch (e) { if (e.code !== "NO_MEANING") { /* non-fatal */ } }
  }
}

const contentParas = () => (WS.draft ? WS.draft.working_content : "").split("\n\n");

function renderWorkspace() {
  const t = WS.task;
  $("#app").innerHTML = `
  <div class="workspace" data-task-id="${esc(t.id)}">
    <section id="pane-left">
       <h3>素材</h3><div id="sources"></div>
       <label class="small muted" for="add-src">追加素材</label>
      <textarea id="add-src" rows="3" placeholder="粘贴补充素材…"></textarea>
      <p class="small muted" style="margin-top:4px">粘贴更多素材(故事、笔记、观点),它会与原素材合并成 "Source Material",在下一次生成与检查时使用。</p>
       <p><button id="add-src-btn" class="small" data-tip="追加素材，将影响下一次生成或检查">添加</button></p>
    </section>
    <section id="pane-center">
      <div class="draft-head">
        <b id="doc-title">${esc(t.title || "未命名稿件")}</b>
        <span id="save-state" class="muted small"></span>
        <span class="grow"></span>
         <div class="tabs" role="tablist" aria-label="稿件视图">
           <button role="tab" aria-selected="${WS.view === "draft"}" id="tab-draft" class="${WS.view === "draft" ? "on" : ""}" data-tip="正文：点段落即可编辑，选段可发起局部修改">正文</button>
           <button role="tab" aria-selected="${WS.view === "map"}" id="tab-map" class="${WS.view === "map" ? "on" : ""}" data-tip="生成时的结构计划；段落映射为估算">原定路径</button>
           <button role="tab" aria-selected="${WS.view === "reader"}" id="tab-reader" class="${WS.view === "reader" ? "on" : ""}" data-tip="只读：检查当前实际正文如何逐段推进">稿件检查</button>
         </div>
         <select id="export-format" class="export-format" aria-label="当前稿导出格式" data-tip="Markdown 保留可编辑的纯文本格式；纯文本适合直接粘贴">
           <option value="md">Markdown</option><option value="txt">纯文本</option>
         </select>
         <button class="small" id="export-current" ${WS.draft ? "" : "disabled"} data-tip="先保存当前编辑，再下载这一份正文">导出当前稿</button>
         <a class="small" href="#/tasks/${t.id}/versions" data-tip="对比差异、恢复旧稿">版本</a>
         <button class="small share-current" id="share-current" ${WS.draft ? "" : "disabled"} data-tip="生成独立阅读页、分享链接和图片卡片">分享</button>
      </div>
      <div id="center-body"></div>
    </section>
    <section id="pane-right">
       <div class="panel-tabs" role="tablist" aria-label="写作面板">${[["goal", "目标与生成:改意图、调阅读体验、重新生成"],
        ["review", "检查:找出可能不工作的段落,由你决定修哪"],
        ["locks", "锁:约束每次修改,做不到就拒绝提案而非偷偷违反"],
        ["settings", "任务类型、状态与保存规则"]].map(([x, tip]) =>
         `<button role="tab" aria-selected="${WS.panelTab === x}" data-t="${x}" class="${WS.panelTab === x ? "on" : ""}" data-tip="${tip}">${({goal:"目标",review:"检查",locks:"保护",settings:"信息"})[x]}</button>`).join("")}</div>
      <div id="panel"></div>
    </section>
  </div>`;
  renderSources(); renderCenter(); renderPanel();
   $("#tab-draft").onclick = async () => {
     await flushAutosave({ checkpoint: false }); WS.view = "draft"; renderWorkspace();
   };
   $("#tab-map").onclick = async () => {
     try {
       await flushAutosave({ checkpoint: false });
       setEditorEditable(false);
       const m = await api("GET", `/tasks/${WS.tid}/writing-map`);
       WS.map = m; WS.view = "map"; renderWorkspace();
     } catch (e) { setEditorEditable(true); toast(e.message || "还没有可用的写作地图。", true); }
  };
   $("#tab-reader").onclick = async () => {
     try {
       await flushAutosave({ checkpoint: false });
       const result = await api("GET", `/tasks/${WS.tid}/reader-path-review`);
       WS.reader = result; WS.view = "reader"; renderWorkspace();
     } catch (e) { toast(e.message || "暂时无法读取稿件检查。", true); }
   };
  $("#export-current").onclick = async () => {
    if (!WS.draft) return;
    const button = $("#export-current"); button.disabled = true;
    try {
      await flushAutosave({ checkpoint: false });
      const format = $("#export-format").value;
      await downloadExport(`/tasks/${encodeURIComponent(WS.tid)}/export?format=${format}&expected_revision=${WS.draft.revision}&include_title=true`);
      toast("当前稿已下载。");
    } catch (e) { toast(e.message || "导出失败。", true); }
    finally { if (button.isConnected) button.disabled = false; }
  };
  $("#share-current").onclick = async () => {
    const button = $("#share-current"); button.disabled = true;
    try { await openTaskShare(); }
    catch (e) { toast(e.message || "暂时无法打开分享设置。", true); }
    finally { if (button.isConnected) button.disabled = !WS.draft; }
  };
   $("#add-src-btn").onclick = async () => {
     const body = $("#add-src").value.trim(); if (!body) return;
     try {
       await flushAutosave({ checkpoint: false });
       await api("POST", `/tasks/${WS.tid}/sources`, { title: "Note", content: body });
       await flushAutosave({ checkpoint: false });
       await reloadTask(); renderSources(); $("#add-src").value = "";
      toast("素材已添加，将用于下一次生成或检查。");
    } catch (e) { toast(e.message, true); }
  };
   $("#pane-right").addEventListener("click", async e => {
     const b = e.target.closest(".panel-tabs button"); if (!b) return;
     try { await saveGoalPanel(); } catch (_) { return; }
     WS.panelTab = b.dataset.t; renderPanel();
     document.querySelectorAll(".panel-tabs button").forEach(x => {
       x.classList.toggle("on", x === b); x.setAttribute("aria-selected", String(x === b));
     });
   });
}

function renderSources() {
  const sources = WS.task.sources;
  if (!sources.length) { $("#sources").innerHTML = '<p class="muted small">还没有素材。</p>'; return; }
  $("#sources").innerHTML = sources.map(s => {
    if (WS.editSourceId === s.id) {
      return `<div class="srcitem editing" data-source-id="${esc(s.id)}">
        <input class="src-edit-title small" value="${esc(s.title)}" placeholder="素材标题" aria-label="素材标题">
        <textarea class="src-edit-body" rows="6" aria-label="素材内容">${esc(s.content)}</textarea>
        <div class="srcitem-head"><span class="grow"></span>
          <button type="button" class="small" data-save-source="${esc(s.id)}" data-tip="保存修改">保存</button>
          <button type="button" class="small" data-cancel-source>取消</button></div></div>`;
    }
    return `<div class="srcitem" data-source-id="${esc(s.id)}">
      <div class="srcitem-head"><b class="small">${esc(s.title)}</b>
      <span class="muted small"> · ${esc(s.role)}</span>
      <span class="grow"></span>
      <button type="button" class="small" data-edit-source="${esc(s.id)}" data-tip="修改这份素材">修改</button>
      <button type="button" class="small" data-del-source="${esc(s.id)}" data-tip="从本任务移除这份素材">移除</button></div>
      <div class="body">${esc(s.content)}</div></div>`;
  }).join("");
  bindSourceButtons();
}

function bindSourceButtons() {
  document.querySelectorAll("[data-edit-source]").forEach(b => b.onclick = () => {
    WS.editSourceId = b.dataset.editSource; renderSources();
    const ta = document.querySelector(".src-edit-body"); if (ta) ta.focus();
  });
  document.querySelectorAll("[data-cancel-source]").forEach(b => b.onclick = () => {
    WS.editSourceId = null; renderSources();
  });
  document.querySelectorAll("[data-save-source]").forEach(b => b.onclick = async () => {
    const sid = b.dataset.saveSource;
    const card = b.closest(".srcitem");
    const title = card.querySelector(".src-edit-title").value;
    const content = card.querySelector(".src-edit-body").value;
    b.disabled = true;
    try {
      await flushAutosave({ checkpoint: false });
      await api("PATCH", `/tasks/${WS.tid}/sources/${encodeURIComponent(sid)}`, { title, content });
      await reloadTask(); WS.editSourceId = null; renderSources();
      toast("素材已修改，将用于下一次生成或检查。");
    } catch (e) {
      toast(e.code === "SHARED_SOURCE"
            ? (e.message || "此素材被其他任务引用，无法在此修改。")
            : (e.message || "素材修改失败。"), true);
      if (b.isConnected) b.disabled = false;
    }
  });
  document.querySelectorAll("[data-del-source]").forEach(b => b.onclick = async () => {
    const sid = b.dataset.delSource;
    const confirmed = await confirmDialog(
      "移除素材",
      "将把这份素材从当前任务移除。引用它的依据卡会失效；项目素材会保留，可再次引用。",
      "移除", "取消");
    if (!confirmed) return;
    b.disabled = true;
    try {
      await flushAutosave({ checkpoint: false });
      await api("DELETE", `/tasks/${WS.tid}/sources/${encodeURIComponent(sid)}`);
      await reloadTask(); renderSources();
      toast("素材已移除。");
    } catch (e) { toast(e.message || "素材移除失败。", true); if (b.isConnected) b.disabled = false; }
  });
}

function renderCenter() {
  const box = $("#center-body");
  if (!WS.draft) {
    box.innerHTML = `<div class="card" style="text-align:center;padding:60px 20px">
       <p class="muted">初稿会出现在这里。</p>
       <p><button class="primary" id="gen-now" data-tip="按你的意图与素材写第一稿">生成初稿</button></p></div>`;
    $("#gen-now").onclick = generateDraft;
    return;
  }
  if (WS.view === "map") { box.innerHTML = mapView(); wireMap(); return; }
  if (WS.view === "reader") { box.innerHTML = readerPathView(); wireReaderPath(); return; }
  box.innerHTML = `
    <div id="selbar"${WS.sel.size ? ' class="show"' : ''}>
       <button data-i="revise" data-tip="对选中段落写自定义修改指令">修改</button>
       <button data-i="shorter" data-tip="压缩选中段落，保留要点">精简</button>
       <button data-i="less" data-tip="少说破，让画面自己说话">少些直白</button>
       <button data-i="natural" data-tip="去掉做作措辞，更像人话">更自然</button>
       <button data-i="immersive" data-tip="增强细节、动作与声音">更沉浸</button>
       <button data-i="preserve" data-tip="保护所选完整段落，后续局部修改不得改变这段原文">保留原文</button>
    </div>
    <div id="revise-box" style="display:none" class="card">
       <b class="small">修改所选段落</b>
      <div class="chips" style="margin:8px 0">
        ${[["更克制", "More restrained"], ["更沉浸", "More immersive"], ["更自然", "More natural"], ["少些直白", "Less explicit"], ["更精简", "Shorter"]].map(([label, instruction]) =>
          `<button class="chip preset" data-instruction="${instruction}" data-tip="点击填入这条修改指令">${label}</button>`).join("")}
      </div>
       <label class="small muted" for="revise-instr">修改要求</label>
       <input id="revise-instr" placeholder="写下你希望怎样修改">
      <div class="row" style="margin-top:8px">
         <label class="small" data-tip="本次修改是否受核心意义保护"><input type="checkbox" id="rv-meaning" checked> 保留意义</label>
         <label class="small" data-tip="本次修改是否受事实保护"><input type="checkbox" id="rv-facts" checked> 保留事实</label>
        <span class="grow"></span>
         <button class="primary" id="revise-go" data-tip="生成修改提案，只有你接受才会改动正文">生成修改提案</button>
         <button id="revise-cancel" data-tip="放弃本次修改，正文不动">取消</button>
      </div>
    </div>
    <div id="editor">${contentParas().map((p, i) => {
      const kept = WS.preserved.some(s => s.status === "active" &&
        s.paragraph_start <= i + 1 && s.paragraph_end >= i + 1);
      return `<div class="para${WS.sel.has(i + 1) ? " sel" : ""}${kept ? " preserved" : ""}" contenteditable="true" data-p="${i + 1}">${esc(p)}</div>`;
    }).join("")}</div>
    <div id="proposals">${WS.proposals.map(proposalCard).join("")}</div>`;
  wireEditor();
  showRecovery();
}

/* editor */
function wireEditor() {
  const ed = $("#editor");
  let composition = null;
  ed.addEventListener("compositionstart", () => {
    clearTimeout(WS.saveTimer);
    WS.composition = new Promise(resolve => { composition = resolve; });
  });
  ed.addEventListener("compositionend", () => {
    if (composition) composition();
    composition = null; WS.composition = null;
    clearTimeout(WS.saveTimer);
    WS.saveTimer = setTimeout(() => saveDraft().catch(() => {}), 1200);
  });
  ed.addEventListener("input", () => {
    WS.dirty = true; WS.editRevision += 1; setSave("保存中…");
    clearTimeout(WS.saveTimer);
    if (!WS.composition) WS.saveTimer = setTimeout(() => saveDraft().catch(() => {}), 1200);
  });
  ed.addEventListener("click", e => {
    const p = e.target.closest(".para"); if (!p) return;
    const i = parseInt(p.dataset.p);
    const browserSelection = window.getSelection();
    const range = browserSelection?.rangeCount && !browserSelection.isCollapsed
      ? browserSelection.getRangeAt(0) : null;
    const selectedByText = range ? [...ed.querySelectorAll(".para")]
      .filter(x => { try { return range.intersectsNode(x); } catch (_) { return false; } })
      .map(x => parseInt(x.dataset.p)) : [];
    if ((e.shiftKey || e.metaKey || e.ctrlKey) && WS.selAnchor !== null) {
      const a = Math.min(WS.selAnchor, i), b = Math.max(WS.selAnchor, i);
      WS.sel.clear();
      for (let k = a; k <= b; k++) WS.sel.add(k);
    } else if (selectedByText.length) {
      WS.sel.clear(); selectedByText.forEach(k => WS.sel.add(k));
      WS.selAnchor = selectedByText[0];
    } else {
      WS.sel.clear(); WS.sel.add(i); WS.selAnchor = i;
    }
    ed.querySelectorAll(".para").forEach(x =>
      x.classList.toggle("sel", WS.sel.has(parseInt(x.dataset.p))));
    $("#selbar").classList.toggle("show", WS.sel.size > 0);
  });
  $("#selbar").querySelectorAll("button").forEach(b => {
    b.onclick = () => {
      if (b.dataset.i === "revise") {
        $("#revise-box").style.display = "block"; $("#revise-instr").focus();
      } else if (b.dataset.i === "preserve") {
        preserveSelection();
      } else {
        proposePatch({ shorter: "Make this shorter.", less: "Make this less explicit.",
          natural: "Make this more natural.", immersive: "Make this more immersive." }[b.dataset.i]);
      }
    };
  });
  $("#revise-cancel").onclick = () => ($("#revise-box").style.display = "none");
  $("#revise-box").querySelectorAll(".preset").forEach(c =>
    c.onclick = () => ($("#revise-instr").value = c.dataset.instruction));
  $("#revise-go").onclick = () => proposePatch($("#revise-instr").value.trim());
}

function captureEditorContent() {
  if (!WS.draft) return false;
  const editor = $("#editor");
  if (!editor) return false;
  const content = [...editor.querySelectorAll(".para")]
    .map(x => x.textContent.replace(/\u00a0/g, " "))
    .join("\n\n");
  if (content === WS.draft.working_content) return false;
  WS.draft.working_content = content;
  if (WS.review) WS.review.stale = true;
  if (WS.evidence) WS.evidence.stale = true;
  if (WS.reader) WS.reader.stale = true;
  WS.preserved.forEach(s => { if (s.status === "active") s.status = "stale"; });
  WS.dirty = true;
  WS.editRevision += 1;
  return true;
}

function setEditorEditable(enabled) {
  const editor = $("#editor");
  if (!editor) return;
  editor.querySelectorAll(".para").forEach(p => p.setAttribute("contenteditable", String(enabled)));
  editor.setAttribute("aria-busy", String(!enabled));
}

async function saveDraft() {
  if (WS.composition) await WS.composition;
  if (!WS.draft) return false;
  clearTimeout(WS.saveTimer); WS.saveTimer = null;
  while (WS.savePromise) await WS.savePromise;
  captureEditorContent();
  if (!WS.dirty) { setSave("已保存"); return true; }
  const draftId = WS.draft.id;
  const content = WS.draft.working_content || "";
  const revision = WS.editRevision;
  try {
    WS.savePromise = api("PATCH", `/drafts/${draftId}`, { working_content: content, expected_revision: WS.draft.revision });
    const saved = await WS.savePromise;
    if (WS.draft && WS.draft.id === draftId) WS.draft.revision = saved.revision;
    if (WS.draft && WS.draft.id === draftId && WS.editRevision === revision) WS.dirty = false;
    setSave(WS.dirty ? "有待保存的修改" : "已保存");
    return true;
  } catch (e) {
    if (["STALE_BASE", "REVISION_REQUIRED"].includes(e.code)) {
      try { sessionStorage.setItem(`workbench-recovery:${draftId}`, WS.draft.working_content); } catch (_) {}
      showRecovery(WS.draft.working_content);
    }
    setSave("保存失败"); toast(e.message || "正文保存失败。", true); throw e;
  } finally { WS.savePromise = null; }
}
function showRecovery(content = null) {
  if (!WS.draft || !$("#editor")) return;
  if (content === null) {
    try { content = sessionStorage.getItem(`workbench-recovery:${WS.draft.id}`); } catch (_) {}
  }
  if (content === null) return;
  $("#save-conflict")?.remove();
  const box = document.createElement("div");
  box.id = "save-conflict"; box.className = "card";
  box.innerHTML = `<b>检测到另一处修改，本地输入已保留</b><p>可复制下方文字，或下载本地副本后载入服务端正文。</p>
    <textarea aria-label="未保存的本地正文" rows="5" readonly></textarea>
    <button id="recover-reload">下载副本并载入服务端正文</button>`;
  box.querySelector("textarea").value = content;
  $("#editor").before(box);
  $("#recover-reload").onclick = async () => {
    const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `稿件本地副本-${WS.draft.id}.txt`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    const draftId = WS.draft.id;
    try {
      await reloadTask();
      sessionStorage.removeItem(`workbench-recovery:${draftId}`);
      renderWorkspace();
    } catch (e) { toast(e.message, true); }
  };
}

function setSave(s) { const el = $("#save-state"); if (el) el.textContent = s; }

/* patches */
function selRange() {
  const a = [...WS.sel].sort((x, y) => x - y);
  return { paragraph_start: a[0], paragraph_end: a[a.length - 1] };
}

async function preserveSelection() {
  if (!WS.sel.size) return;
  try {
    await flushAutosave({ checkpoint: false });
    await api("POST", `/tasks/${WS.tid}/preserved-spans`, {
      expected_revision: WS.draft.revision, selection: selRange(),
    });
    await reloadTask();
    renderWorkspace();
    toast("所选原文已保留，局部修改会避开它。");
  } catch (e) { toast(e.message || "无法保留所选原文。", true); }
}

async function proposePatch(instruction, reviewId = null, revisionItemId = null, claimLinkId = null) {
  if (!instruction) { toast("请写下修改要求。", true); return; }
  try { await flushAutosave({ checkpoint: false }); }
  catch (_) { return; }
  const locks = { ...(WS.task.config.locks || {}) };
  if ($("#rv-facts") && !$("#rv-facts").checked) locks.facts = false;
  if ($("#rv-meaning") && !$("#rv-meaning").checked) locks.core_meaning = false;
  const btn = $("#revise-go");
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Proposing…'; }
  setEditorEditable(false);
  try {
    const p = await api("POST", `/tasks/${WS.tid}/patch`, {
      base_version_id: WS.draft.current_version_id,
      expected_revision: WS.draft.revision, review_id: reviewId,
      revision_item_id: revisionItemId,
      claim_link_id: claimLinkId,
      selection: selRange(), instruction, locks,
    });
    p.instruction = instruction;
    WS.proposals.push(p);
    renderCenter();
  } catch (e) {
    toast(e.message, true);
  } finally { if (btn) btn.disabled = false; setEditorEditable(true); }
}

function proposalCard(p) {
  return `<div class="patch-card" data-id="${p.patch_id}">
     <b class="small">AI 修改提案</b>
    <p class="small muted">${esc(p.instruction)}</p>
     <div class="ba"><div><div class="h">修改前</div>${esc(p.before)}</div>
       <div><div class="h">修改后</div>${esc(p.after)}</div></div>
    <div class="row">
       <button class="primary act-accept" data-tip="只替换选中段落，并存为一个新版本">接受并应用</button>
       <button class="act-reject" data-tip="正文原样保留">拒绝</button>
       ${p.revision_item_id || p.claim_link_id ? "" : '<button class="act-retry" data-tip="同一范围再提一版">再试一版</button>'}</div></div>`;
}

document.addEventListener("click", async e => {
  const card = e.target.closest(".patch-card"); if (!card) return;
  if (card.dataset.busy === "true") return;
  const id = card.dataset.id;
  const prog = WS.proposals.find(x => x.patch_id === id);
  const actionTask = WS.tid;
  card.dataset.busy = "true";
  card.querySelectorAll("button").forEach(button => { button.disabled = true; });
  try {
    if (e.target.classList.contains("act-accept")) {
      await flushAutosave({ checkpoint: false });
      setEditorEditable(false);
      await api("POST", `/patches/${id}/accept`);
      WS.proposals = WS.proposals.filter(x => x !== prog);
      if (location.hash === `#/tasks/${actionTask}`) {
        await reloadTask();
        if (location.hash === `#/tasks/${actionTask}`) renderWorkspace();
      }
       toast("修改已接受，并保存为新版本。");
    } else if (e.target.classList.contains("act-reject")) {
      await api("POST", `/patches/${id}/reject`);
      WS.proposals = WS.proposals.filter(x => x.patch_id !== id);
      if (location.hash === `#/tasks/${actionTask}`) {
        await reloadTask();
        if (location.hash === `#/tasks/${actionTask}`) renderWorkspace();
      }
    } else if (e.target.classList.contains("act-retry")) {
      await proposePatch(prog.instruction);
    }
  } catch (err) { setEditorEditable(true); toast(err.message, true); }
  finally {
    if (card.isConnected) {
      delete card.dataset.busy;
      card.querySelectorAll("button").forEach(button => { button.disabled = false; });
    }
  }
});

/* panel */
function evidenceApplicable() {
  return WS.task.input_mode === "source_grounded"
    && ["narrative_analysis", "character_analysis", "essay"].includes(WS.task.type)
    && WS.task.sources.some(source => source.content.trim());
}

function renderPanel() {
  const box = $("#panel"); const t = WS.task; const c = t.config;
  if (WS.panelTab === "goal") box.innerHTML = `
    ${WS.task.input_mode === "topic_only" && WS.meaning ? `
      <div class="meaning-card">
         <span class="muted small">这篇文字的核心</span>
        <b>${esc(WS.meaning.refined_thesis || WS.meaning.selected_angle)}</b>
        <p class="small">${esc(WS.meaning.core_question)}</p>
         <p class="small muted">切入角度：${esc(WS.meaning.selected_angle)}</p>
         <p class="small muted">读完之后：${esc(WS.meaning.reader_end_state)}</p>
      </div>` : ""}
     <label class="small muted" for="p-instr" data-tip="你要这篇文字做到什么；它会同时指导结构与正文写作。">写作目标</label>
    <textarea id="p-instr" rows="4">${esc(t.instruction)}</textarea>
    <p class="small muted" style="margin-top:4px">你要这篇文字做到什么?写下核心意思、语气和读者读完该带走什么。可留空,但写清意图,成稿更贴近你想要的效果。<br>
      示例:"情感要克制,不出现『想念』『温暖』这类总结词,让物件和动作承担情绪。"(小说场景)<br>
      或:"分析『英雄远行-归来』为什么反复打动观众,讲机制,不要罗列术语。"(叙事分析)</p>
    <p style="margin-top:8px"><button id="p-suggest" data-tip="让模型根据素材/话题与你现在的意图起草一版,再点『使用』填回(可先修改)。仅作为草稿,由你决定。">帮我完善写作目标</button></p>
    <div id="suggest-out"></div>
    <div class="trio" style="margin-top:10px">
      ${[["immersion", "高=偏场景呈现,让读者“身临其境”;低=偏概述与说明;auto=不注入此设置"],
         ["explicitness", "高=主题直说;低=意义藏在画面里,靠读者推断;auto=不注入此设置"],
         ["intensity", "情绪与冲突的强度:高=浓烈,低=克制留白;auto=不注入此设置"]]
        .map(([k, tip]) => `
        <div data-tip="${tip}"><span class="muted small">${({immersion:"沉浸度",explicitness:"直白程度",intensity:"情绪强度"})[k]}</span>
        <select id="p-${k}">${["auto", "low", "medium", "high"].map(x =>
          `<option value="${x}"${(c[k] || "auto") === x ? " selected" : ""}>${({auto:"自动",low:"低",medium:"中",high:"高"})[x]}</option>`).join("")}</select></div>`).join("")}
    </div>
     <label class="small muted" for="p-len">目标字数</label>
    <input id="p-len" type="number" value="${c.target_length ?? ""}" placeholder="800" data-tip="正文目标字数;留空=不设目标(engine 默认 100 字下限)。改后重新生成生效">
    <p style="margin-top:14px"><button class="primary" id="p-gen" style="width:100%"
      data-tip="${WS.draft ? "按当前意图与设置重写一稿(旧稿在 Versions 里永远可回)" : "按你的意图与素材写第一稿(真实引擎约 2–4 分钟)"}">
       ${WS.draft ? "重新生成一稿" : "生成初稿"}</button></p>
    ${WS.task.input_mode === "topic_only" && WS.draft ? `
      <p class="retry-row">
         <button id="p-another" style="flex:1" data-tip="重新寻找切入角度并重写一篇">换个角度</button>
         <button id="p-same" style="flex:1" data-tip="保留当前角度与核心意义，只重写表达">沿此角度重写</button>
      </p>` : ""}
     <p><button id="p-check" style="width:100%" ${WS.draft ? "" : "disabled"} data-tip="把现在的正文存为手动版本，随时可回">保存版本节点</button></p>`;
  if (WS.panelTab === "review") box.innerHTML = `
     <div class="review-actions"><button id="r-run" ${WS.draft ? "" : "disabled"} data-tip="检查表达与推进，问题卡片可定位或发起修改">检查写作问题</button>
     ${evidenceApplicable() ? `<button id="e-run" ${WS.draft ? "" : "disabled"} data-tip="只依据此任务已添加的材料，核查关键陈述">检查材料依据</button>` : ""}</div>
    ${WS.preserved.some(s => s.status === "active") ? `<div class="preserved-list">
      <b class="small">保留原文</b>
      ${WS.preserved.filter(s => s.status === "active").map(s => `<div class="kept-row small">
        <span>¶${s.paragraph_start}${s.paragraph_end !== s.paragraph_start ? "–" + s.paragraph_end : ""} · ${esc(s.quote.slice(0, 36))}${s.quote.length > 36 ? "…" : ""}</span>
        <button class="small" data-unkeep="${s.id}" data-tip="取消后，新的局部修改可以改动这段文字">取消保留</button>
      </div>`).join("")}</div>` : ""}
    <div id="review-out">${WS.review ? reviewView(WS.review) :
       '<p class="muted small">写作检查会指出可能没有起效的段落；修不修、怎么修，由你决定。</p>'}</div>
    ${evidenceApplicable() ? `<div class="evidence-section"><b class="small">材料依据</b>
      <p class="muted small">只对照你已添加的素材；“确认”表示你看过关联，不表示外部事实认证。</p>
      <div id="evidence-out">${WS.evidence ? evidenceView(WS.evidence) :
        '<p class="muted small">尚未检查材料依据。</p>'}</div></div>` : ""}`;
  if (WS.panelTab === "locks") box.innerHTML = `
     <p class="muted small">保护项约束每次修改。无法遵守时，工作台会拒绝提案，而不是静默改写。</p>
     ${[["facts", "事实", "不改变素材中的事实。"],
        ["core_meaning", "核心意义", "保留文章的中心解释。"],
        ["character_logic", "人物逻辑", "保留已经建立的人物行为逻辑。"],
        ["structure", "结构", "保持当前推进方式。"],
        ["wording", "措辞", "尽量保留已经起效的表达。"]].map(([k, n, d]) => `
      <div class="issue"><label class="row"><input type="checkbox" data-lock="${k}"
        ${c.locks[k] ? "checked" : ""}> <b>${n}</b></label>
        <div class="small muted">${d}</div></div>`).join("")}`;
  if (WS.panelTab === "settings") box.innerHTML = `
     <p class="small">任务类型：<b>${esc(t.type)}</b></p>
     <p class="small">状态：<b>${esc(t.status)}</b></p>
     <p class="small muted">自动保存不会创建版本。只有生成、接受 AI 修改、手动节点和恢复操作会留下版本。</p>
     <div class="task-danger-zone">
       <b class="small">删除任务</b>
       <p class="small muted">删除正文、版本、检查、运行记录和分享链接。项目素材会保留。</p>
       <button id="delete-current-task" class="danger">删除这个任务</button>
     </div>`;

  if (WS.panelTab === "goal") {
    $("#p-gen").onclick = generateDraft;
    if (t.input_mode === "draft_revision") $("#p-gen").hidden = true;
    const another = $("#p-another"), same = $("#p-same");
    if (another) another.onclick = () => retryGeneration("rediscover-angle", "Trying another angle…");
    if (same) same.onclick = () => retryGeneration("regenerate", "Rewriting with the same angle…", { preserve_angle: true });
     $("#p-check").onclick = async () => {
       if (!WS.draft) { toast("还没有可保存的正文。", true); return; }
       try {
         await flushAutosave({ checkpoint: false });
         await checkpointDraft();
         await reloadTask(); renderWorkspace(); toast("版本节点已保存。");
       } catch (e) { toast(e.message || "版本节点保存失败。", true); }
     };
    for (const id of ["p-instr", "p-immersion", "p-explicitness", "p-intensity", "p-len"])
      $("#" + id).onchange = () => saveGoalPanel().catch(() => {});
    $("#p-suggest").onclick = suggestIntent;
  }
  if (WS.panelTab === "review") {
    $("#r-run").onclick = runReview;
    if ($("#e-run")) $("#e-run").onclick = runEvidenceCheck;
  }
  if (WS.panelTab === "locks") {
    box.querySelectorAll("[data-lock]").forEach(cb => cb.onchange = async () => {
      const locks = { ...WS.task.config.locks };
      locks[cb.dataset.lock] = cb.checked;
      await api("PATCH", `/tasks/${WS.tid}`, { config: { locks } });
      WS.task.config.locks = locks;
      if (WS.review) WS.review.stale = true;
      toast("保护项已保存。");
    });
  }
  if (WS.panelTab === "settings") {
    $("#delete-current-task").onclick = async () => {
      const taskId = WS.tid;
      const button = $("#delete-current-task");
      try {
        await flushAutosave({ checkpoint: false });
        const confirmed = await confirmDialog(
          "删除任务",
          `将永久删除《${taskDisplayTitle(t)}》及其正文、版本、检查、运行记录和分享链接。项目素材会保留；关联选题会回到待写。`,
          "永久删除", "取消");
        if (!confirmed || WS.tid !== taskId) return;
        button.disabled = true;
        await api("DELETE", `/tasks/${encodeURIComponent(taskId)}`);
        WS.tid = null; WS.task = null; WS.draft = null;
        toast("任务已删除。");
        location.hash = "#/tasks";
      } catch (e) { toast(e.message || "任务删除失败。", true); }
      finally { if (button.isConnected) button.disabled = false; }
    };
  }
}

/* AI intent suggestion (AI proposes, user accepts) */
const priorSuggestions = [];
let goalSavePromise = Promise.resolve();
async function saveGoalPanel() {
  if (!$("#p-instr") || !WS.task) return goalSavePromise;
  const task = WS.task, tid = WS.tid;
  const { instruction, ...config } = collectPanelParams();
  const save = goalSavePromise.catch(() => {}).then(async () => {
    if (instruction === task.instruction && Object.entries(config).every(([k, v]) => task.config[k] === v)) return;
    try {
      await api("PATCH", `/tasks/${tid}`, { instruction, config });
      task.instruction = instruction;
      Object.assign(task.config, config);
      if (WS.tid === tid && WS.review) WS.review.stale = true;
    } catch (e) {
      toast("写作目标尚未保存，请重试。" + (e.message || ""), true);
      throw e;
    }
  });
  goalSavePromise = save;
  return save;
}

async function suggestIntent() {
  const btn = $("#p-suggest");
  const label = btn ? btn.textContent : "帮我完善写作目标";
  if (btn) { btn.disabled = true; btn.textContent = "生成中…"; }
  try {
    await saveGoalPanel();
    const data = await api("POST", `/tasks/${WS.tid}/suggest-intent`,
      priorSuggestions.length ? { avoid: priorSuggestions.slice(-3) } : {});
    const s = (data.suggestion || "").trim();
    if (!s) throw new Error("The model returned an empty suggestion.");
    priorSuggestions.push(s);
    if (priorSuggestions.length > 5) priorSuggestions.shift();
    showSuggestion(s);
  } catch (err) {
    toast(err.message || "Could not draft an instruction. Please retry.", true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}
function showSuggestion(s) {
  const out = $("#suggest-out");
  if (!out) return;
  out.innerHTML = `<div class="proposal-src" style="margin-top:6px">
    <p class="small muted">这是草稿,可改;满意再点『使用』</p>
    <p class="small" style="white-space:pre-wrap">${esc(s)}</p>
    <p class="row" style="gap:8px;margin-top:8px">
      <button class="primary" id="s-use" style="flex:1">使用</button>
      <button id="s-again" style="flex:1">再换一个</button>
    </p></div>`;
  $("#s-use").onclick = async () => {
    try {
      $("#p-instr").value = s;
      await saveGoalPanel();
      out.innerHTML = "";
      toast("写作目标已更新，下次生成生效");
    } catch (err) { toast(err.message, true); }
  };
  $("#s-again").onclick = suggestIntent;
}

/* generation */
const GEN_STAGES = ["Preparing the draft…", "Understanding your material",
  "Designing progression", "Writing the draft"];
const GEN_STAGES_ZH = ["准备中…", "理解你的素材", "设计读者理解推进", "撰写正文"];
const QW_STAGES = ["Preparing the draft…", "Finding something worth saying",
  "Choosing the angle", "Designing progression", "Writing the draft"];
const QW_STAGES_ZH = ["准备中…", "寻找值得说的意义", "确定切入角度", "设计读者理解推进", "撰写正文"];
let GENERATING = false;

function stagesForTask() {
  return WS.task.input_mode === "topic_only"
    ? [QW_STAGES, QW_STAGES_ZH] : [GEN_STAGES, GEN_STAGES_ZH];
}

const STEP_LABELS = {
  queued: ["排队中", ""],
  discovery: ["寻找值得说的意义", ""],
  structure: ["设计读者理解推进", ""],
  writing: ["撰写正文", ""],
  review: ["检查中", ""],
  evidence_check: ["核查材料依据", ""],
  reader_path_review: ["检查稿件路径", ""],
};

function genBanner(on, stg, stgZh) {
  let b = $("#gen-banner");
  if (!on) { if (b) b.remove(); return; }
  const host = $("#center-body") || $("#pane-center");
  if (!host) return;
  host.insertAdjacentHTML("afterbegin",
    `<div class="card" id="gen-banner" style="padding:22px 26px">
       <p style="text-align:center"><span class="spin"></span> <b id="gb-title">正在准备…</b>
         <span class="muted small" id="gb-time">已用时 0 秒</span></p>
      <div id="gb-steps" class="steps"></div>
      <pre id="gb-live" class="live-text" style="display:none"></pre>
       <details id="gb-proc">
         <summary class="muted small">写作进度摘要 <span id="gb-proc-n"></span></summary>
         <div id="gb-sums" class="sum-lines"></div>
       </details>
     </div>`);
}

/* Shared banner renderer for generation and review progress. */
function renderBanner(st) {
  const el = $("#gb-steps");
  if (el) el.innerHTML = stepsView(st.steps, st.angle, st.error);
  const lv = $("#gb-live");
  if (lv) {
    const showing = st.shown && st.steps.includes("writing");
    lv.style.display = showing ? "block" : "none";
    if (showing) { lv.textContent = st.shown; lv.scrollTop = lv.scrollHeight; }
  }
  const ti = $("#gb-title");
  if (ti) {
    if (st.error) ti.textContent = "未能完成";
    else if (st.steps.length) {
      const last = st.steps[st.steps.length - 1];
      const lbl = STEP_LABELS[last] || [last, ""];
      ti.innerHTML = `${esc(lbl[0])} <span class="muted small">${esc(lbl[1])}</span>`;
    } else ti.textContent = "正在准备…";
  }
  const n = $("#gb-proc-n");
  if (n) n.textContent = st.sums.length ? `(${st.sums.length})` : "";
  const su = $("#gb-sums");
  if (su) su.innerHTML = st.sums.length ? st.sums.map(s => {
    const lbl = STEP_LABELS[s.stage] || [s.stage, ""];
    return `<div class="sum-line"><b>${esc(lbl[1] || lbl[0])}</b> ${esc(s.text)}</div>`;
  }).join("") : `<div class="sum-line muted">各阶段完成后会在这里留一条小结；现在还在跑第一步，不用担心。</div>`;
}

function stepsView(steps, angle, errMsg) {
  const rows = steps.map((s, i) => {
    const [en, zh] = STEP_LABELS[s] || [s, ""];
    const active = i === steps.length - 1 && !angle && !errMsg;
    const completed = s === "queued" ? "已开始 ·" : "完成 ·";
    return `<div class="step${active ? " act" : " ok"}">
      ${active ? '<span class="spin"></span>' : completed} ${esc(zh || en)}
      </div>`;
  }).join("");
  const a = angle ? `<div class="step angle">选定角度 · <b>${esc(angle)}</b></div>` : "";
  const e = errMsg ? `<div class="step bad">✗ ${esc(errMsg)}</div>` : "";
  return rows + a + e;
}

function renderProgressState(st) {
  const el = $("#gb-steps"); if (el) el.innerHTML = stepsView(st.steps, st.angle, st.error);
  const lv = $("#gb-live");
  if (lv) {
    const showing = st.shown && st.steps.includes("writing");
    lv.style.display = showing ? "block" : "none";
    if (showing) { lv.textContent = st.shown; lv.scrollTop = lv.scrollHeight; }
  }
  const ti = $("#gb-title");
  if (ti) {
    if (st.error) ti.textContent = "未能完成";
    else if (st.steps.length) {
      const last = st.steps[st.steps.length - 1];
      const lbl = STEP_LABELS[last] || [last, ""];
      ti.innerHTML = `${esc(lbl[0])} <span class="muted small">${esc(lbl[1])}</span>`;
    } else ti.textContent = "正在准备…";
  }
  const n = $("#gb-proc-n");
  if (n) n.textContent = st.sums.length ? `(${st.sums.length})` : "";
  const su = $("#gb-sums");
  if (su) su.innerHTML = st.sums.length ? st.sums.map(s => {
    const lbl = STEP_LABELS[s.stage] || [s.stage, ""];
    return `<div class="sum-line"><b>${esc(lbl[1] || lbl[0])}</b> ${esc(s.text)}</div>`;
  }).join("") : `<div class="sum-line muted">各阶段完成后会在这里留一条小结；现在还在跑第一步，不用担心。</div>`;
}

function genFailureCard(errMsg, endpoint, body, okMsg) {
  const host = $("#center-body") || $("#app");
  host?.insertAdjacentHTML?.("afterbegin",
    `<div class="card" style="border-color:var(--warn)">
      <b style="color:var(--warn)">本次生成未提交，现有正文已保留</b>
      <p class="small">${esc(errMsg || "The draft could not be generated correctly.")}</p>
      <p class="small muted">重试会复用输入与模型配置仍匹配的已完成步骤；配置变化时重新计算。
      想全新重来,请用 Goal 面板的 Generate。</p>
      <button class="primary" id="gen-retry" data-tip="从上一个成功的节点继续,不重复已完成的步骤">重试(继续)Retry</button></div>`);
  const taskId = WS.tid;
  const failureCard = $("#gen-retry")?.closest(".card");
  api("GET", `/tasks/${taskId}`).then(async t => {
    if (!failureCard?.isConnected || !t.operation || t.operation.status !== "failed") return;
    const op = await api("GET", `/tasks/${taskId}/operations/${t.operation.id}`);
    if (!failureCard.isConnected || !op.unapplied_result) return;
    const details = document.createElement("details");
    details.innerHTML = '<summary>查看已保留、尚未应用的生成结果</summary><textarea rows="8" readonly aria-label="未应用的生成结果"></textarea>';
    details.querySelector("textarea").value = op.unapplied_result.content;
    failureCard.appendChild(details);
  }).catch(() => {});
  const r = $("#gen-retry");
  if (r) r.onclick = () => runGeneration(
    endpoint || "generate", { ...collectPanelParams(), ...(body || {}), resume: true },
    okMsg || "初稿已生成。");
}

function openProgress(tid, onUpdate, onEnd, operationId = null) {
  let es, polling = false;
  const previousId = operationId ? null : WS.task.operation?.id;
const state = { steps: [], angle: "", error: "", live: "", shown: "",
                  seq: -1, sums: [], raw: {}, operationId };
  let ended = false;
  const finish = (errMsg) => {
    if (ended) return;
    ended = true;
    if (errMsg) state.error = errMsg;
    clearInterval(iv); clearInterval(poll);
    es.close();
    if (onEnd) onEnd(errMsg || null);
  };
  const query = operationId ? `?operation_id=${encodeURIComponent(operationId)}`
    : previousId ? `?after_operation_id=${encodeURIComponent(previousId)}` : "";
  try { es = new EventSource(`/tasks/${tid}/progress${query}`); }
  catch (e) { return { close() {}, alive: () => false }; }
  const push = () => { if (location.hash === `#/tasks/${tid}`) onUpdate(state); };
  // Reconnect safety: the server replays full history from seq 0 after any
  // EventSource reconnect; without seq dedupe the live text doubles.
  const handle = (kind, fn) => es.addEventListener(kind, ev => {
    let e; try { e = JSON.parse(ev.data); } catch (_) { return; }
    if (e.operation_id) {
      if (!state.operationId && e.operation_id === previousId) return;
      if (state.operationId && e.operation_id !== state.operationId) return;
      state.operationId = e.operation_id;
    }
    if (typeof e.seq === "number" && e.seq <= state.seq) return;
    if (typeof e.seq === "number") state.seq = e.seq;
    fn(e.data || {});
  });
  // Typewriter pacing: fast providers can dump the whole draft in ~1s;
  // reveal at a readable rate instead of flashing text onto the screen.
  const iv = setInterval(() => {
    const behind = state.live.length - state.shown.length;
    if (behind <= 0) return;
    state.shown = state.live.slice(
      0, state.shown.length + Math.max(2, Math.ceil(behind * 0.12)));
    push();
  }, 40);
  handle("stage", d => {
    if (!state.steps.includes(d.stage)) { state.steps.push(d.stage); push(); }
  });
  handle("delta", d => {
    if (d.reset) { state.live = ""; state.shown = ""; }
    else state.live = (state.live || "") + (d.t || "");
    push();
  });
  handle("angle", d => {
    if (!state.steps.includes("structure")) state.steps.push("structure");
    state.angle = d.selected_angle || "";
    push();
  });
  handle("stage_summary", d => {
    if (d.stage && d.text) { state.sums.push(d); push(); }
  });
  handle("stage_delta", d => {
    if (!d.stage) return;
    const cur = d.reset ? "" : (state.raw[d.stage] || "");
    state.raw[d.stage] = (cur.length > 6000 ? cur.slice(-4000) : cur) + (d.t || "");
    push();
  });
  handle("error", d => {
    state.error = d.message || "";
    if (state.error) { push(); finish(d.message || ""); }
  });
  async function checkStatus() {
    if (ended || polling) return;
    polling = true;
    try {
      let op;
      if (state.operationId) op = await api("GET", `/tasks/${tid}/operations/${state.operationId}`);
      else {
        op = (await api("GET", `/tasks/${tid}`)).operation;
        if (!op || op.id === previousId) return;
        state.operationId = op.id;
      }
      if (op.status === "succeeded") finish(null);
      else if (op.status === "failed" || op.status === "interrupted")
        finish(op.status === "interrupted" ? "服务已重启，本次运行中断。已保存正文保留，可手动重试。" : (state.error || "本次运行失败，请重试。"));
    } catch (_) { /* transient disconnect: EventSource and status polling retry */ }
    finally { polling = false; }
  }
  const poll = setInterval(checkStatus, 2000);
  es.addEventListener("done", checkStatus);
  es.addEventListener("eof", checkStatus);
  es.onerror = checkStatus;
  return {
    close() { ended = true; clearInterval(iv); clearInterval(poll); es.close(); },
    alive: () => state.steps.length > 0,
  };
}

function collectPanelParams() {
  const g = (id) => $(id);
  const p = {};
  if (g("#p-instr")) p.instruction = g("#p-instr").value;
  for (const k of ["immersion", "explicitness", "intensity"])
    if (g(`#p-${k}`)) p[k] = g(`#p-${k}`).value === "auto" ? null : g(`#p-${k}`).value;
  if (g("#p-len")) {
    const n = parseInt(g("#p-len").value, 10);
    p.target_length = Number.isFinite(n) ? n : null;   // explicit reset when cleared
  }
  return p;
}

async function generateDraft(extraBody = {}) {
  if (GENERATING) return;
  if (WS.draft && !(await confirmDialog(
      "重新生成一稿？", "当前稿会先保存到版本历史，生成失败也不会改动正文。", "继续生成")))
    return;
  await runGeneration("generate", { ...collectPanelParams(), ...extraBody },
                      "初稿已生成。");
}

async function retryGeneration(endpoint, label, body) {
  if (GENERATING) return;
  if (!(await confirmDialog(
      "确认重新写作", "当前稿会先保存到版本历史，之后可以随时恢复。", "继续"))) return;
  await runGeneration(endpoint, { ...collectPanelParams(), ...(body || {}) },
                      label.replace("…", "") + " — done.");
}

async function checkpointDraft() {
  const r = await api("POST", `/tasks/${WS.tid}/checkpoint`, { expected_revision: WS.draft.revision });
  WS.draft.revision = r.revision;
  WS.draft.current_version_id = r.version_id;
}

async function flushAutosave({ checkpoint = true } = {}) {
  await saveGoalPanel();
  // Persist any in-flight editor text before a destructive generation, and
  // snapshot it as a checkpoint so "your draft is safe in version history"
  // is actually true for edits made since the last version.
  clearTimeout(WS.saveTimer); WS.saveTimer = null;
  if (!WS.draft) return;
  captureEditorContent();
  // An edit can land while a PATCH is in flight. Keep saving until the
  // revision persisted by saveDraft is still the latest local revision.
  while (WS.dirty || WS.savePromise) await saveDraft();
  if (checkpoint) await checkpointDraft();
}

async function runGeneration(endpoint, body, okMsg) {
  const myTid = WS.tid;
  try { await flushAutosave(); }
  catch (_) { return; }
  body = { ...body, expected_revision: WS.draft ? WS.draft.revision : null };
  GENERATING = true;
  WS.panelTab = "goal";
  if (!WS.draft) renderWorkspace();
  const [STG, STG_ZH] = stagesForTask();
  genBanner(true);
  const btns = [$("#p-gen"), $("#gen-now"), $("#p-another"), $("#p-same"),
                $("#r-run")].filter(Boolean);
  btns.forEach(b => { b.disabled = true; });
  setEditorEditable(false);
  let i = 0, t0 = Date.now();
  const render = renderBanner;
  const prog = openProgress(myTid, render);
  const timer = setInterval(() => {
    if (prog.alive()) return;             // real events win; rotate only as fallback
    i = Math.min(i + 1, STG.length - 1);
    const ti = $("#gb-title");
    if (ti) ti.innerHTML = `${STG[i]} <span class="muted small">${STG_ZH[i]}</span>`;
  }, 9000);
  const tick = setInterval(() => {
    const time = $("#gb-time");
    if (!time) return;
    const secs = Math.round((Date.now() - t0) / 1000);
    time.textContent = secs > 180
      ? `已用时 ${secs} 秒（比平时慢，模型可能在排队或思考较长，可继续等或检查设置里的模型地址）`
      : `已用时 ${secs} 秒`;
  }, 1000);
  const stillHere = () => WS.tid === myTid && location.hash === `#/tasks/${myTid}`;
  try {
    await api("POST", `/tasks/${myTid}/${endpoint}`, body);
    if (!stillHere()) { toast("生成已完成，打开任务即可查看。"); }
    else {
      await reloadTask();
      if (!stillHere()) return;
      WS.view = "draft"; renderWorkspace();
      toast(okMsg);
    }
  } catch (e) {
    if (!stillHere()) { toast(e.message || "生成失败。", true); }
    else {
      renderWorkspace();  // clears banner, redraws current draft intact
      genFailureCard(e.message, endpoint, body, okMsg);
      toast(e.message || "生成失败，当前正文没有改变。", true);
    }
  } finally {
    prog.close();
    clearInterval(timer); clearInterval(tick);
    GENERATING = false;
    if (stillHere()) genBanner(false);
  }
}

/* Page refresh mid-generation: the generation runs server-side; reattach to
   the progress stream so the UI shows the in-progress state again (and
   refreshes the draft when it finishes). */
function resumeInProgressGeneration() {
  const myTid = WS.tid;
  if (GENERATING) return;
  GENERATING = true;
  WS.panelTab = "goal";
  renderWorkspace();
  const [STG, STG_ZH] = stagesForTask();
  genBanner(true);
  const btns = [$("#p-gen"), $("#gen-now"), $("#p-another"), $("#p-same")].filter(Boolean);
  btns.forEach(b => { b.disabled = true; });
  let i = 0;
  const startedAt = Date.parse(WS.task.operation?.started_at || "");
  const t0 = Number.isFinite(startedAt) ? startedAt : Date.now();
  const stillHere = () => WS.tid === myTid && location.hash === `#/tasks/${myTid}`;
  const prog = openProgress(myTid, renderProgressState, (errMsg) => {
    prog.close();
    clearInterval(timer); clearInterval(tick);
    GENERATING = false;
    if (!stillHere()) { genBanner(false); toast(errMsg || "生成已完成。", !!errMsg); return; }
    genBanner(false);
    reloadTask().then(() => {
      if (!stillHere()) return;
      WS.view = "draft";
      renderWorkspace();
      if (errMsg) {
        if (WS.task.operation?.kind === "review") {
          WS.panelTab = "review"; renderPanel();
        } else genFailureCard(errMsg);
        toast(errMsg || "生成失败。", true);
      } else {
        toast("生成完成。");
      }
    }).catch(e => toast(e.message || "Reload failed.", true));
  }, WS.task.operation?.id);
  const timer = setInterval(() => {
    if (prog.alive()) return;             // real events win; rotate only as fallback
    i = Math.min(i + 1, STG.length - 1);
    const ti = $("#gb-title");
    if (ti) ti.innerHTML = `${STG[i]} <span class="muted small">${STG_ZH[i]}</span>`;
  }, 9000);
  const updateElapsed = () => {
    const time = $("#gb-time");
    if (!time) return;
    const secs = Math.round((Date.now() - t0) / 1000);
    time.textContent = secs > 180
      ? `已用时 ${secs} 秒（模型仍在处理，将按设置中的单次超时停止）`
      : `已用时 ${secs} 秒`;
  };
  updateElapsed();
  const tick = setInterval(updateElapsed, 1000);
}

/* review */
async function runReview() {
  if (GENERATING) { toast("正在生成，请稍候。", true); return; }
  if (!WS.draft) { toast("请先生成初稿。", true); return; }
  const myTid = WS.tid;
  setEditorEditable(false);
  try { await flushAutosave({ checkpoint: false }); }
  catch (_) { setEditorEditable(true); return; }
  const btn = $("#r-run"); btn.disabled = true; btn.innerHTML = '<span class="spin"></span> 检查中…';
  const genBtns = [$("#p-gen"), $("#gen-now"), $("#p-another"), $("#p-same")].filter(Boolean);
  genBtns.forEach(b => { b.disabled = true; });
  genBanner(true);
  const prog = openProgress(WS.tid, renderBanner);
  const t0 = Date.now();
  const tick = setInterval(() => {
    const time = $("#gb-time");
    if (time) time.textContent = `已用时 ${Math.round((Date.now() - t0) / 1000)} 秒`;
  }, 1000);
  try {
    const review = await api("POST", `/tasks/${myTid}/review`);
    if (WS.tid === myTid) WS.review = review;
  } catch (e) {
    if (WS.tid === myTid) { toast(e.message, true); WS.review = null; }
  }
  finally {
    prog.close(); clearInterval(tick);
    if (WS.tid === myTid) {
      genBanner(false); setEditorEditable(true);
      if (btn.isConnected) btn.disabled = false;
      genBtns.forEach(b => { if (b.isConnected) b.disabled = false; });
      if ($("#panel")) renderPanel();
    }
  }
}

function reviewView(r) {
  const staleBanner = r.stale
    ? `<p class="muted">正文或目标已改变；已记录本轮结果，继续处理前请重新检查。</p>` : "";
  const labels = { progression:"推进", meaning_density:"意义密度", immersion:"沉浸", restraint:"克制", coherence:"连贯" };
  const qualities = { strong:"稳健", good:"良好", needs_attention:"需留意" };
  const decision = r.summary.decision === "PATCH_REQUIRED" ? "这篇还有需要修订的地方。" :
    r.summary.decision === "PASS" ? "本次检查已通过。" : "";
  const statuses = { open:"待处理", proposed:"提案中", resolved:"已完成",
    dismissed:"已跳过", stale:"已失效" };
  const severities = { fatal:"致命", major:"重要", moderate:"中等", minor:"轻微" };
  const activeProposal = r.issues.some(i => i.status === "proposed");
  return staleBanner + `<p class="small">${decision}</p><div class="row" style="flex-wrap:wrap">${Object.entries(labels).map(([k, label]) => {
    const value = Object.hasOwn(qualities, r.summary[k]) ? r.summary[k] : "unknown";
    return `<span class="small">${label}</span> <span class="label ${value}">${qualities[value] || "未完成"}</span>`;
  }).join(" ")}</div>` +
    (r.issues.length ? r.issues.map((is, n) => `
      <div class="issue revision-item ${esc(is.status || "open")}">
      <div class="row"><span class="label">${esc(severities[is.severity] || "中等")}</span><span class="small muted">${esc(statuses[is.status] || "待处理")}</span></div>
      <p class="small"><b>${esc(is.message)}</b></p>
      ${is.effect ? `<p class="small muted">影响：${esc(is.effect)}</p>` : ""}
      ${is.goal ? `<p class="small">修改目标：${esc(is.goal)}</p>` : ""}
      ${is.quote ? `<blockquote class="issue-quote">${esc(is.quote)}</blockquote>` : ""}
      <p class="loc">¶${is.location.paragraph_start}${is.location.paragraph_end !== is.location.paragraph_start ? "–" + is.location.paragraph_end : ""}</p>
      <div class="row"><button class="small" data-show="${n}" data-tip="跳到并高亮对应段落">定位</button>
      ${is.status === "open" ? `<button class="small" data-fix="${n}" ${activeProposal ? "disabled" : ""} data-tip="按修改目标生成局部提案">处理</button>
      <button class="small" data-dismiss="${n}" data-tip="本轮不处理此项，正文不会改变">跳过</button>` : ""}</div></div>`).join("")
      : '<p class="muted small">没有发现需要特别留意的问题。</p>');
}

async function runEvidenceCheck() {
  if (GENERATING) { toast("正在生成，请稍候。", true); return; }
  if (!WS.draft) { toast("请先准备正文。", true); return; }
  const tid = WS.tid;
  try { await flushAutosave({ checkpoint: false }); }
  catch (_) { return; }
  const btn = $("#e-run");
  if (btn) { btn.disabled = true; btn.textContent = "核查中…"; }
  genBanner(true);
  const prog = openProgress(tid, renderBanner);
  try {
    const result = await api("POST", `/tasks/${tid}/check-evidence`);
    if (WS.tid === tid) WS.evidence = result;
  } catch (e) {
    if (WS.tid === tid) toast(e.message, true);
  } finally {
    prog.close();
    if (WS.tid === tid) { genBanner(false); renderPanel(); }
  }
}

function evidenceView(result) {
  const relations = { supported:"材料支持", inference:"作者推断",
    insufficient:"待补证据", conflict:"与材料冲突" };
  const types = { fact:"事实陈述", author_inference:"作者推断", value_judgment:"价值判断" };
  const statuses = { unreviewed:"待核查", confirmed:"已确认关联", dismissed:"本轮忽略" };
  const stale = result.stale
    ? '<p class="muted">正文或素材已改变；这些卡片已过期，请重新检查。</p>' : "";
  if (!result.cards.length) return stale + '<p class="muted small">没有提取到可可靠定位的关键陈述。</p>';
  return stale + result.cards.map(card => `
    <div class="issue evidence-card ${esc(card.relation)}${result.stale ? " stale" : ""}">
      <div class="row"><span class="label relation">${esc(relations[card.relation] || card.relation)}</span>
        <span class="small muted">${esc(types[card.claim_type] || card.claim_type)} · ${esc(statuses[card.user_status] || card.user_status)}</span></div>
      <blockquote class="issue-quote">${esc(card.draft_quote)}</blockquote>
      <p class="small">${esc(card.explanation)}</p>
      ${card.source_quote ? `<div class="source-evidence"><span class="small muted">素材 · ${esc(card.source_title || "未命名素材")}</span>
        <blockquote class="issue-quote">${esc(card.source_quote)}</blockquote></div>` :
        '<p class="small muted">没有可逐字定位的材料原句。</p>'}
      <p class="small">处理目标：${esc(card.revision_goal)}</p>
      <p class="loc">¶${card.location.paragraph_start}${card.location.paragraph_end !== card.location.paragraph_start ? "–" + card.location.paragraph_end : ""}</p>
      <div class="row"><button class="small" data-claim-show="${card.id}">定位正文</button>
        ${card.source_id ? `<button class="small" data-claim-source="${card.id}">查看素材</button>` : ""}
        ${card.actionable ? `<button class="small" data-claim-confirm="${card.id}">确认关联</button>
          <button class="small" data-claim-fix="${card.id}" ${card.patch_id ? "disabled" : ""}>处理</button>
          <button class="small" data-claim-dismiss="${card.id}">忽略</button>` : ""}</div>
    </div>`).join("");
}

document.addEventListener("click", async e => {
  const show = e.target.closest("[data-show]");
  const fix = e.target.closest("[data-fix]");
  const dismiss = e.target.closest("[data-dismiss]");
  if (!show && !fix && !dismiss) return;
  try { await flushAutosave({ checkpoint: false }); } catch (_) { return; }
  if (!WS.review || WS.review.stale) { toast("正文或目标已改变，请重新检查。", true); return; }
  const target = show || fix || dismiss;
  const is = WS.review.issues[parseInt(target.dataset.show ?? target.dataset.fix ?? target.dataset.dismiss)];
  if (dismiss) {
    try {
      await api("POST", `/revision-items/${is.revision_item_id}/dismiss`);
      await reloadTask(); renderWorkspace();
      toast("已跳过这一项，正文未改变。");
    } catch (e) { toast(e.message, true); }
    return;
  }
  WS.view = "draft"; renderWorkspace();
  const a = is.location.paragraph_start, b = is.location.paragraph_end;
  WS.sel.clear(); WS.selAnchor = a;
  for (let k = a; k <= b; k++) WS.sel.add(k);
  renderCenter();
  const el = $(`.para[data-p="${a}"]`);
  if (el) { el.classList.add("hl"); el.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => el.classList.remove("hl"), 2600); }
  if (fix) proposePatch(is.goal, WS.review.id, is.revision_item_id);
});

document.addEventListener("click", async e => {
  const target = e.target.closest("[data-claim-show],[data-claim-source],[data-claim-confirm],[data-claim-fix],[data-claim-dismiss]");
  if (!target || !WS.evidence) return;
  const id = target.dataset.claimShow || target.dataset.claimSource
    || target.dataset.claimConfirm || target.dataset.claimFix || target.dataset.claimDismiss;
  const card = WS.evidence.cards.find(item => item.id === id);
  if (!card) return;
  if (target.dataset.claimSource) {
    const source = document.querySelector(`.srcitem[data-source-id="${CSS.escape(card.source_id)}"]`);
    if (source) { source.classList.add("hl"); source.scrollIntoView({ behavior:"smooth", block:"center" });
      setTimeout(() => source.classList.remove("hl"), 2600); }
    return;
  }
  if (target.dataset.claimConfirm || target.dataset.claimDismiss) {
    try {
      await api("POST", `/claim-links/${id}/${target.dataset.claimConfirm ? "confirm" : "dismiss"}`);
      await reloadTask(); renderWorkspace();
      toast(target.dataset.claimConfirm ? "已记录：你确认了这条材料关联。" : "已在本轮忽略，正文未改变。");
    } catch (err) { toast(err.message, true); }
    return;
  }
  try { await flushAutosave({ checkpoint: false }); } catch (_) { return; }
  if (!WS.evidence || WS.evidence.stale) { toast("正文或素材已改变，请重新检查。", true); return; }
  WS.view = "draft"; renderWorkspace();
  const a = card.location.paragraph_start, b = card.location.paragraph_end;
  WS.sel.clear(); WS.selAnchor = a;
  for (let n = a; n <= b; n++) WS.sel.add(n);
  renderCenter();
  const para = $(`.para[data-p="${a}"]`);
  if (para) { para.classList.add("hl"); para.scrollIntoView({ behavior:"smooth", block:"center" });
    setTimeout(() => para.classList.remove("hl"), 2600); }
  if (target.dataset.claimFix) proposePatch(card.revision_goal, null, null, card.id);
});

document.addEventListener("click", async e => {
  const remove = e.target.closest("[data-unkeep]");
  if (!remove) return;
  try {
    await api("DELETE", `/preserved-spans/${remove.dataset.unkeep}`);
    await reloadTask(); renderWorkspace();
    toast("已取消保留。");
  } catch (err) { toast(err.message, true); }
});

async function runReaderPathReview() {
  if (GENERATING) { toast("正在生成，请稍候。", true); return; }
  const tid = WS.tid;
  const btn = $("#reader-run");
  if (btn) { btn.disabled = true; btn.textContent = "检查中…"; }
  genBanner(true);
  const prog = openProgress(tid, renderBanner);
  try {
    const result = await api("POST", `/tasks/${tid}/reader-path-review`);
    if (WS.tid === tid) WS.reader = result;
  } catch (e) {
    if (WS.tid === tid) toast(e.message, true);
  } finally {
    prog.close();
    if (WS.tid === tid) { genBanner(false); renderCenter(); }
  }
}

function readerPathView() {
  const result = WS.reader || {steps:[], issues:[], stale:false};
  if (!result.id) return `<div class="reader-intro card">
    <h3>检查当前稿的实际推进</h3>
    <p class="muted">逐段查看作用、增加的认识和问题回答关系。结果是模型对可能阅读效果的诊断，不是真实读者实验。</p>
    <button class="primary" id="reader-run">开始检查稿件</button></div>`;
  const statuses = {open:"待处理", proposed:"提案中", resolved:"已完成", dismissed:"已跳过", stale:"已失效"};
  const types = {repetition:"内容重复", reasoning_gap:"推理跳跃",
    unanswered_question:"问题未回答", unclear_transition:"转折不清"};
  return `<div class="reader-path">
    <div class="reader-path-head"><div><b>当前稿件路径</b>
      <p class="muted small">${esc(result.overview)} 这是模型诊断，不是真实读者实验。</p></div>
      <button id="reader-run">${result.stale ? "重新检查" : "再次检查"}</button></div>
    ${result.stale ? '<p class="card muted">正文已经改变；本轮稿件检查已过期，旧问题不能继续处理。</p>' : ""}
    <div class="reader-path-grid"><section><h3>逐段推进</h3>${result.steps.map((step, index) => `
      <article class="path-step" role="button" tabindex="0" data-reader-step="${step.id}">
        <div class="row"><span class="path-number">${index + 1}</span><b>¶${step.location.paragraph_start} · ${esc(step.primary_function)}</b></div>
        <blockquote class="issue-quote">${esc(step.quote)}</blockquote>
        <p class="small"><span class="muted">增加的认识：</span>${esc(step.knowledge_gain)}</p>
        ${step.question_raised ? `<p class="small"><span class="muted">提出：</span>${esc(step.question_raised)}</p>` : ""}
        ${step.question_answered ? `<p class="small"><span class="muted">回答：</span>${esc(step.question_answered)}</p>` : ""}
      </article>`).join("")}</section>
      <aside><h3>路径问题</h3>${result.issues.length ? result.issues.map(issue => `
        <article class="issue reader-issue ${esc(issue.status)}">
          <div class="row"><span class="label">${esc(types[issue.type] || issue.type)}</span><span class="small muted">${esc(statuses[issue.status] || issue.status)}</span></div>
          <p class="small"><b>${esc(issue.message)}</b></p><p class="small muted">可能影响：${esc(issue.effect)}</p>
          <blockquote class="issue-quote">${esc(issue.quote)}</blockquote>
          <p class="small">修改目标：${esc(issue.goal)}</p>
          <div class="row"><button class="small" data-reader-show="${issue.revision_item_id}">定位</button>
            ${issue.status === "open" && !result.stale ? `<button class="small" data-reader-fix="${issue.revision_item_id}">处理</button>
              <button class="small" data-reader-dismiss="${issue.revision_item_id}">跳过</button>` : ""}</div>
        </article>`).join("") : '<p class="muted small">没有发现可可靠定位的路径问题。</p>'}</aside>
    </div></div>`;
}

function wireReaderPath() {
  const run = $("#reader-run"); if (run) run.onclick = runReaderPathReview;
  $("#center-body").querySelectorAll("[data-reader-step]").forEach(element => {
    const activate = () => locateReaderTarget(WS.reader.steps.find(step => step.id === element.dataset.readerStep));
    element.onclick = activate;
    element.onkeydown = event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); activate(); } };
  });
  $("#center-body").querySelectorAll("[data-reader-show],[data-reader-fix],[data-reader-dismiss]").forEach(button => {
    button.onclick = async () => {
      const id = button.dataset.readerShow || button.dataset.readerFix || button.dataset.readerDismiss;
      const issue = WS.reader.issues.find(item => item.revision_item_id === id);
      if (!issue) return;
      if (button.dataset.readerDismiss) {
        try {
          await api("POST", `/revision-items/${id}/dismiss`);
          WS.reader = await api("GET", `/tasks/${WS.tid}/reader-path-review`);
          renderCenter(); toast("已跳过这一项，正文未改变。");
        } catch (error) { toast(error.message, true); }
        return;
      }
      await locateReaderTarget(issue);
      if (button.dataset.readerFix)
        proposePatch(issue.goal, WS.reader.id, issue.revision_item_id);
    };
  });
}

async function locateReaderTarget(item) {
  if (!item) return;
  if (WS.reader && WS.reader.stale) { toast("正文已改变，请重新检查。", true); return; }
  WS.view = "draft"; renderWorkspace();
  const a = item.location.paragraph_start, b = item.location.paragraph_end;
  WS.sel.clear(); WS.selAnchor = a;
  for (let number = a; number <= b; number++) WS.sel.add(number);
  renderCenter();
  const paragraph = $(`.para[data-p="${a}"]`);
  if (paragraph) { paragraph.classList.add("hl");
    paragraph.scrollIntoView({behavior:"smooth", block:"center"});
    setTimeout(() => paragraph.classList.remove("hl"), 2600); }
}

/* writing map */
function mapView() {
  const beats = (WS.map && WS.map.beats) || [];
  return `<p class="muted small">这是生成时的原定路径，段落对应关系为估算；手工修改后可能偏移。原定路径只读。</p>` +
    (beats.length ? beats.map((b, i) => `
      <div class="beat" role="button" tabindex="0" data-a="${b.paragraph_start}" data-b="${b.paragraph_end}">
        <div class="t">第 ${i + 1} 步 · ${esc(b.function)}</div>
        <div class="small arrow">${esc(b.reader_before)} → ${esc(b.reader_after)}</div>
        <div class="small muted">${esc(b.meaning_gain)}</div>
        ${b.paragraph_start ? `<div class="small muted">¶${b.paragraph_start}${b.paragraph_end !== b.paragraph_start ? "–" + b.paragraph_end : ""}</div>` : ""}
      </div>`).join("")
      : '<div class="card"><p class="muted">还没有写作地图，请先生成初稿。</p></div>');
}
function wireMap() {
  $("#center-body").querySelectorAll(".beat").forEach(el => {
    el.onclick = async () => {
      const a = parseInt(el.dataset.a), b = parseInt(el.dataset.b);
      if (!a) return;
      try { await flushAutosave({ checkpoint: false }); } catch (_) { return; }
      WS.view = "draft"; renderWorkspace();
      WS.sel.clear(); WS.selAnchor = a;
      for (let k = a; k <= b; k++) WS.sel.add(k);
      renderCenter();
      const p = $(`.para[data-p="${a}"]`);
      if (p) { p.classList.add("hl"); p.scrollIntoView({ behavior: "smooth", block: "center" });
        setTimeout(() => p.classList.remove("hl"), 2600); }
    };
    el.onkeydown = e => {
      if (!["Enter", " "].includes(e.key)) return;
      e.preventDefault(); el.click();
    };
  });
}

/* ------------------------------------------------------------- versions */
async function versions(tid) {
  if (location.hash !== `#/tasks/${tid}/versions`) return;
  const task = await api("GET", `/tasks/${tid}`);
  if (location.hash !== `#/tasks/${tid}/versions`) return;
  if (!task.draft) { $("#app").innerHTML = '<p class="muted">还没有初稿。</p>'; return; }
  const vs = await api("GET", `/drafts/${task.draft.id}/versions`);
  if (location.hash !== `#/tasks/${tid}/versions`) return;
  const rows = vs.versions.slice().reverse();            // newest first
  const cont = new Map();                                // id -> full content (lazy)
  const open = new Set();                                // expanded ids
  const sel = [];                                        // selected ids (max 2)
  const curId = task.draft.current_version_id;
  const byId = new Map(rows.map(v => [v.id, v]));
  const shortId = id => (id.length > 12 ? "…" + id.slice(-6) : id);
  const short = s => {
    const t = (s || "").replace(/\s+/g, " ").trim();
    return t.length > 160 ? t.slice(0, 160) + "…" : (t || "（空白）");
  };
  const originName = origin => ({
    generation: "初次生成", patch: "接受 AI 修改", manual_checkpoint: "手动节点", restore: "恢复版本",
    "Initial Generation": "初次生成", "AI Patch": "接受 AI 修改", "Manual Checkpoint": "手动节点", Restore: "恢复版本",
  })[origin] || origin;

  $("#app").innerHTML = `
    <h1>版本历史</h1>
    <p class="muted small">最多选择两个版本进行对比；恢复操作也会创建新版本，随时可以反悔。</p>
    <p class="row"><label class="small" for="v-export-format">版本导出格式</label>
      <select id="v-export-format" class="export-format"><option value="md">Markdown</option><option value="txt">纯文本</option></select></p>
    <div id="vlist">${rows.map(rowHtml).join("")}</div>
    <div id="vctrl"><p class="muted small">未选择:点任意版本行开始选择对比。</p></div>
    <div id="compare"></div>
    <p style="margin-top:10px"><a href="#/tasks/${tid}">返回正文</a></p>`;

  function rowHtml(v) {
    const isCur = v.id === curId;
    const instr = v.instruction
      ? ` · <span class="muted small">"${esc(v.instruction)}"</span>` : "";
    return `
    <div class="vrow${isCur ? " cur" : ""}" data-v="${v.id}" role="button" tabindex="0" aria-label="选择版本 ${esc(originName(v.origin))}">
      <span class="vpick"></span>
      <div class="grow">
        <div class="vhead"><b>${esc(originName(v.origin))}</b><span class="muted small">· ${esc(v.created_at)} · ${esc(shortId(v.id))}${instr}</span>${isCur ? '<span class="vtag">当前</span>' : ""}</div>
        <div class="vprev" data-v="${v.id}">载入预览…</div>
      </div>
      <div class="vacts">
        ${isCur ? "" : `<button class="small va-cur" data-v="${v.id}" data-tip="对比此版本与当前草稿">与当前稿对比</button>`}
        <button class="small va-export" data-v="${v.id}" data-tip="下载这个历史版本，不改变当前正文">导出</button>
        <button class="small va-restore" data-v="${v.id}" data-tip="恢复此版本为当前草稿；恢复本身也是新版本">恢复</button>
      </div>
    </div>`;
  }

  // lazy-load contents in parallel; each preview fills as it arrives
  rows.forEach(v => api("GET", `/versions/${v.id}`)
    .then(d => cont.set(v.id, d.content))
    .catch(() => cont.set(v.id, ""))
    .finally(() => paintPreview(v.id)));

  function paintPreview(id) {
    const el = document.querySelector(`.vprev[data-v="${id}"]`);
    if (!el) return;
    const full = (cont.get(id) || "").trim();
    el.textContent = open.has(id) ? "▴ " + (full || "(empty)") : "▸ " + short(full);
  }

  function updatePicks() {
    document.querySelectorAll(".vrow").forEach(r => {
      const i = sel.indexOf(r.dataset.v);
      r.classList.toggle("picked", i >= 0);
      r.setAttribute("aria-selected", String(i >= 0));
      r.querySelector(".vpick").textContent = i >= 0 ? ["①", "②"][i] : "";
    });
  }
  function updateCtrl() {
    const c = $("#vctrl");
    if (sel.length === 1) {
      c.innerHTML = `<p class="muted small">已选 ① 一个版本,再点行选一个即可对比。</p>`;
    } else if (sel.length === 2) {
      const [aId, bId] = sel.slice().sort(
        (x, y) => byId.get(x).created_at.localeCompare(byId.get(y).created_at));
      const a = byId.get(aId), b = byId.get(bId);
      c.innerHTML = `<p class="row"><span class="vtag">旧版</span> <b>${esc(originName(a.origin))}</b>
        <span class="muted small">${esc(shortId(aId))}</span> <span class="muted">→</span>
        <span class="vtag">新版</span> <b>${esc(originName(b.origin))}</b>
        <span class="muted small">${esc(shortId(bId))}</span>
        <button id="do-compare">对比这① ②</button>
        <button id="clear-sel" class="small">清空选择</button></p>`;
      $("#do-compare").onclick = () => renderDiff(aId, bId);
      $("#clear-sel").onclick = () => {
        sel.length = 0; updatePicks(); updateCtrl(); $("#compare").innerHTML = "";
      };
    } else {
      c.innerHTML = `<p class="muted small">未选择:点任意版本行开始选择对比。</p>`;
    }
  }

  async function ensure(id) {
    if (!cont.has(id)) {
      try { cont.set(id, ((await api("GET", `/versions/${id}`)).content) || ""); }
      catch { cont.set(id, ""); }
      paintPreview(id);
    }
  }
  async function renderDiff(aId, bId) {
    await Promise.all([ensure(aId), ensure(bId)]);
    const a = byId.get(aId), b = byId.get(bId);
    $("#compare").innerHTML = `<div class="diff">
      <div><div class="h muted">旧版 · ${esc(originName(a.origin))}</div>${diffHtml(cont.get(aId), cont.get(bId))}</div>
      <div><div class="h muted">新版 · ${esc(originName(b.origin))}</div>${diffHtml(cont.get(bId), cont.get(aId), true)}</div></div>`;
  }

  $("#vlist").addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    const row = e.target.closest(".vrow");
    if (!row) return;
    const id = row.dataset.v;
    if (e.target.closest(".vprev")) {
      if (open.has(id)) open.delete(id); else open.add(id);
      paintPreview(id);
    } else {
      const i = sel.indexOf(id);
      if (i >= 0) sel.splice(i, 1);
      else if (sel.length >= 2) { toast("已选两个版本,先取消一个再换。", true); return; }
      else sel.push(id);
      updatePicks(); updateCtrl();
    }
  });

  document.querySelectorAll(".va-cur").forEach(b => b.onclick = () => renderDiff(b.dataset.v, curId));
  document.querySelectorAll(".va-export").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try {
      const format = $("#v-export-format").value;
      await downloadExport(`/versions/${encodeURIComponent(b.dataset.v)}/export?format=${format}&include_title=true`);
      toast("所选版本已下载。");
    } catch (err) { toast(err.message || "导出失败。", true); }
    finally { if (b.isConnected) b.disabled = false; }
  });
  document.querySelectorAll(".va-restore").forEach(b => b.onclick = async () => {
    if (!(await confirmDialog(
        "恢复这个版本？", "恢复会生成一个新版本，当前状态仍保留在历史里，可以随时反悔。", "恢复版本"))) return;
    try {
      await api("POST", `/versions/${b.dataset.v}/restore`, { expected_revision: task.draft.revision });
      toast("已恢复；原先的当前稿仍保留在版本历史中。");
      if (location.hash === `#/tasks/${tid}/versions`) versions(tid);
    } catch (err) { toast(err.message, true); }
  });
}

function diffHtml(a, b, flip = false) {
  const al = a.split("\n"), bl = b.split("\n");
  const eq = Array.from({ length: al.length + 1 }, () => new Array(bl.length + 1).fill(0));
  for (let i = al.length - 1; i >= 0; i--)
    for (let j = bl.length - 1; j >= 0; j--)
      eq[i][j] = al[i] === bl[j] ? eq[i + 1][j + 1] + 1 : Math.max(eq[i + 1][j], eq[i][j + 1]);
  let i = 0, j = 0, out = "";
  while (i < al.length && j < bl.length) {
    if (al[i] === bl[j]) { out += `<div class="dline eq">${esc(al[i])}</div>`; i++; j++; }
    else if (eq[i + 1][j] >= eq[i][j + 1]) {
      if (!flip) out += `<div class="dline del">${esc(al[i])}</div>`; i++;
    } else {
      if (flip) out += `<div class="dline add">${esc(bl[j])}</div>`; j++;
    }
  }
  while (i < al.length) {                       // drain tail: deletions at end
    if (!flip) out += `<div class="dline del">${esc(al[i])}</div>`; i++;
  }
  while (j < bl.length) {                       // drain tail: additions at end
    if (flip) out += `<div class="dline add">${esc(bl[j])}</div>`; j++;
  }
  return out || '<span class="muted">(identical)</span>';
}

/* ------------------------------------------------------------- examples */
const EXAMPLES = [
  {
    title: "示例一 · 小说场景:年夜饭",
    desc: "练习“不直接说出情感”:约束事实与人物逻辑,只改局部。",
    type: "fiction_scene", instruction: "父亲不要直接表达支持,用动作和细节让读者感到他的态度转变。",
    material: "除夕夜,一家人吃年夜饭。我今年辞了职想做写作,席间说起这事,\n" +
      "家里人都沉默。父亲平时话少,在机械厂干了三十年,一直希望我考公。\n" +
      "饭快吃完时,他起身去厨房,把那条红烧鱼的肚子肉夹了一块到我碗里,\n" +
      "什么也没说。我记得小时候他从不给我夹鱼腹,说那是留给“顶梁柱”的。",
    config: { immersion: "high", explicitness: "low", intensity: "medium", target_length: 700 },
  },
  {
    title: "示例二 · 叙事分析:英雄远行",
    desc: "练习“机制而非标签”:让读者理解母题为什么有效。",
    type: "narrative_analysis", instruction: "分析“英雄远行-归来”这一叙事母题为什么反复打动观众,不要罗列术语,要让读者理解机制。",
    material: "神话学里,英雄故事常有同一形状:离开熟悉的世界,进入考验之地,带着某种领悟归来。\n" +
      "许多现代电影沿用了这个形状:主角离开小镇,在城市或战场经历挫败,回来时\n" +
      "小镇没变,但他看它的方式变了。观众明知道结局,却还是被抓住。\n" +
      "问题是:这个形状到底在读者/观众心里做了什么工作?",
    config: { immersion: "medium", explicitness: "medium", intensity: "medium", target_length: 800 },
  },
  {
    title: "示例三 · 情感复述:外婆的缝纫机",
    desc: "练习“克制”:意义留在动作里,不替读者总结。",
    type: "emotional_retelling", instruction: "复述这段记忆,情感要克制:不出现“想念”“温暖”这类总结词,让物件和动作承担情绪。",
    material: "外婆有一台蝴蝶牌缝纫机,黑色铸铁机头,脚踏板踩起来咔哒咔哒响。\n" +
      "小时候每年暑假,她给我改校服:把裤脚放出来两指,说“个子蹿得快”。\n" +
      "她眼睛花了以后,穿针要让人帮。后来缝纫机搬到阳台,再没人踩它,\n" +
      "台面上放着一盆吊兰。她去世那年冬天,妈妈把缝纫机擦干净,运回了自己家。",
    config: { immersion: "high", explicitness: "low", intensity: "low", target_length: 600 },
  },
];
let PREFILL = null;
function loadExample(i) {
  PREFILL = EXAMPLES[i];
  if (location.hash === "#/tasks/new") newTask();
  else location.hash = "#/tasks/new";
}

/* --------------------------------------------------------------- guide */
function guide() {
  $("#app").innerHTML = `
  <div class="form" style="max-width:820px">
    <h1>使用指南 How to Use</h1>
    <p class="muted">这个工作台的核心不是"聊天生成文字",而是:
    <b>素材 → 意图 → 生成 → 阅读 → 检查 → 局部修改 → 接受</b>。
    一条铁律贯穿始终:<b>AI 只提案,你才拍板</b>——任何修改在你点击
    Accept 之前都不会碰你的正文。</p>

    <h2>快速写作：只有一个想法时</h2>
    <div class="card">首页有三种开始:<b>Start with an idea</b>(只有话题)、
    <b>Write from material</b>(有素材)、<b>Improve a draft</b>(改现有稿)。
    选"Start with an idea"(或顶栏 <b>Quick Write</b>),只写一句你想谈的话题,
    例如"谈谈失败"。系统会<b>先替你找到值得说的角度</b>——生成 3–5 个真正不同的切入,
    选出一个最有意义、最能推进的,再据此设计读者理解推进、写出初稿。
    产出进入<b>同一个工作台</b>,和从素材写作完全一样。
    生成后 Goal 面板顶部会显示"What this piece is about"(选中的角度与核心问题),
    并有<b>Try another angle</b>(换一个角度重写,会避开用过的)与
    <b>Rewrite this angle</b>(保留同一角度,只重写表达)两个独立按钮。
    "Preserve Core Meaning"默认开启:普通修改不会偷换你的核心观点。
    若话题偏事实型(如"罗马为何灭亡"),会提示你继续用通用知识或补充素材——
    没有来源时文章不会假装引用。</div>

    <h2>① 开始一篇写作</h2>
    <div class="card">点顶栏 <b>Write from Material</b>:选任务类型(小说场景/叙事分析/人物分析/随笔/情感复述/自由写作),
    写下<b>你想让这篇文字做到什么</b>(意图),粘贴<b>素材</b>(故事、笔记、观点),
    再调<b>阅读体验</b>:沉浸度 Immersion、显性度 Explicitness、强度 Intensity、目标长度。
    勾选<b>约束</b>(保留事实、保留核心意义、避免过度解释、不编造重大事件),
    点 <b>Create &amp; Write</b> 进入工作台。项目 Project 是可选的,只用来把相关素材和任务归堆。</div>

    <h2>② 认识工作台(三栏)</h2>
    <div class="card">
      <p><b>左 · Sources</b> 你的素材与笔记,可随时追加。</p>
      <p><b>中 · Draft</b> 正文,占最大空间。直接点击任意段落即可编辑,自动保存(Saving…/Saved);
      单击段落=选中；拖选文字会映射到所在段落；Shift/⌘/Ctrl 单击会扩展为连续段落范围。</p>
      <p><b>右 · Writing Panel</b> 四个标签:
      <b>Goal</b>(改意图、调阅读体验、生成)、<b>Review</b>(检查)、
      <b>Locks</b>(锁)、<b>Settings</b>(任务信息)。</p></div>

    <h2>③ 生成第一稿</h2>
    <div class="card">在 Goal 面板点 <b>Generate Draft</b>(约 1–2 分钟)。
    生成失败不会破坏你已有的正文;语言不对会被安全拒绝并重试。
    重新生成会产出新版本,旧稿永远可以在 Versions 里找回。</div>

    <h2>④ 局部修改(Patch)——本工具的灵魂</h2>
    <div class="card">选中段落 → 顶部浮出工具条:<b>Revise / Shorter / Less Explicit /
    More Natural / More Immersive</b>。
    选 Revise 可写自定义指令或用预设,点 <b>Generate Patch</b>。
    系统给出 <b>Before / After</b> 对照,你三选一:
    <b>Accept</b>(只替换选中段落并存为一个版本)、<b>Reject</b>(什么都不发生)、
    <b>Try Again</b>(同范围再提一版)。
    好的段落是资产——修改永远只动你选中的部分,不重写全文。</div>

    <h2>⑤ 检查(Review)</h2>
    <div class="card">Review 面板点 <b>Run Review</b>,得到五个维度的产品级评价
    (Strong / Good / Needs attention)和问题卡片。
    每张卡片:<b>Show</b> 跳到并高亮对应段落;<b>Fix</b> 直接对那段发起局部修改提案。</div>

    <h2>⑥ 锁(Locks)</h2>
    <div class="card">Locks 面板可锁定:<b>Facts</b> 不改事实、<b>Core Meaning</b> 保持核心解释、
    <b>Character Logic</b> 人物行为逻辑、<b>Structure</b> 推进结构、<b>Wording</b> 成功措辞。
    若某次修改做不到这些,系统会<b>拒绝提案并说明原因</b>,而不是偷偷违反。</div>

    <h2>⑦ 版本与写作地图</h2>
    <div class="card">每次生成、接受的修改、手动 Checkpoint、恢复都会存为版本
    (自动保存不算)。Versions 页点行选中两个版本即可自动对比差异,或 <b>Restore</b>
    ——恢复本身也是新版本,可再恢复回去,永远不丢内容。
    <b>Writing Map</b> 标签展示文章的理解推进(每一步读者从哪想到哪),点击可定位段落,只读不编辑。</div>

    <h2>⑧ 小抄</h2>
    <div class="card small muted">
      改完全文满意 → Versions 确认历史干净 → 复制正文走人。<br>
      担心被 AI 乱改?记住:没有你的 Accept,AI 一个字都改不了。<br>
      想离线体验界面?Settings 页查看当前引擎模式;mock 模式下所有交互一致、秒级响应。</div>
    <h2>⑨ 试一试:三个内置示例</h2>
    <div class="card small muted" style="margin-bottom:4px">点击任意示例,素材与设置会自动填入"新建任务",可直接生成第一稿体验完整流程。</div>
    ${EXAMPLES.map((ex, i) => `
      <div class="card">
        <div class="row"><b class="grow">${esc(ex.title)}</b>
          <button class="primary" onclick="loadExample(${i})" data-tip="素材与设置自动填入新建任务表单">用这个示例</button></div>
        <p class="small muted">${esc(ex.desc)}</p>
        <p class="small">意图:${esc(ex.instruction)}</p>
        <details><summary class="small muted">查看素材</summary>
          <p class="small" style="white-space:pre-wrap">${esc(ex.material)}</p></details>
      </div>`).join("")}

    <p><a href="#/tasks/new"><button class="primary">开始写作 Start Writing</button></a></p>
  </div>`;
}

/* --------------------------------------------------------------- boot */
/* Global tooltip layer on <body> — never clipped or covered by containers. */
const TIP = document.createElement("div");
TIP.id = "tip";
document.body.appendChild(TIP);

function showTip(el) {
  const text = el.getAttribute("data-tip");
  if (!text) return;
  TIP.textContent = text;
  TIP.classList.add("show");
  const r = el.getBoundingClientRect();
  const tw = TIP.offsetWidth, th = TIP.offsetHeight;
  let top = r.top - th - 9;
  if (top < 6) top = r.bottom + 9;              // flip below when clipped at top
  let left = r.left + r.width / 2 - tw / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - tw - 8));
  TIP.style.top = top + "px";
  TIP.style.left = left + "px";
}
function hideTip() { TIP.classList.remove("show"); }

document.addEventListener("mouseover", e => {
  const el = e.target.closest("[data-tip]");
  if (el) showTip(el); else hideTip();
});
document.addEventListener("mouseout", e => {
  if (!e.relatedTarget || !e.relatedTarget.closest || !e.relatedTarget.closest("[data-tip]")) hideTip();
});
document.addEventListener("focusin", e => {
  const el = e.target.closest && e.target.closest("[data-tip]");
  if (el) showTip(el);
});
document.addEventListener("focusout", e => {
  if (!e.relatedTarget || !e.relatedTarget.closest || !e.relatedTarget.closest("[data-tip]")) hideTip();
});
document.addEventListener("keydown", e => {
  if ((e.key !== "Enter" && e.key !== " ") || e.target.matches("button,a,input,textarea,select")) return;
  const target = e.target.closest('[role="button"]');
  if (!target) return;
  e.preventDefault(); target.click();
});
document.addEventListener("click", hideTip);
window.addEventListener("scroll", hideTip, true);

window.addEventListener("beforeunload", () => {
  captureEditorContent();
  if (!WS.draft || !WS.dirty) return;
  try {
    fetch(`/drafts/${WS.draft.id}`, {
      method: "PATCH", keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ working_content: WS.draft.working_content }),
    });
  } catch (_) { /* unloading: best effort only */ }
});

const SCREENS = { home, quickWrite, reviseDraft, tasks, newTask, workspace, versions, projects, project, guide, settings };
route();
