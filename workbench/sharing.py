"""Public, product-safe rendering for immutable article share snapshots."""

from __future__ import annotations

from datetime import datetime
from html import escape


PUBLIC_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "script-src 'unsafe-inline'; img-src data:; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-Robots-Tag": "noindex, nofollow",
}


def _display_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return f"{parsed.year} 年 {parsed.month} 月 {parsed.day} 日"
    except (TypeError, ValueError):
        return ""


def _paragraphs(content: str) -> str:
    blocks = []
    for paragraph in content.split("\n\n"):
        if not paragraph.strip():
            continue
        blocks.append(f"<p>{escape(paragraph).replace(chr(10), '<br>')}</p>")
    return "\n".join(blocks)


def render_public_article(share: dict, canonical_url: str) -> str:
    title = escape(share["title"])
    author = escape(share.get("author") or "")
    excerpt = escape(share.get("excerpt") or "")
    canonical = escape(canonical_url, quote=True)
    date = escape(_display_date(share.get("created_at") or ""))
    minutes = int(share.get("reading_minutes") or 1)
    byline = "　·　".join(part for part in (
        author, date, f"约 {minutes} 分钟阅读") if part)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <meta name="referrer" content="no-referrer">
  <meta name="theme-color" content="#f5efe4">
  <title>{title} · 纸墨文章</title>
  <link rel="canonical" href="{canonical}">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{excerpt}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:site_name" content="纸墨写作台">
  <style>
    :root {{ color-scheme: light; --paper:#f5efe4; --sheet:#fffdf8; --ink:#2c2822;
      --muted:#786f63; --line:#d9cebd; --accent:#b84634; }}
    * {{ box-sizing:border-box; }}
    html {{ background:var(--paper); }}
    body {{ margin:0; color:var(--ink); background:var(--paper);
      font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans CJK SC",sans-serif; }}
    nav {{ max-width:920px; margin:auto; min-height:64px; padding:12px 24px;
      display:flex; align-items:center; justify-content:space-between;
      border-bottom:1px solid var(--line); }}
    .brand {{ display:flex; align-items:center; gap:10px; color:var(--ink);
      font-family:"Songti SC","Noto Serif CJK SC",serif; }}
    .seal {{ width:28px; height:28px; display:grid; place-items:center;
      color:var(--accent); border:1px solid var(--accent); border-radius:3px; font-size:12px; }}
    button {{ appearance:none; border:0; background:transparent; color:var(--muted);
      padding:10px; font:inherit; cursor:pointer; }}
    main {{ max-width:720px; margin:auto; padding:72px 28px 100px; }}
    .kicker {{ color:var(--accent); font-size:12px; letter-spacing:.18em; margin-bottom:20px; }}
    h1 {{ margin:0; font-family:"Songti SC","Noto Serif CJK SC",serif;
      font-weight:600; font-size:clamp(32px,6vw,50px); line-height:1.35; letter-spacing:.02em; }}
    .deck {{ margin:20px 0 16px; color:var(--muted);
      font-family:"Songti SC","Noto Serif CJK SC",serif; font-size:18px; line-height:1.8; }}
    .byline {{ color:var(--muted); font-size:13px; }}
    .rule {{ width:58px; height:2px; margin:38px 0; background:var(--accent); }}
    article {{ font-family:"Songti SC","Noto Serif CJK SC",serif;
      font-size:19px; line-height:2.05; letter-spacing:.015em; }}
    article p {{ margin:0 0 28px; }}
    footer {{ margin-top:58px; padding-top:22px; border-top:1px solid var(--line);
      color:var(--muted); font-size:12px; display:flex; justify-content:space-between; gap:18px; }}
    #share-status {{ min-height:1.4em; color:var(--accent); text-align:right; font-size:12px; }}
    @media (max-width:600px) {{
      nav {{ min-height:56px; padding:10px 16px; }}
      main {{ padding:52px 20px 76px; }}
      article {{ font-size:18px; line-height:2; }}
      footer {{ flex-direction:column; }}
    }}
  </style>
</head>
<body>
  <nav aria-label="文章导航">
    <div class="brand"><span class="seal">墨</span><span>纸墨文章</span></div>
    <div><button id="share" type="button">分享</button><div id="share-status" aria-live="polite"></div></div>
  </nav>
  <main>
    <div class="kicker">纸墨写作台 · 文章</div>
    <h1>{title}</h1>
    {f'<p class="deck">{excerpt}</p>' if excerpt else ''}
    <div class="byline">{escape(byline)}</div>
    <div class="rule"></div>
    <article>{_paragraphs(share['content'])}</article>
    <footer><span>由纸墨写作台发布</span><span>这是作者发布时的版本快照</span></footer>
  </main>
  <script>
    const button=document.getElementById('share');
    const status=document.getElementById('share-status');
    button.addEventListener('click',async()=>{{
      try {{
        if(navigator.share) await navigator.share({{title:document.title,url:location.href}});
        else if(navigator.clipboard) {{ await navigator.clipboard.writeText(location.href); status.textContent='链接已复制'; }}
        else {{ prompt('复制链接',location.href); }}
      }} catch(error) {{ if(error.name!=='AbortError') status.textContent='请复制浏览器地址'; }}
    }});
  </script>
</body>
</html>"""


def render_missing_article() -> str:
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>文章不可访问 · 纸墨文章</title>
<style>body{margin:0;background:#f5efe4;color:#2c2822;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:620px;margin:18vh auto;padding:32px;text-align:center}b{font-family:"Songti SC",serif;font-size:28px}p{color:#786f63;line-height:1.8}</style></head>
<body><main><b>这篇文章已经停止分享</b><p>链接可能已失效，或者作者取消了公开访问。</p></main></body></html>"""
