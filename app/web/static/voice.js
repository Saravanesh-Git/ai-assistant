/* Buffered PCM voice transport. Wake state and command dispatch stay local to the UI. */
class AmigoVoice {
  constructor({onState, onTranscript, onCommand}) {
    this.onState = onState; this.onTranscript = onTranscript; this.onCommand = onCommand;
    this.enabled = false; this.awake = false; this.connected = false; this.available = false;
    this.outputAvailable = false; this.speaking = false; this.retries = 0; this.seenUtterances = new Set();
    this.supported = !!(navigator.mediaDevices?.getUserMedia && window.AudioContext && window.WebSocket);
  }
  configure({token, available, outputAvailable}) {
    this.token = token; this.available = !!available; this.outputAvailable = !!outputAvailable; this.emit();
  }
  emit(message, phase) {
    this.onState({enabled:this.enabled, awake:this.awake, connected:this.connected,
      supported:this.supported, available:this.available, phase:phase || (this.enabled ? 'listening' : 'idle'),
      message:message || (this.awake ? 'Listening for your next command.' :
        this.enabled ? 'Say “Hey Amigo” once to start your conversation.' :
        'Enable voice once. Wake me up. Keep the conversation going.')});
  }
  async start() {
    if (this.enabled || !this.supported || !this.available || !this.token) return;
    this.enabled = true; this.awake = false; this.retries = 0;
    this.emit('Requesting microphone access…', 'connecting');
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1, echoCancellation:true, noiseSuppression:true}, video:false});
      this.context = new AudioContext();
      this.source = this.context.createMediaStreamSource(this.stream);
      this.processor = this.context.createScriptProcessor(4096, 1, 1);
      this.silence = this.context.createGain(); this.silence.gain.value = 0;
      this.processor.onaudioprocess = event => this.sendSamples(event.inputBuffer.getChannelData(0), this.context.sampleRate);
      this.source.connect(this.processor); this.processor.connect(this.silence); this.silence.connect(this.context.destination);
      this.openSocket();
    } catch (error) {
      const denied = error?.name === 'NotAllowedError' || error?.name === 'SecurityError';
      this.stop(denied ? 'Microphone permission is blocked. Allow it in site settings, then try again.' :
        'No microphone is available. Check your audio device, then try again.');
    }
  }
  openSocket() {
    if (!this.enabled) return;
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    this.socket = new WebSocket(`${scheme}://${location.host}/api/voice?token=${encodeURIComponent(this.token)}`);
    this.socket.binaryType = 'arraybuffer';
    this.socket.onopen = () => {this.connected = true; this.retries = 0; this.emit('Voice ready. Say “Hey Amigo”.', 'listening');};
    this.socket.onmessage = event => this.receive(event.data);
    this.socket.onerror = () => {};
    this.socket.onclose = () => {
      this.connected = false;
      if (!this.enabled) return;
      if (++this.retries > 4) {this.stop('Voice connection stopped. You can keep using text, or enable voice again.'); return;}
      this.emit('Voice disconnected. Reconnecting…', 'connecting');
      clearTimeout(this.timer); this.timer = setTimeout(() => this.openSocket(), Math.min(500 * 2 ** this.retries, 8000));
    };
  }
  sendSamples(samples, inputRate) {
    if (this.speaking || !this.connected || this.socket.readyState !== WebSocket.OPEN) return;
    const ratio = inputRate / 16000, length = Math.max(1, Math.floor(samples.length / ratio));
    const pcm = new Int16Array(length);
    for (let i = 0; i < length; i++) {
      const start = Math.floor(i * ratio), end = Math.max(start + 1, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = start; j < end && j < samples.length; j++) sum += samples[j];
      const value = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
      pcm[i] = value < 0 ? value * 0x8000 : value * 0x7fff;
    }
    this.socket.send(pcm.buffer);
  }
  receive(raw) {
    let event;
    try {event = JSON.parse(raw);} catch {return;}
    if (event.type === 'error') {this.emit(event.message, 'error'); return;}
    if (event.type === 'status') {this.emit(event.message || 'Voice connected.', event.state); return;}
    if (event.type !== 'interim' && event.type !== 'final') return;
    const utteranceId = event.utterance_id ? String(event.utterance_id) : '';
    if (event.type === 'final' && utteranceId) {
      if (this.seenUtterances.has(utteranceId)) return;
      this.seenUtterances.add(utteranceId);
      if (this.seenUtterances.size > 100) this.seenUtterances.delete(this.seenUtterances.values().next().value);
    }
    this.processTranscript(String(event.text || '').trim(), event.type === 'final');
  }
  processTranscript(original, final) {
    if (!this.enabled || !original) return;
    let text = original;
    const wake = /\bhey[\s,]+amigo\b[\s,.!?]*/i.exec(text);
    if (!this.awake && !wake) {this.onTranscript(text, !final); return;}
    if (wake) text = text.slice(wake.index + wake[0].length).trim();
    this.onTranscript(text || original, !final);
    if (!final) return;
    this.awake = true;
    const control = text.toLowerCase().replace(/[.!?]+$/, '').trim();
    if (/^(?:please )?(?:stop listening|microphone off|turn off (?:the )?microphone)$/.test(control)) {this.stop(); return;}
    if (/^(?:please )?(?:pause listening|pause conversation|go to sleep)$/.test(control)) {this.pause(); return;}
    this.emit('Listening for your next command.', 'listening');
    if (text) this.onCommand(text);
  }
  pause() {this.awake = false; this.onTranscript('', true); this.emit('Conversation paused. Say “Hey Amigo” when you’re ready.', 'listening');}
  async speak(text) {
    if (!this.outputAvailable || !this.token || !String(text).trim()) return;
    this.cleanupSpeech(); this.speaking = true; this.emit('Speaking', 'speaking');
    this.speechAbort = new AbortController();
    try {
      const response = await fetch('/api/speech', {method:'POST', signal:this.speechAbort.signal,
        headers:{'Content-Type':'application/json', 'X-Assistant-Token':this.token},
        body:JSON.stringify({text:String(text)})});
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Voice output failed.');
      }
      const blob = await response.blob();
      this.speechUrl = URL.createObjectURL(blob);
      this.speechAudio = new Audio(this.speechUrl);
      await new Promise((resolve, reject) => {
        this.speechAudio.onended = resolve;
        this.speechAudio.onerror = () => reject(new Error('Browser audio playback failed.'));
        this.speechAudio.play().catch(reject);
      });
      this.cleanupSpeech(); this.emit('Listening for your next command.', 'listening');
    } catch (error) {
      const cancelled = error?.name === 'AbortError';
      this.cleanupSpeech();
      if (!cancelled) this.emit(`${error.message} The response is still available as text.`, 'error');
    }
  }
  cleanupSpeech() {
    this.speechAbort?.abort();
    if (this.speechAudio) {this.speechAudio.pause(); this.speechAudio.src = '';}
    if (this.speechUrl) URL.revokeObjectURL(this.speechUrl);
    this.speechAbort = this.speechAudio = this.speechUrl = null; this.speaking = false;
  }
  stop(message='Microphone off. You can still type a command.') {
    this.enabled = false; this.awake = false; this.connected = false; clearTimeout(this.timer); this.cleanupSpeech();
    if (this.socket) {this.socket.onclose = null; this.socket.close();}
    this.processor?.disconnect(); this.source?.disconnect(); this.silence?.disconnect();
    this.stream?.getTracks().forEach(track => track.stop()); this.context?.close();
    this.socket = this.processor = this.source = this.silence = this.stream = this.context = null;
    this.onTranscript('', true); this.emit(message, 'idle');
  }
}
window.AmigoVoice = AmigoVoice;
