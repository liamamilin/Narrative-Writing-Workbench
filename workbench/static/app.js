/* Narrative Writing Workbench — V0 SPA (no build step) */
"use strict";

/* ------------------------------------------------------------------ util */
const $ = (sel, el = document) => el.querySelector(sel);
const esc = s => (s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function api(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = data.error || { code: "NETWORK", message: r.statusText, retryable: false };
    throw e;
  }
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

/* ---------------------------------------------------------------- router */
const routes = [
  [/^#\/$/, "home"],
  [/^#\/quickwrite$/, "quickWrite"],
  [/^#\/revise$/, "reviseDraft"],
  [/^#\/tasks\/new$/, "newTask"],
  [/^#\/tasks\/([^/]+)$/, "workspace"],
  [/^#\/tasks\/([^/]+)\/versions$/, "versions"],
  [/^#\/projects$/, "projects"],
  [/^#\/projects\/([^/]+)$/, "project"],
  [/^#\/guide$/, "guide"],
  [/^#\/settings$/, "settings"],
];

function route() {
  const h = location.hash || "#/";
  for (const [re, name] of routes) {
    const m = h.match(re);
    if (m) {
      document.querySelectorAll("#topbar nav a").forEach(a =>
        a.classList.toggle("on", a.getAttribute("href") === h));
      Promise.resolve(SCREENS[name](...m.slice(1).map(decodeURIComponent)))
        .catch(e => toast(e.message || "Something went wrong.", true));
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", route);

/* ------------------------------------------------------------------ home */
async function home() {
  const [tasks, projects] = await Promise.all([api("GET", "/tasks"), api("GET", "/projects")]);
  $("#app").innerHTML = `
    <div class="hero">
      <h1>你想写点什么?</h1>
      <div class="entries">
        <a class="entry" href="#/quickwrite" data-tip="只有一个话题也行:系统先找到值得说的角度再写">
          <b>从一个话题开始</b>
          <span class="muted small">Turn a topic into a strong piece of writing</span></a>
        <a class="entry" href="#/tasks/new" data-tip="粘贴笔记、素材、观点,生成初稿">
          <b>从素材写起</b>
          <span class="muted small">Turn notes and sources into a draft</span></a>
        <a class="entry" href="#/revise" data-tip="贴入你的旧稿,只做局部修改,不重写全文">
          <b>改一篇旧稿</b>
          <span class="muted small">Revise without rewriting everything</span></a>
      </div>
      <div class="cta">
        <button onclick="newProjectPrompt()" data-tip="项目用来把相关素材与任务归堆(可选)">新建项目</button>
      </div>
    </div>
    <div class="cols">
      <section class="card"><h3>最近任务</h3>${
        tasks.tasks.length ? tasks.tasks.slice(0, 8).map(t => `
          <div class="vrow"><a class="grow" href="#/tasks/${t.id}">
            <b>${esc(t.title || t.topic || t.instruction.slice(0, 40) || "Untitled")}</b>
            <span class="muted small"> · ${esc(t.status)}</span></a>
            <a class="small" href="#/tasks/${t.id}" data-tip="在新标签页打开此任务">打开</a></div>`).join("")
        : `<p class="muted">还没有任务。从一个话题或一批素材开始。</p>`}
      </section>
      <section class="card"><h3>最近项目</h3>${
        projects.projects.length ? projects.projects.slice(0, 8).map(p => `
          <div class="vrow"><a class="grow" href="#/projects/${p.id}"><b>${esc(p.name)}</b></a>
          <a class="small" href="#/projects/${p.id}" data-tip="在新标签页打开此项目">打开</a></div>`).join("")
        : `<p class="muted">项目用于把相关素材与任务归堆(可选)。</p>`}
      </section>
    </div>`;
}

async function newProjectPrompt() {
  const name = prompt("项目名称:");
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

/* topic library + compose state persist client-side only; the server never
   stores suggestions, so "AI proposes, user accepts" stays untouched. */
const LIB_KEY = "qw_topic_lib_v1", COMPOSE_KEY = "qw_compose_v1", LIB_MAX = 200;
const loadLib = () => {
  try { return JSON.parse(localStorage.getItem(LIB_KEY) || "[]") || []; }
  catch { return []; }
};
const saveLib = lib => {
  try {
    localStorage.setItem(LIB_KEY, JSON.stringify(lib.slice(-LIB_MAX)));
  } catch { /* private mode: degrade to session-only */ }
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
    <section class="card qw-col qw-left">
      <h1 class="qw-title">从一个值得说的话题开始</h1>
      <p class="muted small qw-sub">左栏发现可争论的话题,点选填入右栏;开始写仍由你自己按下。</p>
      <input id="qw-tax-search" placeholder="🔍 搜索领域,如 教育 / 职场 / AI"
             data-tip="输入即过滤领域 chips">
      <span class="muted small qw-fld-label">领域 <span class="muted">(点选一个;选中的会高亮)</span></span>
      <div class="tax-row" id="qw-tax-domains" data-tip="点选一个领域;不限 = 全领域漫游"></div>
      <input id="qw-tax-hint" placeholder="方向提示(可选),如 关注外卖骑手 / 只看平台经济"
             data-tip="想聚焦时填;空着则按领域全面铺开">
      <p class="row">
        <button id="qw-topic-suggest" data-tip="右侧已输入话题时:围绕它生产 8 条不同切面;为空时:按领域铺开 8 条。再点会累加不重复的一批">✦ 生成一批话题</button>
        <span class="muted small" id="qw-tax-sel"></span></p>
      <div class="qw-lib-head">
        <h3>已生成话题 <span class="muted small" id="qw-lib-stats"></span></h3>
        <button class="ghost" id="qw-topic-clear" style="display:none"
                data-tip="清空整个话题库与去重记录">清空</button>
      </div>
      <div id="qw-lib"></div>
      <div id="qw-skel" style="display:none">
        <div class="qw-card qw-skel"></div><div class="qw-card qw-skel"></div>
        <div class="qw-card qw-skel"></div>
      </div>
    </section>
    <section class="card qw-col qw-right">
      <label>你要谈的话题</label>
      <textarea id="qw-topic" rows="3"
                placeholder="在这里写下话题,或点选左侧任意一条">${esc(saved.topic || "")}</textarea>
      <div class="chips" id="qw-ex">${QW_EXAMPLES.map(x =>
        `<button class="chip" data-tip="点击填入示例话题" data-v="${esc(x)}">${esc(x.slice(0, 18))}${x.length > 18 ? "…" : ""}</button>`).join("")}</div>
      <label>写作模式</label>
      <select id="qw-mode" data-tip="Deep Narrative=先体验后领悟、延迟解释、克制收束(旗舰模式);Clear Essay=观点清晰直给;Fiction=以故事呈现;Free Writing=放松随笔">
        <option value="deep_narrative" selected>Deep Narrative(推荐)</option>
        <option value="clear_essay">Clear Essay(观点直给)</option>
        <option value="fiction">Fiction(以故事呈现)</option>
        <option value="free_writing">Free Writing(放松随笔)</option>
      </select>
      <label>切入角度</label>
      <select id="qw-angle" data-tip="Auto Discover=系统找最有意义、最能推进的切入角度;不满意可生成后换">
        <option value="auto" selected>Auto Discover(自动发现)</option>
        <option value="custom">I have an angle in mind(自己定)</option>
      </select>
      <textarea id="qw-custom" rows="2" placeholder="你的角度 — 系统会提炼,不会替换。" style="display:none"></textarea>
      <div class="qw-duo">
        <div data-tip="正文目标字数,模型会在 ±20% 内调节">
          <span class="muted small">目标字数</span>
          <input id="qw-length" type="number" min="200" step="50" value="900"></div>
        <div data-tip="正文输出语言;auto = 跟随话题语言">
          <span class="muted small">语言</span>
          <select id="qw-lang"><option value="auto">auto</option><option value="zh">中文</option><option value="en">English</option></select></div>
      </div>
      <p class="row qw-cta">
        <button class="primary" id="qw-go" data-tip="先找意义,再写初稿;完成后进入工作台(⌘/Ctrl+Enter 同效)">开始写</button>
        <button onclick="location.hash='#/'">取消</button>
      </p>
      <p class="muted small">系统先找到值得说的角度与读者旅程,再动笔;写完进入同一工作台审阅修改。</p>
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
    saveComposeNow();
  };

  /* topic suggestion v5: domain chips -> batch generate -> grouped library
     (localStorage). Objects/tensions stay engine-internal resources. */
  const TX = { tax: null, domain: "", lib: loadLib(), selected: saved.topic || "" };
  const composeState = () => ({
    topic: $("#qw-topic").value, mode: $("#qw-mode").value,
    angle: $("#qw-angle").value, custom: $("#qw-custom").value,
    length: $("#qw-length").value, lang: $("#qw-lang").value });
  const saveComposeNow = () => saveCompose(composeState());
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
  const renderLib = (freshTs = 0, freshDomain = "") => {
    const lib = TX.lib;
    $("#qw-topic-clear").style.display = lib.length ? "" : "none";
    const doms = [...new Set(lib.map(t => t.domainName))];
    $("#qw-lib-stats").textContent =
      lib.length ? `${lib.length} 条 · ${doms.length} 个领域` : "";
    if (!lib.length) {
      $("#qw-lib").innerHTML = `<div class="qw-empty">还没有生成过话题。选个领域(或不限),
        点「✦ 生成一批话题」—— 每批 8 条,覆盖领域不同侧面;点任意一条填到右侧开始写。</div>`;
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
          <div class="qw-card${t.text === TX.selected ? " sel" : ""}${t.ts >= freshTs ? " fresh" : ""}" data-i="${i}">
            <b>${esc(t.text)}</b>
            <span class="sub">${esc(t.hook)}
              <button class="qw-del" data-i="${i}"
                      title="移除这条(${new Date(t.ts).toLocaleTimeString()})">✕</button></span>
          </div>`).join("")}</div>
      </details>`;
    }).join("");
  };
  $("#qw-lib").onclick = e => {
    const del = e.target.closest(".qw-del");
    if (del) {
      TX.lib.splice(+del.dataset.i, 1);
      saveLib(TX.lib);
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
    TX.selected = TX.lib[+card.dataset.i].text;
    $("#qw-topic").value = TX.selected;
    saveComposeNow();
    renderLib();
    $("#qw-topic").focus();
  };
  const seedNow = () => ($("#qw-topic").value || "").trim();
  const refreshSuggestBtn = () => {
    $("#qw-topic-suggest").textContent =
      seedNow() ? "✦ 围绕它生成一批" : "✦ 生成一批话题";
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
          avoid: TX.lib.map(t => t.text) });
      const now = Date.now(), dname = domainName(TX.domain);
      TX.lib = [...TX.lib, ...r.topics.map(t => ({
        domain: TX.domain, domainName: dname,
        text: t.text, hook: t.hook, ts: now }))];
      saveLib(TX.lib);
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
    TX.lib = []; saveLib(TX.lib); TX.selected = ""; renderLib();
  };
  renderLib();                 // empty-state guidance (no taxonomy needed)
  refreshSuggestBtn();         // now safe: defined above
  api("GET", "/taxonomy").then(t => {
    TX.tax = t; renderDomains();
  }).catch(() => {});
  $("#qw-angle").onchange = e => {
    $("#qw-custom").style.display = e.target.value === "custom" ? "" : "none";
    saveComposeNow();
  };
  $("#qw-topic").oninput = () => { saveComposeNow(); refreshSuggestBtn(); };
  $("#qw-mode").onchange = saveComposeNow;
  $("#qw-length").oninput = saveComposeNow;
  $("#qw-lang").onchange = saveComposeNow;
  $("#qw-topic").addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      $("#qw-go").click();
    }
  });
  $("#qw-go").onclick = async () => {
    const btn = $("#qw-go");
    const topic = $("#qw-topic").value.trim();
    if (!topic) { toast("先写下你想谈的话题。", true); return; }
    btn.disabled = true; btn.innerHTML = '<span class="spin"></span> 写作中…';
    try {
      const t = await api("POST", "/tasks", {
        input_mode: "topic_only", topic,
        title: topic.slice(0, 40),
        writing_mode: $("#qw-mode").value,
        angle_mode: $("#qw-angle").value,
        custom_angle: $("#qw-custom").value.trim(),
        config: { expected_language: $("#qw-lang").value,
                  target_length: parseInt($("#qw-length").value) || null },
      });
      const d = await api("GET", `/tasks/${t.id}`);
      if (d.factuality_warning &&
          !confirm("这个话题可能依赖具体事实。\n\n确定 = 用通用知识继续(文章不会假装引用来源)\n"
                   + "取消 = 进入该任务,可先添加素材做更紧的落地。")) {
        btn.disabled = false; btn.textContent = "开始写";
        location.hash = `#/tasks/${t.id}`;   // don't orphan the created task
        return;
      }
      saveComposeNow();
      AUTOSTART = t.id;
      location.hash = `#/tasks/${t.id}`;
    } catch (e) {
      toast(e.message || "Could not start.", true);
      btn.disabled = false; btn.textContent = "开始写";
    }
  };
}

function reviseDraft() {
  newTask("", "draft_revision");
}

/* ------------------------------------------------------------- new task */
const TASK_TYPES = [
  ["fiction_scene", "Fiction Scene", "写一个具体场景的小说片段(场景、动作、对话)"],
  ["narrative_analysis", "Narrative Analysis", "分析故事的叙事机制:视角、信息释放、推进"],
  ["character_analysis", "Character Analysis", "剖析一个人物:行为、动机、矛盾"],
  ["essay", "Essay", "观点性散文:论点要有推进与重量"],
  ["emotional_retelling", "Emotional Retelling", "带着情感重述一段事件/记忆"],
  ["free_writing", "Free Writing", "放松随笔,结构约束最弱"],
];

function newTask(projectId = "", mode = "source_grounded") {
  let chosenType = TASK_TYPES[0][0];
  const rev = mode === "draft_revision";
  $("#app").innerHTML = `
  <div class="form">
    <h1>${rev ? "Improve a draft" : "Write from material"}</h1>
    <div class="chips" id="types">${TASK_TYPES.map(([v, l, tip], i) =>
      `<button class="chip${i === 0 ? " on" : ""}" data-v="${v}" data-tip="${tip}">${l}</button>`).join("")}</div>
    <label>${rev ? "What should change?" : "What do you want this writing to do?"}</label>
    <textarea id="f-instruction" rows="3" placeholder="${rev ?
      "e.g. 结尾说教味太重,让最后一段只呈现画面。" : "e.g. 父亲不要直接表达支持。"}"></textarea>
    <label>${rev ? "Paste your draft" : "What should the writing be based on?"}</label>
    <textarea id="f-material" rows="7" placeholder="${rev ?
      "Paste the draft you want to improve…" : "Paste notes, scenes, sources…"}"></textarea>
    <div class="row">
      <input id="f-file" type="file" accept=".txt,.md" class="grow" data-tip="从 .txt/.md 文件载入素材,内容会填入下方素材框">
      <select id="f-project" class="grow" data-tip="可选:把任务归入某个项目"><option value="">No project</option></select>
    </div>
    <label>How should it read?</label>
    <div class="trio">
      ${[["immersion", "高=偏场景呈现,让读者“身临其境”;低=偏概述与说明"],
         ["explicitness", "高=主题直说;低=意义藏在画面里,靠读者推断(推荐低)"],
         ["intensity", "情绪与冲突的强度:高=浓烈,低=克制留白"]]
        .map(([k, tip]) => `
        <div data-tip="${tip}"><span class="muted small">${k[0].toUpperCase() + k.slice(1)}</span>
        <select id="f-${k}"><option>low</option><option${k !== "explicitness" ? " selected" : ""}>medium</option><option${k === "immersion" ? " selected" : ""}>high</option></select></div>`).join("")}
      <div data-tip="正文目标字数,模型会在 ±20% 内调节">
        <span class="muted small">Target length</span>
        <input id="f-length" type="number" min="100" step="50" value="800"></div>
      <div data-tip="正文输出语言;auto = 跟随你的素材/话题语言">
        <span class="muted small">Language</span>
        <select id="f-lang"><option value="auto">auto</option><option value="zh">中文</option><option value="en">English</option></select></div>
    </div>
    <label>Constraints</label>
    <div class="checks">
      <label data-tip="作为锁生效:修改时不得增删改素材中的事实"><input type="checkbox" id="c-facts" checked> Preserve facts</label>
      <label data-tip="作为锁生效:局部修改不得偷换文章的核心观点"><input type="checkbox" id="c-meaning" checked> Preserve core meaning</label>
      <label data-tip="提示生成与检查少做“把意义说破”的解释"><input type="checkbox" id="c-avoid" checked> Avoid over-explanation</label>
      <label data-tip="允许文学性细节,但不许编造改变故事走向的重大事件"><input type="checkbox" id="c-invent" checked> Do not invent major events</label>
    </div>
    <p class="row" style="margin-top:22px">
      <button class="primary" id="f-go" data-tip="创建任务并进入工作台">Create &amp; Write</button>
      <button onclick="location.hash='#/'">Cancel</button>
    </p>
  </div>`;
  $("#types").onclick = e => {
    const b = e.target.closest(".chip"); if (!b) return;
    chosenType = b.dataset.v;
    $("#types").querySelectorAll(".chip").forEach(x => x.classList.toggle("on", x === b));
  };
  (async () => {
    const ps = await api("GET", "/projects");
    $("#f-project").innerHTML += ps.projects.map(p =>
      `<option value="${p.id}"${p.id === projectId ? " selected" : ""}>${esc(p.name)}</option>`).join("");
  })();
  $("#f-file").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    $("#f-material").value = await f.text();
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
    toast("示例已填入,点 Create & Write 开始。");
  }
}

/* ------------------------------------------------------------- projects */
async function projects() {
  const ps = await api("GET", "/projects");
  $("#app").innerHTML = `<h1>Projects</h1>
    <p><button class="primary" onclick="newProjectPrompt()" data-tip="新建一个项目">New Project</button></p>` +
    (ps.projects.map(p => `<div class="card row">
      <a class="grow" href="#/projects/${p.id}"><b>${esc(p.name)}</b></a>
      <span class="muted small">${esc(p.updated_at)}</span></div>`).join("") ||
      '<p class="muted">No projects yet.</p>');
}

async function project(pid) {
  const p = await api("GET", `/projects/${pid}`);
  $("#app").innerHTML = `
    <h1>${esc(p.name)}</h1><p class="muted">${esc(p.description || "")}</p>
    <div class="row"><button class="primary" data-tip="为本项目新建写作任务" onclick="location.hash='#/tasks/new'">New Writing Task</button></div>
    <div class="cols">
      <section class="card"><h3>Tasks</h3>${p.tasks.map(t => `
        <div class="vrow"><a class="grow" href="#/tasks/${t.id}">
          <b>${esc(t.title || t.instruction.slice(0, 40) || "Untitled")}</b>
          <span class="muted small"> · ${esc(t.status)}</span></a></div>`).join("")
        || '<p class="muted">No tasks yet.</p>'}</section>
      <section class="card"><h3>Sources</h3>
        <div id="src-list">${p.sources.map(s => `
          <div class="srcitem"><b class="small">${esc(s.title)}</b>
          <span class="muted small"> · ${esc(s.type)}</span></div>`).join("")
        || '<p class="muted small">No sources.</p>'}</div>
        <label class="small muted" style="margin-top:10px">Add source (text)</label>
        <input id="src-title" data-tip="给这份素材起个名字" placeholder="Title">
        <textarea id="src-body" rows="4" placeholder="Paste material…"></textarea>
        <p><button id="src-add" data-tip="把素材存入本项目,供任务引用">Add Source</button></p></section>
    </div>`;
  $("#src-add").onclick = async () => {
    try {
      await api("POST", `/projects/${pid}/sources`, {
        title: $("#src-title").value || "Untitled",
        type: "pasted_text", content: $("#src-body").value });
      project(pid);
    } catch (e) { toast(e.message, true); }
  };
}

/* ------------------------------------------------------------- settings */
async function settings() {
  const [s, pr] = await Promise.all([api("GET", "/settings"), api("GET", "/settings/providers")]);
  const known = pr.providers.find(p => p.base_url && p.base_url === s.base_url);
  $("#app").innerHTML = `
  <div class="form" style="max-width:640px">
    <h1>Settings</h1>
    <p class="muted small">配置保存在本机 <code>workbench/settings.json</code>(仅本地,保存后立即生效,无需重启)。
    密钥只写入本地文件,接口永远不会回传完整密钥。</p>
    <label>引擎模式 Engine</label>
    <select id="s-engine" data-tip="mock=离线秒级体验界面;real=调用真实 LLM harness">
      <option value="real"${s.engine === "real" ? " selected" : ""}>real(真实引擎)</option>
      <option value="mock"${s.engine === "mock" ? " selected" : ""}>mock(离线演示)</option>
    </select>
    <label>API 服务商</label>
    <select id="s-provider" data-tip="选本地 Ollama / LM Studio 无需密钥">
      ${pr.providers.map(p => `<option value="${p.id}"${known && known.id === p.id ? " selected" : ""}${p.id === "custom" && !known ? " selected" : ""}>${esc(p.name)}</option>`).join("")}
    </select>
    <label>API Base URL</label>
    <input id="s-base" data-tip="OpenAI 兼容端点;选上方服务商可自动填入" value="${esc(s.base_url)}" placeholder="https://…/v1 或 http://127.0.0.1:11434/v1">
    <label>API Key</label>
    <input id="s-key" type="password" data-tip="仅保存在本机 settings.json,接口只回传掩码" placeholder="${s.has_key ? "已保存 " + esc(s.api_key_masked) + "(留空则不修改)" : "sk-…(本地 Ollama 可留空)"}">
    <label>模型 Model</label>
    <div class="row">
      <input id="s-model" class="grow" list="s-model-list" value="${esc(s.model)}" placeholder="选择或输入模型名" data-tip="下拉选常见模型;也可手填">
      <datalist id="s-model-list">${(known && known.models.length ? known.models : ["mimo-v2.5"]).map(m => `<option value="${esc(m)}">`).join("")}</datalist>
      <button id="s-fetch" data-tip="从该 Base URL 拉取可用模型列表(GET /models)">拉取模型</button>
    </div>
    <div class="trio" style="margin-top:10px">
      <div><span class="muted small">超时(秒)</span>
        <input id="s-timeout" type="number" min="30" step="30" value="${s.timeout_seconds || 150}" data-tip="单次 LLM 调用超时"></div>
      <div><span class="muted small">写作温度</span>
        <input id="s-temp" type="number" min="0" max="2" step="0.1" value="${s.writer_temperature ?? ""}" placeholder="0.7" data-tip="越高越发散,越低越克制(仅作用于正文写作)"></div>
    </div>
    <p class="row" style="margin-top:20px">
      <button class="primary" id="s-save" data-tip="保存并热切换引擎">Save</button>
      <button id="s-test" data-tip="用右侧当前填写的参数发一次最小请求,不保存">Test connection</button>
      <span id="s-result" class="small"></span>
    </p>
  </div>`;

  const PROVIDERS = pr.providers;
  const showResult = html => { $("#s-result").innerHTML = html; };
  let fetchSeq = 0;
  async function fetchModels(quiet = false) {
    const btn = $("#s-fetch");
    const my = ++fetchSeq;
    if (btn) { btn.disabled = true; btn.textContent = "拉取中…"; }
    try {
      const r = await api("POST", "/settings/models", {
        base_url: $("#s-base").value.trim(), api_key: $("#s-key").value.trim() });
      if (my !== fetchSeq) return;               // a newer fetch won
      if (r.ok && r.models.length) {
        $("#s-model-list").innerHTML = r.models.map(m => `<option value="${esc(m)}">`).join("");
        if (!r.models.includes($("#s-model").value)) $("#s-model").value = r.models[0];
        if (!quiet) showResult(`<span style="color:var(--accent)">✓ ${r.models.length} 个模型已载入下拉</span>`);
        else showResult(`<span class="muted">✓ 已自动载入 ${r.models.length} 个模型</span>`);
      } else if (!quiet) {
        showResult(`<span style="color:var(--warn)">✗ ${esc(r.error || "该端点没有返回模型列表")}</span>`);
      }
    } catch (e) { if (!quiet && my === fetchSeq) showResult(`<span style="color:var(--warn)">✗ ${esc(e.message)}</span>`); }
    finally { if (my === fetchSeq && btn) { btn.disabled = false; btn.textContent = "拉取模型"; } }
  }
  $("#s-provider").onchange = e => {
    const p = PROVIDERS.find(x => x.id === e.target.value);
    if (!p) return;
    if (p.id !== "custom") $("#s-base").value = p.base_url;
    const list = $("#s-model-list");
    list.innerHTML = (p.models.length ? p.models : ["deepseek-v4-flash"])
      .map(m => `<option value="${esc(m)}">`).join("");
    if (p.models.length && !p.models.includes($("#s-model").value))
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
        writer_temperature: $("#s-temp").value === "" ? null : parseFloat($("#s-temp").value),
      });
      toast(`已保存,引擎已切换为 ${r.engine}。`);
      settings();
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; }
  };
  $("#s-test").onclick = async () => {
    const btn = $("#s-test"); btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Testing…';
    showResult("");
    try {
      const r = await api("POST", "/settings/test", {
        base_url: $("#s-base").value.trim(),
        api_key: $("#s-key").value.trim(),
        model: $("#s-model").value.trim(),
      });
      if (r.ok) showResult(`<span style="color:var(--accent)">✓ 连通(${r.latency_seconds}s)</span>`);
      else showResult(`<span style="color:var(--warn)">✗ ${esc(r.error)}</span>`);
    } catch (e) { showResult(`<span style="color:var(--warn)">✗ ${esc(e.message)}</span>`); }
    finally { btn.disabled = false; btn.textContent = "Test connection"; }
  };
}

/* =============================================================== workspace */
const WS = {
  tid: null, task: null, draft: null, versions: [], sel: new Set(),
  panelTab: "goal", view: "draft", review: null, map: null,
  proposals: [], saveTimer: null, dirty: false,
};

async function workspace(tid) {
  WS.tid = tid; WS.sel.clear(); WS.proposals = []; WS.review = null; WS.map = null;
  await reloadTask();
  if (WS.task.status === "generating" && !GENERATING) {
    resumeInProgressGeneration();
    return;
  }
  renderWorkspace();
  if (AUTOSTART) {
    if (AUTOSTART === tid) {
      AUTOSTART = false;
      if (!WS.draft && WS.task.input_mode === "topic_only") generateDraft();
    } else AUTOSTART = false;   // navigated elsewhere first: drop, don't misfire
  }
}

async function reloadTask() {
  WS.task = await api("GET", `/tasks/${WS.tid}`);
  WS.draft = WS.task.draft;
  WS.dirty = false;
  WS.versions = WS.draft ? WS.task.draft.versions : [];
  WS.proposals = (WS.task.pending_patches || [])
    .filter(p => p.after);   // restorable after reload/refactor
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
  <div class="workspace">
    <section id="pane-left">
      <h3>Sources</h3><div id="sources"></div>
      <label class="small muted">Add source</label>
      <textarea id="add-src" rows="3" placeholder="Paste more material…"></textarea>
      <p class="small muted" style="margin-top:4px">粘贴更多素材(故事、笔记、观点),它会与原素材合并成 "Source Material",在下一次生成与检查时使用。</p>
      <p><button id="add-src-btn" class="small" data-tip="追加素材,将影响下一次生成或检查">Add</button></p>
    </section>
    <section id="pane-center">
      <div class="draft-head">
        <b id="doc-title">${esc(t.title || "Untitled")}</b>
        <span id="save-state" class="muted small"></span>
        <span class="grow"></span>
        <div class="tabs">
          <button id="tab-draft" class="${WS.view === "draft" ? "on" : ""}" data-tip="正文:点段落即可编辑,选段可发起局部修改">Draft</button>
          <button id="tab-map" class="${WS.view === "map" ? "on" : ""}" data-tip="只读:看每一步读者理解如何推进,点击定位段落">Writing Map</button>
        </div>
        <a class="small" href="#/tasks/${t.id}/versions" data-tip="所有历史版本:对比差异、恢复旧稿">Versions</a>
      </div>
      <div id="center-body"></div>
    </section>
    <section id="pane-right">
      <div class="panel-tabs">${[["goal", "目标与生成:改意图、调阅读体验、重新生成"],
        ["review", "检查:找出可能不工作的段落,由你决定修哪"],
        ["locks", "锁:约束每次修改,做不到就拒绝提案而非偷偷违反"],
        ["settings", "任务类型、状态与保存规则"]].map(([x, tip]) =>
        `<button data-t="${x}" class="${WS.panelTab === x ? "on" : ""}" data-tip="${tip}">${x[0].toUpperCase() + x.slice(1)}</button>`).join("")}</div>
      <div id="panel"></div>
    </section>
  </div>`;
  renderSources(); renderCenter(); renderPanel();
  $("#tab-draft").onclick = () => { WS.view = "draft"; renderWorkspace(); };
  $("#tab-map").onclick = async () => {
    try {
      const m = await api("GET", `/tasks/${WS.tid}/writing-map`);
      WS.map = m; WS.view = "map"; renderWorkspace();
    } catch (e) { toast(e.message || "No writing map available yet.", true); }
  };
  $("#add-src-btn").onclick = async () => {
    const body = $("#add-src").value.trim(); if (!body) return;
    try {
      await api("POST", `/tasks/${WS.tid}/sources`, { title: "Note", content: body });
      await reloadTask(); renderSources(); $("#add-src").value = "";
      toast("Source added — it will inform the next generation or review.");
    } catch (e) { toast(e.message, true); }
  };
  $("#pane-right").addEventListener("click", e => {
    const b = e.target.closest(".panel-tabs button"); if (!b) return;
    WS.panelTab = b.dataset.t; renderWorkspace();
  });
}

function renderSources() {
  $("#sources").innerHTML = WS.task.sources.map(s => `
    <div class="srcitem"><b class="small">${esc(s.title)}</b>
    <span class="muted small"> · ${esc(s.role)}</span>
    <div class="body">${esc(s.content)}</div></div>`).join("")
    || '<p class="muted small">No sources yet.</p>';
}

function renderCenter() {
  const box = $("#center-body");
  if (!WS.draft) {
    box.innerHTML = `<div class="card" style="text-align:center;padding:60px 20px">
      <p class="muted">Your draft will appear here.</p>
      <p><button class="primary" id="gen-now" data-tip="按你的意图与素材写第一稿(真实引擎约 2–4 分钟)">Generate Draft</button></p></div>`;
    $("#gen-now").onclick = generateDraft;
    return;
  }
  if (WS.view === "map") { box.innerHTML = mapView(); wireMap(); return; }
  box.innerHTML = `
    <div id="selbar">
      <button data-i="revise" data-tip="对选中段落写自定义修改指令">Revise</button>
      <button data-i="shorter" data-tip="压缩选中段落,保留要点">Shorter</button>
      <button data-i="less" data-tip="少说破:让画面自己说话,删去解释">Less Explicit</button>
      <button data-i="natural" data-tip="去掉翻译腔/做作措辞,更像人话">More Natural</button>
      <button data-i="immersive" data-tip="增强现场感:细节、动作、声音">More Immersive</button>
    </div>
    <div id="revise-box" style="display:none" class="card">
      <b class="small">Revise selection</b>
      <div class="chips" style="margin:8px 0">
        ${["More restrained", "More immersive", "More natural", "Less explicit", "Shorter"].map(x =>
          `<button class="chip preset" data-tip="点击填入这条修改指令">${x}</button>`).join("")}
      </div>
      <input id="revise-instr" placeholder="…or describe the revision you want">
      <div class="row" style="margin-top:8px">
        <label class="small" data-tip="本次修改是否受“核心意义锁”约束"><input type="checkbox" id="rv-meaning" checked> Preserve meaning</label>
        <label class="small" data-tip="本次修改是否受“事实锁”约束"><input type="checkbox" id="rv-facts" checked> Preserve facts</label>
        <span class="grow"></span>
        <button class="primary" id="revise-go" data-tip="生成 Before/After 提案,你 Accept 才会改动正文">Generate Patch</button>
        <button id="revise-cancel" data-tip="放弃本次修改,正文不动">Cancel</button>
      </div>
    </div>
    <div id="editor">${contentParas().map((p, i) =>
      `<div class="para${WS.sel.has(i + 1) ? " sel" : ""}" contenteditable="true" data-p="${i + 1}">${esc(p)}</div>`).join("")}</div>
    <div id="proposals">${WS.proposals.map(proposalCard).join("")}</div>`;
  wireEditor();
}

/* editor */
function wireEditor() {
  const ed = $("#editor");
  ed.addEventListener("input", () => {
    WS.dirty = true; setSave("Saving…");
    clearTimeout(WS.saveTimer);
    WS.saveTimer = setTimeout(saveDraft, 1200);
  });
  ed.addEventListener("click", e => {
    const p = e.target.closest(".para"); if (!p) return;
    const i = parseInt(p.dataset.p);
    if (e.shiftKey && WS.sel.size) {
      const a = Math.min(...WS.sel), b = Math.max(i, ...WS.sel);
      for (let k = a; k <= b; k++) WS.sel.add(k);
    } else if (e.metaKey || e.ctrlKey) {
      WS.sel.has(i) ? WS.sel.delete(i) : WS.sel.add(i);
    } else {
      const inside = window.getSelection().toString().length > 0;
      if (!inside) { WS.sel.clear(); WS.sel.add(i); }
    }
    ed.querySelectorAll(".para").forEach(x =>
      x.classList.toggle("sel", WS.sel.has(parseInt(x.dataset.p))));
    $("#selbar").classList.toggle("show", WS.sel.size > 0);
  });
  $("#selbar").querySelectorAll("button").forEach(b => {
    b.onclick = () => {
      if (b.dataset.i === "revise") {
        $("#revise-box").style.display = "block"; $("#revise-instr").focus();
      } else {
        proposePatch({ shorter: "Make this shorter.", less: "Make this less explicit.",
          natural: "Make this more natural.", immersive: "Make this more immersive." }[b.dataset.i]);
      }
    };
  });
  $("#revise-cancel").onclick = () => ($("#revise-box").style.display = "none");
  $("#revise-box").querySelectorAll(".preset").forEach(c =>
    c.onclick = () => ($("#revise-instr").value = c.textContent));
  $("#revise-go").onclick = () => proposePatch($("#revise-instr").value.trim());
}

async function saveDraft() {
  const content = [...$("#editor").querySelectorAll(".para")].map(x => x.textContent.trim())
    .filter(x => x.length).join("\n\n");
  try {
    const r = await api("PATCH", `/drafts/${WS.draft.id}`, { working_content: content });
    WS.draft.working_content = content;
    setSave("Saved");
  } catch (e) { setSave("Save failed"); toast(e.message, true); }
}
function setSave(s) { const el = $("#save-state"); if (el) el.textContent = s; }

/* patches */
function selRange() {
  const a = [...WS.sel].sort((x, y) => x - y);
  return { paragraph_start: a[0], paragraph_end: a[a.length - 1] };
}

async function proposePatch(instruction) {
  if (!instruction) { toast("Describe the revision you want.", true); return; }
  const locks = { ...(WS.task.config.locks || {}) };
  if ($("#rv-facts") && !$("#rv-facts").checked) locks.facts = false;
  if ($("#rv-meaning") && !$("#rv-meaning").checked) locks.core_meaning = false;
  const btn = $("#revise-go");
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Proposing…'; }
  try {
    const p = await api("POST", `/tasks/${WS.tid}/patch`, {
      base_version_id: WS.draft.current_version_id,
      selection: selRange(), instruction, locks,
    });
    p.instruction = instruction;
    WS.proposals.push(p);
    renderCenter();
  } catch (e) {
    toast(e.message, true);
  } finally { if (btn) btn.disabled = false; }
}

function proposalCard(p) {
  return `<div class="patch-card" data-id="${p.patch_id}">
    <b class="small">Suggested revision</b>
    <p class="small muted">${esc(p.instruction)}</p>
    <div class="ba"><div><div class="h">Before</div>${esc(p.before)}</div>
      <div><div class="h">After</div>${esc(p.after)}</div></div>
    <div class="row">
      <button class="primary act-accept" data-tip="只替换选中段落,并存为一个新版本">Accept</button>
      <button class="act-reject" data-tip="什么都不发生,正文原样保留">Reject</button>
      <button class="act-retry" data-tip="同一范围再提一版,直到你满意">Try Again</button></div></div>`;
}

document.addEventListener("click", async e => {
  const card = e.target.closest(".patch-card"); if (!card) return;
  const id = card.dataset.id;
  const prog = WS.proposals.find(x => x.patch_id === id);
  try {
    if (e.target.classList.contains("act-accept")) {
      await api("POST", `/patches/${id}/accept`);
      WS.proposals = WS.proposals.filter(x => x !== prog);
      await reloadTask(); renderWorkspace();
      toast("Accepted — new version saved.");
    } else if (e.target.classList.contains("act-reject")) {
      await api("POST", `/patches/${id}/reject`);
      card.remove();
      WS.proposals = WS.proposals.filter(x => x.patch_id !== id);
    } else if (e.target.classList.contains("act-retry")) {
      await proposePatch(prog.instruction);
    }
  } catch (err) { toast(err.message, true); }
});

/* panel */
function renderPanel() {
  const box = $("#panel"); const t = WS.task; const c = t.config;
  if (WS.panelTab === "goal") box.innerHTML = `
    ${WS.task.input_mode === "topic_only" && WS.meaning ? `
      <div class="meaning-card">
        <span class="muted small">What this piece is about</span>
        <b>${esc(WS.meaning.selected_angle)}</b>
        <p class="small">${esc(WS.meaning.core_question)}</p>
        <p class="small muted">Reader leaves with: ${esc(WS.meaning.reader_end_state)}</p>
      </div>` : ""}
    <label class="small muted" data-tip="你要这篇文字做到什么。它作为『写作指令』进入生成管线:同时指导结构设计与正文写作。">Intent</label>
    <textarea id="p-instr" rows="4">${esc(t.instruction)}</textarea>
    <p class="small muted" style="margin-top:4px">你要这篇文字做到什么?写下核心意思、语气和读者读完该带走什么。可留空,但写清意图,成稿更贴近你想要的效果。<br>
      示例:"情感要克制,不出现『想念』『温暖』这类总结词,让物件和动作承担情绪。"(小说场景)<br>
      或:"分析『英雄远行-归来』为什么反复打动观众,讲机制,不要罗列术语。"(叙事分析)</p>
    <p style="margin-top:8px"><button id="p-suggest" data-tip="让模型根据素材/话题与你现在的意图起草一版,再点『使用』填回(可先修改)。仅作为草稿,由你决定。">AI 帮我写/改进 Intent</button></p>
    <div id="suggest-out"></div>
    <div class="trio" style="margin-top:10px">
      ${[["immersion", "高=偏场景呈现,让读者“身临其境”;低=偏概述与说明"],
         ["explicitness", "高=主题直说;低=意义藏在画面里,靠读者推断"],
         ["intensity", "情绪与冲突的强度:高=浓烈,低=克制留白"]]
        .map(([k, tip]) => `
        <div data-tip="${tip}"><span class="muted small">${k}</span>
        <select id="p-${k}">${["low", "medium", "high"].map(x =>
          `<option${c[k] === x ? " selected" : ""}>${x}</option>`).join("")}</select></div>`).join("")}
    </div>
    <label class="small muted">Target length</label>
    <input id="p-len" type="number" value="${c.target_length || 800}" data-tip="正文目标字数,改后重新生成生效">
    <p style="margin-top:14px"><button class="primary" id="p-gen" style="width:100%"
      data-tip="${WS.draft ? "按当前意图与设置重写一稿(旧稿在 Versions 里永远可回)" : "按你的意图与素材写第一稿(真实引擎约 2–4 分钟)"}">
      ${WS.draft ? "Regenerate Draft" : "Generate Draft"}</button></p>
    ${WS.task.input_mode === "topic_only" && WS.draft ? `
      <p class="retry-row">
        <button id="p-another" style="flex:1" data-tip="重新寻找切入角度(避开用过的),并重写一篇">Try another angle</button>
        <button id="p-same" style="flex:1" data-tip="保留当前角度与核心意义,只重写表达">Rewrite this angle</button>
      </p>` : ""}
    <p><button id="p-check" style="width:100%" data-tip="把现在的正文存为手动版本,随时可回">Save Checkpoint</button></p>`;
  if (WS.panelTab === "review") box.innerHTML = `
    <p><button id="r-run" style="width:100%" data-tip="五个维度检查当前稿,问题卡片可一键定位或发起修改">Run Review</button></p>
    <div id="review-out">${WS.review ? reviewView(WS.review) :
      '<p class="muted small">Review finds passages that may not be working — you decide what to fix.</p>'}</div>`;
  if (WS.panelTab === "locks") box.innerHTML = `
    <p class="muted small">Locks constrain every revision. If a change can't respect
    them, the workbench refuses instead of silently rewriting.</p>
    ${[["facts", "Facts", "Do not alter source facts."],
       ["core_meaning", "Core Meaning", "Preserve the central interpretation."],
       ["character_logic", "Character Logic", "Preserve established character behavior."],
       ["structure", "Structure", "Keep the current progression."],
       ["wording", "Wording", "Keep successful phrasing."]].map(([k, n, d]) => `
      <div class="issue"><label class="row"><input type="checkbox" data-lock="${k}"
        ${c.locks[k] ? "checked" : ""}> <b>${n}</b></label>
        <div class="small muted">${d}</div></div>`).join("")}`;
  if (WS.panelTab === "settings") box.innerHTML = `
    <p class="small">Task: <b>${esc(t.type)}</b></p>
    <p class="small">Status: <b>${esc(t.status)}</b></p>
    <p class="small muted">Autosave creates no versions; versions appear only at
    generation, accepted revisions, checkpoints and restores.</p>`;

  if (WS.panelTab === "goal") {
    $("#p-gen").onclick = generateDraft;
    const another = $("#p-another"), same = $("#p-same");
    if (another) another.onclick = () => retryGeneration("rediscover-angle", "Trying another angle…");
    if (same) same.onclick = () => retryGeneration("regenerate", "Rewriting with the same angle…", { preserve_angle: true });
    $("#p-check").onclick = async () => {
      await saveDraft(); await api("POST", `/tasks/${WS.tid}/checkpoint`);
      await reloadTask(); toast("Checkpoint saved.");
    };
    $("#p-instr").onchange = async () => {
      await api("PATCH", `/tasks/${WS.tid}`, { instruction: $("#p-instr").value });
    };
    $("#p-suggest").onclick = suggestIntent;
  }
  if (WS.panelTab === "review") $("#r-run").onclick = runReview;
  if (WS.panelTab === "locks") {
    box.querySelectorAll("[data-lock]").forEach(cb => cb.onchange = async () => {
      const locks = { ...WS.task.config.locks };
      locks[cb.dataset.lock] = cb.checked;
      await api("PATCH", `/tasks/${WS.tid}`, { config: { locks } });
      WS.task.config.locks = locks;
      toast("Locks saved.");
    });
  }
}

/* AI intent suggestion (AI proposes, user accepts) */
const priorSuggestions = [];
async function suggestIntent() {
  const btn = $("#p-suggest");
  const label = btn ? btn.textContent : "AI 帮我写/改进 Intent";
  if (btn) { btn.disabled = true; btn.textContent = "生成中…"; }
  try {
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
      await api("PATCH", `/tasks/${WS.tid}`, { instruction: s });
      WS.task.instruction = s;
      out.innerHTML = "";
      toast("Intent 已更新,下次生成生效");
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
  queued: ["Queued", "排队中"],
  discovery: ["Finding something worth saying", "寻找值得说的意义"],
  structure: ["Designing the progression", "设计读者理解推进"],
  writing: ["Writing the draft", "撰写正文"],
  review: ["Reviewing", "检查中"],
};

function genBanner(on, stg, stgZh) {
  let b = $("#gen-banner");
  if (!on) { if (b) b.remove(); return; }
  const host = $("#center-body") || $("#pane-center");
  if (!host) return;
  host.insertAdjacentHTML("afterbegin",
    `<div class="card" id="gen-banner" style="padding:22px 26px">
      <p style="text-align:center"><span class="spin"></span> <b id="gb-title">Working…</b>
         <span class="muted small" id="gb-time">已用时 0 秒</span></p>
      <div id="gb-steps" class="steps"></div>
      <pre id="gb-live" class="live-text" style="display:none"></pre>
      <details id="gb-proc">
        <summary class="muted small">过程流 · 阶段摘要 <span id="gb-proc-n"></span></summary>
        <div id="gb-sums" class="sum-lines"></div>
        <p class="muted small" style="margin:8px 0 2px">
          <label><input type="checkbox" id="gb-dbg"
            data-tip="开启后,各阶段模型的原始输出(JSON)会逐 token 显示在下方;仅调试用,下次生成起生效">
            调试原始流 raw tokens<span class="muted">(下次生成起生效)</span></label></p>
        <div id="gb-raw"></div>
      </details>
    </div>`);
  const dbg = $("#gb-dbg");
  if (dbg) {
    api("GET", "/settings").then(s => { dbg.checked = !!s.stream_debug; })
      .catch(() => {});
    dbg.onchange = async () => {
      try {
        await api("POST", "/settings", { stream_debug: dbg.checked });
        toast(dbg.checked ? "调试原始流已开启 — 下次生成起生效。"
                          : "调试原始流已关闭。");
      } catch (e) { dbg.checked = !dbg.checked; toast(e.message, true); }
    };
  }
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
    if (st.error) ti.textContent = "Failed";
    else if (st.steps.length) {
      const last = st.steps[st.steps.length - 1];
      const lbl = STEP_LABELS[last] || [last, ""];
      ti.innerHTML = `${esc(lbl[0])} <span class="muted small">${esc(lbl[1])}</span>`;
    } else ti.textContent = "Working…";
  }
  const n = $("#gb-proc-n");
  if (n) n.textContent = st.sums.length ? `(${st.sums.length})` : "";
  const su = $("#gb-sums");
  if (su) su.innerHTML = st.sums.map(s => {
    const lbl = STEP_LABELS[s.stage] || [s.stage, ""];
    return `<div class="sum-line"><b>${esc(lbl[1] || lbl[0])}</b> ${esc(s.text)}</div>`;
  }).join("");
  const rw = $("#gb-raw");
  if (rw) {
    const stages = Object.keys(st.raw);
    rw.innerHTML = stages.map(s =>
      `<div class="raw-lbl">${esc((STEP_LABELS[s] || [s, ""])[1] || s)}</div>
       <pre class="raw-pane" id="raw-${esc(s)}">${esc(st.raw[s])}</pre>`).join("");
    stages.forEach(s => {
      const p = document.getElementById("raw-" + s);
      if (p) p.scrollTop = p.scrollHeight;
    });
  }
}

function stepsView(steps, angle, errMsg) {
  const rows = steps.map((s, i) => {
    const [en, zh] = STEP_LABELS[s] || [s, ""];
    const active = i === steps.length - 1 && !angle && !errMsg;
    return `<div class="step${active ? " act" : " ok"}">
      ${active ? '<span class="spin"></span>' : "✓"} ${esc(en)}
      <span class="muted small">${esc(zh)}</span></div>`;
  }).join("");
  const a = angle ? `<div class="step angle">✦ <b>${esc(angle)}</b></div>` : "";
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
    if (st.error) ti.textContent = "Failed";
    else if (st.steps.length) {
      const last = st.steps[st.steps.length - 1];
      const lbl = STEP_LABELS[last] || [last, ""];
      ti.innerHTML = `${esc(lbl[0])} <span class="muted small">${esc(lbl[1])}</span>`;
    } else ti.textContent = "Working…";
  }
}

function genFailureCard(errMsg, endpoint, body, okMsg) {
  const host = $("#center-body") || $("#app");
  host?.insertAdjacentHTML?.("afterbegin",
    `<div class="card" style="border-color:var(--warn)">
      <b style="color:var(--warn)">生成失败 — 你的现有正文没有被改动</b>
      <p class="small">${esc(errMsg || "The draft could not be generated correctly.")}</p>
      <button class="primary" id="gen-retry" data-tip="再试一次;现有正文与历史版本不受影响">重试 Retry</button></div>`);
  const r = $("#gen-retry");
  if (r) r.onclick = () => runGeneration(
    endpoint || "generate", body || {},
    okMsg || "Draft ready — 第一稿已生成。");
}

function openProgress(tid, onUpdate, onEnd) {
  let es;
const state = { steps: [], angle: "", error: "", live: "", shown: "",
                  seq: -1, sums: [], raw: {} };
  let ended = false;
  const finish = (errMsg) => {
    if (ended) return;
    ended = true;
    if (errMsg) state.error = errMsg;
    clearInterval(iv);
    es.close();
    if (onEnd) onEnd(errMsg || null);
  };
  try { es = new EventSource(`/tasks/${tid}/progress`); }
  catch (e) { return { close() {}, alive: () => false }; }
  const push = () => onUpdate(state);
  // Reconnect safety: the server replays full history from seq 0 after any
  // EventSource reconnect; without seq dedupe the live text doubles.
  const handle = (kind, fn) => es.addEventListener(kind, ev => {
    let e; try { e = JSON.parse(ev.data); } catch (_) { return; }
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
    onUpdate(state);
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
  es.addEventListener("done", () => finish(null));
  es.addEventListener("eof", () => finish(null));
  return {
    close() { clearInterval(iv); es.close(); },
    alive: () => state.steps.length > 0,
  };
}

function collectPanelParams() {
  const g = (id) => $(id);
  const p = {};
  if (g("#p-instr")) p.instruction = g("#p-instr").value;
  for (const k of ["immersion", "explicitness", "intensity"])
    if (g(`#p-${k}`)) p[k] = g(`#p-${k}`).value;
  if (g("#p-len")) {
    const n = parseInt(g("#p-len").value, 10);
    if (Number.isFinite(n)) p.target_length = n;
  }
  return p;
}

async function generateDraft() {
  if (GENERATING) return;
  if (WS.draft && !confirm("Generate a new draft? Your current draft stays safe in version history."))
    return;
  await runGeneration("generate", collectPanelParams(), "Draft ready — 第一稿已生成。");
}

async function retryGeneration(endpoint, label, body) {
  if (GENERATING) return;
  if (!confirm("Your current draft stays safe in version history.继续?")) return;
  await runGeneration(endpoint, { ...collectPanelParams(), ...(body || {}) },
                      label.replace("…", "") + " — done.");
}

async function flushAutosave() {
  // Persist any in-flight editor text before a destructive generation, and
  // snapshot it as a checkpoint so "your draft is safe in version history"
  // is actually true for edits made since the last version.
  clearTimeout(WS.saveTimer); WS.saveTimer = null;
  if (!WS.draft) return;
  if (WS.dirty) { await saveDraft(); WS.dirty = false; }
  try { await api("POST", `/tasks/${WS.tid}/checkpoint`); } catch (e) { /* non-fatal */ }
}

async function runGeneration(endpoint, body, okMsg) {
  const myTid = WS.tid;
  GENERATING = true;
  WS.panelTab = "goal";
  if (!WS.draft) renderWorkspace();
  const [STG, STG_ZH] = stagesForTask();
  genBanner(true);
  const btns = [$("#p-gen"), $("#gen-now"), $("#p-another"), $("#p-same"),
                $("#r-run")].filter(Boolean);
  btns.forEach(b => { b.disabled = true; });
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
    if (time) time.textContent = `已用时 ${Math.round((Date.now() - t0) / 1000)} 秒`;
  }, 1000);
  const stillHere = () => WS.tid === myTid;
  try {
    await api("POST", `/tasks/${myTid}/${endpoint}`, body);
    if (!stillHere()) { toast("Generation finished — open the task to view it."); }
    else {
      await reloadTask();
      WS.view = "draft"; renderWorkspace();
      toast(okMsg);
    }
  } catch (e) {
    if (!stillHere()) { toast(e.message || "Generation failed.", true); }
    else {
      renderWorkspace();  // clears banner, redraws current draft intact
      genFailureCard(e.message, endpoint, body, okMsg);
      toast(e.message || "Generation failed — your current draft is unchanged.", true);
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
  let i = 0, t0 = Date.now();
  const stillHere = () => WS.tid === myTid;
  const prog = openProgress(myTid, renderProgressState, (errMsg) => {
    prog.close();
    clearInterval(timer); clearInterval(tick);
    GENERATING = false;
    if (!stillHere()) { genBanner(false); toast(errMsg || "Generation finished.", true); return; }
    genBanner(false);
    reloadTask().then(() => {
      WS.view = "draft";
      renderWorkspace();
      if (errMsg) {
        genFailureCard(errMsg);
        toast(errMsg || "Generation failed.", true);
      } else {
        toast("Generation finished — 生成完成。");
      }
    }).catch(e => toast(e.message || "Reload failed.", true));
  });
  const timer = setInterval(() => {
    if (prog.alive()) return;             // real events win; rotate only as fallback
    i = Math.min(i + 1, STG.length - 1);
    const ti = $("#gb-title");
    if (ti) ti.innerHTML = `${STG[i]} <span class="muted small">${STG_ZH[i]}</span>`;
  }, 9000);
  const tick = setInterval(() => {
    const time = $("#gb-time");
    if (time) time.textContent = `已用时 ${Math.round((Date.now() - t0) / 1000)} 秒`;
  }, 1000);
}

/* review */
async function runReview() {
  if (GENERATING) { toast("Generation is already running.", true); return; }
  const btn = $("#r-run"); btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Reviewing…';
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
    WS.review = await api("POST", `/tasks/${WS.tid}/review`);
  } catch (e) { toast(e.message, true); WS.review = null; }
  finally {
    prog.close(); clearInterval(tick); genBanner(false);
    btn.disabled = false; genBtns.forEach(b => { b.disabled = false; });
    renderPanel();
  }
}

function reviewView(r) {
  return `<div class="row" style="flex-wrap:wrap">${Object.entries(r.summary).map(([k, v]) =>
    `<span class="small">${k}</span> <span class="label ${v}">${v.replace("_", " ")}</span>`).join(" ")}</div>` +
    (r.issues.length ? r.issues.map((is, n) => `
      <div class="issue"><p class="small">${esc(is.message)}</p>
      <p class="loc">¶${is.location.paragraph_start}${is.location.paragraph_end !== is.location.paragraph_start ? "–" + is.location.paragraph_end : ""}</p>
      <div class="row"><button class="small" data-show="${n}" data-tip="跳到并高亮对应段落">Show</button>
      ${is.fixable ? `<button class="small" data-fix="${n}" data-tip="对该段落直接发起局部修改提案">Fix</button>` : ""}</div></div>`).join("")
      : '<p class="muted small">No issues flagged.</p>');
}

document.addEventListener("click", async e => {
  const show = e.target.closest("[data-show]");
  const fix = e.target.closest("[data-fix]");
  if (!show && !fix) return;
  const is = WS.review.issues[parseInt((show || fix).dataset.show ?? (show || fix).dataset.fix)];
  WS.view = "draft"; renderWorkspace();
  const a = is.location.paragraph_start, b = is.location.paragraph_end;
  for (let k = a; k <= b; k++) WS.sel.add(k);
  renderCenter();
  const el = $(`.para[data-p="${a}"]`);
  if (el) { el.classList.add("hl"); el.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => el.classList.remove("hl"), 2600); }
  if (fix) proposePatch(is.message);
});

/* writing map */
function mapView() {
  const beats = (WS.map && WS.map.beats) || [];
  return `<p class="muted small">See how the reader's understanding changes through the draft.</p>` +
    (beats.length ? beats.map((b, i) => `
      <div class="beat" data-a="${b.paragraph_start}" data-b="${b.paragraph_end}">
        <div class="t">Step ${i + 1} · ${esc(b.function)}</div>
        <div class="small arrow">${esc(b.reader_before)} → ${esc(b.reader_after)}</div>
        <div class="small muted">${esc(b.meaning_gain)}</div>
        ${b.paragraph_start ? `<div class="small muted">¶${b.paragraph_start}${b.paragraph_end !== b.paragraph_start ? "–" + b.paragraph_end : ""}</div>` : ""}
      </div>`).join("")
      : '<div class="card"><p class="muted">No writing map yet — generate a draft first.</p></div>');
}
function wireMap() {
  $("#center-body").querySelectorAll(".beat").forEach(el => el.onclick = () => {
    const a = parseInt(el.dataset.a), b = parseInt(el.dataset.b);
    if (!a) return;
    WS.view = "draft"; renderWorkspace();
    for (let k = a; k <= b; k++) WS.sel.add(k);
    renderCenter();
    const p = $(`.para[data-p="${a}"]`);
    if (p) { p.classList.add("hl"); p.scrollIntoView({ behavior: "smooth", block: "center" });
      setTimeout(() => p.classList.remove("hl"), 2600); }
  });
}

/* ------------------------------------------------------------- versions */
async function versions(tid) {
  const task = await api("GET", `/tasks/${tid}`);
  if (!task.draft) { $("#app").innerHTML = '<p class="muted">No draft yet.</p>'; return; }
  const vs = await api("GET", `/drafts/${task.draft.id}/versions`);
  const rows = vs.versions.slice().reverse();            // newest first
  const cont = new Map();                                // id -> full content (lazy)
  const open = new Set();                                // expanded ids
  const sel = [];                                        // selected ids (max 2)
  const curId = task.draft.current_version_id;
  const byId = new Map(rows.map(v => [v.id, v]));
  const shortId = id => (id.length > 12 ? "…" + id.slice(-6) : id);
  const short = s => {
    const t = (s || "").replace(/\s+/g, " ").trim();
    return t.length > 160 ? t.slice(0, 160) + "…" : (t || "(empty)");
  };

  $("#app").innerHTML = `
    <h1>Version History</h1>
    <p class="muted small">点行选中最多两个版本自动出对比;点正文预览展开/收起全文;Restore 恢复本身也是新版本,永远可再反悔。</p>
    <div id="vlist">${rows.map(rowHtml).join("")}</div>
    <div id="vctrl"><p class="muted small">未选择:点任意版本行开始选择对比。</p></div>
    <div id="compare"></div>
    <p style="margin-top:10px"><a href="#/tasks/${tid}">Back to draft</a></p>`;

  function rowHtml(v) {
    const isCur = v.id === curId;
    const instr = v.instruction
      ? ` · <span class="muted small">"${esc(v.instruction)}"</span>` : "";
    return `
    <div class="vrow${isCur ? " cur" : ""}" data-v="${v.id}">
      <span class="vpick"></span>
      <div class="grow">
        <div class="vhead"><b>${esc(v.origin)}</b><span class="muted small">· ${esc(v.created_at)} · ${esc(shortId(v.id))}${instr}</span>${isCur ? '<span class="vtag">当前</span>' : ""}</div>
        <div class="vprev" data-v="${v.id}">载入预览…</div>
      </div>
      <div class="vacts">
        ${isCur ? "" : `<button class="small va-cur" data-v="${v.id}" data-tip="对比此版本与当前草稿">vs 当前</button>`}
        <button class="small va-restore" data-v="${v.id}" data-tip="恢复此版本为当前草稿(恢复本身也是新版本,可再反悔)">Restore</button>
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
      c.innerHTML = `<p class="row"><span class="vtag">旧版</span> <b>${esc(a.origin)}</b>
        <span class="muted small">${esc(shortId(aId))}</span> <span class="muted">→</span>
        <span class="vtag">新版</span> <b>${esc(b.origin)}</b>
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
      <div><div class="h muted">旧版 · ${esc(a.origin)}</div>${diffHtml(cont.get(aId), cont.get(bId))}</div>
      <div><div class="h muted">新版 · ${esc(b.origin)}</div>${diffHtml(cont.get(bId), cont.get(aId), true)}</div></div>`;
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
  document.querySelectorAll(".va-restore").forEach(b => b.onclick = async () => {
    if (!confirm("把此版本恢复为当前草稿?(恢复会生成一个新版本,之前的当前状态仍保留在历史里)")) return;
    try {
      await api("POST", `/versions/${b.dataset.v}/restore`);
      toast("Restored — the previous state is kept as its own version.");
      versions(tid);
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

    <h2>✦ Quick Write:只有一个想法时</h2>
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
      单击段落=选中,Shift 单击=扩选多段,⌘/Ctrl 单击=加选/取消。</p>
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
document.addEventListener("click", hideTip);
window.addEventListener("scroll", hideTip, true);

/* Open every in-app link in a new tab (user preference). Modifier clicks
   (⌘/ctrl/shift) keep native behavior. */
document.addEventListener("click", e => {
  const a = e.target.closest('a[href^="#/"]');
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  window.open(a.href, "_blank");
});

const SCREENS = { home, quickWrite, reviseDraft, newTask, workspace, versions, projects, project, guide, settings };
route();
