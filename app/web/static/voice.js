/* Browser speech adapter. A future local STT adapter can expose the same callbacks. */
class AmigoVoice {
  constructor({Recognition, onState, onTranscript, onCommand}) {
    this.onState = onState;
    this.onTranscript = onTranscript;
    this.onCommand = onCommand;
    this.enabled = false;
    this.awake = false;
    this.retries = 0;
    this.lastFinal = -1;
    if (!Recognition) return;
    this.recognition = new Recognition();
    this.recognition.continuous = true;
    this.recognition.interimResults = true;
    this.recognition.lang = 'en-US';
    this.recognition.onstart = () => {
      this.lastFinal = -1;
      this.emit();
    };
    this.recognition.onresult = event => this.receive(event);
    this.recognition.onerror = event => this.error(event.error);
    this.recognition.onend = () => {
      if (!this.enabled) return;
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.startRecognition(), Math.min(400 * 2 ** this.retries, 8000));
    };
  }
  emit(message) {
    this.onState({enabled: this.enabled, awake: this.awake, supported: !!this.recognition,
      message: message || (this.awake ? 'I’m listening. Say your next command — no wake phrase needed.' :
        this.enabled ? 'Say “Hey Amigo” once to start your conversation.' :
        'Enable voice once. Wake me up. Keep the conversation going.')});
  }
  startRecognition() {
    if (!this.enabled) return;
    try { this.recognition.start(); }
    catch (error) {
      if (error.name !== 'InvalidStateError') this.stop('Voice could not start. Check your browser’s microphone permission.');
    }
  }
  start() {
    if (!this.recognition || this.enabled) return;
    this.enabled = true;
    this.awake = false;
    this.retries = 0;
    this.emit('Connecting to your microphone…');
    this.startRecognition();
  }
  stop(message = 'Microphone off. You can still type a command.') {
    this.enabled = false;
    this.awake = false;
    clearTimeout(this.timer);
    this.recognition?.abort();
    this.onTranscript('');
    this.emit(message);
  }
  pause() {
    this.awake = false;
    this.onTranscript('');
    this.emit('Conversation paused. Say “Hey Amigo” when you’re ready.');
  }
  error(error) {
    if (error === 'aborted' || error === 'no-speech') return;
    if (error === 'network' && ++this.retries <= 4) {
      this.emit('Speech service disconnected. Reconnecting…');
      return;
    }
    const reasons = {
      'not-allowed': 'Microphone permission is blocked. Allow it in your browser’s site settings, then enable voice.',
      'service-not-allowed': 'The browser’s speech service is unavailable. Try Chrome on Windows, or type a command.',
      'audio-capture': 'No microphone is available. Check your audio device, then enable voice.',
      'network': 'The speech service is offline. Check your connection, then enable voice again.',
    };
    this.stop(reasons[error] || `Voice stopped (${error}). Enable voice to reconnect, or keep typing.`);
  }
  receive(event) {
    if (!this.enabled) return;
    this.retries = 0;
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (i <= this.lastFinal) continue;
      let text = result[0].transcript.trim();
      const wake = /\bhey[\s,]+amigo\b[\s,.!?]*/i.exec(text);
      if (!this.awake && !wake) {
        if (result.isFinal) this.lastFinal = i;
        continue;
      }
      if (wake) text = text.slice(wake.index + wake[0].length);
      this.onTranscript(text, !result.isFinal);
      if (!result.isFinal) continue;
      this.lastFinal = i;
      this.awake = true;
      const control = text.toLowerCase().replace(/[.!?]+$/, '').trim();
      if (/^(?:please )?(?:stop listening|microphone off|turn off (?:the )?microphone)$/.test(control)) {
        this.stop();
        return;
      }
      if (/^(?:please )?(?:pause listening|pause conversation|go to sleep)$/.test(control)) {
        this.pause();
        continue;
      }
      this.emit();
      if (text) this.onCommand(text);
    }
  }
}
window.AmigoVoice = AmigoVoice;
