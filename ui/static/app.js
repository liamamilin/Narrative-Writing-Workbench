/* ============ Narrative Writing Harness UI ============ */
const $ = (s, el = document) => el.querySelector(s);
const main = () => $("#main");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  return r.json();
};
const post = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const DIMS = [
  ["immersion", "沉浸感"], ["progression", "推进感"], ["meaning_density", "意义密度"],
  ["restraint", "克制"], ["coherence", "连贯性"], ["naturalness", "自然度"],
  ["overall", "综合"],
];
const prose = (t) => (t || "").split(/\n{2,}/).map((p) => `<p>${esc(p.trim())}</p>`).join("");
const badge = (status) => {
  const map = { success: "b-green", pass: "b-green", PASS: "b-green", fail: "b-red", PATCH_REQUIRED: "b-amber", REWRITE_REQUIRED: "b-red", unknown: "b-gray" };
  return `<span class="badge ${map[status] || "b-ink"}">${esc(status ?? "-")}</span>`;
};
const fmtTime = (t) => (t ? t.replace("T", " ").slice(5, 16) : "-");
const wq = (v) => (v == null ? "-" : v);

/* ---------------- router ---------------- */
const routes = {};
async function route() {
  const hash = location.hash.slice(2) || "overview";
  const parts = hash.split("/");
  document.querySelectorAll("#nav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.route === parts[0]));
  main().innerHTML = '<div class="loading">载入中…</div>';
  try { await routes[parts[0]](parts[1], parts[2]); }
  catch (e) { main().innerHTML = `<div class="page-title">出错了</div><div class="doc mt"><div class="diff del">${esc(e.message)}</div></div>`; }
}
window.addEventListener("hashchange", route);

/* ---------------- overview ---------------- */
routes.overview = async () => {
  const [{ runs }, { benchmarks }] = await Promise.all([api("/api/runs"), api("/api/benchmarks")]);
  const ok = runs.filter((r) => r.status === "success").length;
  const wqs = runs.map((r) => r.wq).filter((v) => v != null);
  const avg = wqs.length ? (wqs.reduce((a, b) => a + b, 0) / wqs.length).toFixed(1) : "-";
  const pending = benchmarks.reduce((a, b) => a + b.pending, 0);
  main().innerHTML = `
    <div class="page-title">总览</div>
    <div class="page-sub">Input → Architect → WIR → Writer → Critic → (Patcher) → Final</div>
    <div class="cards">
      <div class="card"><div class="k">运行 RUNS</div><div class="v">${runs.length}</div></div>
      <div class="card"><div class="k">成功率 SUCCESS</div><div class="v">${runs.length ? Math.round((ok / runs.length) * 100) : 0}<small>%</small></div></div>
      <div class="card"><div class="k">平均 WQ</div><div class="v">${avg}</div></div>
      <div class="card"><div class="k">待盲评 PENDING</div><div class="v">${pending}</div></div>
    </div>
    <div class="mb" style="font-weight:600;font-size:14px">最近运行 Recent Runs</div>
    ${runsTable(runs.slice(0, 8))}`;
};

function runsTable(runs) {
  if (!runs.length) return '<div class="doc muted">暂无运行记录,去「新建运行」跑第一条。</div>';
  return `<table><tr><th>RUN</th><th>时间</th><th>状态</th><th>Critic</th><th>WQ</th><th>Patched</th></tr>
    ${runs.map((r) => `<tr class="click" onclick="location.hash='#/run/${r.run_id}'">
      <td><b>${r.run_id}</b></td><td class="muted">${fmtTime(r.timestamp)}</td>
      <td>${badge(r.status)}</td><td>${badge(r.decision)}</td>
      <td>${wq(r.wq)}<span class="muted">/30</span></td>
      <td>${r.patched ? '<span class="badge b-amber">是</span>' : '<span class="muted">—</span>'}</td>
    </tr>`).join("")}</table>`;
}

/* ---------------- runs list ---------------- */
routes.runs = async () => {
  const { runs } = await api("/api/runs");
  main().innerHTML = `
    <div class="page-title">运行记录</div>
    <div class="page-sub">共 ${runs.length} 条 · 点击查看详情</div>
    ${runsTable(runs)}`;
};

/* ---------------- run detail ---------------- */
routes.run = async (id) => {
  const r = await api(`/api/runs/${id}`);
  if (r.error) { main().innerHTML = `<div class="doc">${esc(r.error)}</div>`; return; }
  const m = r.metadata || {}, c = r.critique || {};
  main().innerHTML = `
    <div class="page-sub"><a class="link" href="#/runs">← 运行记录</a></div>
    <div class="page-title">Run ${esc(id)}</div>
    <div class="cards" style="margin-top:16px">
      <div class="card"><div class="k">状态</div><div>${badge(m.status)}</div></div>
      <div class="card"><div class="k">Critic 决定</div><div>${badge(c.decision)}</div></div>
      <div class="card"><div class="k">WQ</div><div class="v">${wq(sumQ(c))}<small>/30</small></div></div>
      <div class="card"><div class="k">Patched</div><div class="v" style="font-size:20px">${m.patched ? "✔ 是" : "—"}</div></div>
      <div class="card"><div class="k">耗时 / Tokens</div><div class="v" style="font-size:20px">${m.usage ? Math.round(m.usage.latency_seconds) + "s" : "-"}<small>${m.usage ? " · in " + m.usage.input_tokens + " / out " + m.usage.output_tokens : ""}</small></div></div>
    </div>
    <div class="tabs" id="tabs"></div><div id="tabbody"></div>`;
  const tabs = [
    ["终稿 Final", () => docTab(r.final)],
    ["输入 Input", () => `<div class="doc"><div class="kv"><b>任务类型</b>${esc(r.input?.task_type)}<br><b>指令</b>${esc(r.input?.instruction)}</div><div class="mt"><div class="k muted mb" style="font-size:12px">素材 MATERIAL</div><div class="prose">${prose(r.input?.material)}</div></div></div>`],
    ["WIR 意图结构", () => wirTab(r.wir)],
    ["草稿 Draft", () => docTab(r.draft)],
    ["评审 Critique", () => critiqueTab(c)],
    ["修改对比 Diff", () => diffTab(r.draft, r.final)],
  ];
  const tabsEl = $("#tabs");
  tabsEl.innerHTML = tabs.map((t, i) => `<button class="${i === 0 ? "on" : ""}">${t[0]}</button>`).join("");
  const body = $("#tabbody");
  body.innerHTML = tabs[0][1]();
  tabsEl.querySelectorAll("button").forEach((b, i) =>
    b.onclick = () => {
      tabsEl.querySelectorAll("button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on"); body.innerHTML = tabs[i][1]();
    });
};
const docTab = (text) => `<div class="doc prose">${prose(text) || '<span class="muted">(空)</span>'}</div>`;
const sumQ = (c) => { const q = c.quality || {}; const ks = Object.keys(q); return ks.length ? Object.values(q).reduce((a, b) => a + b, 0) : null; };

function wirTab(w) {
  if (!w) return '<div class="doc muted">无 WIR</div>';
  const beats = (w.beats || []).map((b, i) => `
    <div class="beat">
      <div class="beat-rail"><div class="beat-dot">${i + 1}</div>${i < w.beats.length - 1 ? '<div class="beat-line"></div>' : ""}</div>
      <div class="beat-body">
        <div class="beat-state">${esc(b.start_state)} <b>→</b> ${esc(b.end_state)}</div>
        <div class="beat-detail"><span class="tag">触发</span>${esc(b.trigger)}<br><span class="tag">操作</span>${esc(b.operation)}${b.reveal ? `<br><span class="tag">揭示</span><span class="chip red">${esc(b.reveal)}</span>` : ""}</div>
      </div>
    </div>`).join("");
  return `<div class="doc">
    <div class="kv"><b>意义内核</b>${esc(w.meaning)}<br><b>读者状态</b>${esc(w.reader_state)}<br><b>视角</b>${esc(w.perspective)}</div>
    ${w.devices?.length ? `<div class="mt mb"><b class="muted" style="font-size:12px">手法 DEVICES</b><div class="chips">${w.devices.map((d) => `<span class="chip">${esc(typeof d === "string" ? d : (d.name || JSON.stringify(d)))}</span>`).join("")}</div></div>` : ""}
    <div class="mt" style="font-weight:600;font-size:13.5px;margin-bottom:14px">节拍 BEATS · 读者状态转移</div>${beats}</div>`;
}

function critiqueTab(c) {
  if (!c || !c.decision) return '<div class="doc muted">无评审结果</div>';
  const q = c.quality || {};
  const issues = (c.issues || []).map((i) => `
    <div class="issue sev-${esc(i.severity)}">
      <div style="display:flex;gap:10px;align-items:center;margin-bottom:5px">
        <span class="badge ${i.severity === "high" ? "b-red" : i.severity === "moderate" ? "b-amber" : "b-gray"}">${esc(i.severity)}</span>
        <b style="font-size:13.5px">${esc(i.diagnosis?.type || i.type || "")}</b>
        <span class="issue-loc">${esc(i.location || "")}</span></div>
      <div class="muted" style="font-size:12.5px;line-height:1.7">${esc(i.diagnosis?.evidence || i.evidence || "")}${i.action ? "<br><b>建议:</b>" + esc(i.action) : ""}</div>
    </div>`).join("") || '<div class="muted">无问题</div>';
  return `
    <div class="qgrid">${Object.entries(q).map(([k, v]) => `<div class="qcell"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join("")}</div>
    <div class="mb" style="font-weight:600;font-size:13.5px">问题 ISSUES (${(c.issues || []).length})</div>${issues}
    <div class="mt mb" style="font-weight:600;font-size:13.5px">保留清单 PRESERVE</div>
    <div class="chips mb">${(c.preserve || []).map((p) => `<span class="chip green">${esc(p)}</span>`).join("") || '<span class="muted">—</span>'}</div>
    <div class="mb" style="font-weight:600;font-size:13.5px">修补目标 PATCH TARGETS</div>
    <div class="chips">${(c.patch_targets || []).map((p) => `<span class="chip red">${esc(p)}</span>`).join("") || '<span class="muted">—</span>'}</div>`;
}

function diffTab(draft, final) {
  if (!draft || !final) return '<div class="doc muted">草稿与终稿相同或不存在(未触发 Patcher)</div>';
  const a = draft.split("\n"), b = final.split("\n");
  const out = []; let n = 0, del = 0, add = 0;
  const sm = similarityLines(a, b);
  // simple LCS-based line diff
  const diff = lcsDiff(a, b);
  for (const [t, line] of diff) {
    if (t === "-") { out.push(`<span class="del">- ${esc(line)}</span>`); del++; }
    else if (t === "+") { out.push(`<span class="add">+ ${esc(line)}</span>`); add++; }
    else { out.push(`<span class="ctx">&nbsp;&nbsp;${esc(line)}</span>`); n++; }
  }
  return `<div class="muted mb">未触发 Patcher 时草稿即终稿 · 保留 ${n} 行,删除 ${del},新增 ${add}</div>
    <div class="doc diff">${out.join("\n")}</div>`;
}
function similarityLines() { return 0; }
function lcsDiff(a, b) {
  const m = a.length, n = b.length;
  const dp = Array.from({ length: m + 1 }, () => new Uint16Array(n + 1));
  for (let i = m - 1; i >= 0; i--) for (let j = n - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) { out.push(["=", a[i]]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push(["-", a[i]]); i++; }
    else { out.push(["+", b[j]]); j++; }
  }
  while (i < m) out.push(["-", a[i++]]);
  while (j < n) out.push(["+", b[j++]]);
  return out;
}

/* ---------------- new run ---------------- */
routes.new = async () => {
  main().innerHTML = `
    <div class="page-title">新建运行</div>
    <div class="page-sub">完整管线:Architect → Writer → Critic →(可选 Patcher)。约需 2–10 分钟,取决于网关负载。</div>
    <div class="form">
      <label class="f">素材 Material(原文片段)</label>
      <textarea id="material" class="mono" placeholder="粘贴素材文本…"></textarea>
      <label class="f">写作指令 Instruction</label>
      <textarea id="instruction" style="min-height:80px" placeholder="例:写一段叙事分析,解释这种结构为什么会产生宿命感。不要增加新的情节事实。"></textarea>
      <label class="f">任务类型 Task Type</label>
      <select id="tasktype">
        <option value="narrative_commentary">narrative_commentary 叙事评析</option>
        <option value="character_sketch">character_sketch 人物素描</option>
        <option value="scene_rewrite">scene_rewrite 场景改写</option>
      </select>
      <div class="mt"><button class="btn" id="go">▶ 开始运行</button>
      <span class="hint" id="msg">需要服务端已配置 OPENAI_API_KEY</span></div>
      <div id="prog"></div>
    </div>`;
  $("#go").onclick = async () => {
    const body = { material: $("#material").value, instruction: $("#instruction").value, task_type: $("#tasktype").value };
    if (!body.material.trim() || !body.instruction.trim()) { $("#msg").textContent = "素材与指令不能为空"; return; }
    $("#go").disabled = true;
    const res = await post("/api/runs", body);
    if (res.error) { $("#msg").textContent = "启动失败:" + res.error; $("#go").disabled = false; return; }
    pollJob(res.job_id);
  };
};
const STAGES = [["starting", "排队"], ["architect", "Architect"], ["writer", "Writer"], ["critic", "Critic"], ["patcher", "Patcher"], ["done", "完成"]];
async function pollJob(jobId) {
  const el = $("#prog");
  const timer = setInterval(async () => {
    const j = await api(`/api/runs/job/${jobId}`);
    const idx = STAGES.findIndex((s) => s[0] === j.stage);
    el.innerHTML = `<div class="stepper">${STAGES.map((s, i) =>
      `<div class="step ${j.done && j.ok ? "done" : i < idx ? "done" : i === idx ? "on" : ""}"><div class="dot">${i < idx || (j.done && j.ok) ? "✓" : i + 1}</div>${s[1]}</div>`).join("")}</div>
      ${j.done ? (j.ok
        ? `<div class="blind-note">运行完成 → <a class="link" href="#/run/${j.run_id}">查看 Run ${esc(j.run_id)}</a></div>`
        : `<div class="issue sev-high"><b>失败</b><div class="muted">${esc(j.error || "未知错误")}</div></div>`) : ""}`;
    if (j.done) { clearInterval(timer); $("#go").disabled = false; }
  }, 4000);
}

/* ---------------- benchmarks ---------------- */
routes.benchmarks = async () => {
  const { benchmarks } = await api("/api/benchmarks");
  main().innerHTML = `
    <div class="page-title">基准评测</div>
    <div class="page-sub">消融变体(docs/14):B0/B1 基线 · A1 大纲 · A2 WIR · A2_GI 沉浸 · A3 全管线 · 匿名 A/B 对</div>
    ${benchmarks.length ? benchmarks.map((b) => {
      const pct = b.packets ? Math.round((b.judged / b.packets) * 100) : 0;
      return `<div class="card mb" style="display:flex;gap:22px;align-items:center;flex-wrap:wrap">
        <div style="flex:1;min-width:220px">
          <b style="font-size:15px">${esc(b.name)}</b>
          <div class="muted" style="margin:6px 0">人工盲评 ${b.judged}/${b.packets}${b.llm_judged ? ` · LLM 参考评 ${b.llm_judged}(advisory)` : ""}</div>
          <div class="pbar" style="max-width:280px"><div style="width:${pct}%"></div></div>
        </div>
        <div style="display:flex;gap:10px">
          <a class="btn small" href="#/review/${encodeURIComponent(b.name)}">⚖ 进入盲评</a>
          <a class="btn small ghost" href="#/report/${encodeURIComponent(b.name)}">📊 胜率报告</a>
          <button class="btn small ghost" onclick="toggleVariants('${esc(b.name)}',this)">变体统计</button>
        </div>
        <div id="v-${esc(b.name)}" style="flex-basis:100%"></div></div>`;
    }).join("") : '<div class="doc muted">暂无 benchmark 结果目录。</div>'}`;
};

async function toggleVariants(name, btn) {
  const el = $("#v-" + name);
  if (el.innerHTML) { el.innerHTML = ""; return; }
  const [sum, gates] = await Promise.all([
    api(`/api/benchmarks/${encodeURIComponent(name)}/summary`),
    api(`/api/benchmarks/${encodeURIComponent(name)}/gates`),
  ]);
  const pb = (sum && sum.per_baseline) || {};
  const rows = Object.entries(pb).map(([v, s]) => {
    const g = (gates.per_variant || {})[v] || {};
    const failReasons = Object.entries(g.reasons || {}).map(([r, n]) => `${r}×${n}`).join(", ");
    return `<tr><td><b>${esc(v)}</b></td><td>${s.success}/${s.n}</td>
      <td>${s.mean_chars ?? "-"}</td><td>${s.mean_wq ?? "-"}</td>
      <td>${s.patched ?? 0}</td>
      <td>${s.hard_fail ? `<span class="badge b-red">${s.hard_fail}</span> <span class="muted">${esc(failReasons)}</span>` : '<span class="badge b-green">0</span>'}</td></tr>`;
  }).join("");
  el.innerHTML = rows ? `<table class="mt"><tr><th>变体 Variant</th><th>成功</th><th>均字数</th><th>WQ</th><th>Patched</th><th>Hard Fail</th></tr>${rows}</table>` : '<div class="muted mt">无 summary.json</div>';
}

/* ---------------- blind review ---------------- */
routes.review = async (name) => {
  if (!name) {
    const { benchmarks } = await api("/api/benchmarks");
    const b = benchmarks.filter((x) => x.packets > 0).sort((x, y) => y.pending - x.pending)[0];
    if (!b) { main().innerHTML = '<div class="page-title">盲评工作台</div><div class="doc mt muted">没有可评的 pairwise packets。先运行 benchmark。</div>'; return; }
    location.hash = `#/review/${encodeURIComponent(b.name)}`; return;
  }
  name = decodeURIComponent(name);
  const p = await api(`/api/benchmarks/${encodeURIComponent(name)}/packet`);
  if (!p.packet) {
    main().innerHTML = `<div class="page-title">盲评工作台</div>
      <div class="blind-note mt">「${esc(name)}」全部 ${p.total} 对已评完 🎉 → <a class="link" href="#/report/${encodeURIComponent(name)}">查看胜率报告</a></div>`;
    return;
  }
  const pk = p.packet;
  const sel = {};
  main().innerHTML = `
    <div class="page-sub"><a class="link" href="#/benchmarks">← 基准评测</a> · ${esc(name)}</div>
    <div class="page-title">盲评 · ${esc(pk.case_id)} <span class="muted" style="font-size:14px">${esc(pk.pair)}</span></div>
    <div class="page-sub">第 ${p.index + 1} / ${p.total} 对</div>
    <div class="blind-note">双盲:A/B 顺序与系统归属已隐藏。请只凭文本质量逐维度选择更优一方。</div>
    <div class="duel">
      <div><div class="duel-head"><span class="lab a">文本 A</span><span class="muted">Text A</span></div><div class="doc prose">${prose(pk.text_a)}</div></div>
      <div><div class="duel-head"><span class="lab b">文本 B</span><span class="muted">Text B</span></div><div class="doc prose">${prose(pk.text_b)}</div></div>
    </div>
    <div class="doc">
      ${DIMS.map(([k, zh]) => `
        <div class="dimrow ${k === "overall" ? "overall" : ""}" data-dim="${k}">
          <div class="dimname">${zh}<small>${k}</small></div>
          <div class="seg">
            <button data-v="A">A 优</button><button data-v="Tie" class="t">平手</button><button data-v="B">B 优</button>
          </div>
        </div>`).join("")}
      <label class="f">评语 Rationale(可选)</label>
      <textarea id="rationale" style="min-height:60px" placeholder="为什么?一两句话即可"></textarea>
      <div class="review-foot">
        <button class="btn green" id="submit">提交并下一对 →</button>
        <span class="hint" id="rmsg"></span>
      </div>
    </div>`;
  document.querySelectorAll(".dimrow").forEach((row) => {
    const dim = row.dataset.dim;
    row.querySelectorAll(".seg button").forEach((b) =>
      b.onclick = () => {
        row.querySelectorAll(".seg button").forEach((x) => x.classList.remove("on"));
        b.classList.add("on"); sel[dim] = b.dataset.v;
      });
  });
  $("#submit").onclick = async () => {
    const missing = DIMS.filter(([k]) => !sel[k]);
    if (missing.length) { $("#rmsg").textContent = "还有维度未选:" + missing.map(([, zh]) => zh).join("、"); return; }
    $("#submit").disabled = true;
    const dims = {}; DIMS.forEach(([k]) => (dims[k] = sel[k]));
    const res = await post(`/api/benchmarks/${encodeURIComponent(name)}/judge`, {
      case_id: pk.case_id, pair: pk.pair, dimensions: dims, rationale: $("#rationale").value.trim(),
    });
    if (res.error) { $("#rmsg").textContent = res.error; $("#submit").disabled = false; return; }
    route();
  };
};

/* ---------------- report ---------------- */
routes.report = async (name) => {
  name = decodeURIComponent(name);
  const [human, llm] = await Promise.all([
    api(`/api/benchmarks/${encodeURIComponent(name)}/report?reviewer=human`),
    api(`/api/benchmarks/${encodeURIComponent(name)}/report?reviewer=llm`),
  ]);
  main().innerHTML = `
    <div class="page-sub"><a class="link" href="#/benchmarks">← 基准评测</a></div>
    <div class="page-title">胜率报告 · ${esc(name)}</div>
    <div class="tabs" id="rtabs">
      <button class="on">人工盲评 (${human.judgments || 0})</button>
      <button>LLM 参考 (${llm.judgments || 0})</button>
    </div><div id="rbody"></div>`;
  const render = (rep, isHuman) => {
    if (!rep.pairwise) return `<div class="doc muted">${esc(rep.note || "暂无判断")}${isHuman ? " → <a class='link' href='#/review/" + encodeURIComponent(name) + "'>开始盲评</a>" : ""}</div>`;
    const gated = rep.pairwise_hard_gated;
    return (isHuman ? "" : '<div class="blind-note mb">LLM judge 与生成模型同源,存在风格自偏好(docs/08 §8),仅供参考;H1 判定以人工盲评为准。</div>') +
      ((rep.hard_failures || []).length ? `<div class="blind-note mb" style="background:var(--red-soft);border-color:#f0d3cf;color:var(--accent)">硬门失败 ${rep.hard_failures.length} 例:${rep.hard_failures.slice(0, 5).map((f) => esc(f.case_id + "/" + f.variant)).join("、")}${rep.hard_failures.length > 5 ? "…" : ""}(gate 失败方在「硬门校正」视图中不得获胜)</div>` : "") +
      Object.entries(rep.pairwise).map(([pair, data]) => renderPairTable(pair, data, gated && gated[pair], "原始判断", gated ? "硬门校正后" : null)).join("");
  };
  const renderPairTable = (pair, data, gdata, rawLabel, gatedLabel) => {
    const wrClass = (v) => (v >= 0.6 ? "hi" : v > 0.4 ? "mid" : "lo");
    const dimsOf = (d) => d.dims || d.dimensions || {};
    const sys = data.system || pair.split("_vs_")[0];
    const base = data.baseline || pair.split("_vs_")[1] || "";
    const DD = dimsOf(data);
    const col = (d) => {
      const tot = d.wins + d.losses + d.ties || 1;
      const rate = d.win_rate != null ? d.win_rate : d.wins / tot;
      return `<td><span class="wr ${wrClass(rate)}">${(rate * 100).toFixed(0)}%</span>
        <div class="wbar"><div class="w" style="width:${(d.wins / tot) * 100}%"></div><div class="t" style="width:${(d.ties / tot) * 100}%"></div><div class="l" style="width:${(d.losses / tot) * 100}%"></div></div></td>`;
    };
    return `<div class="doc mb">
      <div class="duel-head"><b style="font-size:15px">${esc(sys)} vs ${esc(base)}</b><span class="badge b-ink">${esc(pair)}</span><span class="muted">${rep.judgments} 条判断</span></div>
      <table style="margin-top:10px"><tr><th>维度</th><th>胜</th><th>负</th><th>平</th><th style="width:200px">${esc(rawLabel)} (${esc(sys)})</th>
      ${gdata ? `<th style="width:200px">${esc(gatedLabel)}</th>` : ""}</tr>
      ${DIMS.map(([k, zh]) => {
        const d = DD[k]; if (!d) return "";
        const gd = gdata ? dimsOf(gdata)[k] : null;
        return `<tr><td>${zh} <small class="muted">${k}</small></td><td>${d.wins}</td><td>${d.losses}</td><td>${d.ties}</td>${col(d)}${gd ? col(gd) : ""}</tr>`;
      }).join("")}</table></div>`;
  };
  const body = $("#rbody");
  body.innerHTML = render(human, true);
  $("#rtabs").querySelectorAll("button").forEach((b, i) =>
    b.onclick = () => {
      $("#rtabs").querySelectorAll("button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      body.innerHTML = render(i === 0 ? human : llm, i === 0);
    });
};

route();
