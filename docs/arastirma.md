# İngilizce Konuşma Pratiği Uygulaması: Araştırma Notları

Tarih: 2026-09-30

## Fikir
1. Kullanıcı bir konu seçer (ör. "iş görüşmesi", "tatil planı").
2. Model bu konuya göre "İngilizce öğretmeni" rolüne hazırlanır.
3. Kullanıcı mikrofona konuşur, konuşma yazıya dökülür (STT).
4. Yerel LLM öğretmen gibi yazılı cevap verir (sesli çıktı gerekmiyor).
5. Her şey yerelde, açık kaynak modellerle çalışır.

## Akış
```
Mikrofon -> VAD / bas-konuş -> STT (Whisper vb.) -> metin
      -> LLM (Ollama, öğretmen system prompt + konu + seviye)
      -> ekranda: doğal cevap + düzeltmeler + yeni kelimeler
```

## 1. Konuşma tanıma (STT) seçenekleri

| Model | Artı | Eksi | Ne zaman |
|---|---|---|---|
| Whisper large-v3-turbo (faster-whisper ile) | Aksanlı İngilizcede güçlü, çok dilli, en yaygın | GPU'suz yavaş olabilir; sessizlikte uydurabilir | Varsayılan seçim |
| Whisper small / distil-whisper | CPU'da hızlı | Doğruluk düşer | GPU yoksa |
| NVIDIA Parakeet TDT | Çok hızlı, akış için uygun | Yalnız İngilizce, NVIDIA ekosistemi | Gerçek zamanlıya yakın |
| NVIDIA Canary-Qwen 2.5B | Doğruluk sıralamasında en üstte | Daha ağır | Doğruluk öncelikliyse |
| Moonshine | Çok küçük (27MB'tan başlıyor) | Daha az doğru | Zayıf cihaz |
| Gemma 4 E2B/E4B (dahili ses girişi) | STT ve LLM tek modelde | Transkript kalitesi Whisper kadar oturmuş değil | Deneysel |

Araçlar: `faster-whisper` (Python, CTranslate2, 4 kata kadar hızlı), `whisper.cpp` (C++, Mac/CPU için iyi), `mlx-whisper` (Apple Silicon), `silero-vad` (konuşmanın ne zaman bittiğini algılar).

### Önemli tuzak: STT hataları "düzeltir"
Whisper güçlü bir dil modeline sahip olduğundan öğrencinin gramer hatalarını transkriptte
sessizce düzeltebilir ("he go" -> "he goes"). Öğretmen hatayı hiç göremez. Önlemler:
- `condition_on_previous_text=False`, `temperature=0`, "düzgün" bir initial_prompt vermemek.
- Kullanıcıya transkripti göstermek, gerekirse elle düzeltme imkânı.
- Daha "harfiyen" yazan CTC tabanlı modelleri (Parakeet-CTC, wav2vec2) karşılaştırmak.
- Prototipte bilerek hatalı cümleler söyleyip test etmek.

Tarayıcının Web Speech API'si (Chrome) yerel değildir, sesi Google'a gönderir.

## 2. Öğretmen LLM seçenekleri (Ollama ile)

2026 itibarıyla öne çıkan açık ağırlıklı aileler (hepsi Apache 2.0, Ollama'da var):

- **Gemma 4** (Google, Nisan 2026): E2B (~1.5GB Q4), E4B (~5GB), 12B (~8GB), 26B MoE (A4B, 14-18GB), 31B (~20GB).
  Doğal sohbet dili ve çok dilli kalite açısından iyi; E2B/E4B ses girişini de destekliyor.
- **Qwen 3.5** (Alibaba, Şubat 2026): 0.8B'den 397B'a kadar sekiz boyut. Talimat takibi güçlü.
  Düşünme (thinking) modu gecikmeyi artırır; sohbette kapatılmalı.
- Alternatifler: gpt-oss-20b, Phi-4-mini (zayıf donanım), Llama 3.x.

Öneri: **Gemma 4 12B** (veya donanım zayıfsa E4B) ile başlamak, **Qwen 3.5** ile aynı senaryoları karşılaştırmak.

### Donanıma göre kabaca eşleşme
| Donanım | STT | LLM |
|---|---|---|
| GPU yok, 8-16GB RAM | Whisper small / distil (CPU) | Gemma 4 E4B, Qwen 3.5 4B |
| 8GB VRAM | large-v3-turbo (int8) | Gemma 4 E4B / Qwen 3.5 ~9B Q4 (sıkışık) |
| 12-16GB VRAM | large-v3-turbo | Gemma 4 12B, Qwen 3.5 ~9B |
| 24GB+ VRAM / Apple Silicon 32GB+ | large-v3 / Canary-Qwen | Gemma 4 26B MoE / 31B |

STT ve LLM aynı GPU'yu paylaşacağı için ikisinin toplam belleği hesaba katılmalı.

## 3. "Öğretmen" davranışını tasarlamak
Model seçimi kadar prompt ve çıktı yapısı önemli.
- System prompt'ta konu, CEFR seviyesi (A2-C1) ve düzeltme stili (her cevapta / sadece önemli hatalar / oturum sonunda) yer alır.
- Yapılandırılmış çıktı (Ollama `format` + JSON şema):
  `{ "reply": "...", "corrections": [{"original","corrected","explanation"}], "vocabulary": [...], "follow_up_question": "..." }`
  Böylece arayüz sohbeti ve düzeltmeleri ayrı gösterebilir.
- Konuşmayı canlı tutması için her cevabın bir soruyla bitmesi.
- Oturum sonunda özet: sık yapılan hatalar, öğrenilen kelimeler (yerel SQLite'ta saklanabilir).
- İsteğe bağlı: açıklamaları Türkçe verme seçeneği.

## 4. İsteğe bağlı: telaffuz geri bildirimi
Transkript metni telaffuzu göstermez. Telaffuz için ayrıca fonem düzeyinde değerlendirme gerekir:
wav2vec2 tabanlı [OpenPronounce](https://github.com/Halleck45/OpenPronounce); speechocean762 veri seti.
İlk sürüm için gerekli değil.

## 5. İncelemeye değer benzer projeler
- [talk-to-me](https://github.com/juanmanuelruizm/talk-to-me): Whisper + Ollama, CLI, 3 seviye, hata düzeltme.
- [english-tutor-agent](https://github.com/MaxBarannikov/english-tutor-agent): faster-whisper + LangGraph + Chainlit, CEFR'ye göre düzeltme.
- [local-ai-english-speaking-coach](https://github.com/MohammadElayyan117/local-ai-english-speaking-coach): n8n + Ollama, konu, seviye ve düzeltme modu seçimi.

## 6. Önerilen ilk mimari (MVP)
- Backend: Python + FastAPI, `faster-whisper`, `silero-vad`, Ollama HTTP API.
- Frontend: basit web sayfası (konu seçimi, bas-konuş düğmesi, sohbet + düzeltme paneli).
- Depolama: SQLite (oturumlar, hatalar, kelimeler).

## Netleşmesi gerekenler
- Donanım: işletim sistemi, GPU/VRAM, RAM.
- Arayüz: web (localhost), masaüstü veya terminal.
- Konuşma modu: bas-konuş mu, otomatik algılama mı.
- Düzeltme stili ve açıklama dili.

## Kaynaklar
- https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks
- https://www.gladia.io/blog/best-open-source-speech-to-text-models
- https://www.assemblyai.com/blog/top-open-source-stt-options-for-voice-applications
- https://huggingface.co/blog/daya-shankar/open-source-llm-models-to-run-locally
- https://whatllm.org/best-ollama-models
- https://aurigait.com/blog/gemma-4-features-benchmarks-guide/
- https://www.betterclaw.io/blog/gemma-4-vs-qwen-3-5
- https://en.wikipedia.org/wiki/Qwen
