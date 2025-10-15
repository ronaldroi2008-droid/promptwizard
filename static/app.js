// ---------- helpers ----------
const $ = (s, el=document) => el.querySelector(s);

// ---------- DOM refs ----------
const form = $('#genForm');
const output = $('#output');
const outputConcise = $('#outputConcise');
const msg = $('#msg');
const historyDiv = $('#history');

const LS_KEY = 'pw_presets_v1';

// ---------- Build / Enhance / Copy / Save ----------
async function buildPrompt(e){
  try{
    if(e) e.preventDefault();
    if(msg) msg.textContent = 'Building…';
    const fd = new FormData(form);
    const payload = Object.fromEntries(fd.entries());

    const r = await fetch('/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if(!r.ok){
      const t = await r.text().catch(()=> '');
      throw new Error(`Build failed: ${r.status} ${r.statusText} ${t}`);
    }

    const data = await r.json();
    if(output) output.value = data.prompt || '';
    if(outputConcise) outputConcise.value = data.concise || '';
    if(msg) msg.textContent = data.ok ? 'Done.' : (data.error || 'Error');
  }catch(err){
    console.error(err);
    if(msg) msg.textContent = (err && err.message) ? err.message : 'Build error';
  }
}

async function enhanceField(fieldId){
  const box = document.getElementById(fieldId);
  const text = (box?.value || '').trim();
  if(!text){ if(msg) msg.textContent='Nothing to enhance.'; return; }
  try{
    if(msg) msg.textContent = 'Enhancing…';
    const r = await fetch('/enhance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: text }),
    });
    const data = await r.json();
    if(!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
    if(data.prompt) box.value = data.prompt;
    if(msg) msg.textContent = 'Enhanced.';
    if(data.usage)  updateUsageUI?.(data.usage);
    if(data.credits)updateCreditsUI?.(data.credits);
  }catch(err){
    console.error(err);
    if(msg) msg.textContent = (err && err.message) ? err.message : 'Enhance error';
  }
}

async function copyOut(e){ if(e) e.preventDefault(); await navigator.clipboard.writeText(output?.value||''); if(msg) msg.textContent='Copied.'; }
async function copyConcise(e){ if(e) e.preventDefault(); await navigator.clipboard.writeText(outputConcise?.value||''); if(msg) msg.textContent='Concise copied.'; }

async function saveItem(e){
  if(e) e.preventDefault();
  try{
    const r = await fetch('/save', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ prompt: output?.value||'' })});
    const d = await r.json();
    if(msg) msg.textContent = d.ok ? 'Saved.' : 'Error saving';
    loadHistory();
  }catch(err){
    console.error(err);
    if(msg) msg.textContent = 'Save error';
  }
}

async function loadHistory(){
  try{
    const r = await fetch('/history');
    const d = await r.json();
    if(!historyDiv) return;
    historyDiv.innerHTML = '';
    (d.items||[]).forEach(it=>{
      const div=document.createElement('div'); div.className='item';
      div.innerHTML=`<div class="small">${it.created_at}</div><pre style="white-space:pre-wrap;margin:0">${it.prompt}</pre>`;
      historyDiv.appendChild(div);
    });
  }catch(e){ /* ignore */ }
}

// ---------- Presets (local only) ----------
function applyPreset(val){
  if(val?.startsWith('user:')){ applyUserPreset(val.slice(5)); return; }
  if(val==='ecom_ig'){
    form.audience.value='Online shoppers, young adults';
    form.tone.value='Friendly';
    form.goal.value='Instagram caption';
    form.platform.value='Instagram Reels';
    form.constraints.value='120 chars, include CTA';
    form.brand.value='witty';
  }
  if(val==='tiktok_hook'){
    form.audience.value='Gen Z TikTok users';
    form.tone.value='Casual';
    form.goal.value='TikTok script';
    form.platform.value='TikTok';
    form.constraints.value='Short, catchy, use 2 trending hashtags';
    form.brand.value='playful';
  }
  if(val==='email_subject'){
    form.audience.value='Newsletter subs';
    form.tone.value='Persuasive';
    form.goal.value='Email subject lines';
    form.platform.value='Email';
    form.constraints.value='Under 60 chars';
    form.brand.value='premium';
  }
}
function getPresets(){ try { return JSON.parse(localStorage.getItem(LS_KEY)||'{}'); } catch(e){ return {}; } }
function setPresets(obj){ localStorage.setItem(LS_KEY, JSON.stringify(obj)); }
function renderUserPresets(){
  const og=document.getElementById('myPresets'); if(!og) return;
  og.innerHTML='';
  const p=getPresets();
  Object.keys(p).sort().forEach(name=>{
    const opt=document.createElement('option');
    opt.value='user:'+name; opt.textContent=name;
    og.appendChild(opt);
  });
  renderPresetList();
}
function renderPresetList(){
  const list=document.getElementById('presetList'); if(!list) return;
  const p=getPresets(); list.innerHTML='';
  const names=Object.keys(p).sort();
  if(names.length===0){ list.innerHTML='<div class="small">No saved presets yet.</div>'; return; }
  names.forEach(name=>{
    const row=document.createElement('div'); row.className='item';
    row.innerHTML=`<b>${name}</b>
      <div class="small">${Object.keys(p[name]).join(', ')}</div>
      <div style="margin-top:6px">
        <button data-load="${name}">Load</button>
        <button class="ghost" data-del="${name}">Delete</button>
      </div>`;
    list.appendChild(row);
  });
  list.addEventListener('click',(e)=>{
    const load=e.target.getAttribute('data-load');
    const del=e.target.getAttribute('data-del');
    if(load){ applyUserPreset(load); }
    if(del){
      if(confirm('Delete preset "'+del+'"?')){
        const obj=getPresets(); delete obj[del]; setPresets(obj); renderUserPresets();
      }
    }
  }, { once:true });
}
function applyUserPreset(name){
  const p=getPresets()[name]; if(!p) return;
  Object.entries(p).forEach(([k,v])=>{ if(form[k]!==undefined) form[k].value=v; });
}

// ---------- Usage/Credits bars ----------
let resetTimerInterval=null;
function formatHMS(sec){
  sec=Math.max(0,Math.floor(sec));
  const h=String(Math.floor(sec/3600)).padStart(2,'0');
  const m=String(Math.floor((sec%3600)/60)).padStart(2,'0');
  const s=String(sec%60).padStart(2,'0');
  return `${h}:${m}:${s}`;
}
function startCountdown(elementId, resetIso){
  const el=document.getElementById(elementId); if(!el) return;
  if(resetTimerInterval) clearInterval(resetTimerInterval);
  const target=Date.parse(resetIso);
  function tick(){
    const left=(target-Date.now())/1000;
    el.textContent='Resets in: '+formatHMS(left);
    if(left<=0){ clearInterval(resetTimerInterval); refreshUsage?.(); refreshCredits?.(); }
  }
  tick(); resetTimerInterval=setInterval(tick,1000);
}
function updateUsageUI(u){
  const tag=document.getElementById('usageBadge'); if(tag){
    tag.textContent = `Usage: ${u.count}/${u.limit} (left ${u.remaining})`;
    const pct = u.limit ? (u.count/u.limit)*100 : 0;
    if(pct >= 80) tag.classList.add('warn'); else tag.classList.remove('warn');
  }
  if(u.reset_at) startCountdown('resetTimerUsage', u.reset_at);
}
async function refreshUsage(){
  try{
    const r=await fetch('/usage_today'); const u=await r.json();
    updateUsageUI(u);
  }catch(e){}
}
function updateCreditsUI(c){
  const tag=document.getElementById('creditsBadge'); if(!tag) return;
  tag.textContent=`Credits: ${c.balance}/${c.max_balance}`;
  if(c.reset_at) startCountdown('resetTimerCredits', c.reset_at);
}
async function refreshCredits(){
  try{
    const r=await fetch('/credits_status'); const c=await r.json();
    updateCreditsUI(c);
  }catch(e){}
}

// Paid/free detection resilient to "paid" or "paid_credits"
async function initModeBars(){
  try{
    const r = await fetch('/health');
    const h = await r.json();
    const mode = (h.mode||'').toLowerCase();
    const isPaid = (mode === 'paid' || mode === 'paid_credits');

    const usageBar = document.getElementById('usageBar');
    const creditsBar = document.getElementById('creditsBar');

    if(isPaid){
      if(creditsBar) creditsBar.style.display = 'flex';
      if(usageBar) usageBar.style.display = 'none';
      refreshCredits();
    }else{
      if(usageBar) usageBar.style.display = 'flex';
      if(creditsBar) creditsBar.style.display = 'none';
      refreshUsage();
    }
  }catch(e){
    // fallback: try credits endpoint; if it returns balance, assume paid
    try{
      const r=await fetch('/credits_status');
      if(r.ok){
        const c=await r.json();
        if(typeof c.balance === 'number'){
          document.getElementById('creditsBar')?.style.setProperty('display','flex');
          document.getElementById('usageBar')?.style.setProperty('display','none');
          updateCreditsUI(c);
          return;
        }
      }
    }catch(_){}
    // default to free meter
    document.getElementById('usageBar')?.style.setProperty('display','flex');
  }
}

// ---------- Theme toggle ----------
(function themeInit(){
  const root = document.documentElement;
  const btn = document.getElementById('themeToggle');
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

// ---------- Free CTA + Signup modal ----------
document.getElementById('ctaFree')?.addEventListener('click', () => {
  if (window.CAPTURE_REQUIRED) {
    document.getElementById('signupModal').style.display = 'grid';
  } else if (window.FREE_PROMPTS_URL) {
    // direct link or local /static PDF
    window.location.href = window.FREE_PROMPTS_URL;
  } else {
    window.location.href = '/free';
  }
});
document.getElementById('signupClose')?.addEventListener('click', () => {
  document.getElementById('signupModal').style.display = 'none';
});
document.getElementById('signupSubmit')?.addEventListener('click', async () => {
  const email = (document.getElementById('signupEmail')?.value || '').trim();
  const msgEl = document.getElementById('signupMsg');
  if (!email) { msgEl.textContent = 'Enter a valid email'; return; }
  msgEl.textContent = 'Sending…';
  try {
    const r = await fetch('/api/signup', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ email, source: 'free' })});
    const data = await r.json();
    if(!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
    msgEl.innerHTML = `Done! <a href="${data.download_url}" target="_blank" rel="noopener">Download here</a>`;
  } catch (e) {
    msgEl.textContent = e.message || 'Error';
  }
});

// ---------- Listeners ----------
document.getElementById('buildBtn')?.addEventListener('click', buildPrompt);
document.getElementById('enhanceBtn')?.addEventListener('click', (e)=>{ e.preventDefault(); enhanceField('output'); });
document.getElementById('enhanceConciseBtn')?.addEventListener('click', (e)=>{ e.preventDefault(); enhanceField('outputConcise'); });
document.getElementById('copyBtn')?.addEventListener('click', (e)=>{ e.preventDefault(); copyOut(e); });
document.getElementById('copyConciseBtn')?.addEventListener('click', (e)=>{ e.preventDefault(); copyConcise(e); });
document.getElementById('saveBtn')?.addEventListener('click', (e)=>{ e.preventDefault(); saveItem(e); });

// ---------- Init ----------
window.addEventListener('load', ()=>{
  loadHistory();
  renderUserPresets?.();
  initModeBars();
  setInterval(()=> initModeBars(), 60000);
});
