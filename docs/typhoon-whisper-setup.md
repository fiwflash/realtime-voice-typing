# เพิ่มโมเดล Typhoon Whisper (SCB 10X) เข้าในแอป

Typhoon Whisper เป็นโมเดล ASR ภาษาไทยฟรี (MIT) ที่แม่นกว่า Pathumma / Thai Distill
ที่แอปมีอยู่ตอนนี้ แต่**เป็น format `safetensors` (Transformers)** — แอปนี้โหลดโมเดลด้วย
`faster-whisper` ซึ่งต้องใช้ **CTranslate2 (`model.bin`)** จึงต้องแปลงก่อน แล้วอัปโหลดขึ้น
Hugging Face ก่อนที่แอปจะดาวน์โหลดได้ผ่านปุ่ม "จัดการโมเดล" ตามปกติ

คู่มือนี้ครอบคลุมทั้ง 3 ขั้นตอน: (1) แปลง → (2) อัปโหลด → (3) เพิ่มรายการในแอป

---

## ขั้นที่ 1 — ติดตั้ง dependencies (ครั้งเดียว)

```powershell
python -m pip install ctranslate2 transformers torch huggingface_hub
```

> ต้องการพื้นที่ดิสก์รวมราว 6–8 GB (ดาวน์โหลด weights ต้นฉบับ + ไฟล์แปลง)

## ขั้นที่ 2 — แปลงเป็น CTranslate2

มีสคริปต์สำเร็จรูปใน `scripts/convert_typhoon_ct2.py`:

```powershell
# Turbo — เร็ว เหมาะ dictation (~1.6 GB)
python scripts/convert_typhoon_ct2.py turbo

# Large v3 — แม่นสุด (~3 GB)
python scripts/convert_typhoon_ct2.py large-v3
```

สคริปต์จะสร้างโฟลเดอร์ `ct2-turbo` / `ct2-large-v3` ที่มี `model.bin`,
`config.json`, `tokenizer.json`, `preprocessor_config.json` ครบตามที่แอปต้องการ

## ขั้นที่ 3 — อัปโหลดขึ้น Hugging Face

แอปดาวน์โหลดโมเดลผ่าน `snapshot_download(repo_id=...)` จึงต้องเอาไฟล์ CT2 ขึ้น HF:

```powershell
python scripts/convert_typhoon_ct2.py turbo --repo-id <your_username>/typhoon-whisper-turbo-ct2 --token hf_xxxx
python scripts/convert_typhoon_ct2.py large-v3 --repo-id <your_username>/typhoon-whisper-large-v3-ct2 --token hf_xxxx
```

- `<your_username>` = บัญชี Hugging Face ของคุณ (เช่น `fiwflash`)
- `--token` = write token สร้างได้ที่ https://huggingface.co/settings/tokens

## ขั้นที่ 4 — เพิ่มรายการในแอป

เมื่ออัปโหลดเสร็จ ให้เพิ่ม entry ใน `src/realtime_voice_typing/model_manager.py`
(ใน `MODEL_CATALOG`) — วางตามลำดับที่ต้องการ:

```python
    ModelEntry(
        key="typhoon-turbo",
        label="Typhoon Turbo — Thai (fast)",
        repo_id="<your_username>/typhoon-whisper-turbo-ct2",
        size_gb=1.6,
        languages="ไทยล้วน",
        note="SOTA ภาษาไทยจาก SCB 10X เร็ว+แม่น เน้นไทยล้วน",
    ),
    ModelEntry(
        key="typhoon-large",
        label="Typhoon Large v3 — Thai (accurate)",
        repo_id="<your_username>/typhoon-whisper-large-v3-ct2",
        size_gb=3.0,
        languages="ไทยล้วน",
        note="แม่นภาษาไทยสูงสุดในชุด เน้นเครื่องมีการ์ดจอแยก",
    ),
```

และเพิ่มสเปคใน `src/realtime_voice_typing/settings.py` (ใน `MODEL_SPECS`) เพื่อให้
ปุ่ม "สเปคแต่ละโมเดล" และคำแนะนำสเปคเครื่องทำงานถูกต้อง:

```python
    ModelSpecInfo(
        key="typhoon-turbo",
        label="Typhoon Turbo — Thai (fast)",
        languages="ไทยล้วน",
        disk_gb="~1.6 GB",
        vram_gb="~1.8–2.4 GB",
        ram_gb="~2.0–3.0 GB",
        min_spec="GPU 4 GB VRAM หรือ CPU 6–8 คอร์, RAM 16 GB",
        recommended_spec="GPU 6–8 GB VRAM (RTX 3050/3060/4060), RAM 16 GB",
        note="SOTA ภาษาไทยจาก SCB 10X เร็ว+แม่น เน้นไทยล้วน",
        min_vram_gb=4.0,
        cpu_realtime_ok=True,
    ),
    ModelSpecInfo(
        key="typhoon-large",
        label="Typhoon Large v3 — Thai (accurate)",
        languages="ไทยล้วน",
        disk_gb="~3.0 GB",
        vram_gb="~3.3–4.2 GB",
        ram_gb="~3.5–5.0 GB",
        min_spec="GPU 6 GB VRAM, RAM 16 GB (ไม่แนะนำบน CPU ล้วน)",
        recommended_spec="GPU 8 GB VRAM+ (RTX 3060/4060), RAM 16 GB",
        note="แม่นภาษาไทยสูงสุดในชุด เน้นเครื่องมีการ์ดจอแยก",
        min_vram_gb=6.0,
        cpu_realtime_ok=False,
    ),
```

> **หมายเหตุ** — ค่า `size_gb`, `vram_gb`, `ram_gb`, `min_spec` ด้านบนเป็นค่าประมาณ
> จากสถาปัตยกรรม Whisper large-v3-turbo / large-v3 ตามลำดับ ควรยืนยันกับขนาดไฟล์จริง
> หลังแปลงเสร็จ (ดู `model.bin` ที่ได้จากขั้นที่ 2)

---

## สรุปตัวเลข (อ้างอิง Typhoon ASR Benchmark — CER ยิ่งน้อยยิ่งดี)

| โมเดล | Gigaspeech2 | TVSpeech (noisy) | Fleurs |
|---|---:|---:|---:|
| Typhoon Whisper Large v3 | **4.69** | **6.32** | 9.98 |
| Typhoon Whisper Turbo | 4.79 | 6.85 | 10.52 |
| Pathumma (ที่แอปมี) | 5.84 | 10.36 | 6.29 |
| Thai Distill (ที่แอปมี) | 8.24 | 13.82 | 6.77 |

ทั้งคู่เป็น **ไทยล้วน** — ถ้าต้องการประโยคปนอังกฤษ Pathumma ยังเป็นตัวเลือก bilingual ที่ดี
