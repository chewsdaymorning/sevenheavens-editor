'use strict';

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const e = escapeHtml;
const state = {data:null, projectId:localStorage.getItem('sevenheavens-project'), tab:'direction', planId:null, dirty:false, importing:false, musicMaps:{}};
const time = value => Number(value || 0).toFixed(2) + 's';
const fileName = asset => asset?.original_path?.split(/[\\/]/).pop() || 'Unavailable source';
const mediaUrl = asset => `/api/assets/${encodeURIComponent(asset.id)}/media`;
const outputUrl = plan => `/api/plans/${encodeURIComponent(plan.id)}/output`;
const project = () => state.data?.projects?.find(item => item.id === state.projectId);
const projectPlans = () => (state.data?.plans || []).filter(item => item.project_id === state.projectId).sort((a,b) => b.version-a.version);
const projectJobs = () => (state.data?.jobs || []).filter(item => item.project_id === state.projectId).sort((a,b) => b.created_at.localeCompare(a.created_at));
const assetById = id => state.data?.assets?.find(item => item.id === id);
const activePlan = () => projectPlans().find(item => item.id === state.planId) || projectPlans()[0];
let noticeTimer;

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers:{'Content-Type':'application/json',...options.headers}});
  let body;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) {
    const detail = body?.detail || body?.error || `Request failed (${response.status})`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return body;
}
const send = (path, body, method = 'POST') => api(path, {method,body:JSON.stringify(body)});

function notify(message, error = false) {
  clearTimeout(noticeTimer);
  const node = $('#notice'); node.textContent = message; node.classList.toggle('error', error); node.hidden = false;
  noticeTimer = setTimeout(() => { node.hidden = true; }, error ? 10000 : 5000);
}

async function refresh({render = true} = {}) {
  try {
    state.data = await api('/api/state');
    if (!project() && state.projectId) { state.projectId = null; localStorage.removeItem('sevenheavens-project'); }
    $('#service-state').textContent = state.data.ai_configured ? 'Local analysis connected' : 'AI setup pending · $0 cloud spend';
    renderSidebar();
    if (render) renderWorkspace();
  } catch (error) {
    $('#service-state').textContent = 'Local service unavailable';
    if (!state.data) $('#workspace').innerHTML = `<section class="welcome"><span class="eyebrow">CONNECTION</span><h1>The studio is<br>waiting to connect.</h1><p class="lede">The local service could not be reached. Start the application, then try again.</p><div class="callout error">${e(error.message)}</div><button class="button secondary spacer-top" data-action="refresh">Try again</button></section>`;
    else notify(error.message, true);
  }
}

function renderSidebar() {
  const projects = state.data?.projects || [];
  $('#project-count').textContent = projects.length;
  $('#project-list').innerHTML = projects.length ? projects.map(item => `<button class="project-item ${item.id===state.projectId?'active':''}" data-project="${e(item.id)}" ${item.id===state.projectId?'aria-current="page"':''}><strong>${e(item.name)}</strong><small>${item.width}:${item.height} · ${item.duration_s ? time(item.duration_s) : 'Duration open'}</small></button>`).join('') : '<p class="muted small">Your edits will appear here.</p>';
}

function modeLabel(mode) { return ({live_ai:'AI selected',assisted:'Manual selection',fixture:'Test fixture',offline:'Offline'})[mode] || mode; }
function badge(text, type='neutral') { return `<span class="badge ${type}">${e(text)}</span>`; }
function assetOptions(role, selected, emptyText) {
  return `<option value="">${e(emptyText)}</option>`+(state.data.assets || []).filter(a=>a.role===role).map(a=>`<option value="${e(a.id)}" ${a.id===selected?'selected':''}>${e(fileName(a))}</option>`).join('');
}
function empty(title, description, action='', label='') {
  return `<div class="empty-state"><div class="empty-symbol" aria-hidden="true">↗</div><h3>${e(title)}</h3><p>${e(description)}</p>${action?`<button class="button secondary" data-action="${e(action)}">${e(label)}</button>`:''}</div>`;
}

function renderWorkspace() {
  const p = project();
  if (!p) return;
  const plans = projectPlans();
  const shots = activePlan()?.shots || [];
  $('#workspace').innerHTML = `<div class="page-heading"><div><span class="eyebrow">EDIT WORKSPACE</span><h1>${e(p.name)}</h1><p>${p.width} × ${p.height} · ${e(time(p.duration_s))} · ${(p.fps_num/p.fps_den).toFixed(2).replace(/\.00$/,'')} fps</p></div><div class="heading-actions">${badge(state.data.ai_configured?'Local analysis ready':'AI setup pending',state.data.ai_configured?'':'warning')}<button class="button secondary small" data-action="import">Add media +</button></div></div>
    <nav class="section-tabs" aria-label="Edit steps">${[['direction','Direction','01'],['footage','Footage',p.source_asset_ids.length],['shots','Selected shots',shots.length],['versions','Versions',plans.length]].map(([key,label,count])=>`<button class="tab ${state.tab===key?'active':''}" data-tab="${key}" ${state.tab===key?'aria-current="page"':''}>${label}<span>${count}</span></button>`).join('')}</nav>
    <div id="tab-content">${({direction:directionView,footage:footageView,shots:shotsView,versions:versionsView})[state.tab]()}</div>`;
  wireForms();
  if (state.tab==='direction' && p.music_asset_id) loadMusicMap(p.music_asset_id);
}

function directionView() {
  const p = project();
  const sourceAssets = state.data.assets.filter(a=>a.role==='source');
  return `<div class="layout-grid"><div class="stack"><section class="panel"><div class="panel-header"><div><h2>The direction</h2><p>Set the intent and the boundaries for this piece.</p></div></div><form id="brief-form" class="panel-body">
    <label>Edit name<input name="name" value="${e(p.name)}" required maxlength="120"></label><label>Creative direction<textarea name="directions" rows="5" placeholder="What should the viewer see and feel? Which moments matter?">${e(p.directions)}</textarea></label>
    <div class="form-grid"><label>Reference approach<select name="reference_mode"><option value="recreate" ${p.reference_mode==='recreate'?'selected':''}>Match structure & timing</option><option value="adapt" ${p.reference_mode==='adapt'?'selected':''}>Adapt the style</option></select></label><label>Confirmed outfit / product<input name="product_group" value="${e(p.product_group || '')}" placeholder="Any confirmed group"></label></div>
    <div class="form-grid three"><label>Duration <span class="field-unit">seconds</span><input name="duration_s" type="number" min="1" max="120" step="0.01" value="${p.duration_s || ''}"></label><label>Frame rate<select name="fps_num">${[24,25,30].map(n=>`<option value="${n}" ${p.fps_num===n?'selected':''}>${n} fps</option>`).join('')}${![24,25,30].includes(p.fps_num)?`<option value="${p.fps_num}" selected>${p.fps_num}/${p.fps_den} fps</option>`:''}</select></label><label>Format<select name="format"><option value="1080x1920" ${p.width===1080&&p.height===1920?'selected':''}>Portrait · 9:16</option><option value="1080x1080" ${p.width===1080&&p.height===1080?'selected':''}>Square · 1:1</option><option value="1920x1080" ${p.width===1920&&p.height===1080?'selected':''}>Landscape · 16:9</option>${!['1080x1920','1080x1080','1920x1080'].includes(`${p.width}x${p.height}`)?`<option value="${p.width}x${p.height}" selected>${p.width} × ${p.height}</option>`:''}</select></label></div>
    <label>Must keep / must avoid <span class="field-unit">one per line</span><textarea name="hard_constraints" rows="3" placeholder="Keep the whole garment visible. No replacement footage.">${e((p.hard_constraints || []).join('\n'))}</textarea></label>
    <label class="check-row"><input name="allow_crop" type="checkbox" ${p.allow_crop?'checked':''}> Allow reframing and cropping</label>
    <label>Source pool</label>${sourceAssets.length?sourceAssets.map(a=>`<label class="check-row"><input type="checkbox" name="source_asset_ids" value="${e(a.id)}" ${p.source_asset_ids.includes(a.id)?'checked':''}><span>${e(fileName(a))} <span class="muted">· ${e(a.product_group || 'Group unconfirmed')}</span></span></label>`).join(''):'<p class="form-note">Add source footage to choose the pool for this edit.</p>'}
    <p id="brief-error" class="inline-error" role="alert" hidden></p><div class="inline-actions spacer-top"><button class="button secondary" type="submit">Save direction</button><span class="small muted" id="save-state">${state.dirty?'Unsaved changes':''}</span></div></form></section>
    <section class="panel"><div class="panel-header"><h2>Reference & music</h2></div><div class="panel-body"><div class="media-slots"><div class="media-slot"><h3>Your reference</h3><p>Supplied by you; used for the chosen approach.</p><select aria-label="Reference video" id="reference-select">${assetOptions('reference',p.reference_asset_id,'No reference selected')}</select>${p.reference_asset_id?`<video class="spacer-top" controls preload="metadata" src="${mediaUrl(assetById(p.reference_asset_id)||{id:p.reference_asset_id})}"></video>`:''}</div><div class="media-slot"><h3>Your soundtrack</h3><p>The exact excerpt matters for the cut.</p><select aria-label="Music track" id="music-select">${assetOptions('music',p.music_asset_id,'No music selected')}</select>${p.music_asset_id?`<audio class="spacer-top" controls preload="metadata" src="${mediaUrl(assetById(p.music_asset_id)||{id:p.music_asset_id})}"></audio>`:''}<label class="spacer-top">Excerpt start <span class="field-unit">seconds</span><input id="music-offset" type="number" min="0" step="0.01" value="${p.music_offset_s || 0}"></label></div></div><button class="button secondary small spacer-top" data-action="save-media">Save reference & music</button>${p.music_asset_id?musicMapView():''}</div></section></div>
    <aside class="stack"><section class="panel"><div class="panel-header"><h2>Make the first cut</h2></div><div class="panel-body"><p class="section-description">Analyze the reference and source footage to propose usable moments, then review their source ranges.</p>${!state.data.ai_configured?'<div class="callout warning"><strong>Local AI setup is pending.</strong>No footage analysis has run. Connect the approved local model before expecting selected moments.</div>':''}<div class="input-summary spacer-top"><span><strong>${p.source_asset_ids.length}</strong> source clips</span><span><strong>${p.reference_asset_id?'1':'0'}</strong> reference</span></div></div><div class="panel-footer"><span class="muted">Local processing · no cloud calls</span><button class="button primary" data-action="analyze" ${!p.source_asset_ids.length?'disabled':''}>Analyze footage</button></div></section><section class="panel"><div class="panel-header"><h2>Activity</h2><button class="button quiet small" data-action="refresh">Refresh</button></div><div class="panel-body" id="jobs-region">${jobsView()}</div></section></aside></div>`;
}

function musicMapView() {
  const p = project(), map = state.musicMaps[p.music_asset_id];
  return `<details><summary>Adjust musical anchors</summary><p class="form-note">Enter the track’s absolute timestamps after listening. These are manual anchors, not detected beats.</p><form id="music-map-form"><label>Anchor timestamps <span class="field-unit">seconds, separated by commas</span><input name="anchors" value="${e((map?.manual_anchors_s || []).join(', '))}" placeholder="0.50, 1.00, 1.50"></label><label class="check-row"><input name="verified" type="checkbox" ${map?.verified?'checked':''}> I checked these anchors against the music</label><button class="button secondary small" type="submit">Save anchors</button></form></details>`;
}
async function loadMusicMap(id) {
  if (id in state.musicMaps) return;
  state.musicMaps[id] = null;
  try {
    const map = await api(`/api/music-maps/${encodeURIComponent(id)}`); state.musicMaps[id] = map;
    const input = $('#music-map-form [name=anchors]'); if (input && document.activeElement !== input) input.value = (map?.manual_anchors_s || []).join(', ');
    const check = $('#music-map-form [name=verified]'); if (check) check.checked = !!map?.verified;
  } catch { /* A track without a saved map starts with explicitly manual, empty anchors. */ }
}

function footageView() {
  const assets = state.data.assets || [];
  return `<div class="page-heading"><div><h2 style="font-size:16px;font-weight:500;margin:0 0 5px">Registered media</h2><p>Source files are read from your chosen folder. Select a source pool in Direction.</p></div><button class="button secondary" data-action="import">Add media +</button></div>${assets.length?`<div class="asset-grid">${assets.map(a=>`<article class="asset-card">${a.role==='music'?`<div class="asset-audio"><audio controls preload="none" src="${mediaUrl(a)}"></audio></div>`:`<video controls preload="metadata" src="${mediaUrl(a)}"></video>`}<div class="asset-info"><h3>${e(fileName(a))}</h3><div class="asset-meta">${e(a.role)} · ${time(a.duration_s)}${a.width?` · ${a.width} × ${a.height}`:''}</div>${badge(a.product_group || 'Product group unconfirmed',a.product_group?'':'warning')}<p class="status-line">${e(a.rate_mode)}${a.rotation_degrees?` · rotation ${a.rotation_degrees}°`:''}</p>${(a.warnings||[]).map(w=>`<p class="small" style="color:var(--warning)">${e(w)}</p>`).join('')}<details><summary>Source details</summary><p class="status-line">${e(a.original_path)}</p><p class="status-line">${e(a.color_transfer || 'Color transfer not tagged')} · ${e(a.color_primaries || 'Primaries not tagged')}</p><p class="status-line">SHA-256 ${e(a.sha256)}</p></details></div></article>`).join('')}</div>`:empty('Bring in your shoot','Choose a local media folder, then register source footage, your reference and music.','import','Add your first files')}`;
}

function jobsView() {
  const jobs = projectJobs();
  return jobs.length?`<div class="job-list">${jobs.slice(0,5).map(j=>`<article class="job-row"><div class="job-top"><span class="job-name">${e(j.stage==='analyze'?'Footage analysis':j.stage==='render'?'Render':j.stage)}</span>${badge(j.status.replaceAll('_',' '),['blocked','needs_attention'].includes(j.status)?'warning':j.status==='failed'?'error':j.status==='succeeded'?'':'neutral')}</div><p class="job-meta">${e(modeLabel(j.mode))} · ${new Date(j.created_at).toLocaleString()}</p>${j.error?`<p class="job-error">${e(j.error)}</p>`:''}${['queued','running'].includes(j.status)?`<div class="job-progress" role="progressbar" aria-label="Job progress" aria-valuenow="${Math.round(j.progress*100)}" aria-valuemin="0" aria-valuemax="100"><span style="width:${Math.round(j.progress*100)}%"></span></div><div class="job-actions"><button class="button quiet small" data-cancel="${e(j.id)}">Cancel</button></div>`:''}</article>`).join('')}</div>`:'<p class="section-description" style="margin:0">No analysis or render has been requested for this edit.</p>';
}

function shotsView() {
  const plan = activePlan();
  if (!plan) return `<div class="stack"><section class="panel">${empty('No selected moments yet','Selected shots will appear here after a real analysis. Each shot will show the source file, interval and decision evidence.')}<div class="panel-body">${!state.data.ai_configured?'<div class="callout warning"><strong>AI analysis is not connected.</strong>There are no inferred choices or sample edits in this workspace.</div>':''}</div></section>${manualPanel()}</div>`;
  const candidates = state.data.candidates || state.data.candidate_windows || [];
  return `<div class="layout-grid"><section class="panel"><div class="panel-header"><div><h2>The selected moments</h2><p>Version ${plan.version} · ${e(plan.variation_label)}</p></div>${badge(modeLabel(plan.mode),plan.mode==='fixture'?'warning':'')}</div><div class="panel-body"><div class="shot-list">${plan.shots.map((shot,index)=>{
    const asset=assetById(shot.asset_id), c=candidates.find(item=>item.id===shot.candidate_id);
    const run=(state.data.analysis_runs||[]).find(item=>item.id===c?.analysis_run_id);
    return `<article class="shot-card"><div class="shot-thumb">${asset?`<video controls preload="metadata" src="${mediaUrl(asset)}#t=${shot.source_start_s},${shot.source_end_s}"></video>`:'<span class="small muted">Source unavailable</span>'}<span class="shot-number">${String(index+1).padStart(2,'0')}</span></div><div class="shot-details"><h3>${e(fileName(asset))}</h3><p>${e(c?.action || c?.role || (shot.manual_override_reason?'Manually chosen source interval':'Selection evidence is attached to the plan.'))}</p><div class="shot-times"><span>Source range<strong>${time(shot.source_start_s)} – ${time(shot.source_end_s)}</strong></span><span>In the edit<strong>${time(shot.timeline_start_frame*plan.fps_den/plan.fps_num)} – ${time(shot.timeline_end_frame*plan.fps_den/plan.fps_num)}</strong></span></div>${c?`<p class="confidence">Model confidence ${Math.round(c.confidence*100)}% · ${e(c.framing)}</p>${(c.warnings||[]).map(w=>`<p style="color:var(--warning)">${e(w)}</p>`).join('')}`:''}<p class="provenance">${e(shot.manual_override_reason?`Manual override: ${shot.manual_override_reason}`:shot.candidate_id?`Candidate ${shot.candidate_id}`:'No candidate evidence')}</p><div class="shot-bottom"><a class="small muted" href="${asset?mediaUrl(asset)+'#t='+shot.source_start_s:'#'}" target="_blank" rel="noopener">Open source ↗</a><button class="button secondary small" data-edit-shot="${e(shot.id)}">Replace / trim</button></div></div></article>`;
  }).join('')}</div></div></section><aside class="stack">${renderPanel(plan)}${coveragePanel(plan)}<section class="panel"><div class="panel-header"><h2>Decision record</h2></div><div class="panel-body"><p class="section-description">The plan keeps source intervals and the evidence supplied by the analysis. Manual changes are identified.</p>${plan.shots.map(shot=>{const c=candidates.find(item=>item.id===shot.candidate_id),run=(state.data.analysis_runs||[]).find(item=>item.id===c?.analysis_run_id);return c?`<p class="status-line"><strong>${e(c.action||c.role||'Candidate')}</strong><br>Source samples: ${(c.sample_times_s||[]).map(t=>e(time(t))).join(', ')||'None recorded'}<br>${e(run?`${run.provider||'Local provider'} · ${run.model||'Model not recorded'}`:'Call metadata unavailable')}${c.analysis_run_id?`<br><a href="/api/analysis-runs/${encodeURIComponent(c.analysis_run_id)}/evidence" target="_blank" rel="noopener">Inspect recorded model inputs / decisions ↗</a>`:''}</p>`:'';}).join('')}<details><summary>Inspect plan & provenance</summary><pre>${e(JSON.stringify(plan,null,2))}</pre></details><a class="button quiet small spacer-top" href="/api/plans/${encodeURIComponent(plan.id)}" target="_blank" rel="noopener">Open canonical plan ↗</a></div></section></aside></div>`;
}
function manualRow() {
  return `<div class="manual-row form-grid three"><label>Source<select name="asset_id">${project().source_asset_ids.map(id=>assetById(id)).filter(Boolean).map(a=>`<option value="${e(a.id)}">${e(fileName(a))} · ${time(a.duration_s)}</option>`).join('')}</select></label><label>Source in (seconds)<input name="source_start_s" type="number" min="0" step="0.01" value="0" required></label><label>Source out (seconds)<input name="source_end_s" type="number" min="0.01" step="0.01" value="2" required></label></div>`;
}
function manualPanel() {
  if (!project().source_asset_ids.length) return '';
  return `<section class="panel"><div class="panel-header"><h2>Create an assisted cut</h2>${badge('Manual selection','warning')}</div><form id="manual-plan-form" class="panel-body"><p class="section-description">Choose the actual source ranges yourself to test playback, rendering and revisions. This does not run AI selection. The total length must match your saved direction, or leave duration open.</p><div id="manual-rows">${manualRow()}</div><button type="button" class="button quiet small" data-action="add-manual-shot">Add another shot</button><label class="spacer-top">Why these moments?<input name="manual_reason" required placeholder="Your reason for these source choices"></label><p id="manual-error" class="inline-error" role="alert" hidden></p><button type="submit" class="button secondary">Save manual plan</button></form></section>`;
}
function renderPanel(plan) {
  return `<section class="panel"><div class="panel-header"><h2>Render this version</h2></div><div class="panel-body"><p class="section-description">Compile the selected source intervals into the complete edit. Previous versions keep their own outputs.</p>${badge(modeLabel(plan.mode),plan.mode==='fixture'?'warning':'')}</div><div class="panel-footer"><span class="muted">Version ${plan.version}</span><button class="button primary" data-render="${e(plan.id)}" ${plan.coverage_gaps?.length?'disabled':''}>Render edit</button></div></section>`;
}
function coveragePanel(plan) {
  return plan.coverage_gaps?.length?`<section class="panel"><div class="panel-header"><h2>Coverage needs attention</h2></div><div class="panel-body"><ul class="coverage-list">${plan.coverage_gaps.map(g=>`<li>${e(g)}</li>`).join('')}</ul><p class="form-note">Resolve the missing coverage before rendering this plan.</p></div></section>`:'';
}
function versionsView() {
  const plans=projectPlans(), plan=activePlan();
  if (!plan) return `<section class="panel">${empty('Your first version belongs here','Once a plan is rendered, play the complete edit here. Corrections create a new version and keep earlier plans intact.')}</section>`;
  const rendered=projectJobs().some(j=>j.plan_id===plan.id&&j.stage==='render'&&j.status==='succeeded');
  const corrections=(state.data.corrections||[]).filter(c=>c.project_id===state.projectId);
  return `<div class="layout-grid"><section class="panel">${rendered?`<div class="output-player"><video controls preload="metadata" src="${outputUrl(plan)}"></video></div>`:empty('This version has no rendered output','Review its selected moments, then render to create a playable complete edit.')}<div class="output-info"><h3>${e(plan.variation_label)} · Version ${plan.version}</h3>${badge(modeLabel(plan.mode),plan.mode==='fixture'?'warning':'')}<p class="status-line">${plan.width} × ${plan.height} · ${plan.shots.length} shots · ${time(plan.shots.at(-1).timeline_end_frame*plan.fps_den/plan.fps_num)}</p><div class="output-actions">${rendered?`<a class="button primary" href="${outputUrl(plan)}" download>Download MP4 ↗</a>`:`<button class="button primary" data-render="${e(plan.id)}">Render edit</button>`}<button class="button secondary" data-tab="shots">Review shots</button><a class="button quiet" href="/api/plans/${encodeURIComponent(plan.id)}" target="_blank" rel="noopener">Canonical plan ↗</a></div><p class="form-note">Native editor export has not been connected. The canonical plan preserves the edit decisions.</p></div></section><aside class="stack"><section class="panel"><div class="panel-header"><h2>Version history</h2></div><div class="panel-body"><div class="version-list">${plans.map(v=>`<button class="version-button ${v.id===plan.id?'active':''}" data-plan="${e(v.id)}"><span>Version ${v.version} · ${e(v.variation_label)}</span><span>${e(modeLabel(v.mode))}</span></button>`).join('')}</div></div></section><section class="panel"><div class="panel-header"><h2>Saved corrections</h2></div><div class="panel-body">${corrections.length?`<ul class="feedback-list">${corrections.map(c=>`<li>${e(c.reason)}<br><span class="provenance">${e(({edit:'This edit',format:'This format',reusable_rule:'Reusable rule'})[c.scope])} · ${e(c.approval_state)}</span></li>`).join('')}</ul>`:'<p class="section-description">Replace or trim a shot to save a correction. Choose where that decision should apply.</p>'}<p class="form-note">Saved decisions are workflow memory. They do not train the model’s parameters.</p></div></section><section class="panel"><div class="panel-header"><h2>Activity</h2></div><div class="panel-body">${jobsView()}</div></section></aside></div>`;
}

function openImport() {
  $('#import-content').innerHTML = `<p class="section-description">Select a folder by its actual path, then register files inside it. Originals remain in place.</p><form id="media-root-form"><label>Media folder on this Mac<input name="path" required placeholder="/Users/you/Movies/Sevenheavens/shoot-01" autocomplete="off"></label><button class="button secondary small" type="submit">Select folder</button></form><p class="status-line" id="selected-roots">${(state.data?.media_roots||[]).length?'Selected folders: '+(state.data.media_roots||[]).map(r=>e(typeof r==='string'?r:r.path)).join(' · '):'No media folder selected yet.'}</p><form id="media-import-form" class="spacer-top"><label>Files to register <span class="field-unit">one absolute path per line</span><textarea name="paths" rows="4" required placeholder="/Users/you/Movies/Sevenheavens/shoot-01/take-01.mov"></textarea></label><div class="form-grid"><label>Use these files as<select name="role"><option value="source">Source footage</option><option value="reference">Reference</option><option value="music">Music</option></select></label><label>Confirmed outfit / product<input name="product_group" placeholder="Optional, confirmed by you"></label></div><p class="form-note">Import one reference or track at a time. Source clips are added to this edit’s selected pool.</p><p id="import-error" class="inline-error" role="alert" hidden></p><div id="import-result" class="import-result" role="status"></div><div class="dialog-footer"><button class="button secondary" type="button" data-close="import-dialog">Close</button><button class="button primary" type="submit">Register files</button></div></form>`;
  $('#import-dialog').showModal();
  $('#media-root-form').addEventListener('submit',async event=>{
    event.preventDefault(); const form=event.currentTarget,path=new FormData(form).get('path').trim();
    await guarded(form,async()=>{await send('/api/media-roots',{path});await refresh({render:false});$('#selected-roots').textContent='Selected folders: '+state.data.media_roots.map(r=>typeof r==='string'?r:r.path).join(' · ');notify('Media folder selected.');});
  });
  $('#media-import-form').addEventListener('submit',importFiles);
}
async function importFiles(event) {
  event.preventDefault(); const form=event.currentTarget, fields=new FormData(form);
  const paths=[...new Set(fields.get('paths').split('\n').map(p=>p.trim()).filter(Boolean))];
  await guarded(form,async()=>{
    const registered=[], failed=[];state.importing=true;
    try {
      for (const path of paths) {
        $('#import-result').textContent=`Registering ${registered.length+failed.length+1} of ${paths.length}…`;
        try { registered.push(await send('/api/assets',{path,role:fields.get('role'),product_group:fields.get('product_group').trim()||null})); } catch(error) { failed.push(`${path}: ${error.message}`); }
      }
      const p=project();
      if (p&&registered.length) {
        const change=fields.get('role')==='source'?{source_asset_ids:[...new Set([...p.source_asset_ids,...registered.map(a=>a.id)])]}:fields.get('role')==='reference'?{reference_asset_id:registered[0].id}:{music_asset_id:registered[0].id};
        await send(`/api/projects/${encodeURIComponent(p.id)}`,change,'PATCH');
      }
      await refresh();
      $('#import-result').textContent=`${registered.length} registered.${failed.length?' '+failed.length+' failed.':''}`;
      if (failed.length) { const err=$('#import-error');err.hidden=false;err.textContent=failed.join('\n'); }
      else { $('#import-dialog').close();notify(`${registered.length} file${registered.length===1?'':'s'} registered.`); }
    } finally {state.importing=false;}
  },'#import-error');
}

function openShot(id) {
  const plan=activePlan(),shot=plan?.shots.find(s=>s.id===id);if (!shot)return;
  const asset=assetById(shot.asset_id),p=project();
  $('#shot-dialog-content').innerHTML=`<div class="dialog-header"><div><span class="eyebrow">REVISE A MOMENT</span><h2 id="shot-dialog-title">Replace or trim this shot.</h2></div><button class="icon-button" type="button" data-close="shot-dialog" aria-label="Close shot editor">×</button></div>${asset?`<video class="revision-preview" controls preload="metadata" src="${mediaUrl(asset)}#t=${shot.source_start_s},${shot.source_end_s}"></video>`:''}<form id="shot-form"><label>Source clip<select name="asset_id">${p.source_asset_ids.map(id=>assetById(id)).filter(Boolean).map(a=>`<option value="${e(a.id)}" ${a.id===shot.asset_id?'selected':''}>${e(fileName(a))} · ${time(a.duration_s)}</option>`).join('')}</select></label><div class="form-grid"><label>Source in <span class="field-unit">seconds</span><input name="source_start_s" type="number" min="0" step="0.01" required value="${shot.source_start_s}"></label><label>Source out <span class="field-unit">seconds</span><input name="source_end_s" type="number" min="0.01" step="0.01" required value="${shot.source_end_s}"></label></div><p class="form-note">The source range must fit the timeline slot (${time((shot.timeline_end_frame-shot.timeline_start_frame)*plan.fps_den/plan.fps_num)}). This is recorded as your manual choice.</p><label>What should change, and why?<textarea name="reason" required rows="2" placeholder="Use the turn after the jacket settles; keep the full silhouette."></textarea></label><label>Apply this decision to<select name="scope"><option value="edit">This edit only</option><option value="format">Future edits in this format</option><option value="reusable_rule">A reusable editing rule</option></select></label><p id="shot-error" class="inline-error" role="alert" hidden></p><div class="dialog-footer"><button class="button secondary" type="button" data-close="shot-dialog">Cancel</button><button class="button primary" type="submit">Save a new version</button></div></form>`;
  $('#shot-dialog').showModal();
  $('#shot-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget,f=new FormData(form);
    await guarded(form,async()=>{const result=await send(`/api/projects/${encodeURIComponent(p.id)}/corrections`,{plan_id:plan.id,shot_id:shot.id,reason:f.get('reason'),scope:f.get('scope'),changes:{asset_id:f.get('asset_id'),source_start_s:Number(f.get('source_start_s')),source_end_s:Number(f.get('source_end_s'))}});state.planId=result.plan?.id||null;$('#shot-dialog').close();await refresh();notify('Correction saved. Previous version preserved.');},'#shot-error');
  });
}

async function guarded(form, operation, errorSelector) {
  const controls=$$('button,input,textarea,select',form); const previous=controls.map(c=>c.disabled);
  if(errorSelector){$(errorSelector).hidden=true;}
  controls.forEach(c=>c.disabled=true);
  try { await operation(); } catch(error) { if(errorSelector&&$(errorSelector)){const n=$(errorSelector);n.textContent=error.message;n.hidden=false;}else notify(error.message,true); }
  finally {controls.forEach((c,i)=>c.disabled=previous[i]);}
}

function wireForms() {
  if(state.tab==='footage')$$('.asset-card .asset-info').forEach((node,index)=>{
    const asset=state.data.assets[index],form=document.createElement('form');form.className='asset-group-form spacer-top';
    form.innerHTML=`<label>Confirmed product group<input name="product_group" value="${e(asset.product_group||'')}" placeholder="Leave empty to clear"></label><label>Reason for the change<input name="reason" required placeholder="How you confirmed this outfit"></label><button class="button secondary small" type="submit">Save confirmed group</button>`;
    node.append(form);form.addEventListener('submit',async event=>{event.preventDefault();const f=new FormData(form);await guarded(form,async()=>{await send(`/api/assets/${encodeURIComponent(asset.id)}`,{product_group:f.get('product_group').trim()||null,reason:f.get('reason')},'PATCH');await refresh();notify('Confirmed grouping saved with its revision record.');});});
  });
  const manualForm=$('#manual-plan-form');
  if(manualForm)manualForm.addEventListener('submit',async event=>{
    event.preventDefault();const p=project(),reason=new FormData(manualForm).get('manual_reason'),rows=$$('.manual-row',manualForm).map(row=>({asset_id:$('[name=asset_id]',row).value,start:Number($('[name=source_start_s]',row).value),end:Number($('[name=source_end_s]',row).value)}));
    await guarded(manualForm,async()=>{
      let total=0,previous=0;const shots=rows.map(row=>{if(row.end<=row.start)throw new Error('Every source out must follow its source in.');total+=row.end-row.start;const end=Math.round(total*p.fps_num/p.fps_den),shot={asset_id:row.asset_id,source_start_s:row.start,source_end_s:row.end,timeline_start_frame:previous,timeline_end_frame:end,manual_override_reason:reason};previous=end;return shot;});
      const plan=await send('/api/plans',{project_id:p.id,brief_id:p.id,mode:'assisted',width:p.width,height:p.height,fps_num:p.fps_num,fps_den:p.fps_den,shots,music:p.music_asset_id?{asset_id:p.music_asset_id,source_start_s:p.music_offset_s||0}:null,operations:['cut','scale',...(p.music_asset_id?['music']:[])],variation_label:'Your manual cut'});state.planId=plan.id;await refresh();notify('Assisted plan saved. No AI selection was performed.');
    },'#manual-error');
  });
  const form=$('#brief-form');
  if(form){form.addEventListener('input',()=>{state.dirty=true;$('#save-state').textContent='Unsaved changes';});form.addEventListener('submit',async event=>{event.preventDefault();const f=new FormData(form),[width,height]=f.get('format').split('x').map(Number);await guarded(form,async()=>{await send(`/api/projects/${encodeURIComponent(state.projectId)}`,{name:f.get('name'),directions:f.get('directions'),reference_mode:f.get('reference_mode'),product_group:f.get('product_group').trim()||null,duration_s:f.get('duration_s')?Number(f.get('duration_s')):null,fps_num:Number(f.get('fps_num')),fps_den:project().fps_num===Number(f.get('fps_num'))?project().fps_den:1,width,height,allow_crop:f.get('allow_crop')==='on',hard_constraints:f.get('hard_constraints').split('\n').map(t=>t.trim()).filter(Boolean),source_asset_ids:f.getAll('source_asset_ids')},'PATCH');state.dirty=false;await refresh();notify('Direction saved.');},'#brief-error');});}
  const musicForm=$('#music-map-form');
  if(musicForm)musicForm.addEventListener('submit',async event=>{event.preventDefault();const f=new FormData(musicForm);await guarded(musicForm,async()=>{const anchors=f.get('anchors').split(',').map(v=>v.trim()).filter(Boolean).map(Number);if(anchors.some(n=>!Number.isFinite(n)||n<0))throw new Error('Use positive timestamps in seconds, separated by commas.');const map=await send('/api/music-maps',{asset_id:project().music_asset_id,excerpt_offset_s:Number($('#music-offset').value||0),manual_anchors_s:[...new Set(anchors)].sort((a,b)=>a-b),analysis_version:'manual',verified:f.get('verified')==='on'});state.musicMaps[map.asset_id]=map;notify('Manual musical anchors saved.');});});
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('button,a[data-action]');if(!button)return;
  try {
    if(button.dataset.close){$('#'+button.dataset.close).close();return;}
    if(button.dataset.project){if(state.dirty&&!confirm('Leave the unsaved direction changes?'))return;state.projectId=button.dataset.project;state.planId=null;state.dirty=false;localStorage.setItem('sevenheavens-project',state.projectId);renderSidebar();renderWorkspace();return;}
    if(button.dataset.tab){if(state.dirty&&!confirm('Leave the unsaved direction changes?'))return;state.dirty=false;state.tab=button.dataset.tab;renderWorkspace();return;}
    if(button.dataset.plan){state.planId=button.dataset.plan;renderWorkspace();return;}
    if(button.dataset.editShot){openShot(button.dataset.editShot);return;}
    if(button.dataset.cancel){await send(`/api/jobs/${encodeURIComponent(button.dataset.cancel)}/cancel`,{});await refresh();return;}
    if(button.dataset.render){button.disabled=true;await send(`/api/projects/${encodeURIComponent(state.projectId)}/runs`,{action:'render',plan_id:button.dataset.render});state.tab='versions';await refresh();return;}
    if(button.id==='new-project'||button.dataset.action==='new-project'){$('#project-dialog').showModal();return;}
    if(button.dataset.action==='refresh'){await refresh();return;}
    if(button.dataset.action==='import'){openImport();return;}
    if(button.dataset.action==='add-manual-shot'){$('#manual-rows').insertAdjacentHTML('beforeend',manualRow());return;}
    if(button.dataset.action==='save-media'){await send(`/api/projects/${encodeURIComponent(state.projectId)}`,{reference_asset_id:$('#reference-select').value||null,music_asset_id:$('#music-select').value||null,music_offset_s:Number($('#music-offset').value||0)},'PATCH');await refresh();notify('Reference and music saved.');return;}
    if(button.dataset.action==='analyze'){if(state.dirty)throw new Error('Save the direction before starting analysis.');button.disabled=true;await send(`/api/projects/${encodeURIComponent(state.projectId)}/runs`,{action:'analyze',plan_id:null});await refresh();return;}
  }catch(error){button.disabled=false;notify(error.message,true);}
});

$('#project-create-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget,f=new FormData(form);
  await guarded(form,async()=>{const p=await send('/api/projects',{name:f.get('name'),directions:f.get('directions'),duration_s:Number(f.get('duration_seconds')),fps_num:Number(f.get('fps')),fps_den:1,width:1080,height:1920});state.projectId=p.id;state.planId=null;state.tab='direction';state.dirty=false;localStorage.setItem('sevenheavens-project',p.id);$('#project-dialog').close();form.reset();await refresh();},'#create-error');
});

setInterval(async()=>{
  if(state.importing||document.querySelector('dialog[open]'))return;
  if(projectJobs().some(j=>['queued','running'].includes(j.status))){
    const before=JSON.stringify(projectJobs());await refresh({render:false});
    if(before!==JSON.stringify(projectJobs())){
      if(state.dirty){const region=$('#jobs-region');if(region)region.innerHTML=jobsView();}
      else renderWorkspace();
    }
  }
},2500);

refresh();
