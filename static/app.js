/* Prompt Wizard — app.js (old 2-column form kept)
   - Build -> /build
   - Enhance -> /enhance (short/medium/detailed)
   - Quick Preset (loads /static/templates.json; has fallback)
   - Templates modal
   - Favorites, Copy/Export, Split, Emojis
   - Usage/Credits meters (auto on load + every 60s; countdown HH:MM:SS)
   - NEW: Upgrade button (Gumroad or /upgrade)
*/

(function () {
  const $  = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const byId = (id) => document.getElementById(id);

  // Elements
  const elOutput   = byId('output');
  const elConcise  = byId('outputConcise');
  const elMsg      = byId('msg');
  const elEnhMode  = byId('enhMode');

  // Flags (from Jinja)
  const ENABLE_GPT       = !!window.ENABLE_GPT;
  const ROLLOVER_MODE    = !!window.ROLLOVER_MODE;
  const CAPTURE_REQUIRED = !!window.CAPTURE_REQUIRED;
  const UPGRADE_URL      = window.UPGRADE_URL || '/upgrade';

  // -----------------------------------------------------------------------
  // Helpers
  function toast(msg, ok = true) {
    if (!elMsg) return;
    elMsg.textContent = msg;
    elMsg.style.color = ok ? 'var(--text,#111)' : '#c0392b';
    setTimeout(() => (elMsg.textContent = ''), 2500);
  }

  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await r.json(); } catch {}
    if (!r.ok || data.ok === false) {
      const err = (data && (data.error || data.detail)) || `${r.status} ${r.statusText}`;
      throw new Error(err);
    }
    return data;
  }

  function formData() {
    return {
      audience:   byId('audience')?.value || '',
      tone:       byId('tone')?.value || 'Friendly',
      goal:       byId('goal')?.value || 'content',
      platform:   byId('platform')?.value || '',
      language:   byId('language')?.value || 'English',
      constraints:byId('constraints')?.value || '',
      brand:      byId('brand')?.value || '',
      details:    byId('details')?.value || '',
    };
  }

  function escapeHtml(s){return (s||'').replace(/[&<>"']/g,m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}

  // -----------------------------------------------------------------------
  // Build
  byId('buildBtn')?.addEventListener('click', async () => {
    try {
      const data = await postJSON('/build', formData());
      elOutput.value = data.prompt || '';
      elConcise.value = data.concise || '';
      toast('Built ✅');
      log('Build', 'success');
    } catch (e) {
      toast('Build failed: ' + e.message, false);
      log('Build', 'error', e.message);
    }
  });

  // Enhance
  byId('enhanceBtn')?.addEventListener('click', async () => {
    const prompt = (elOutput.value || elConcise.value || '').trim();
    if (!prompt) return toast('Nothing to enhance. Build or paste a prompt first.', false);

    const mode = (elEnhMode?.value || 'medium').toLowerCase();
    try {
      const data = await postJSON('/enhance', { prompt, mode });
      const improved = data.prompt || '';
      if (improved) {
        elOutput.value = improved;
        toast(`Enhanced (${mode}) ✨`);
        if (data.usage)  showUsage(data.usage);
        if (data.credits)showCredits(data.credits);
        log('Enhance', 'success', `mode=${mode}`);
        const b = byId('badge-detailed');
        if (b){ b.style.display='inline-block'; b.textContent = `Enhanced: ${mode}`; }
      } else {
        toast('No content returned from enhancer.', false);
        log('Enhance', 'warn', 'empty result');
      }
    } catch (e) {
      toast('Enhance failed: ' + e.message, false);
      log('Enhance', 'error', e.message);
    }
  });

  // -----------------------------------------------------------------------
  // Usage/Credits meters + countdown HH:MM:SS
  let usageTimerId = null;
  let creditsTimerId = null;

  function formatHMS(msLeft){
    const totalSec = Math.max(0, Math.floor(msLeft/1000));
    const h = String(Math.floor(totalSec/3600)).padStart(2,'0');
    const m = String(Math.floor((totalSec%3600)/60)).padStart(2,'0');
    const s = String(totalSec%60).padStart(2,'0');
    return `${h}:${m}:${s}`;
  }

  function startCountdown(targetEl, resetAtIso, storeIdName){
    const el = byId(targetEl);
    if (!el || !resetAtIso) return;
    const resetAt = new Date(resetAtIso).getTime();
    if (storeIdName === 'usage' && usageTimerId)   { clearInterval(usageTimerId);   usageTimerId = null; }
    if (storeIdName === 'credits' && creditsTimerId){ clearInterval(creditsTimerId); creditsTimerId = null; }

    const tick = () => {
      const left = resetAt - Date.now();
      el.textContent = `Resets in ${formatHMS(left)}`;
    };
    tick();
    const id = setInterval(tick, 1000);
    if (storeIdName === 'usage') usageTimerId = id;
    if (storeIdName === 'credits') creditsTimerId = id;
  }

  function showUsage(u) {
    const bar = byId('usageBar'); const b = byId('usageBadge'); const t = byId('resetTimerUsage');
    if (!bar || !b || !t) return;
    bar.style.display = 'flex';

    const total = Number(u.limit ?? 0);
    const used  = Number(u.count ?? 0);
    const remaining = Number.isFinite(u.remaining) ? Number(u.remaining) : Math.max(0, total - used);

    b.textContent = `Free uses: ${remaining}/${total}`;
    startCountdown('resetTimerUsage', u.reset_at, 'usage');
  }

  function showCredits(c) {
    const bar = byId('creditsBar'); const b = byId('creditsBadge'); const t = byId('resetTimerCredits');
    if (!bar || !b || !t) return;
    bar.style.display = 'flex';

    const balance = Number(c.balance ?? 0);
    const maxBal  = Number(c.max_balance ?? 0);

    // Show "for paid" label only if we're in paid/rollover mode
    const paidTag = ROLLOVER_MODE ? '<span class="badge-paid">for paid</span>' : '';
    b.innerHTML = `Credits: ${balance}/${maxBal} ${paidTag}`;

    startCountdown('resetTimerCredits', c.reset_at, 'credits');
  }

  // Auto-fetch on load + refresh every 60s
  (async function initMeters(){
    try { const r=await fetch('/usage_today',{cache:'no-store'}); if(r.ok) showUsage(await r.json()); } catch{}
    try { const r2=await fetch('/credits_status',{cache:'no-store'}); if(r2.ok) showCredits(await r2.json()); } catch{}
    setInterval(async ()=>{
      try { const r=await fetch('/usage_today',{cache:'no-store'}); if(r.ok) showUsage(await r.json()); } catch{}
      try { const r2=await fetch('/credits_status',{cache:'no-store'}); if(r2.ok) showCredits(await r2.json()); } catch{}
    }, 60000);
  })();

  // -----------------------------------------------------------------------
  // Copy / Export / Split
  byId('copyBtn')?.addEventListener('click', () => {
    navigator.clipboard.writeText(elOutput.value || '');
    toast('Copied (detailed) 📋');
  });
  byId('copyConciseBtn')?.addEventListener('click', () => {
    navigator.clipboard.writeText(elConcise.value || '');
    toast('Copied (concise) 📋');
  });

  byId('exportTxtBtn')?.addEventListener('click', () => {
    const text = [elOutput.value, elConcise.value].filter(Boolean).join('\n\n---\n\n');
    if (!text.trim()) return toast('Nothing to export.', false);
    const blob = new Blob([text], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'promptwizard_export.txt';
    a.click();
    URL.revokeObjectURL(a.href);
    toast('Exported TXT 📝');
  });

  byId('exportPdfBtn')?.addEventListener('click', async () => {
    const items = [elOutput.value, elConcise.value].filter(Boolean);
    if (!items.length) return toast('Nothing to export.', false);
    try {
      const r = await fetch('/export_pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const blob = await r.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'promptwizard_export.pdf';
      a.click();
      URL.revokeObjectURL(a.href);
      toast('Exported PDF 📄');
      log('Export PDF', 'success');
    } catch (e) {
      toast('Export PDF failed: ' + e.message, false);
      log('Export PDF', 'error', e.message);
    }
  });

  byId('splitBtn')?.addEventListener('click', () => {
    byId('splitHost')?.classList.toggle('open');
  });

  // -----------------------------------------------------------------------
  // Emoji
  byId('addEmojiBtn')?.addEventListener('click', () => {
    const emoji = byId('emojiPick')?.value || '';
    if (!emoji) return;
    const ta = elOutput;
    const start = ta.selectionStart ?? ta.value.length;
    ta.value = ta.value.slice(0, start) + emoji + ' ' + ta.value.slice(start);
    ta.focus();
    ta.selectionStart = ta.selectionEnd = start + emoji.length + 1;
  });

  // -----------------------------------------------------------------------
  // Favorites
  byId('saveFavBtn')?.addEventListener('click', () => {
    const txt = (elOutput.value || '').trim();
    if (!txt) return toast('Nothing to save.', false);
    const key = 'pw:favs';
    const favs = JSON.parse(localStorage.getItem(key) || '[]');
    favs.unshift({ t: Date.now(), v: txt });
    localStorage.setItem(key, JSON.stringify(favs.slice(0, 50)));
    renderFavs();
    toast('Saved to favorites ⭐');
  });

  function renderFavs() {
    const host = byId('favoritesList'); if (!host) return;
    const favs = JSON.parse(localStorage.getItem('pw:favs') || '[]');
    host.innerHTML = '';
    favs.forEach((f, i) => {
      const div = document.createElement('div');
      div.className = 'fav-pre';
      div.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <strong>Favorite #${i + 1}</strong>
          <div style="display:flex;gap:6px;">
            <button class="btn" data-act="copy" data-i="${i}">Copy</button>
            <button class="btn" data-act="del" data-i="${i}">Delete</button>
          </div>
        </div>
        <pre style="white-space:pre-wrap;margin:0">${escapeHtml(f.v)}</pre>
      `;
      host.appendChild(div);
    });
    host.onclick = (e) => {
      const b = e.target.closest('button'); if (!b) return;
      const i = +b.dataset.i;
      const favs = JSON.parse(localStorage.getItem('pw:favs') || '[]');
      if (b.dataset.act === 'copy') {
        navigator.clipboard.writeText(favs[i]?.v || '');
        toast('Copied favorite 📋');
      } else if (b.dataset.act === 'del') {
        favs.splice(i, 1); localStorage.setItem('pw:favs', JSON.stringify(favs)); renderFavs();
      }
    };
  }
  renderFavs();

  // -----------------------------------------------------------------------
  // Templates modal (safe if /static/templates.json missing)
  byId('tmplBtn')?.addEventListener('click', async () => {
    byId('tmplModal').style.display = 'grid';
    await loadTemplatesModal();
  });
  byId('tmplClose')?.addEventListener('click', () => {
    byId('tmplModal').style.display = 'none';
  });

  async function loadTemplatesModal() {
    const list = byId('tmplList'); const preview = byId('tmplPreview');
    const applyBtn = byId('tmplApply'); const catSel = byId('tmplCat'); const search = byId('tmplSearch');
    if (!list || !preview || !applyBtn || !catSel) return;

    let items = await fetchTemplatesFallback();
    const cats = ['All', ...Array.from(new Set(items.map(x => x.category || x.cat || 'Other')))];
    catSel.innerHTML = cats.map(c => `<option>${c}</option>`).join('');
    let cur = null;

    function render() {
      const kw = (search.value || '').toLowerCase();
      const cat = catSel.value || 'All';
      list.innerHTML = '';
      items
        .filter(x => (cat === 'All' || (x.category||x.cat) === cat) && (!kw || (x.title||'').toLowerCase().includes(kw)))
        .forEach((x) => {
          const item = document.createElement('div');
          item.className = 'tmpl-item';
          item.innerHTML = `<div class="ti-title">${escapeHtml(x.title || '')}</div>
                            <div class="ti-cat">${escapeHtml(x.category || x.cat || '')}</div>`;
          item.addEventListener('click', () => {
            cur = x;
            preview.classList.remove('empty');
            preview.textContent = x.preview || x.text || '';
            applyBtn.disabled = false;
          });
          list.appendChild(item);
        });
    }
    render();
    search.oninput = render; catSel.onchange = render;

    applyBtn.onclick = () => {
      if (!cur) return;
      applyTemplateToForm(cur);
      byId('tmplModal').style.display = 'none';
    };
  }

  // QUICK PRESET (top select)
  (async function initQuickPreset(){
    const sel = byId('quickPreset');
    if (!sel) return;
    const items = await fetchTemplatesFallback();

    sel.innerHTML = `<option value="">-- choose preset --</option>`;
    const byCat = {};
    items.forEach((t, idx) => {
      const c = t.category || t.cat || 'Other';
      (byCat[c] ||= []).push({ i: idx, t });
    });
    Object.entries(byCat).forEach(([cat, arr]) => {
      const og = document.createElement('optgroup');
      og.label = cat;
      arr.forEach(({i,t}) => {
        const opt = document.createElement('option');
        opt.value = String(i);
        opt.textContent = t.title || `Preset #${i+1}`;
        og.appendChild(opt);
      });
      sel.appendChild(og);
    });

    sel.addEventListener('change', () => {
      const i = sel.value === '' ? -1 : Number(sel.value);
      if (i >= 0 && items[i]) {
        applyTemplateToForm(items[i]);
        byId('presetName') && (byId('presetName').value = items[i].title || '');
        toast('Preset applied ✅');
      }
    });
  })();

  async function fetchTemplatesFallback(){
    try {
      const r = await fetch('/static/templates.json', { cache: 'no-store' });
      if (r.ok) {
        const data = await r.json();
        if (Array.isArray(data) && data.length) return data;
      }
    } catch {}
    return [
      {"title":"Facebook Post - Product Launch","category":"Facebook","preview":"Create a Facebook post announcing a new product for {{audience}}. Tone: Friendly. Include CTA + 2 trending hashtags.","fill":{"audience":"Filipino freelancers","tone":"Friendly","goal":"Facebook post","platform":"Facebook","language":"English","constraints":"Short, catchy, with CTA","brand":"premium, witty"},"details":"Organic soap ₱199. Highlight natural ingredients."},
      {"title":"Instagram Caption - Giveaway","category":"Instagram","preview":"Write 3 Instagram captions for {{audience}} announcing a giveaway. Use emojis and hashtags.","fill":{"audience":"Gen Z creators","tone":"Playful","goal":"Instagram caption","platform":"Instagram","language":"Taglish","constraints":"≤120 chars, 3 emojis","brand":"fun, youthful"},"details":"Mechanics: follow + tag 3 friends. Winner Friday!"},
      {"title":"TikTok Script - Tutorial (30s)","category":"TikTok","preview":"Create a 30-sec TikTok how-to script for {{audience}} with a hook, 3 steps, and CTA.","fill":{"audience":"Beginners in Canva","tone":"Energetic","goal":"TikTok script","platform":"TikTok","language":"English","constraints":"Hook + 3 steps + CTA","brand":"helpful"},"details":"Topic: How to make viral posters. Mention free template."},
      {"title":"YouTube Script - Product Review (5 min)","category":"YouTube","preview":"Write a 5-min YouTube product review for {{audience}}. Include pros, cons, and verdict.","fill":{"audience":"Budget-conscious buyers","tone":"Informative","goal":"YouTube review","platform":"YouTube","language":"English","constraints":"Objective tone, timestamps","brand":"trustworthy"},"details":"Compare mid-range phones under ₱15k."},
      {"title":"LinkedIn Post - Founder Insight","category":"LinkedIn","preview":"Write a LinkedIn post for {{audience}} sharing a practical insight. Use 3 bullets + 1 question.","fill":{"audience":"Startup founders","tone":"Authoritative","goal":"LinkedIn post","platform":"LinkedIn","language":"English","constraints":"3 bullets + 1 question","brand":"expert, human"},"details":"Topic: Hiring your first marketer in a lean team."},
      {"title":"Blog Outline - SEO Intro","category":"Blog","preview":"Create a blog outline for {{audience}} with H2/H3 and 3 target keywords.","fill":{"audience":"Small business owners","tone":"Informative","goal":"Blog outline","platform":"Website","language":"English","constraints":"H2/H3 + meta description","brand":"educational"},"details":"Topic: Benefits of AI tools for marketing."},
      {"title":"Email Subject Lines - Flash Sale","category":"Email","preview":"Write 10 subject lines for {{audience}}. Include urgency, % discount, and one emoji.","fill":{"audience":"Ecommerce shoppers","tone":"Persuasive","goal":"Email subject lines","platform":"Email","language":"English","constraints":"≤45 chars, 1 emoji","brand":"bold"},"details":"Flash sale 24 hours only. 30% OFF sitewide."},
      {"title":"Product Description - Shopee/Lazada","category":"Ecommerce","preview":"Write a product listing for {{audience}} with features, benefits, specs, and FAQ.","fill":{"audience":"Online shoppers PH","tone":"Clear","goal":"Product description","platform":"Shopee/Lazada","language":"English","constraints":"Bulleted, scannable","brand":"practical"},"details":"Item: Minimalist LED desk lamp with 3 color temps."},
      {"title":"Twitter/X Thread - Tips (5 tweets)","category":"Twitter/X","preview":"Create a 5-tweet thread for {{audience}} with a hook, tips, CTA, and hashtags.","fill":{"audience":"Freelance designers","tone":"Actionable","goal":"Twitter thread","platform":"Twitter","language":"English","constraints":"≤280 chars per tweet","brand":"friendly"},"details":"Topic: Pricing your design services the smart way."},
      {"title":"Ad Copy - Facebook Primary Text + Headline","category":"Ads","preview":"Write 3 variations of FB ad primary text + headline for {{audience}}.","fill":{"audience":"SMB owners","tone":"Persuasive","goal":"Facebook post","platform":"Facebook Ads","language":"English","constraints":"Comply with ad policies, include CTA","brand":"trusted"},"details":"Offer: Free 7-day trial of social media scheduler."}
    ];
  }

  function applyTemplateToForm(t){
    const f = t.fill || {};
    if (byId('audience'))    byId('audience').value    = f.audience    ?? byId('audience').value;
    if (byId('tone'))        byId('tone').value        = f.tone        ?? byId('tone').value;
    if (byId('goal'))        byId('goal').value        = f.goal        ?? byId('goal').value;
    if (byId('platform'))    byId('platform').value    = f.platform    ?? byId('platform').value;
    if (byId('language'))    byId('language').value    = f.language    ?? byId('language').value;
    if (byId('constraints')) byId('constraints').value = f.constraints ?? byId('constraints').value;
    if (byId('brand'))       byId('brand').value       = f.brand       ?? byId('brand').value;
    if (byId('details'))     byId('details').value     = t.details     ?? byId('details').value;
  }

  // -----------------------------------------------------------------------
  // Merge Vars (simple replace: {{var}})
  byId('mergeVarsBtn')?.addEventListener('click', async () => {
    const vars = prompt('Enter variables as JSON (e.g. {"product":"soap","audience":"moms"})');
    if (!vars) return;
    let map = {};
    try { map = JSON.parse(vars); } catch (e) { return alert('Invalid JSON.'); }
    const apply = (s) => s.replace(/\{\{\s*([\w.-]+)\s*\}\}/g, (_, k) => (map[k] ?? `{{${k}}}`));
    if (elOutput.value)  elOutput.value  = apply(elOutput.value);
    if (elConcise.value) elConcise.value = apply(elConcise.value);
  });

  // Theme toggle
  (function themeInit(){
    const root = document.documentElement;
    const btn = byId('themeToggle');
    function apply(theme){
      root.setAttribute('data-theme', theme);
      if (btn) btn.textContent = theme === 'dark' ? '☀️ Light' : '🌙 Dark';
    }
    const saved = localStorage.getItem('theme') || 'light';
    apply(saved);
    btn?.addEventListener('click', () => {
      const cur = root.getAttribute('data-theme') || 'light';
      const next = cur === 'dark' ? 'light' : 'dark';
      localStorage.setItem('theme', next); apply(next);
    });
  })();

  // Free CTA & signup
  byId('ctaFree')?.addEventListener('click', () => {
    if (CAPTURE_REQUIRED) byId('signupModal').style.display = 'grid';
    else window.location.href = '/free';
  });
  byId('signupClose')?.addEventListener('click', () => {
    byId('signupModal').style.display = 'none';
  });
  byId('signupSubmit')?.addEventListener('click', async () => {
    const email = (byId('signupEmail')?.value || '').trim();
    const msg = byId('signupMsg');
    if (!email) { msg.textContent = 'Enter a valid email'; return; }
    msg.textContent = 'Sending…';
    try {
      const r = await postJSON('/api/signup', { email, source: 'free' });
      msg.innerHTML = `Done! <a href="${r.download_url}" target="_blank">Download here</a>`;
    } catch (e) {
      msg.textContent = e.message;
    }
  });

  // NEW: Upgrade button
  byId('upgradeBtn')?.addEventListener('click', () => {
    // open in new tab para di mawala ang gawa ng user
    window.open(UPGRADE_URL || '/upgrade', '_blank');
  });

  // Activity log
  function log(action, level = 'info', note = '') {
    const tbody = byId('activityBody'); if (!tbody) return;
    const tr = document.createElement('tr');
    const ts = new Date().toLocaleTimeString();
    tr.innerHTML = `<td>[${ts}]</td><td>${escapeHtml(action)}</td><td>${escapeHtml(level)}</td><td>${escapeHtml(note)}</td>`;
    tbody.prepend(tr);
    while (tbody.rows.length > 200) tbody.deleteRow(-1);
  }
})();

























