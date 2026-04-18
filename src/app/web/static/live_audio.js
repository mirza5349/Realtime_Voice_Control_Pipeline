(() => {
  const DEFAULT_VOICE_THRESHOLD = 0.018;
  const DEFAULT_SILENCE_WINDOW_MS = 1200;
  const DEFAULT_MIN_MS = 500;
  const DEFAULT_MAX_MS = 10000;
  const POST_STOP_DELAY_MS = 60;

  const pickMimeType = () => {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
    for (const candidate of candidates) {
      if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(candidate)) {
        return candidate;
      }
    }
    return "";
  };

  const extensionFor = (mimeType) => {
    if (!mimeType) return ".webm";
    if (mimeType.includes("mp4")) return ".mp4";
    if (mimeType.includes("ogg")) return ".ogg";
    return ".webm";
  };

  class LiveAudioCapture {
    constructor(options) {
      this._options = options;
      this._voiceThreshold = options.voiceThreshold ?? DEFAULT_VOICE_THRESHOLD;
      this._silenceWindowMs = options.silenceWindowMs ?? DEFAULT_SILENCE_WINDOW_MS;
      this._minMs = options.minMs ?? DEFAULT_MIN_MS;
      this._maxMs = options.maxMs ?? DEFAULT_MAX_MS;
      this._onUtterance = options.onUtterance || (() => {});
      this._onVoiceState = options.onVoiceState || (() => {});
      this._onError = options.onError || (() => {});
      this._stream = null;
      this._audioContext = null;
      this._analyser = null;
      this._recorder = null;
      this._recorderStartedAt = 0;
      this._lastVoiceAt = 0;
      this._hasVoiceSinceStart = false;
      this._active = false;
      this._rotating = false;
      this._rafId = null;
      this._mimeType = "";
    }

    get active() {
      return this._active;
    }

    async start() {
      if (this._active) return;
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("microphone capture is not supported in this browser");
      }
      if (typeof MediaRecorder === "undefined") {
        throw new Error("MediaRecorder is not supported in this browser");
      }
      this._mimeType = pickMimeType();
      this._stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      });
      const AudioContextImpl = window.AudioContext || window.webkitAudioContext;
      this._audioContext = new AudioContextImpl();
      const source = this._audioContext.createMediaStreamSource(this._stream);
      this._analyser = this._audioContext.createAnalyser();
      this._analyser.fftSize = 1024;
      source.connect(this._analyser);
      this._active = true;
      this._startRecorder();
      this._tick();
    }

    stop() {
      if (!this._active) return;
      this._active = false;
      if (this._rafId != null) {
        cancelAnimationFrame(this._rafId);
        this._rafId = null;
      }
      const recorder = this._recorder;
      this._recorder = null;
      if (recorder && recorder.state === "recording") {
        try {
          recorder.stop();
        } catch (err) {
          this._onError(err);
        }
      }
      if (this._stream) {
        for (const track of this._stream.getTracks()) {
          track.stop();
        }
        this._stream = null;
      }
      if (this._audioContext) {
        this._audioContext.close().catch(() => {});
        this._audioContext = null;
      }
      this._analyser = null;
      this._onVoiceState(false);
    }

    _startRecorder() {
      if (!this._stream) return;
      const options = this._mimeType ? { mimeType: this._mimeType } : undefined;
      const recorder = new MediaRecorder(this._stream, options);
      const chunks = [];
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data && event.data.size > 0) {
          chunks.push(event.data);
        }
      });
      recorder.addEventListener("stop", () => {
        const duration = Date.now() - this._recorderStartedAt;
        const blob = chunks.length
          ? new Blob(chunks, { type: this._mimeType || "audio/webm" })
          : null;
        const hadVoice = this._hasVoiceSinceStart;
        this._hasVoiceSinceStart = false;
        if (blob && hadVoice && duration >= this._minMs) {
          this._onUtterance({
            blob,
            durationMs: duration,
            filename: `utterance${extensionFor(this._mimeType)}`,
            mimeType: this._mimeType || "audio/webm",
          });
        }
        if (this._active && this._rotating) {
          this._rotating = false;
          setTimeout(() => {
            if (this._active) {
              this._startRecorder();
            }
          }, POST_STOP_DELAY_MS);
        }
      });
      recorder.addEventListener("error", (event) => {
        this._onError(event.error || new Error("recorder error"));
      });
      this._recorder = recorder;
      this._recorderStartedAt = Date.now();
      this._lastVoiceAt = this._recorderStartedAt;
      this._hasVoiceSinceStart = false;
      recorder.start();
    }

    _rotate() {
      if (this._rotating || !this._recorder || this._recorder.state !== "recording") return;
      this._rotating = true;
      try {
        this._recorder.stop();
      } catch (err) {
        this._rotating = false;
        this._onError(err);
      }
    }

    _tick() {
      if (!this._active || !this._analyser) return;
      const buffer = new Uint8Array(this._analyser.fftSize);
      this._analyser.getByteTimeDomainData(buffer);
      let sum = 0;
      for (let i = 0; i < buffer.length; i++) {
        const value = (buffer[i] - 128) / 128;
        sum += value * value;
      }
      const rms = Math.sqrt(sum / buffer.length);
      const now = Date.now();
      const speaking = rms > this._voiceThreshold;
      if (speaking) {
        this._hasVoiceSinceStart = true;
        this._lastVoiceAt = now;
      }
      this._onVoiceState(speaking);

      const duration = now - this._recorderStartedAt;
      const silenceElapsed = now - this._lastVoiceAt;
      const shouldRotateOnSilence =
        this._hasVoiceSinceStart &&
        silenceElapsed >= this._silenceWindowMs &&
        duration >= this._minMs;
      const shouldRotateOnMax = duration >= this._maxMs;

      if (shouldRotateOnSilence || shouldRotateOnMax) {
        this._rotate();
      }

      this._rafId = requestAnimationFrame(() => this._tick());
    }
  }

  window.LiveAudioCapture = LiveAudioCapture;
})();
