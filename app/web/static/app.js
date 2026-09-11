const $ = (id) => document.getElementById(id);
let token, busy = false, enabled = false, awake = false, recognizer, restartTimer, wakeTimer;
function addMessage(text, kind = '') {
  const node = document.createElement('div'); node.className = `message ${kind}`;
  node.textContent = text; $('messages').append(node); node.scrollIntoView({behavior: 'smooth', block: 'nearest'}); return node;
}
async function send(payload) {
  if (busy || !token) return;
  busy = true; $('send').disabled = true;
  try {
    const response = await fetch('/api/command', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Assistant-Token': token}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Request failed');
    if (data.approval) {
      const node = addMessage(`${data.description}\n${JSON.stringify(data.arguments, null, 2)}\nApprove within two minutes.`);
      const actions = document.createElement('div'); actions.className = 'actions';
      for (const [label, accept] of [['Approve', true], ['Cancel', false]]) {
        const button = document.createElement('button'); button.textContent = label;
        button.onclick = () => {if (busy) return; actions.querySelectorAll('button').forEach(b => b.disabled = true); send({approval: data.approval, accept});}; actions.append(button);
      } node.append(actions);
    } else addMessage(data.reply);
  } catch (error) { addMessage(error.message); }
  finally {busy = false; $('send').disabled = !token;}
}
$('composer').onsubmit = event => {event.preventDefault(); const message = $('command').value.trim(); if (!message || busy || !token) return; awake = false; clearTimeout(wakeTimer); addMessage(message, 'user'); $('command').value = ''; send({message});};
$('command').onkeydown = event => {if (event.key === 'Enter' && !event.shiftKey) {event.preventDefault(); $('composer').requestSubmit();}};
document.querySelectorAll('[data-command]').forEach(button => button.onclick = () => {$('command').value = button.dataset.command; $('command').focus();});
$('send').disabled = true;
fetch('/api/config').then(r => {if (!r.ok) throw new Error(); return r.json();}).then(data => {token = data.token; $('send').disabled = false; $('connection').textContent = `${data.tools.length} tools connected`;}).catch(() => {$('connection').textContent = 'Connection unavailable';});
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
function stopVoice(message) {enabled = awake = false; clearTimeout(restartTimer); clearTimeout(wakeTimer); recognizer?.abort(); $('mic').textContent = 'Enable voice'; $('voice-status').textContent = message; $('live').textContent = 'Text or voice';}
if (!Recognition) {$('mic').disabled = true; $('voice-status').textContent = 'Speech recognition is unavailable in this browser. Try Chrome on Windows or type below.';}
else {
  recognizer = new Recognition(); recognizer.continuous = true; recognizer.interimResults = true; recognizer.lang = 'en-US';
  recognizer.onresult = event => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i]; let text = result[0].transcript.trim();
      const wake = /\bhello[\s,]+buddy\b[\s,.!?]*/i.exec(text);
      if (!awake && !wake) continue;
      if (wake) text = text.slice(wake.index + wake[0].length);
      $('live').textContent = result.isFinal ? 'Transcript ready' : 'Transcribing…';
      if (text) $('command').value = text;
      if (!result.isFinal) continue;
      awake = true; clearTimeout(wakeTimer);
      $('voice-status').textContent = 'Listening for your command…';
      wakeTimer = setTimeout(() => {awake = false; $('voice-status').textContent = 'Say “hello buddy” to start a command.';}, 15000);
      if (text) {
        awake = false; clearTimeout(wakeTimer);
        $('voice-status').textContent = 'Say “hello buddy” for another command.';
        if (busy) {$('live').textContent = 'Draft ready — send when the current action finishes';}
        else $('composer').requestSubmit();
      }
    }
  };
  recognizer.onerror = event => {if (event.error !== 'no-speech' && event.error !== 'aborted') stopVoice(`Voice stopped: ${event.error}. You can still type your command.`);};
  recognizer.onend = () => {if (enabled) restartTimer = setTimeout(() => {if (enabled) {try {recognizer.start();} catch {stopVoice('Could not restart voice. Enable it again.');}}}, 400);};
  $('mic').onclick = () => {if (enabled) return stopVoice('Microphone off.'); try {recognizer.start(); enabled = true; $('mic').textContent = 'Stop listening'; $('voice-status').textContent = 'Say “hello buddy” followed by your command.';} catch {stopVoice('Microphone could not start. Check browser permissions.');}};
}
window.addEventListener('pagehide', () => stopVoice('Microphone off.'));
