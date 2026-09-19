'use strict';
const $ = id => document.getElementById(id);
let token, busy = false, queue = [], voiceState = {enabled: false, awake: false}, statusTimer;
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function updateClock() {
  const now = new Date();
  $('clock').textContent = now.toLocaleTimeString('en-GB');
  $('clock').dateTime = now.toISOString();
  $('date').textContent = now.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'}).toUpperCase();
}
updateClock();
setInterval(updateClock, 1000);

function updateState() {
  const state = busy ? 'processing' : voiceState.awake ? 'awake' : 'idle';
  $('reactor').dataset.state = state;
  $('core-state').textContent = busy ? 'PROCESSING REQUEST' : voiceState.awake ? 'LISTENING TO YOU' : voiceState.enabled ? 'AWAITING WAKE PHRASE' : 'STANDING BY';
  $('core-kicker').textContent = busy ? 'ON IT, JUST A MOMENT' : voiceState.awake ? 'WHAT’S NEXT?' : 'READY WHEN YOU ARE';
  $('activity').textContent = busy ? (queue.length ? `WORKING · ${queue.length} QUEUED` : 'WORKING') : 'READY';
  $('input-mode').textContent = voiceState.awake ? 'VOICE + TEXT' : 'TEXT';
  $('send').disabled = !token;
  document.querySelectorAll('[data-command]').forEach(button => button.disabled = !token);
}

function appendLinkedText(node, text) {
  // Render output as text, with only explicit HTTPS links made clickable.
  const parts = String(text).split(/(https:\/\/[^\s<>]+)/g);
  for (const part of parts) {
    if (/^https:\/\//.test(part)) {
      const link = document.createElement('a');
      link.href = part; link.textContent = part; link.target = '_blank'; link.rel = 'noopener noreferrer';
      node.append(link);
    } else node.append(document.createTextNode(part));
  }
}
function addMessage(text, kind = '', source = '') {
  $('welcome')?.remove();
  const node = document.createElement('div'); node.className = `message ${kind}`;
  const label = document.createElement('span'); label.className = 'message-label';
  label.textContent = kind === 'user' ? (source === 'voice' ? 'YOU / VOICE' : 'YOU / TEXT') : 'A.M.I.G.O.';
  const body = document.createElement('div'); body.className = 'message-body'; appendLinkedText(body, text);
  const time = document.createElement('time'); time.className = 'message-time'; time.dateTime = new Date().toISOString();
  time.textContent = new Date().toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit'});
  node.append(label, body, time); $('messages').append(node);
  while ($('messages').children.length > 100) $('messages').firstElementChild.remove();
  $('messages').scrollTo({top: $('messages').scrollHeight, behavior: reducedMotion ? 'instant' : 'smooth'});
  return body;
}
function enqueue(message, source = 'text') {
  message = message.trim();
  if (!message) return;
  if (!token) {addMessage('The desktop connection is unavailable. Your command was not sent. Reconnect and try again.', 'error'); return;}
  if (queue.length >= 10) {addMessage('The command queue is full. Please wait for the current actions, then repeat your request.', 'error'); return;}
  addMessage(message, 'user', source);
  queue.push({message});
  drainQueue();
}
async function drainQueue() {
  if (busy || !queue.length) {updateState(); return;}
  busy = true; updateState();
  const payload = queue.shift();
  try {
    const response = await fetch('/api/command', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Assistant-Token': token}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 403) {
        token = undefined; queue = [];
        connect();
      }
      throw new Error(data.error || 'The request could not be completed.');
    }
    if (data.approval) {
      const body = addMessage(`${data.description}\n${JSON.stringify(data.arguments, null, 2)}\nConfirmation mode is enabled. Approve within two minutes.`);
      const actions = document.createElement('div'); actions.className = 'actions';
      for (const [label, accept] of [['Approve', true], ['Cancel', false]]) {
        const button = document.createElement('button'); button.textContent = label;
        button.onclick = () => {
          actions.querySelectorAll('button').forEach(item => item.disabled = true);
          queue.push({approval: data.approval, accept}); drainQueue();
        };
        actions.append(button);
      }
      body.append(actions);
    } else addMessage(data.reply || 'The action returned no response.');
  } catch (error) {
    addMessage(`${error.message} If the connection was interrupted, check the result before repeating the command.`, 'error');
  } finally {
    busy = false; updateState();
    drainQueue();
  }
}
$('composer').onsubmit = event => {
  event.preventDefault();
  const message = $('command').value.trim();
  if (!message || !token) return;
  enqueue(message);
  $('command').value = '';
};
$('command').onkeydown = event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {event.preventDefault(); $('composer').requestSubmit();}
};
document.querySelectorAll('[data-command]').forEach(button => button.onclick = () => enqueue(button.dataset.command));
document.querySelectorAll('[data-draft]').forEach(button => button.onclick = () => {
  $('command').value = button.dataset.draft; $('command').focus();
});
$('clear').onclick = () => {
  $('messages').replaceChildren();
  addMessage('Command history cleared. Ready for your next request.');
};
function openGuide() {$('guide').showModal();}
$('help').onclick = openGuide;
$('all-commands').onclick = openGuide;
$('close-guide').onclick = () => $('guide').close();
$('guide').onclick = event => {if (event.target === $('guide')) {
  const bounds = $('guide').getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) $('guide').close();
}};

async function connect() {
  try {
    const response = await fetch('/api/config');
    if (!response.ok) throw new Error('Connection unavailable');
    const data = await response.json();
    token = data.token;
    $('connection').textContent = `${data.tools.length} tools connected`;
    $('connection-dot').classList.remove('offline');
    $('platform').textContent = `${data.platform} · ${data.platform === 'Windows + WSL' ? 'WSL vitals' : 'Local machine'}`;
    $('desktop-state').textContent = data.windows_available ? 'WINDOWS + WSL' : data.platform === 'Windows + WSL' ? 'WSL ONLY' : 'LINUX';
    $('engine').textContent = data.provider === 'rule_based' ? 'LOCAL RULES' : data.provider.toUpperCase();
    $('tool-count').textContent = String(data.tools.length).padStart(2, '0') + ' CONNECTED';
    $('action-mode').textContent = data.confirm_actions ? 'CONFIRM FIRST' : 'DIRECT';
    $('allowed-paths').replaceChildren();
    for (const path of data.allowed_paths) {const item = document.createElement('li'); item.textContent = path; $('allowed-paths').append(item);}
    $('notepad-launch').dataset.command = data.platform === 'Windows + WSL' ? 'open windows notepad' : 'open code';
    $('notepad-launch').lastElementChild.textContent = data.platform === 'Windows + WSL' ? 'Notepad' : 'VS Code';
    updateState();
    refreshStatus();
  } catch {
    token = undefined; updateState();
    $('connection').textContent = 'Reconnecting to desktop…';
    $('connection-dot').classList.add('offline');
    setTimeout(connect, 5000);
  }
}
function setMetric(prefix, data, valueKey, detail) {
  const value = data?.[valueKey];
  const valid = typeof value === 'number' && Number.isFinite(value);
  $(`${prefix}-value`).textContent = valid ? `${Math.round(value)}%` : '—';
  $(`${prefix}-bar`).value = valid ? value : 0;
  $(`${prefix}-detail`).textContent = valid ? detail(data) : 'Reading unavailable';
  return valid;
}
async function refreshStatus() {
  clearTimeout(statusTimer);
  if (!token) return;
  let data = {};
  try {
    const response = await fetch('/api/status', {headers: {'X-Assistant-Token': token}});
    if (response.status === 403) {token = undefined; connect(); return;}
    if (!response.ok) throw new Error();
    data = await response.json();
  } catch { /* Mark readings unavailable; never invent telemetry. */ }
  const readings = [setMetric('cpu', data.get_cpu_usage, 'cpu_percent', cpu => `${cpu.cores} logical cores`),
    setMetric('memory', data.get_memory_usage, 'percent', memory => `${memory.used} / ${memory.total}`),
    setMetric('disk', data.get_disk_usage, 'percent', disk => `${disk.free} available`)];
  $('telemetry-status').textContent = readings.every(Boolean) ? 'Updated just now · 15s refresh' : 'Some readings unavailable';
  $('telemetry-dot').classList.toggle('offline', !readings.every(Boolean));
  statusTimer = setTimeout(refreshStatus, 15000);
}
const voice = new window.AmigoVoice({
  Recognition: window.SpeechRecognition || window.webkitSpeechRecognition,
  onState: state => {
    voiceState = state;
    $('mic-label').textContent = state.enabled ? 'Turn off mic' : 'Enable voice';
    $('mic').setAttribute('aria-pressed', String(state.enabled));
    $('voice-status').textContent = state.message;
    $('voice-heading').textContent = state.awake ? 'I’m with you. What’s next?' : 'Just say “Hey Amigo”';
    $('pause').hidden = !state.awake;
    updateState();
  },
  onTranscript: (text, interim) => {
    $('live').textContent = text ? `${interim ? 'Hearing' : 'Heard'}: ${text}` : 'Text and voice, working together.';
  },
  onCommand: text => enqueue(text, 'voice'),
});
$('mic').onclick = () => voice.enabled ? voice.stop() : voice.start();
$('pause').onclick = () => voice.pause();
if (!voice.recognition) {
  $('mic').disabled = true;
  $('voice-status').textContent = 'Voice isn’t supported here. Try Chrome on Windows, or type a command below.';
}
window.addEventListener('pagehide', () => {voice.stop(); clearTimeout(statusTimer);});
window.addEventListener('pageshow', event => {if (event.persisted) connect();});
updateState();
connect();
