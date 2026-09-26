/* User-flow checks against a disposable local mock server. No real model calls. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const root = path.resolve(__dirname, '../..');
const output = path.join(root, '.scratch/browser-report');
fs.mkdirSync(output, { recursive: true });
const results = [], pageErrors = [];
let environment = {};
const delay = ms => new Promise(r => setTimeout(r, ms));
async function until(fn, message, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (await fn()) return; await delay(80); }
  throw new Error(message);
}
async function main() {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'workbench-browser-restart-'));
  let server, stdout = '', stderr = '', browser, base;
  async function startServer(port = 0) {
    stdout = ''; stderr = '';
    server = spawn(process.env.PYTHON_BIN || 'python3',
      ['scripts/mock_server.py', '--data-dir', dataDir, '--port', String(port)],
      { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
    server.stdout.on('data', d => stdout += d);
    server.stderr.on('data', d => stderr += d);
    await until(() => /MOCK_URL=(http:\/\/127.0.0.1:\d+)/.test(stdout), 'mock startup: ' + stderr);
    base = stdout.match(/MOCK_URL=(http:\/\/127.0.0.1:\d+)/)[1];
    await until(async () => { try { return (await fetch(base + '/_test/ready')).ok; } catch { return false; } }, 'mock not ready');
  }
  async function stopServer(signal = 'SIGTERM') {
    if (!server || server.exitCode !== null || server.signalCode !== null) return;
    server.kill(signal);
    await Promise.race([new Promise(r => server.once('exit', r)), delay(3000)]);
    if (server.exitCode === null && server.signalCode === null) server.kill('SIGKILL');
  }
  try {
    await startServer();
    browser = await chromium.launch({headless: true, ...(process.env.BROWSER_EXECUTABLE ? {executablePath: process.env.BROWSER_EXECUTABLE} : {})});
    environment = {playwright:require('playwright/package.json').version, browser:await browser.version(), platform:process.platform, node:process.version};
    const context = await browser.newContext({ viewport: {width:1440, height:1000}, acceptDownloads:true });
    const page = await context.newPage();
    context.on('page', p => p.on('pageerror', e => pageErrors.push(String(e))));
    page.on('pageerror', e => pageErrors.push(String(e)));
    const api = async (method, route, data) => {
      const r = await context.request.fetch(base + route, {method, ...(data === undefined ? {} : {data})});
      assert.ok(r.ok(), `${route}: ${r.status()} ${await r.text()}`);
      return r.json();
    };
    const go = async route => {
      await page.goto(base + '/#' + route);
      const workspace = route.match(/^\/tasks\/([^/?]+)$/);
      if (workspace && workspace[1] !== 'new') {
        await page.locator(`.workspace[data-task-id="${workspace[1]}"]`).waitFor();
      }
    };
    const taskId = () => page.url().match(/#\/tasks\/([^/]+)/)[1];
    const editor = () => page.locator('#editor .para').first();
    async function confirm() { await page.locator('dialog[open] button[value=confirm]').click(); }
    async function check(name, fn) {
      const start = Date.now();
      try { await fn(); results.push({name, status:'passed', elapsed_ms:Date.now()-start}); console.log('PASS ' + name); }
      catch(e) {
        const message = e instanceof Error ? e.message : String(e);
        results.push({name,status:'failed',error:String(e)});
        await page.screenshot({path:path.join(output, 'failure.png'),fullPage:true});
        throw new Error(`${name}: ${message}`, {cause:e});
      }
    }
    let source, quick, imported, firstVersion, firstMeaning, releaseAcceptReload, linkedIdeaTask;
    await check('B00 home task overview opens a task', async()=>{
      const overview = await api('POST', '/tasks', {
        type: 'essay', title: '任务总览入口验收',
        instruction: '验证任务可以从总览页打开。',
        material: '一段用于任务列表验收的素材。',
        config: {expected_language: 'zh', target_length: 400,
          immersion: 'medium', explicitness: 'medium', intensity: 'medium'}
      });
      await go('/');
      await page.locator('a[href="#/tasks"]').click();
      await page.locator('.task-list').waitFor();
      assert.match(await page.locator('.task-list').innerText(), /任务总览入口验收/);
      await page.locator(`.task-row a[href="#/tasks/${overview.id}"]`).first().click();
      await page.locator(`.workspace[data-task-id="${overview.id}"]`).waitFor();
      assert.match(page.url(), new RegExp(`#\\/tasks\\/${overview.id}$`));
    });
    await check('B01 source generation, manual edit and reload', async()=>{
      await go('/tasks/new');
      await page.locator('#f-material').fill('修好的钟放在桌上。老人仍每天等待邮递员。');
      await page.locator('#f-instruction').fill('用具体细节写等待，不直接说教。');
      await page.reload();
      assert.match(await page.locator('#f-material').inputValue(), /修好的钟/);
      await page.locator('#f-go').click();
      await page.locator('#gen-now').click();
      await editor().waitFor(); source = taskId();
      await editor().fill('手工修改的第一段。');
      await until(async()=> (await api('GET', `/tasks/${source}`)).draft.working_content.startsWith('手工修改的第一段。'), 'autosave');
      await page.reload();
      assert.equal(await editor().innerText(), '手工修改的第一段。');
    });
    await check('B02 quick write, another angle and same-angle rewrite', async()=>{
      await go('/quickwrite');
      await page.locator('#qw-topic').fill('等待为什么会改变一个人');
      await page.locator('#qw-go').click();
      await editor().waitFor(); quick = taskId();
      let t = await api('GET', `/tasks/${quick}`); firstVersion=t.draft.current_version_id;
      firstMeaning = await api('GET', `/tasks/${quick}/meaning`);
      await page.locator('#p-another').click(); await confirm();
      await until(async()=> (await api('GET', `/tasks/${quick}`)).draft.current_version_id !== firstVersion, 'angle change');
      await until(async()=>await page.locator('#p-same').isEnabled(), 'rewrite ready');
      const meaning = await api('GET', `/tasks/${quick}/meaning`); assert.notDeepEqual(meaning,firstMeaning);
      t=await api('GET', `/tasks/${quick}`); const v=t.draft.current_version_id;
      await page.locator('#p-same').click(); await confirm();
      await until(async()=> (await api('GET', `/tasks/${quick}`)).draft.current_version_id !== v, 'same angle rewrite');
      assert.deepEqual(await api('GET', `/tasks/${quick}/meaning`),meaning);
    });
    await check('B03 import, review, locate and proposal only', async()=>{
      await go('/revise');
      await page.locator('#f-material').fill('老人把钟放回桌上。'.repeat(12)+'\n\n他每天听见邮递员的脚步，却从不打开门。\n\n他终于决定出去走走。');
      await page.locator('#f-instruction').fill('收紧结尾'); await page.locator('#f-go').click();
      await editor().waitFor(); imported=taskId();
      const before=(await api('GET', `/tasks/${imported}`)).draft.working_content;
      await page.locator('[data-t=review]').click(); await page.locator('#r-run').click();
      await page.locator('[data-show]').first().waitFor();
      assert.match(await page.locator('#review-out').innerText(), /本次检查已通过/);
      assert.doesNotMatch(await page.locator('#review-out').innerText(), /decision|wq|PASS/);
      await page.locator('[data-show]').first().click();
      await page.locator('#selbar.show').waitFor();
      await page.locator('[data-fix]').first().click();
      await page.locator('.patch-card').waitFor();
      assert.equal((await api('GET', `/tasks/${imported}`)).draft.working_content,before);
    });
    await check('B04 reject, retry, accept and duplicate click', async()=>{
      let t=await api('GET', `/tasks/${imported}`); const count=t.draft.versions.length;
      await page.locator('.act-reject').click(); assert.equal((await api('GET', `/tasks/${imported}`)).draft.versions.length,count);
      await editor().click(); await page.locator('[data-i=shorter]').click();
      await page.locator('.patch-card').waitFor(); await page.locator('.act-retry').first().click();
      await until(async()=>await page.locator('.patch-card').count()===2,'retry proposal');
      let acceptReloadStarted=false;
      const acceptReloadHold=new Promise(resolve=>{ releaseAcceptReload=resolve; });
      await page.route(`**/tasks/${imported}/preserved-spans`,async route=>{
        acceptReloadStarted=true; await acceptReloadHold; await route.continue();
      },{times:1});
      await page.locator('.act-accept').last().dblclick();
      await until(async()=> (await api('GET', `/tasks/${imported}`)).draft.versions.length===count+1,'accept one version');
      await until(()=>acceptReloadStarted,'accept refresh held');
      assert.equal((await api('GET', `/tasks/${imported}`)).draft.versions.length,count+1);
    });
    await check('B05 restore original angle and structure reference', async()=>{
      await go(`/tasks/${quick}/versions`);
      releaseAcceptReload();
      await page.locator(`.va-restore[data-v="${firstVersion}"]`).click(); await confirm();
      await until(async()=> (await api('GET', `/tasks/${quick}`)).draft.current_version_id !== firstVersion &&
        JSON.stringify(await api('GET', `/tasks/${quick}/meaning`))===JSON.stringify(firstMeaning), 'restore meaning');
      await go(`/tasks/${quick}`); await page.locator('#tab-map').click();
      const beat=page.locator('.beat').first(); await beat.waitFor();
      assert.match(await page.locator('#center-body').innerText(),/原定路径/);
      await beat.focus(); await page.keyboard.press('Enter');
      await page.locator('#selbar.show').waitFor();
      assert.ok(await page.locator('#editor .para.sel').count());
    });
    await check('B06 two-tab conflict retains local input and reload path', async()=>{
      await go(`/tasks/${source}`); await editor().waitFor();
      const other=await context.newPage(); await other.goto(base+`/#/tasks/${source}`);
      await other.locator('#editor .para').first().fill('另一标签页的已保存正文。');
      await until(async()=> (await api('GET', `/tasks/${source}`)).draft.working_content.startsWith('另一标签页'), 'second tab saved');
      await editor().fill('当前标签页尚未保存的文字。');
      await page.locator('#save-conflict').waitFor();
      assert.match(await page.locator('#save-conflict textarea').inputValue(),/尚未保存/);
      await page.locator('#topbar a[href="#/settings"]').click();
      await until(()=>page.url().endsWith(`#/tasks/${source}`),'conflict blocks navigation');
      assert.equal(await editor().innerText(),'当前标签页尚未保存的文字。');
      await page.reload(); await page.locator('#save-conflict').waitFor();
      const download=page.waitForEvent('download'); await page.locator('#recover-reload').click(); await download;
      await until(async()=> await page.locator('#save-conflict').count()===0,'conflict resolved');
      assert.equal(await editor().innerText(),'另一标签页的已保存正文。'); await other.close();
    });
    await check('B07 crash, restart, interrupted state and manual retry', async()=>{
      await api('POST','/_test/delay',{seconds:8});
      await go(`/tasks/${quick}`); await page.locator('#p-gen').click(); await confirm();
      await until(async()=> (await api('GET', `/tasks/${quick}`)).operation.status==='running','running operation');
      const interrupted = (await api('GET', `/tasks/${quick}`)).operation.id;
      const port = Number(new URL(base).port);
      await stopServer('SIGKILL');
      await startServer(port);
      await until(async()=> (await api('GET', `/tasks/${quick}`)).operation.status==='interrupted','interrupted operation');
      await page.reload(); await editor().waitFor();
      assert.match(await page.locator('#toast').innerText(),/运行中断/);
      await page.locator('#gen-retry').click();
      try {
        await until(async()=> {
          const op=(await api('GET', `/tasks/${quick}`)).operation;
          if (op.id !== interrupted && ['failed','interrupted'].includes(op.status))
            throw new Error(`retry operation ${op.id} ended as ${op.status} (${op.error_code || 'no error code'})`);
          return op.id !== interrupted && op.status === 'succeeded';
        },'manual retry after restart',30000);
      } catch (e) {
        const op=(await api('GET', `/tasks/${quick}`)).operation;
        throw new Error(`${e.message}; latest operation=${JSON.stringify(op)}`, {cause:e});
      }
      assert.equal((await api('GET', `/tasks/${quick}/operations/${interrupted}`)).status,'interrupted');
    });
    await check('B08 model failures, endpoint races and manual aliases', async()=>{
      let response={ok:false,error:'Endpoint unavailable <img src=x onerror="window.injected=1">'}, hold=null;
      await page.route('**/settings/models',async r=>{ if(hold) await hold; await r.fulfill({json:response}); });
      await go('/settings'); await page.locator('#s-model').fill('custom-local:latest');
      await page.locator('#s-provider').selectOption('ollama');
      await until(async()=>await page.locator('#s-fetch').isEnabled(),'failed model list');
      assert.equal(await page.locator('#s-model').inputValue(),'custom-local:latest');
      let release; hold=new Promise(r=>release=r); response={ok:true,models:['suggested-only']};
      await page.locator('#s-fetch').click(); await page.locator('#s-model').fill('typed-during-fetch'); release(); hold=null;
      await until(async()=>await page.locator('#s-fetch').isEnabled(),'model response');
      assert.equal(await page.locator('#s-model').inputValue(),'typed-during-fetch');
      hold=new Promise(r=>release=r); await page.locator('#s-fetch').click();
      await page.locator('#s-base').fill('http://127.0.0.1:1234/v1'); release(); hold=null;
      await page.locator('#s-save').click();
      await until(async()=> (await api('GET','/settings')).model==='typed-during-fetch','custom model saved');
      assert.equal(await page.evaluate(()=>window.injected),undefined);
      await page.unroute('**/settings/models');
    });
    await check('B09 long paste, composition and contiguous paragraph selection', async()=>{
      await go(`/tasks/${source}`); await editor().waitFor();
      const longText=('钟声穿过院子，老人把信封压在杯子下面。'.repeat(300)).slice(0,5200);
      const priorParagraphs=(await api('GET', `/tasks/${source}`)).draft.working_content.split('\n\n');
      const expectedPaste=[longText,...priorParagraphs.slice(1)].join('\n\n');
      await context.grantPermissions(['clipboard-read','clipboard-write'], {origin:base});
      await page.evaluate(text=>navigator.clipboard.writeText(text),longText);
      await editor().click(); await page.keyboard.press('ControlOrMeta+A');
      await page.keyboard.press('ControlOrMeta+V');
      await until(async()=> (await api('GET', `/tasks/${source}`)).draft.working_content.length>=5000,'long paste autosave');
      const pasted=(await api('GET', `/tasks/${source}`)).draft.working_content;
      assert.equal(pasted,expectedPaste,
        `long paste mismatch: expected ${expectedPaste.length}, got ${pasted.length}; head=${JSON.stringify(pasted.slice(0,30))}; tail=${JSON.stringify(pasted.slice(-30))}`);
      await page.reload(); assert.equal(await editor().innerText(),longText);
      const before=(await api('GET', `/tasks/${source}`)).draft.working_content;
      await editor().dispatchEvent('compositionstart');
      await editor().fill('输入法组合中的中文段落。'); await delay(1400);
      assert.equal((await api('GET', `/tasks/${source}`)).draft.working_content,before);
      await editor().dispatchEvent('compositionend');
      await until(async()=> (await api('GET', `/tasks/${source}`)).draft.working_content.startsWith('输入法组合'), 'composition committed');

      await go(`/tasks/${imported}`); await editor().waitFor();
      await page.locator('.para[data-p="3"]').click();
      await page.locator('.para[data-p="1"]').click({modifiers:['Shift']});
      assert.deepEqual(await page.locator('#editor .para.sel').evaluateAll(
        els=>els.map(x=>Number(x.dataset.p))),[1,2,3]);
      await page.evaluate(()=>window.getSelection().removeAllRanges());
      await page.evaluate(()=>{
        const paras=[...document.querySelectorAll('#editor .para')];
        const range=document.createRange();
        range.setStart(paras[1].firstChild,1);
        range.setEnd(paras[2].firstChild,Math.min(3,paras[2].firstChild.length));
        const selection=window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
        paras[2].dispatchEvent(new MouseEvent('click',{bubbles:true}));
      });
      assert.deepEqual(await page.locator('#editor .para.sel').evaluateAll(
        els=>els.map(x=>Number(x.dataset.p))),[2,3]);
      const importedBefore=(await api('GET', `/tasks/${imported}`)).draft.working_content;
      const priorPatchIds=new Set(await page.locator('.patch-card').evaluateAll(
        cards=>cards.map(card=>card.dataset.id)));
      await page.locator('#selbar [data-i=shorter]').click();
      await until(async()=>await page.locator('.patch-card').count()===priorPatchIds.size+1,'cross-paragraph proposal');
      const currentPatchIds=await page.locator('.patch-card').evaluateAll(
        cards=>cards.map(card=>card.dataset.id));
      const patchId=currentPatchIds.find(id=>!priorPatchIds.has(id));
      assert.ok(patchId,'new proposal id must be distinguishable from older pending proposals');
      const card=page.locator(`.patch-card[data-id="${patchId}"]`);
      const pending=(await api('GET', `/tasks/${imported}`)).pending_patches
        .find(p=>p.patch_id===patchId);
      assert.deepEqual({start:pending.selection.paragraph_start,end:pending.selection.paragraph_end},{start:2,end:3});
      assert.equal((await api('GET', `/tasks/${imported}`)).draft.working_content,importedBefore);
      await card.locator('.act-reject').click();
    });
    await check('B10 desktop layout and keyboard dialog', async()=>{
      await go(`/tasks/${source}`); await editor().waitFor();
      await page.setViewportSize({width:1280,height:800});
      await page.screenshot({path:path.join(output,'workspace-1280.png'),fullPage:true});
      await page.locator('#p-gen').click(); await page.locator('dialog[open]').waitFor();
      await page.keyboard.press('Escape'); assert.equal(await page.locator('dialog[open]').count(),0);
      assert.equal(await page.evaluate(()=>document.activeElement?.id),'p-gen');
      await go('/quickwrite'); await page.setViewportSize({width:1440,height:1000});
      await page.locator('#qw-topic-suggest').click();
      const cards=page.locator('.qw-card'); await cards.first().waitFor();
      const firstText=await cards.first().locator('b').innerText();
      await cards.first().focus(); await page.keyboard.press('Enter');
      assert.equal(await page.locator('#qw-topic').inputValue(),firstText);
      assert.equal(await page.evaluate(()=>document.activeElement?.id),'qw-topic');
      const second=page.locator('.qw-card').nth(1);
      const secondText=await second.locator('b').innerText();
      await second.focus(); await page.keyboard.press('Space');
      assert.equal(await page.locator('#qw-topic').inputValue(),secondText);
      await page.screenshot({path:path.join(output,'quickwrite-1440.png'),fullPage:true});
    });
    await check('B11 current and historical version export', async()=>{
      await go(`/tasks/${source}`); await editor().waitFor();
      const beforeExport=(await api('GET', `/tasks/${source}`)).draft;
      const versionCount=beforeExport.versions.length;
      const exportFirst='导出前刚完成的正文，保留 # Markdown 字符与🙂。';
      const exportText=[exportFirst,...beforeExport.working_content.split('\n\n').slice(1)].join('\n\n');
      await editor().fill(exportFirst);
      await page.locator('#export-format').selectOption('txt');
      const currentDownload=page.waitForEvent('download');
      await page.locator('#export-current').click();
      const current=await currentDownload;
      assert.equal(fs.readFileSync(await current.path(),'utf8'),exportText);
      const saved=(await api('GET', `/tasks/${source}`)).draft;
      assert.equal(saved.working_content,exportText);
      assert.equal(saved.versions.length,versionCount,'export must not create a version');

      await go(`/tasks/${source}/versions`);
      await page.locator('#v-export-format').selectOption('md');
      const exportButton=page.locator('.va-export').first();
      const versionId=await exportButton.getAttribute('data-v');
      const expected=(await api('GET', `/versions/${versionId}`)).content;
      const versionDownload=page.waitForEvent('download');
      await exportButton.click();
      const historical=await versionDownload;
      assert.equal(fs.readFileSync(await historical.path(),'utf8'),expected);
      assert.equal((await api('GET', `/tasks/${source}`)).draft.working_content,exportText);
    });
    await check('B12 workspace backup inspection and independent restore', async()=>{
      const before=(await api('GET', `/tasks/${source}`)).draft;
      await go('/settings'); await page.locator('#backup-download').waitFor();
      const download=page.waitForEvent('download');
      await page.locator('#backup-download').click();
      const saved=await download;
      const backupPath=await saved.path();
      assert.match(saved.suggestedFilename(),/\.nwb-backup\.zip$/);
      assert.ok(fs.statSync(backupPath).size>0);

      await page.locator('#backup-file').setInputFiles(backupPath);
      assert.equal(await page.locator('#backup-restore').isDisabled(),true);
      await page.locator('#backup-inspect').click();
      await until(async()=>await page.locator('#backup-restore').isEnabled(),'backup inspection');
      assert.match(await page.locator('#backup-result').innerText(),/预检通过.*任务.*版本/);

      await page.locator('#backup-restore').click(); await confirm();
      await until(async()=>/恢复完成/.test(await page.locator('#backup-result').innerText()),'independent restore');
      const restoredRoot=path.join(dataDir,'restored');
      const copies=fs.readdirSync(restoredRoot).filter(name=>name.startsWith('restored-'));
      assert.equal(copies.length,1);
      assert.ok(fs.existsSync(path.join(restoredRoot,copies[0],'workbench.db')));
      assert.deepEqual((await api('GET', `/tasks/${source}`)).draft,before,'restore must not mutate current draft');
    });
    await check('B13 preview, edit and confirm angle before writing', async()=>{
      await go('/quickwrite');
      await page.locator('#qw-topic').fill('为什么失败会改变过去努力的意义');
      await page.locator('#qw-preview').click();
      await page.locator('dialog[open]').waitFor(); await confirm();
      const cards=page.locator('.qw-angle-card');
      await until(async()=>await cards.count()===3,'three angle cards');
      const newest=(await api('GET','/tasks')).tasks[0];
      const previewTask=await api('GET',`/tasks/${newest.id}`);
      assert.equal(previewTask.draft,null,'preview must not create a draft');
      assert.equal(previewTask.operation.kind,'angle_options');
      assert.equal(previewTask.operation.status,'succeeded');

      await cards.nth(1).focus(); await page.keyboard.press('Enter');
      assert.equal(await cards.nth(1).getAttribute('aria-selected'),'true');
      await page.locator('.qw-angle-edit summary').click();
      const editedLabel='失败不是结论，而是对既有投入的重新定价';
      await page.locator('#qa-label').fill(editedLabel);
      await page.locator('#qa-question').fill('结果为什么会反过来改写投入？');
      await page.locator('#qa-meaning').fill('结果改变的是投入的解释框架。');
      await page.locator('#qa-boundary').fill('只适用于投入意义依赖结果的情况。');
      await page.locator('#qa-end').fill('以后先区分投入本身与结果评价。');
      await page.locator('#qw-confirm-angle').click();
      await editor().waitFor();
      assert.equal(taskId(),newest.id);
      const meaning=await api('GET',`/tasks/${newest.id}/meaning`);
      assert.equal(meaning.selected_angle,editedLabel);
      const written=await api('GET',`/tasks/${newest.id}`);
      assert.ok(written.draft.working_content.length>0);
      assert.equal(written.operation.kind,'generate');
      await page.screenshot({path:path.join(output,'angle-confirmation.png'),fullPage:true});
    });
    await check('B14 revision worklist and preserved passage', async()=>{
      await go('/revise');
      const opening='老人把钟放回桌上，却又一次解释自己为何等待。'.repeat(12);
      const exact='这一段必须逐字保留。';
      await page.locator('#f-material').fill(`${opening}\n\n${exact}\n\n门外终于传来脚步声。`);
      await page.locator('#f-instruction').fill('删去重复解释，保留具体动作。');
      await page.locator('#f-go').click(); await editor().waitFor();
      const workTask=taskId();
      await editor().click();
      await page.locator('#selbar [data-i=preserve]').click();
      await until(async()=>await page.locator('.para.preserved').count()===1,'preserved highlight');
      await page.locator('[data-t=review]').click();
      assert.match(await page.locator('.preserved-list').innerText(),/已保留|保留原文/);
      await page.locator('#r-run').click();
      await page.locator('[data-fix]').first().waitFor();
      const before=(await api('GET',`/tasks/${workTask}`)).draft;
      await page.locator('[data-fix]').first().click();
      await until(async()=>/保留/.test(await page.locator('#toast').innerText()),'preserve conflict');
      assert.equal(await page.locator('.patch-card').count(),0);
      assert.equal((await api('GET',`/tasks/${workTask}`)).draft.working_content,before.working_content);

      await page.locator('[data-t=review]').click();
      await page.locator('[data-unkeep]').click();
      await page.locator('[data-fix]').first().click();
      await page.locator('.patch-card').waitFor();
      await page.locator('.act-reject').click();
      await page.locator('[data-fix]').first().waitFor();
      assert.match(await page.locator('#review-out').innerText(),/待处理/);
      await page.locator('[data-fix]').first().click();
      await page.locator('.patch-card').waitFor();
      await page.locator('.act-accept').click();
      await until(async()=>/已完成/.test(await page.locator('#review-out').innerText()),'work item resolved');
      const after=(await api('GET',`/tasks/${workTask}`)).draft;
      assert.equal(after.versions.length,before.versions.length+1);
      assert.match(after.working_content, new RegExp(exact));
      await page.screenshot({path:path.join(output,'revision-worklist.png'),fullPage:true});
    });
    await check('B15 evidence cards, source lookup and safe patch', async()=>{
      const created=await api('POST','/tasks',{
        input_mode:'source_grounded',type:'essay',title:'材料依据测试',
        instruction:'根据材料解释访问量变化。',
        material:'报告显示，2024 年访问量同比增长 20%，统计范围仅含已登录用户。'
      });
      await api('POST',`/tasks/${created.id}/generate`,{});
      await go(`/tasks/${created.id}`); await editor().waitFor();
      await page.locator('[data-t=review]').click();
      await page.locator('#e-run').click();
      await page.locator('.evidence-card').waitFor();
      assert.match(await page.locator('#evidence-out').innerText(),/作者推断/);
      assert.match(await page.locator('#evidence-out').innerText(),/不表示外部事实认证|材料/);
      await page.locator('[data-claim-source]').click();
      await page.locator('.srcitem.hl').waitFor();
      await page.locator('[data-claim-confirm]').click();
      await until(async()=>/已确认关联/.test(await page.locator('#evidence-out').innerText()),'claim confirmation');
      const before=(await api('GET',`/tasks/${created.id}`)).draft;
      await page.locator('[data-claim-fix]').click();
      await page.locator('.patch-card').waitFor();
      assert.equal((await api('GET',`/tasks/${created.id}`)).draft.working_content,before.working_content);
      await page.locator('.act-accept').click();
      await until(async()=>/已过期/.test(await page.locator('#evidence-out').innerText()),'evidence stales after accepted patch');
      const after=(await api('GET',`/tasks/${created.id}`)).draft;
      assert.equal(after.versions.length,before.versions.length+1);
      await page.screenshot({path:path.join(output,'evidence-cards.png'),fullPage:true});
    });
    await check('B16 current-draft reader path and revision lifecycle', async()=>{
      const repeated='老人把钟放回桌上。';
      const created=await api('POST','/tasks',{
        input_mode:'draft_revision',type:'essay',title:'稿件路径测试',
        instruction:'检查实际推进，删去重复。',
        material:`${repeated}\n\n${repeated}\n\n因此，他已经不再等待。`
      });
      await go(`/tasks/${created.id}`); await editor().waitFor();
      assert.match(await page.locator('.tabs').innerText(),/原定路径/);
      assert.match(await page.locator('.tabs').innerText(),/稿件检查/);
      await page.locator('#tab-reader').click();
      await page.locator('#reader-run').waitFor();
      assert.match(await page.locator('#center-body').innerText(),/不是真实读者实验/);
      await page.locator('#reader-run').click();
      await until(async()=>await page.locator('.path-step').count()===3,'three reader path steps');
      await page.locator('[data-reader-fix]').first().waitFor();
      const pathReview=await api('GET',`/tasks/${created.id}/reader-path-review`);
      assert.equal(pathReview.steps.length,3);
      assert.ok(pathReview.issues.some(issue=>issue.type==='repetition'));
      assert.ok(pathReview.issues.some(issue=>issue.type==='reasoning_gap'));
      const before=(await api('GET',`/tasks/${created.id}`)).draft;

      await page.locator('.path-step').nth(1).focus();
      await page.keyboard.press('Enter');
      await page.locator('.para[data-p="2"].hl').waitFor();
      await page.locator('#tab-reader').click();
      await page.locator('[data-reader-fix]').first().click();
      await page.locator('.patch-card').waitFor();
      assert.equal((await api('GET',`/tasks/${created.id}`)).draft.working_content,
        before.working_content,'reader path proposal must not edit the draft');
      await page.locator('.act-reject').click();
      await until(async()=>await page.locator('.patch-card').count()===0,
        'reader path rejection refresh');
      await page.locator('#tab-reader').click();
      await until(async()=>/待处理/.test(await page.locator('.reader-issue').first().innerText()),
        'rejected path issue reopens');

      await page.locator('[data-reader-fix]').first().click();
      await page.locator('.patch-card').waitFor();
      await page.locator('.act-accept').click();
      await until(async()=>await page.locator('.patch-card').count()===0,
        'reader path acceptance refresh');
      await page.locator('#tab-reader').click();
      await until(async()=>/已过期/.test(await page.locator('#center-body').innerText()),
        'reader path stales after accepted patch');
      const after=(await api('GET',`/tasks/${created.id}`)).draft;
      assert.equal(after.versions.length,before.versions.length+1);
      await page.screenshot({path:path.join(output,'reader-path.png'),fullPage:true});
    });
    await check('B17 local idea box migration, collection and task link', async()=>{
      const legacy=[
        {text:'迁移后继续写',hook:'验证旧题库安全进入选题箱',domain:'culture',domainName:'文化',ts:1},
        {text:'保存灵感之后发生什么',hook:'区分候选与明确收藏',domain:'work',domainName:'劳动与职场',ts:2},
      ];
      const before=(await api('GET','/ideas?limit=200')).ideas.length;
      await page.evaluate(items=>localStorage.setItem('qw_topic_lib_v1',JSON.stringify(items)),legacy);
      await go('/quickwrite');
      await until(async()=>await page.locator('.idea-card').count()===before+2,
        'legacy ideas imported');
      assert.equal(await page.evaluate(()=>localStorage.getItem('qw_topic_lib_v1')),null,
        'legacy key is removed only after confirmed import');
      let ideas=(await api('GET','/ideas?limit=200')).ideas;
      const migrated=ideas.find(x=>x.topic==='迁移后继续写');
      assert.ok(migrated); assert.equal(migrated.origin,'legacy');

      const countBeforeSuggestion=ideas.length;
      await page.locator('#qw-topic').fill('');
      await page.locator('#qw-topic-suggest').click();
      const generated=page.locator('#qw-lib .qw-card'); await generated.first().waitFor();
      assert.equal((await api('GET','/ideas?limit=200')).ideas.length,countBeforeSuggestion,
        'uncollected suggestions must remain session-only');
      const generatedTopic=await generated.first().locator('b').innerText();
      await generated.first().hover();
      await generated.first().locator('[data-i].qw-save').click();
      await until(async()=>{
        const rows=(await api('GET','/ideas?limit=200')).ideas;
        return rows.some(x=>x.topic===generatedTopic);
      },'generated idea collected');

      await page.locator('#idea-search').fill('迁移后继续');
      await until(async()=>await page.locator('.idea-card').count()===1,'idea search');
      const card=page.locator('.idea-card').first();
      await card.locator('.idea-note').fill('下一步从迁移与明确收藏的差异写起。');
      await card.locator('[data-save-note]').click();
      await until(async()=>{
        const row=(await api('GET',`/ideas?q=${encodeURIComponent('迁移后继续')}`)).ideas[0];
        return row?.note.includes('明确收藏');
      },'idea note saved');
      await page.evaluate(()=>localStorage.clear());
      await page.reload();
      await until(async()=>await page.locator('.idea-card').count()>=3,'idea box survives reload');
      assert.ok((await api('GET','/ideas?limit=200')).ideas.some(x=>x.topic===generatedTopic));

      await page.locator('#idea-search').fill('迁移后继续');
      await until(async()=>await page.locator('.idea-card').count()===1,'migrated idea visible');
      await page.locator('.idea-card [data-use-idea]').click();
      assert.equal(await page.locator('#qw-topic').inputValue(),'迁移后继续写');
      await page.locator('#qw-go').click(); await editor().waitFor();
      linkedIdeaTask=taskId();
      const linked=(await api('GET',`/ideas?q=${encodeURIComponent('迁移后继续')}`)).ideas[0];
      assert.equal(linked.status,'written'); assert.equal(linked.task_id,linkedIdeaTask);

      await go('/quickwrite'); await page.locator('#idea-status').selectOption('written');
      await until(async()=>await page.locator('.idea-card').count()===1,'written idea filter');
      await page.locator('.idea-card [data-open-idea]').click();
      await page.locator(`.workspace[data-task-id="${linkedIdeaTask}"]`).waitFor();
      await page.screenshot({path:path.join(output,'idea-box-linked-task.png'),fullPage:true});
    });
    await check('B18 task deletion confirmation and idea release', async()=>{
      await go('/tasks');
      const button=page.locator(`[data-delete-task="${linkedIdeaTask}"]`);
      await button.waitFor();
      await button.click();
      await page.locator('dialog[open] button[value=cancel]').click();
      assert.equal(await button.count(),1,'cancel keeps the task');
      await button.click(); await confirm();
      await until(async()=>await page.locator(`[data-delete-task="${linkedIdeaTask}"]`).count()===0,
        'deleted task leaves overview');
      const missing=await context.request.get(base+`/tasks/${linkedIdeaTask}`);
      assert.equal(missing.status(),404);
      const released=(await api('GET',`/ideas?q=${encodeURIComponent('迁移后继续')}`)).ideas[0];
      assert.equal(released.status,'to_write'); assert.equal(released.task_id,null);
      await page.screenshot({path:path.join(output,'task-deleted.png'),fullPage:true});
    });
    await check('B19 immutable article share, card and revocation', async()=>{
      await go(`/tasks/${source}`);
      await page.locator('#share-current').click();
      await page.locator('.share-dialog[open]').waitFor();
      assert.match(await page.locator('.share-local-warning').innerText(),/只在这台电脑/);
      await page.locator('#share-author').fill('林墨');
      await page.locator('#share-excerpt').fill('一篇用于验证独立阅读页的文章。');
      await page.locator('#share-create').click();
      await page.locator('#share-link').waitFor();
      const oldUrl=await page.locator('#share-link').inputValue();
      await page.locator('#share-copy').click();
      await until(async()=> (await page.locator('#share-copy').innerText())==='已复制',
        'share link copy feedback');
      assert.equal(await page.locator('#share-copy').innerText(),'已复制');
      assert.match(await page.locator('#share-copy-status').innerText(),/已复制到剪贴板/);
      assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),oldUrl);
      const publicPage=await context.request.get(oldUrl);
      assert.equal(publicPage.status(),200);
      assert.match(await publicPage.text(),/用于验证独立阅读页/);
      const cardDownload=page.waitForEvent('download');
      await page.locator('#share-card').click();
      assert.match((await cardDownload).suggestedFilename(),/分享卡片\.png$/);
      await page.locator('.share-dialog .dialog-close').click();

      await editor().fill('分享之后修改的新正文。');
      await until(async()=> (await api('GET',`/tasks/${source}`)).draft.working_content.startsWith('分享之后'),
        'shared draft autosave');
      assert.doesNotMatch(await (await context.request.get(oldUrl)).text(),/分享之后/,
        'published snapshot stays immutable');
      await page.locator('#share-current').click();
      await page.locator('#share-replace').waitFor();
      assert.match(await page.locator('.share-note.warn').innerText(),/正文已有新修改/);
      await page.locator('#share-replace').click(); await confirm();
      await until(async()=> (await page.locator('#share-link').inputValue())!==oldUrl,
        'share link replaced');
      assert.equal((await context.request.get(oldUrl)).status(),404);
      const newUrl=await page.locator('#share-link').inputValue();
      assert.match(await (await context.request.get(newUrl)).text(),/分享之后修改的新正文/);
      await page.locator('#share-revoke').click(); await confirm();
      await until(async()=>await page.locator('.share-dialog').count()===0,'share dialog closes');
      assert.equal((await context.request.get(newUrl)).status(),404);
      await page.screenshot({path:path.join(output,'article-share-revoked.png'),fullPage:true});
    });
    assert.deepEqual(pageErrors,[], 'unhandled browser exceptions');
  } finally {
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({environment,results,pageErrors},null,2));
    if(browser) await browser.close();
    await stopServer();
    fs.rmSync(dataDir, {recursive:true, force:true});
  }
}
main().catch(e=>{
  console.error(e);
  if (process.env.GITHUB_ACTIONS === 'true') {
    const message = String(e && e.message || e)
      .replaceAll('%','%25').replaceAll('\r','%0D').replaceAll('\n','%0A');
    console.error(`::error title=Browser smoke failed::${message}`);
  }
  process.exitCode=1;
});
