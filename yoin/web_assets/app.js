"use strict";
const $ = (id) => document.getElementById(id);
const state = { token: "", ready: false, busy: false, run: null, job: null, score: null, timer: null };
const players = [$('draftAudio'), $('finalAudio')];
let syncingVolume = false;
for (const player of players) {
  player.volume = 0.55;
  player.addEventListener('play', () => players.filter((other) => other !== player).forEach((other) => other.pause()));
  player.addEventListener('volumechange', () => {
    if (syncingVolume) return;
    syncingVolume = true;
    for (const other of players) if (other !== player) { other.volume = player.volume; other.muted = player.muted; }
    syncingVolume = false;
  });
}

async function api(path, data) {
  const options = data === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Yoin-Token': state.token }, body: JSON.stringify(data) };
  let response, result;
  try { response = await fetch(path, options); result = await response.json(); }
  catch { const failure = new Error('与本地服务的连接暂时中断，已有声音仍保存在电脑里。'); failure.connection = true; throw failure; }
  if (!response.ok) throw new Error(result.error || '操作没有完成，请稍后重试。');
  return result;
}
function error(message) { $('errorBox').textContent = message; $('errorBox').hidden = !message; }
function media(runId, filename, download = false) { return `/media/${encodeURIComponent(runId)}/${filename}${download ? '?download=1' : ''}`; }
function formatDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '' : date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}
function setBusy(value) {
  state.busy = value;
  $('generateButton').disabled = value || !state.ready;
  $('generateButton').textContent = value ? '正在调配…' : '调配声音 ↗';
  $('refineButton').disabled = value || !state.ready || !state.run?.can_refine;
  $('ratingButton').disabled = value;
  $('generateForm').setAttribute('aria-busy', String(value));
  document.querySelectorAll('.history-item').forEach((button) => { button.disabled = value; });
  $('progress').hidden = !value;
}
function resetScore() {
  state.score = null;
  $('scoreLabel').textContent = '还没有评分';
  $('ratingStatus').textContent = '';
  document.querySelectorAll('[data-score]').forEach((button) => { button.classList.remove('selected'); button.setAttribute('aria-pressed', 'false'); });
}
function setAudio(which, run) {
  const ready = run[`has_${which}`];
  const audio = $(which + 'Audio');
  audio.hidden = !ready;
  $(which + 'Placeholder').hidden = ready;
  const download = $(which + 'Download');
  download.hidden = !ready;
  if (ready) {
    const source = media(run.run_id, which + '.wav');
    if (audio.dataset.source !== source) { audio.pause(); audio.src = source; audio.dataset.source = source; audio.load(); }
    download.href = media(run.run_id, which + '.wav', true);
    download.download = which + '.wav';
  }
}
function renderRun(run) {
  const changed = state.run?.run_id !== run.run_id;
  if (changed) { players.forEach((player) => { player.pause(); player.removeAttribute('src'); delete player.dataset.source; player.load(); }); resetScore(); $('ratingNote').value = ''; }
  state.run = run;
  $('emptyState').hidden = true;
  $('runPanel').hidden = false;
  $('runTitle').textContent = run.title;
  $('runDate').textContent = formatDate(run.created_at);
  const providerNames = { codex: 'Codex', claude: 'Claude', openai: 'GPT', deepseek: 'DeepSeek' };
  $('runBadge').textContent = run.scripted ? '脚本演示' : (providerNames[run.provider] || '模型') + ' 调配';
  $('runBadge').title = run.model;
  $('runParent').textContent = run.parent_run_id ? '在上一版上微调' : '';
  setAudio('draft', run); setAudio('final', run);
  $('shortExplanation').textContent = (run.explanation || '').split('保留的分析建议')[0].split('素材来源与许可')[0].trim();
  $('fullExplanation').textContent = run.explanation || '调配完成后会留下选择与调整说明。';
  $('recipeDownload').href = media(run.run_id, 'final.json', true);
  $('recipeDownload').hidden = !run.has_final;
  $('ratingWhich').querySelector('[value="final"]').disabled = !run.has_final;
  $('ratingWhich').querySelector('[value="draft"]').disabled = !run.has_draft;
  if (changed) $('ratingWhich').value = run.has_final ? 'final' : 'draft';
  $('refineButton').disabled = state.busy || !state.ready || !run.can_refine;
  $('refineButton').textContent = run.status === 'failed' && run.has_draft ? '从初稿继续 ↗' : '在这版上微调 ↗';
  if (run.status === 'failed') error(run.error || '这次生成已中断，已有试听已保留。');
  document.querySelectorAll('.history-item').forEach((button) => button.classList.toggle('selected', button.dataset.run === run.run_id));
}
async function selectRun(runId) {
  error('');
  const run = await api('/api/runs/' + encodeURIComponent(runId));
  renderRun(run);
}
async function history(selectLatest = false) {
  const result = await api('/api/runs');
  const list = $('historyList'); list.replaceChildren();
  if (!result.runs.length) { const text = document.createElement('p'); text.className = 'history-empty'; text.textContent = '还没有声音足迹。\n从一句场景描述开始。'; list.append(text); return; }
  for (const run of result.runs) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'history-item'; button.dataset.run = run.run_id; button.disabled = state.busy;
    button.classList.toggle('selected', state.run?.run_id === run.run_id);
    const title = document.createElement('strong'); title.textContent = run.title;
    const meta = document.createElement('small');
    const date = document.createElement('span'); date.textContent = formatDate(run.created_at);
    const tag = document.createElement('span'); tag.textContent = run.scripted ? '演示' : run.status === 'failed' ? '未完成' : run.has_final ? '可试听' : '调配中';
    meta.append(date, tag); button.append(title, meta); button.addEventListener('click', () => selectRun(run.run_id).catch((failure) => error(failure.message)));
    list.append(button);
  }
  if (selectLatest && !state.run && !state.busy) {
    const latest = result.runs.find((run) => run.has_final && !run.scripted) || result.runs.find((run) => run.has_final);
    if (latest) await selectRun(latest.run_id);
  }
}
async function connection() {
  const bootstrap = await api('/api/bootstrap'); state.token = bootstrap.token; state.ready = bootstrap.connection.ready;
  $('connectionText').textContent = bootstrap.connection.label; $('connection').classList.toggle('ready', state.ready);
  $('connectionHint').hidden = state.ready; $('connectionHint').textContent = bootstrap.connection.error || '';
  setBusy(state.busy);
  if (bootstrap.active_job && !state.job) { state.job = bootstrap.active_job; setBusy(true); await watchJob(); }
}
async function startJob(request, fromRun) {
  error(''); players.forEach((player) => player.pause());
  $('progressText').textContent = fromRun ? '正在保留喜欢的部分，做一点微调' : '正在理解你想要的场景';
  $('progressDetail').textContent = '声音正在慢慢成形。'; $('progressRound').textContent = '';
  setBusy(true);
  try {
    const data = { request }; if (fromRun) data.from_run = fromRun;
    const job = await api('/api/jobs', data); state.job = job.job_id;
    await watchJob();
  } catch (failure) { setBusy(false); error(failure.message); }
}
async function watchJob() {
  clearTimeout(state.timer);
  try {
    const job = await api('/api/jobs/' + state.job);
    state.retries = 0;
    if (job.run) {
      renderRun(job.run); $('progressText').textContent = job.run.phase;
      $('progressRound').textContent = job.run.step ? `第 ${job.run.step} 轮` : '';
      $('progressDetail').textContent = job.run.has_draft ? '初稿已可试听，正在继续打磨。' : '先留住第一版，再慢慢调整。';
    }
    if (job.status === 'completed' || job.status === 'failed') {
      state.job = null; setBusy(false);
      if (job.status === 'failed') error(job.error || '这次调配没有完成，已有试听已保留。');
      else if (job.run?.status === 'fallback') error('本次未主动提交，已经为你保留最后一份有效版本。');
      await history();
      return;
    }
    state.timer = setTimeout(watchJob, 1000);
  } catch (failure) {
    if (failure.connection && (state.retries || 0) < 10) {
      state.retries = (state.retries || 0) + 1;
      $('progressText').textContent = '正在重新连接本地服务';
      $('progressDetail').textContent = '已有声音仍保存在电脑里，请稍等。';
      state.timer = setTimeout(watchJob, 2000); return;
    }
    state.job = null; state.retries = 0; setBusy(false);
    try { await connection(); if (state.busy) return; if (state.run) await selectRun(state.run.run_id); await history(); } catch {}
    error(failure.connection ? failure.message : '上次连接已中断，已保存的声音可在「声音足迹」中打开并继续。');
  }
}
$('generateForm').addEventListener('submit', (event) => { event.preventDefault(); const value = $('scene').value.trim(); if (value) startJob(value); });
$('refineForm').addEventListener('submit', (event) => { event.preventDefault(); const value = $('refinement').value.trim(); if (value && state.run?.can_refine) startJob(value, state.run.run_id); });
document.querySelectorAll('[data-scene]').forEach((button) => button.addEventListener('click', () => { $('scene').value = button.dataset.scene; $('scene').focus(); }));
document.querySelectorAll('[data-score]').forEach((button) => button.addEventListener('click', () => {
  state.score = Number(button.dataset.score); $('scoreLabel').textContent = `${state.score} / 5`;
  document.querySelectorAll('[data-score]').forEach((star) => { const selected = Number(star.dataset.score) <= state.score; star.classList.toggle('selected', selected); star.setAttribute('aria-pressed', String(Number(star.dataset.score) === state.score)); });
}));
$('ratingWhich').addEventListener('change', resetScore);
$('ratingForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.run || !state.score) { $('ratingStatus').textContent = '先选一个分数，再留下你的听感。'; return; }
  $('ratingButton').disabled = true;
  try { await api('/api/ratings', { run_id: state.run.run_id, which: $('ratingWhich').value, score: state.score, note: $('ratingNote').value }); $('ratingStatus').textContent = `已记录 ${state.score} 分，谢谢你留下这次听感。`; }
  catch (failure) { $('ratingStatus').textContent = failure.message; }
  finally { $('ratingButton').disabled = state.busy; }
});
$('refreshHistory').addEventListener('click', () => history().catch((failure) => error(failure.message)));
$('connection').addEventListener('click', () => connection().catch((failure) => error(failure.message)));

let savedConnections = null;
let settingsBusy = false;
function syncConnectionOptions() {
  let option = $('modelProvider').querySelector('[value="codex"]');
  if (savedConnections.local_codex_enabled) {
    if (!option) { option = document.createElement('option'); option.value = 'codex'; $('modelProvider').append(option); }
    option.textContent = '本机 Codex · 订阅测试';
  } else if (option) option.remove();
  $('modelSettingsIntro').textContent = savedConnections.local_codex_enabled
    ? '本机订阅测试已开启，也可以选择各家的 API Key。' : '分别保存各家的密钥，选择这次想用的模型。';
  $('modelProvider').value = savedConnections.active;
}
function showConnectionFields() {
  const provider = $('modelProvider').value;
  const local = provider === 'codex' && savedConnections?.local_codex_enabled;
  $('apiConnectionFields').hidden = local;
  for (const field of $('apiConnectionFields').querySelectorAll('input')) field.disabled = local;
  $('localCodexFields').hidden = !local;
  $('saveConnection').hidden = local;
  $('testConnection').textContent = local ? '检查本机登录' : '测试连接';
  $('connectionTestHint').textContent = local
    ? '检查登录不发送模型请求；实际生成和微调会使用你的 ChatGPT 订阅额度。'
    : '测试会发送一条简短请求，使用所选 API 的额度；保存和切换不发送生成请求。';
  $('activeConnection').textContent = `当前使用：${savedConnections?.active_label || 'GPT · API Key'}`;
  $('modelApiKey').value = '';
  if (local) { $('deleteConnection').hidden = true; return; }
  const profile = savedConnections?.profiles.find((item) => item.provider === provider);
  if (!profile) return;
  $('modelApiKey').required = !profile.configured;
  $('deleteConnection').hidden = !profile.configured;
  $('modelName').value = profile.model;
  $('modelBaseUrl').value = profile.base_url;
  $('modelKeyState').textContent = profile.configured ? '已保存 · 留空沿用' : '尚未绑定';
  $('modelProviderHint').textContent = provider === 'claude' ? 'CC 使用 Claude / Anthropic API Key。' : `填写 ${profile.label} 的 API Key。`;
}
function settingsStatus(message, failed = false) {
  $('modelSettingsStatus').textContent = message;
  $('modelSettingsStatus').classList.toggle('failed', failed);
}
async function updateSettings(action) {
  if (settingsBusy) return;
  settingsBusy = true;
  for (const id of ['modelProvider', 'saveConnection', 'testConnection', 'useConnection', 'deleteConnection', 'closeModelSettings']) $(id).disabled = true;
  settingsStatus('正在处理…');
  try { await action(); }
  catch (failure) { settingsStatus(failure.message, true); }
  finally {
    settingsBusy = false;
    for (const id of ['modelProvider', 'saveConnection', 'testConnection', 'useConnection', 'deleteConnection', 'closeModelSettings']) $(id).disabled = false;
  }
}
async function saveSelectedConnection() {
  const provider = $('modelProvider').value;
  if (!savedConnections.profiles.some((profile) => profile.provider === provider)) return;
  const data = { provider, model: $('modelName').value.trim(), base_url: $('modelBaseUrl').value.trim() };
  const key = $('modelApiKey').value.trim();
  if (key) data.api_key = key;
  savedConnections = await api('/api/connections/save', data);
  showConnectionFields();
}
$('modelSettingsButton').addEventListener('click', async () => {
  try {
    savedConnections = await api('/api/connections');
    syncConnectionOptions();
    showConnectionFields(); settingsStatus(''); $('modelSettings').showModal();
  } catch (failure) { error(failure.message); }
});
$('closeModelSettings').addEventListener('click', () => { $('modelApiKey').value = ''; $('modelSettings').close(); });
$('modelSettings').addEventListener('cancel', (event) => { if (settingsBusy) event.preventDefault(); });
$('modelSettings').addEventListener('close', () => { $('modelApiKey').value = ''; });
$('modelBaseUrl').addEventListener('invalid', () => { $('modelBaseUrl').closest('details').open = true; });
$('modelProvider').addEventListener('change', () => { showConnectionFields(); settingsStatus(''); });
$('modelSettingsForm').addEventListener('submit', (event) => {
  event.preventDefault();
  if (!$('modelSettingsForm').reportValidity()) return;
  updateSettings(async () => { await saveSelectedConnection(); await connection(); settingsStatus('配置已保存。点击「使用此入口」切换。'); });
});
$('testConnection').addEventListener('click', () => {
  if (!$('modelSettingsForm').reportValidity()) return;
  updateSettings(async () => {
    await saveSelectedConnection();
    settingsStatus($('modelProvider').value === 'codex' ? '正在检查本机登录状态…' : '正在检查连接与工具调用，请稍等…');
    const result = await api('/api/connections/test', { provider: $('modelProvider').value });
    settingsStatus(result.message);
  });
});
$('useConnection').addEventListener('click', () => {
  if (!$('modelSettingsForm').reportValidity()) return;
  updateSettings(async () => {
    await saveSelectedConnection();
    savedConnections = await api('/api/connections/select', { provider: $('modelProvider').value });
    showConnectionFields(); await connection();
    settingsStatus(`已切换为 ${savedConnections.active_label}，下次生成或微调使用这个入口。`);
  });
});
$('deleteConnection').addEventListener('click', () => updateSettings(async () => {
  savedConnections = await api('/api/connections/delete', { provider: $('modelProvider').value });
  showConnectionFields(); await connection(); settingsStatus('这家的密钥和配置已删除。');
}));
(async () => { try { await connection(); await history(true); } catch (failure) { error('本地服务暂时无法连接，请刷新页面重试。'); } })();
