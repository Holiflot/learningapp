# Speaking Tutor

İngilizce konuşma pratiği için yerel çalışan bir web uygulaması. Bir konu seçiyorsun, düğmeyi
(ya da `Space` tuşunu) basılı tutup konuşuyorsun. Konuşman yazıya dökülüyor, yerel bir dil modeli
de İngilizce öğretmeni gibi yazılı cevap veriyor, hatalarını düzeltiyor ve ders sonunda özet çıkarıyor.
Hiçbir veri bilgisayarından çıkmaz.

```
Tarayıcı (bas-konuş, 16 kHz WAV) ──► FastAPI ──► whisper.cpp server (Vulkan, GPU)  → metin
                                          └────► Ollama (gemma4:12b, Vulkan, GPU)  → öğretmen cevabı (JSON)
```

## Seçilen modeller (AMD RX 6700 XT, 12 GB)

| Görev | Model | VRAM | Neden |
|---|---|---|---|
| Konuşma → metin | Whisper **large-v3-turbo** (q5_0, whisper.cpp) | ~1 GB | Aksanlı İngilizcede en sağlam açık model. whisper.cpp Vulkan ile AMD'de GPU'da çalışır. |
| Öğretmen | **Gemma 4 12B** (`gemma4:12b`, Q4) | ~8 GB | 12 GB karta tamamen sığan en güçlü güncel model. Sohbet dili doğal, Türkçe açıklamada iyi. |

İkisi birlikte yaklaşık 10-11 GB kullanır. Neden diğerleri değil:

- **Qwen 3.8** (Ağustos 2026) sadece 27B ve 2.4T boyutlarında çıktı. 27B'nin Q4 hali ~17 GB,
  Q3 hali ~13 GB. 12 GB'a sığmıyor, RAM'e taşınınca ~4 token/sn'ye düşüyor. Varsayılan olarak
  da çok uzun "düşünüyor". Sohbet için fazla yavaş.
- **Qwen 3.6-35B-A3B** (MoE, aktif 3B): Q4 ~20 GB. 32 GB RAM'in varsa, bir kısmı RAM'de
  olacak şekilde çalışır ama Gemma 4 12B'den yavaştır. Sohbet kalitesi benzer. Denemek istersen
  `.env` içinde `OLLAMA_MODEL`'i değiştir ve `OLLAMA_THINK=false` yap.
- **Gemma 4 E4B** (`gemma4:e4b`, ~5 GB): Daha hızlı ve hafif bir yedek.
- NVIDIA'nın STT modelleri (Parakeet, Canary) CUDA istediği için AMD'de pratik değil.

## Kurulum

### 1. Ollama (AMD GPU ile)
1. [ollama.com](https://ollama.com) adresinden Ollama'yı kur.
2. RX 6700 XT (gfx1031) resmi ROCm listesinde yok. **Vulkan** arka ucunu aç:
   - **Windows:** Ayarlar → Sistem → Gelişmiş sistem ayarları → Ortam değişkenleri →
     yeni sistem değişkeni `OLLAMA_VULKAN` = `1`. Ardından Ollama'yı tepsiden kapatıp yeniden aç.
   - **Linux:** `sudo systemctl edit ollama` → `[Service]` altına
     `Environment="OLLAMA_VULKAN=1"` ekle, sonra `sudo systemctl restart ollama`.
     (ROCm + `HSA_OVERRIDE_GFX_VERSION=10.3.0` de bir yol, ama ROCm 6.4.3 ve sonrasında bu kartta
     çökme hatası bildiriliyor. Vulkan daha sorunsuz.)
3. Modeli indir ve GPU'da çalıştığını kontrol et:
   ```
   ollama pull gemma4:12b
   ollama run gemma4:12b "hello"
   ollama ps        # PROCESSOR sütununda "100% GPU" görmelisin
   ```

### 2. whisper.cpp server (Vulkan)
[Vulkan SDK](https://vulkan.lunarg.com/) ve CMake gerekir (Windows'ta ayrıca Visual Studio Build Tools).
```
git clone https://github.com/ggml-org/whisper.cpp
cd whisper.cpp
cmake -B build -DGGML_VULKAN=1
cmake --build build -j --config Release

# model (~550 MB)
# Linux:   sh ./models/download-ggml-model.sh large-v3-turbo-q5_0
# Windows: .\models\download-ggml-model.cmd large-v3-turbo-q5_0

# sunucuyu başlat (Windows'ta: build\bin\Release\whisper-server.exe)
./build/bin/whisper-server -m models/ggml-large-v3-turbo-q5_0.bin --host 127.0.0.1 --port 8178 -l en
```
Başlangıç günlüğünde Vulkan cihazı olarak `AMD Radeon RX 6700 XT` görünmeli.

**Derlemekle uğraşmak istemezsen:** `.env` içinde `STT_BACKEND=faster-whisper` yap ve
`pip install -r requirements-cpu-stt.txt` çalıştır. Whisper bu durumda işlemcide çalışır.
Kısa cümlelerde birkaç saniye sürer ama whisper-server'a gerek kalmaz.

### 3. Uygulama
Python 3.10+ gerekir.
```
python -m venv .venv
# Windows: .venv\Scripts\activate     Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
python -m app.main
```
Tarayıcıda **http://127.0.0.1:8000** adresini aç. Sağ üstteki `LLM` ve `STT` göstergeleri yeşil olmalı.
Mikrofon izni ilk konuşmada istenir (localhost güvenli sayılır).

## Kullanım
- Konu seç ya da kendi konunu yaz. Seviyeyi (A2-C1), düzeltme sıklığını ve açıklama dilini seç.
- Mikrofon düğmesini **basılı tut**, konuş ve bırak. Klavyede `Space` tuşunu basılı tutmak da aynı işi yapar.
- Her mesajının altında düzeltmeler ve "daha doğal" hali, öğretmenin mesajında da yeni kelimeler çıkar.
- **Bitir ve değerlendir** düğmesi tekrar eden hataları ve sonraki adımları özetler.

### Whisper'ın hataları "düzeltmesi"
Whisper bazen dilbilgisi hatalarını yazıya dökerken sessizce düzeltir ("he go" → "he goes").
Bu durumda öğretmen hatayı göremez. Uygulama bunu azaltmak için Whisper'ı sıcaklık 0 ile ve
yönlendirme metni vermeden çalıştırır. Yine de şüphelenirsen **"Göndermeden önce yazıya dökülen
metni kontrol edeyim"** seçeneğini aç. Metin gönderilmeden önce kutuya düşer, düzeltip Enter'a basarsın.

## Ayarlar (`.env`)
| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `OLLAMA_MODEL` | `gemma4:12b` | Öğretmen modeli |
| `OLLAMA_THINK` | (boş) | Qwen gibi düşünen modellerde `false` yap |
| `OLLAMA_KEEP_ALIVE` | `30m` | Model VRAM'de ne kadar süre bekleyecek |
| `STT_BACKEND` | `whispercpp` | `whispercpp` veya `faster-whisper` (CPU) |
| `WHISPER_SERVER_URL` | `http://127.0.0.1:8178` | whisper-server adresi |

VRAM yetmezse (Windows masaüstü de VRAM kullanır) önce `gemma4:e4b`'yi dene ya da STT'yi CPU'ya al.

## Geliştirme
```
pip install -r requirements-dev.txt
pytest
```
Testler sahte STT ve sahte LLM ile çalışır, GPU gerektirmez.
