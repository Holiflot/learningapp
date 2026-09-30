// Push-to-talk recorder: records with MediaRecorder, then converts the clip to
// 16 kHz mono 16-bit WAV in the browser (what Whisper wants), so the server
// needs no ffmpeg.
const TARGET_RATE = 16000;

class PushToTalkRecorder {
  constructor() {
    this.stream = null;
    this.recorder = null;
    this.chunks = [];
    this.startedAt = 0;
  }

  async ensureStream() {
    if (this.stream) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  }

  async start() {
    await this.ensureStream();
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    this.recorder.start();
    this.startedAt = performance.now();
  }

  get isRecording() {
    return this.recorder && this.recorder.state === "recording";
  }

  // Resolves to { wav: Blob, seconds: number }.
  stop() {
    return new Promise((resolve, reject) => {
      if (!this.isRecording) return reject(new Error("not recording"));
      const rec = this.recorder;
      rec.onstop = async () => {
        try {
          const blob = new Blob(this.chunks, { type: rec.mimeType });
          const { wav, seconds } = await toWav16k(blob);
          resolve({ wav, seconds });
        } catch (err) {
          reject(err);
        }
      };
      rec.stop();
    });
  }
}

async function toWav16k(blob) {
  const ctx = new AudioContext();
  let decoded;
  try {
    decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
  } finally {
    ctx.close();
  }
  const length = Math.max(1, Math.ceil(decoded.duration * TARGET_RATE));
  const offline = new OfflineAudioContext(1, length, TARGET_RATE);
  const src = offline.createBufferSource();
  src.buffer = decoded; // multi-channel input is down-mixed to mono by the 1-channel context
  src.connect(offline.destination);
  src.start();
  const rendered = await offline.startRendering();
  return { wav: encodeWav(rendered.getChannelData(0), TARGET_RATE), seconds: decoded.duration };
}

function encodeWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buffer);
  const str = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE");
  str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}
