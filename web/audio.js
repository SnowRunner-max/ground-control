// Audio: mic capture for push-to-talk (-> 16 kHz mono WAV), and playback of
// ATC/ATIS audio through a "radio" effect chain (bandpass + soft clip + noise).

const RadioAudio = {
  ctx: null,
  // playback chain
  radioIn: null,
  noiseGain: null,
  // capture
  stream: null,
  procNode: null,
  chunks: [],
  keyed: false,
  // atis
  atisBuffer: null,
  atisSource: null,
  queue: Promise.resolve(),

  async init() {
    this.ctx = new AudioContext();

    const hp = this.ctx.createBiquadFilter();
    hp.type = "highpass";
    hp.frequency.value = 320;
    const lp = this.ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.value = 2800;
    const shaper = this.ctx.createWaveShaper();
    shaper.curve = this.makeSaturationCurve(2.2);
    const out = this.ctx.createGain();
    out.gain.value = 1.0;

    this.radioIn = this.ctx.createGain();
    this.radioIn.connect(hp);
    hp.connect(lp);
    lp.connect(shaper);
    shaper.connect(out);
    out.connect(this.ctx.destination);

    // constant low hiss, only audible while something is "received"
    const noiseBuf = this.ctx.createBuffer(1, this.ctx.sampleRate * 2, this.ctx.sampleRate);
    const data = noiseBuf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    const noise = this.ctx.createBufferSource();
    noise.buffer = noiseBuf;
    noise.loop = true;
    this.noiseGain = this.ctx.createGain();
    this.noiseGain.gain.value = 0;
    noise.connect(this.noiseGain);
    this.noiseGain.connect(hp);
    noise.start();
  },

  makeSaturationCurve(k) {
    const n = 1024, curve = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const x = (i * 2) / n - 1;
      curve[i] = Math.tanh(k * x) / Math.tanh(k);
    }
    return curve;
  },

  squelch(atTime) {
    // short static burst — the classic squelch tail
    const g = this.noiseGain.gain;
    g.setValueAtTime(0.09, atTime);
    g.setValueAtTime(0.0, atTime + 0.045);
  },

  // ---- receive ------------------------------------------------------------

  async playAtc(b64wav, delayMs = 0) {
    // queue transmissions so overlapping replies/pushes don't talk over each other
    this.queue = this.queue.then(() => this._play(b64wav, delayMs)).catch(() => {});
    return this.queue;
  },

  async _play(b64wav, delayMs) {
    const buf = await this.decodeB64(b64wav);
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    return new Promise((resolve) => {
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.connect(this.radioIn);
      const t = this.ctx.currentTime;
      this.squelch(t);
      this.noiseGain.gain.setValueAtTime(0.012, t + 0.05);
      src.start(t + 0.06);
      src.onended = () => {
        const te = this.ctx.currentTime;
        this.squelch(te);
        resolve();
      };
    });
  },

  async decodeB64(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return this.ctx.decodeAudioData(bytes.buffer);
  },

  // ---- ATIS loop ----------------------------------------------------------

  async loadAtis() {
    const r = await fetch("/api/atis.wav");
    if (!r.ok) return false;
    this.atisBuffer = await this.ctx.decodeAudioData(await r.arrayBuffer());
    return true;
  },

  setAtis(on) {
    if (on && this.atisBuffer && !this.atisSource) {
      const src = this.ctx.createBufferSource();
      src.buffer = this.atisBuffer;
      src.loop = true;
      // start mid-broadcast like a real ATIS
      src.connect(this.radioIn);
      this.squelch(this.ctx.currentTime);
      this.noiseGain.gain.setValueAtTime(0.012, this.ctx.currentTime + 0.05);
      src.start(0, Math.random() * this.atisBuffer.duration);
      this.atisSource = src;
    } else if (!on && this.atisSource) {
      this.atisSource.stop();
      this.atisSource = null;
      this.noiseGain.gain.setValueAtTime(0, this.ctx.currentTime);
      this.squelch(this.ctx.currentTime);
    }
  },

  // ---- transmit (mic capture) ----------------------------------------------

  async ensureMic() {
    if (this.stream) return true;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      const src = this.ctx.createMediaStreamSource(this.stream);
      this.procNode = this.ctx.createScriptProcessor(4096, 1, 1);
      this.procNode.onaudioprocess = (e) => {
        if (this.keyed) this.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      };
      const sink = this.ctx.createGain();
      sink.gain.value = 0;
      src.connect(this.procNode);
      this.procNode.connect(sink);
      sink.connect(this.ctx.destination);
      return true;
    } catch {
      return false;
    }
  },

  keyDown() {
    this.chunks = [];
    this.keyed = true;
  },

  keyUp() {
    this.keyed = false;
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    if (!total) return null;
    const all = new Float32Array(total);
    let off = 0;
    for (const c of this.chunks) {
      all.set(c, off);
      off += c.length;
    }
    this.chunks = [];
    return this.encodeWav(this.downsample(all, this.ctx.sampleRate, 16000), 16000);
  },

  downsample(samples, fromRate, toRate) {
    if (fromRate === toRate) return samples;
    const ratio = fromRate / toRate;
    const out = new Float32Array(Math.floor(samples.length / ratio));
    for (let i = 0; i < out.length; i++) {
      const pos = i * ratio;
      const i0 = Math.floor(pos);
      const frac = pos - i0;
      out[i] = samples[i0] * (1 - frac) + (samples[i0 + 1] ?? samples[i0]) * frac;
    }
    return out;
  },

  encodeWav(samples, rate) {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const v = new DataView(buf);
    const wstr = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    wstr(0, "RIFF");
    v.setUint32(4, 36 + samples.length * 2, true);
    wstr(8, "WAVE");
    wstr(12, "fmt ");
    v.setUint32(16, 16, true);
    v.setUint16(20, 1, true);  // PCM
    v.setUint16(22, 1, true);  // mono
    v.setUint32(24, rate, true);
    v.setUint32(28, rate * 2, true);
    v.setUint16(32, 2, true);
    v.setUint16(34, 16, true);
    wstr(36, "data");
    v.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  },
};
