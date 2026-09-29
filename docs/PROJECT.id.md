# Thesis Radar — Project Reference

Peta teknis lengkap dari project ini: apa itu Thesis Radar, bagaimana setiap bagian bekerja, dan di mana setiap perilaku (*behaviour*) diatur di dalam kode. Untuk konsep dasar *investing*-nya (apa itu *thesis*, kenapa bisa basi, dan bagaimana suatu *claim* bisa dicek), baca [`THESIS-PRIMER.id.md`](THESIS-PRIMER.id.md) terlebih dahulu.

---

## 1. Masalah yang Dihadapi

Seorang investor menuliskan alasan kenapa dia memiliki suatu saham:

> "Beli BBRI karena kredit tumbuh minimal 10% YoY dan pendapatan bunga bersih naik terus."

Kalimat tersebut adalah sebuah **thesis** — sebuah alasan fundamental, bukan target harga (*price target*). Kalimat itu ditulis sekali, lalu kondisi di lapangan terus berjalan. Pertumbuhan kredit mulai melambat. Pendapatan bunga bersih mendatar (*flatten*). Harga saham bisa saja turun karena hal-hal yang tidak ada hubungannya sama sekali dengan kondisi perusahaan.

Tidak ada yang memberi tahu si pemilik saham. Posisinya masih di-*hold*, tapi *alasan* awal memegangnya sudah tidak lagi benar — dan satu-satunya cara untuk mengetahuinya adalah dengan membuka laporan tahunan (*annual report*), menarik angka-angka kuartalan, dan mengingat kembali angka-angka aslinya dulu.

**Thesis Radar hadir untuk menutup celah tersebut.** Sistem ini mengubah alasan tertulis menjadi *claims* yang bisa dicek oleh mesin, mengukurnya terhadap data laporan keuangan riil, dan menjawab satu pertanyaan secara terjadwal: *apakah alasan ini masih valid?*

### Apa yang Bukan Bagian dari Sistem Ini

- **Bukan nasihat investasi (*investment advice*).** Sistem ini hanya melaporkan apa yang berubah dan seberapa tinggi tingkat keyakinannya (*confidence*). Sistem tidak akan pernah menyuruh beli atau jual. Semua tampilan layar membawa batasan ini.
- **Bukan automated trading.** Tidak ada jalur pembuatan *order* sama sekali di seluruh *codebase* (terverifikasi: tidak ada pemanggilan `order`/`execute`/`broker_order`).
- **Bukan chatbot.** Tidak ada kolom *chat* bebas (*free-form*). Antarmukanya adalah *workspace* riset yang dibangun khusus untuk satu *workflow* kerja yang presisi.

---

## 2. Tiga Lapisan Otoritas (Three Layers of Authority)

Keputusan desain utamanya: **tiga *tools* berbeda menjalankan tiga tugas berbeda, dan masing-masing bekerja jauh lebih baik pada tugasnya dibanding jika dikerjakan yang lain.**

| Tugas | Siapa yang mengerjakan | Kenapa bukan yang lain |
| --- | --- | --- |
| Mengukur angka yang dilaporkan | **Python** | *Language model* tidak bisa dipercaya untuk urusan aritmatika. 16.4% harus tetap 16.4%. |
| Menentukan status *claim*, menjaga teks | **Jev** (TypeSafe System One) | Jawaban keluar berupa *typed values* dengan probabilitas terkalibrasi — tanpa perlu *parse* teks bebas, tanpa perlu menebak-nebak teks. |
| Menulis teks konteks | **LLM** (Hermes atau model apa pun yang kompatibel dengan OpenAI) | Jev sama sekali tidak membuat teks. Ini satu-satunya tugas yang tidak bisa dia lakukan. |

Urutan otoritas ini diatur tegas dan diterapkan langsung di dalam kode:

1. **Pengukuran yang sudah memutus suatu *claim* adalah pemenang mutlak.** Mesin (*engine*) tidak boleh menimpa hasil aritmatika.
2. **Keputusan *typed* dari Jev mengalahkan teks (*prose*).** Keputusan ini dibuat langsung dari bukti (*evidence*), lengkap dengan nilai probabilitasnya.
3. **Engine hanya mengisi celah yang tersisa** — yaitu *claims* yang tidak bisa diputuskan oleh lapisan sebelumnya, serta memberikan konteks di sekitarnya.

Konsekuensinya sengaja dibuat demikian: produk ini **tetap berguna bahkan ketika model sedang tidak aktif/tersedia**. Sistem akan otomatis beralih ke mode pengukuran saja (*measurement-only*), menyatakannya secara transparan, dan membatasi nilai *confidence*-nya di angka `0.0`.

---

## 3. Arsitektur

```
┌─────────────────────────────────────────────────────────────────────┐
│  INPUT                                                              │
│  "Beli BBRI karena kredit tumbuh minimal 10% YoY ..."               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  thesis.decompose()  ← LLM, dengan
                               ▼                        fallback offline
┌─────────────────────────────────────────────────────────────────────┐
│  CLAIMS (disimpan di SQLite)                                        │
│  { metric: gross_loan,           direction: up, threshold: 0.10 }   │
│  { metric: net_interest_income,  direction: up, threshold: null }   │
│  { metric: earnings,             direction: up, threshold: null }   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  THE CHECK  — audit.run()                                           │
│                                                                     │
│  1. watermark      apa yang baru sejak pengecekan terakhir? [code]  │
│  2. measure        ambil data time-series, hitung YoY, trend, [code]│
│                    uji threshold, deteksi diskontinuitas            │
│  3. roll up        claim terburuk menentukan status akhir   [code]  │
│  4. brief          kumpulkan bukti (evidence) jadi teks     [code]  │
│  5. decide         pilihan typed Choice untuk claim         [Jev]   │
│                    yang belum settle, evidence per claim            │
│  6. gate           apakah turn agent benar-benar perlu?     [code]  │
│  7. investigate    loop: model panggil tools, atau          [LLM]   │
│                    keluarkan JSON verdict                           │
│  8. merge          status dari Jev tetap berlaku; engine    [code]  │
│                    hanya menyentuh claim yang belum settle          │
│  9. guard          apakah teks menyebutkan angka yang tidak [Jev]   │
│                    pernah dikembalikan oleh tool?                   │
│ 10. finalise       status, confidence, summary              [code]  │
│ 11. persist        claims, evidence, changes, notify        [code]  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  OUTPUT                                                             │
│  verdict · status per-claim · tabel evidence · change strip ·       │
│  transcript · notifikasi · ringkasan email digest                   │
└─────────────────────────────────────────────────────────────────────┘
```

Setiap tahap mencatat **siapa yang memutuskan**: `decision_path` bernilai salah satu dari:
`measurement` · `jev` · `jev+agent` · `agent` · `agent_unverified`.

---

## 4. Pipeline Tahap demi Tahap

### Stage 1 — Decompose (`thesis.py`)

Satu paragraf dipecah menjadi 1–6 *claims* yang bisa dicek langsung oleh program.

Fungsi `decompose()` meminta model bekerja dengan instruksi ketat terkait bentuk *claim*:

> Setiap claim WAJIB memiliki `metric` dari daftar yang diizinkan, KECUALI penilaian relatif seperti
> valuation … untuk kasus tersebut set `metric` ke null dan `cadence` ke "valuation". Hal lain yang tidak bisa
> diekspresikan dengan metrik yang diizinkan dimasukkan ke `unresolved` — **jangan pernah mengarang metrik sendiri**.

Tersedia dua mekanisme *fallback*, dan keduanya sangat krusial:

- **Tanpa engine** → memakai `decompose_offline()`, sebuah heuristik berbasis pemisah kalimat dan kata sambung.
- **Respons buruk (*bad reply*)** → memakai heuristik yang sama, dengan catatan `engine_error` agar pengguna tahu alasannya.

Sebuah *claim* memuat: `text`, `metric`, `direction` (up/down/flat/none), `threshold` dan `threshold_target` (`growth` vs `level`), `cadence` (quarterly/price/flow/insider/news/corporate_action/valuation), serta nilai *baseline* + tanggal yang dicatat saat *thesis* pertama kali dibuat.

Contoh *output* tipikal:

```json
{"claims": [
  {"text": "kredit tumbuh minimal 10% YoY", "metric": "gross_loan",
   "direction": "up", "threshold": 0.1, "threshold_target": "growth", "cadence": "quarterly"},
  {"text": "pendapatan bunga bersih naik terus", "metric": "net_interest_income",
   "direction": "up", "threshold": null, "cadence": "quarterly"},
  {"text": "valuasi masih murah dibanding bank besar lain", "metric": null,
   "direction": "none", "cadence": "valuation"}
]}
```

### Stage 2 — Watermark (`audit.compute_watermark`)

Setiap *thesis* menyimpan tanggal terakhir pengecekan melihat *ke depan* (*forward from*). Ketika dilakukan pengecekan ulang (*re-check*), *client* hanya meminta data yang lebih baru dari tanggal tersebut. Hal ini membuat pengecekan ulang sangat ringan dan hampir gratis, serta menjadikan *change strip* ("sejak 22 Sep: …") sebagai bukti riil, bukan sekadar rangkuman.

### Stage 3 — Measure (`audit.measure`)

Murni perhitungan matematika tanpa model AI. Untuk setiap *claim*:

- Ubah istilah bahasa manusia menjadi *field* API — `kredit` → `gross_loan`, `laba bersih` → `earnings`, `NII` → `net_interest_income` (menggunakan tabel alias Indonesia/Inggris yang lengkap di `metrics.METRIC_ALIASES`);
- Ambil data kuartalan (*quarterly series*), hitung **YoY** serta **perubahan antar kuartal (QoQ)**;
- Uji *threshold* bawaan *thesis*, jika ada;
- Terapkan **discontinuity guard** (penjelasan di bawah);
- Keluarkan status `supported` / `weakening` / `broken` / `unknown`, **lengkap dengan hitungan aritmatika tertulis** sebagai dasar alasannya (*rationale*).

Uji *threshold* diperiksa *paling awal*, karena angka adalah fakta matematis, bukan opini:

```python
if threshold_ok is False:
    return BROKEN, "...the thesis set a >= threshold of 0.1 on growth and the
                     reported figures do not clear it"
```

Kemudian arah (*direction*), dengan aturan tren:

```python
if trending is True:   return SUPPORTED, "...and the last movements are all up, so the claim holds"
if trending is False:  return WEAKENING, "...but the recent movements (+6.9%, -0.9%, -0.3%)
                                          are not consistently up, so the claim no longer holds"
```

### The Discontinuity Guard (`metrics.break_index`)

Keputusan akurasi paling penting di seluruh *codebase*.

Kasus nyata: laporan `gross_loan` BMRI sempat berubah dari **Rp1.850T → Rp1.568T dalam satu kuartal (−15.2%)**. Kode versi awal membacanya secara polos sebagai penurunan riil, melaporkan "−1.5% YoY", lalu menandai *thesis* sebagai `broken`.

Padahal itu adalah **restatement** — dasar pelaporan angka seri tersebut yang berubah, bukan bisnis perbankannya yang hancur. Oleh karena itu, setiap metrik sekarang dilengkapi batasan asimetris (*asymmetric band*), dan perubahan kuartalan di luar rentang wajar dianggap sebagai **sinyal integritas data, bukan tren bisnis**:

```python
DISCONTINUITY_BANDS = {
    "gross_loan": (0.20, 0.08),      # pertumbuhan hingga +20% masih masuk akal; penurunan di atas -8% tidak wajar
    "revenue":    (0.60, 0.45),
    "provision":  (1.20, 0.90),
    ...
}
DEFAULT_BAND = (1.00, 0.60)
```

Rentang batas ini **sengaja dibuat asimetris**: penyaluran kredit bank sangat mungkin tumbuh 20% dalam satu kuartal, tetapi mustahil tiba-tiba anjlok 20% tanpa peristiwa luar biasa. Saat lonjakan tidak wajar (*break*) terdeteksi, produk ini **menolak perbandingan**, mengubah status *claim* menjadi `unknown`, dan menyimpan insiden tersebut sebagai *evidence* lengkap dengan tanggal serta batasan yang dipakai — jawaban jujur "data ini tidak bisa dibandingkan secara langsung" jauh lebih baik daripada jawaban salah yang tampak meyakinkan.

### Stage 4 — Roll up (`audit._status_from_states`)

*Claim* dengan kondisi terburuk menentukan status akhir *thesis*:

```
any claim broken      → broken
any claim weakening   → weakened
all supported         → intact
otherwise             → needs_review
```

### Stage 5 — Decide (Jev)

Fungsi `audit._decide_with_jev()` mengajukan pertanyaan **typed `Choice` ke Jev untuk setiap claim yang belum tuntas**, dengan menyertakan bukti spesifik milik *claim* tersebut saja. Jev mengembalikan status beserta probabilitas terkalibrasi, dan kode akan mencatat apakah Jev menimpa hasil aritmatika. Contoh catatan aslinya:

```
"Jev overruled the measurement (supported → weakening): Jev decided weakening
 over this claim's measured evidence (confidence 0.95)"
```

Bacalah secara harfiah: **aritmatika menyatakan claim ini didukung (supported), tetapi layer keputusan tidak setuju dengan probabilitas keyakinan 0.95.** Ini adalah contoh tepat di mana angka saja tidak cukup.

Tahap ini juga berfungsi untuk *routing*: jawabannya menentukan apakah *agent* perlu dijalankan atau tidak (`needs_agent`).

### Stage 6 — Gate (`audit.py:762`)

```python
needs_agent   = (not fully_decided) or (decidable not in (None, "none"))
loop_rounds   = 0 if not needs_agent else min(max_rounds, TOOL_CALLS_WHEN_ASSISTED)
```

Jika setiap *claim* sudah berhasil diputuskan dari data pengukuran, **model tidak akan dipanggil sama sekali**. Inilah alasan kenapa pengecekan yang sudah *fully-decided* berjalan instan dan hampir tanpa biaya (*cost*).

### Stage 7 — Investigate (The Agent Loop)

Sebuah *loop* nyata yang ditulis langsung di *repo* ini — bukan sekadar *single prompt*:

```python
for round_no in range(loop_rounds):          # MAX_TOOL_ROUNDS = 3
    if sectors.budget.remaining <= 0: break  # batas kredit ketat (ceiling)
    turn = engine.reply(SYSTEM, messages, tools.schemas())
    ...
    if fingerprint in seen_calls:            # panggilan identik DITOLAK, tidak memotong kredit lagi
        messages.append({"role": "user", "content":
            "You already called {name} with those exact arguments; the result is above
             and unchanged. Choose a different tool or conclude."})
        continue
    outcome = tools.execute(name, args, sectors, store)
    messages.append({"role": "user", "content": _results_message(None, name, outcome)})
```

Aturan perilaku yang ditanamkan dalam *loop*:

- **Budget ceiling** menghentikan *loop* di tengah investigasi jika batas tercapai, dan *transcript* akan mencatatnya secara jelas.
- **Penolakan panggilan duplikat (*duplicate-call refusal*)** — *tool* yang sama dengan argumen persis sama dijawab langsung dari *transcript* tanpa membuang kuota kredit.
- **Dorongan saat macet (*nudge on a stall*)** — jawaban yang tidak memanggil *tool* dan tidak menghasilkan JSON *verdict* akan diminta untuk segera membuat keputusan.
- **Keluar lebih cepat (*early exit*)** — JSON *verdict* yang valid akan langsung menghentikan putaran *loop*.

Satu-satunya tugas model, sebagaimana didefinisikan dalam `SYSTEM`: *claim yang sudah diputuskan bukan urusanmu untuk diubah; tugasmu adalah memberikan konteks* — apakah pergerakan terjadi di level perusahaan atau seluruh sektor, apakah aksi harga itu riil atau efek samping *stock split*/*suspension*, apakah aliran dana masih sesuai asumsi *thesis*, dan apakah cerita di pasar memiliki penyebab bertanggal yang valid.

### Stage 8 — Merge (dengan Hak Veto)

```python
if _measurement_shortfall(measurement) is None and claim_id in jev_states:
    # Ditolak: claim sudah diputuskan dari data terukur, dan teks (prose)
    # tidak berhak mengalahkan hasil aritmatika.
    overrule_notes.append(f"...engine proposed {state}, refused in favour of {measured_state}")
    continue
```

Engine hanya boleh menyentuh *claim* yang **tidak dapat** diselesaikan oleh aritmatika **maupun** Jev. Selain dari itu, intervensi engine ditolak dan dicatat di dalam *notes*.

### Stage 9 — Guard (Jev)

Sistem pengaman teks (*prose guardrail*), dan rancangan pengganti yang memperbaiki sistem lama yang bermasalah.

Jawaban LLM terhadap pertanyaan "apakah kamu mengarang angka itu?" hanyalah opini. Oleh karena itu, kode akan mengekstrak setiap token yang berbentuk angka dari teks, lalu menanyakan ke Jev melalui **pertanyaan `Choice` dengan *framing* positif**: *angka kandidat mana dari daftar ini yang TIDAK ada di dalam bukti (evidence)?*

Perilaku terukur: lima kalimat jujur mendapat skor 0.07–0.09; empat angka karangan (*halusinasi*) mendapat skor 0.64–1.00; kalimat tanpa angka akan langsung melewati model. Batas *threshold*-nya adalah `0.5`.

Jika pengaman ini menyala, status akan diturunkan (`intact` → `weakened`), ringkasan diawali tanda peringatan `⚠︎`, angka bermasalah disimpan sebagai *evidence*, dan nilai *confidence* dibatasi. Sebagai catatan, alternatif yang ditolak: pertanyaan bernada negatif ("apakah laporan ini mengutip angka yang tidak ada…") justru memberi skor tinggi pada kalimat jujur di angka 0.65–0.89 — bahkan kalimat tanpa angka sama sekali diberi skor 0.76. Pertanyaan *positif* terhadap kandidat yang diekstrak kode adalah metode yang terbukti bekerja akurat.

### Stage 10–11 — Finalise dan Persist

Menetapkan status, *confidence* (probabilitas terkalibrasi dari Jev jika diputuskan oleh Jev; dibatasi jika lolos tanpa *guard*), menyusun ringkasan yang bisa dipahami manusia, lalu menjalankan satu transaksi penulisan *claims*, *evidence*, *changes*, dan — hanya jika status benar-benar berubah — mengirimkan notifikasi.

---

## 5. Data Layer (`sectors.py`)

- **REST, bukan MCP.** Menggunakan `https://api.sectors.app`, **17 jalur query berbeda** di bawah `/v2/...`, murni dengan `urllib` standar — tanpa pustaka HTTP pihak ketiga, sehingga *client* dapat berjalan di *bare interpreter*.
- **Disk cache** dengan *key* `sha256(path + "?" + urlencoded params)`. Pengecekan ulang membaca file lokal, dan *cache hit* dicatat di dalam buku besar (*ledger*) dengan `credits: 0` agar penghematan terlihat jelas.
- **Credit ledger** — file *append-only* `.thesisradar/credits.jsonl`, satu baris per panggilan, dilaporkan per *endpoint* termasuk penghematan dari *cache*.
- **Batas kredit ketat (*hard budget ceiling*)** per pengecekan (`THESISRADAR_CHECK_BUDGET`, default 25).

Daftar 17 path *endpoint* yang digunakan:

```
financials/quarterly/{sym}        daily/{sym}                foreign-flow/{sym}
foreign-flow/                     broker-summary/{sym}/top/  filings/
news/                             company/report/{sym}       company/get-segments/{sym}
company/shareholders-composition/{sym}
company/corporate-actions/{sym}   company/get_quarterly_financial_dates/{sym}
subsector/report/{sector}         suspensions/               companies/
companies/top-changes/            index-daily/{index}        index-daily/
tags/
```

---

## 6. Penyimpanan Data / Memory (`store.py`)

Delapan tabel SQLite (mode WAL). Struktur inilah yang menjadikan produk ini sebuah **sistem terstruktur**, bukan sekadar fungsi pemanggil:

| Tabel | Berisi |
| --- | --- |
| `theses` | symbol, statement, status, confidence, **watermark**, flag pantauan (watch), baseline |
| `claims` | claims hasil dekomposisi: metric, direction, cadence, threshold, nilai baseline + tanggal |
| `checks` | satu baris per eksekusi: verdict, confidence, credits, tool_calls, `decision_path`, `confidence_source`, `since` |
| `claim_results` | status per claim + nilai teramati + tanggal + delta + **alasan dasar (rationale)** |
| `evidence` | setiap angka beserta sumbernya: metric, value, as_of, **endpoint**, params, catatan |
| `changes` | apa yang bergeser sejak cek terakhir, besaran pergeseran, dan nomor urut evidence |
| `notifications` | transisi status, dengan tingkat urgensi `alert`/`warning`/`info`/`ok` |
| `runs` | siklus hidup proses (job lifecycle) dan lokasi file log |

Tabel *evidence* adalah bukti audit otentik: **setiap angka di dalam *verdict* bisa dilacak langsung ke *endpoint* dan parameter pemanggilnya**. Tampilan *dashboard* menyediakannya lengkap dengan perintah `curl` yang bisa langsung disalin di setiap baris.

---

## 7. Agent (`tools.py`, `engines.py`)

Tersedia **sepuluh tools**, didefinisikan dalam JSON Schema, di mana masing-masing menjawab sebuah *pertanyaan*, bukan sekadar membungkus *endpoint*:

| Tool | Pertanyaan yang dijawab |
| --- | --- |
| `what_changed` | Apa saja yang baru sejak tanggal tertentu — harga, flow, keterbukaan informasi, berita, aksi korporasi. Panggilan awal paling hemat biaya. |
| `fundamentals_delta` | Data kuartalan time-series untuk satu metrik, lengkap dengan perbandingan YoY dan QoQ. |
| `flow_delta` | Apakah dana masih masuk, atau sudah berbalik keluar? |
| `insider_activity` | Laporan transaksi jual/beli oleh orang dalam (*insider*) dan pemegang saham pengendali, lengkap dengan tanggal. |
| `corporate_action_check` | Apakah pergerakan harga ini murni pasar, atau sekadar efek samping stock split/rights issue/dividen? Apakah saham sedang disuspensi? |
| `sector_context` | Apakah pergerakan ini khusus terjadi di perusahaan ini, atau dialami seluruh sektor? |
| `market_context` | Bagaimana kinerja IHSG dalam periode waktu yang sama? |
| `news_search` | Artikel berita bertanggal, untuk menguji kebenaran cerita/alasan di balik pergerakan. |
| `screen_companies` | Mencari saham berdasarkan bahasa natural atau kriteria mirip query SQL. |
| `evidence_ledger` | Data apa saja yang sudah diketahui sistem saat ini. 0 kredit — baca ini terlebih dahulu. |

**Dua engine di balik satu antarmuka** (`engines.Engine`), sehingga Hermes dapat diganti sewaktu-waktu:

- `hermes` — mengendalikan agent Hermes lokal secara *headless* dengan **tool bawaannya sendiri dimatikan** (`-t '' --ignore-rules --max-turns 8`). Hermes hanya diposisikan sebagai *model endpoint*, bukan sebagai produk: *loop*, *tools*, *state*, dan UI sepenuhnya dikelola oleh *repo* ini.
- `direct` — *endpoint* model apa pun yang kompatibel dengan format OpenAI yang mendukung fungsi *native function calling*.

Fungsi `engines.make()` akan memilih engine terbaik yang tersedia dan melaporkannya.

---

## 8. Otomasi Mandiri (Autonomy)

Produk yang hanya melaporkan perubahan kepada orang yang sedang menatap layar *dashboard* belum benar-benar menyelesaikan masalah. Oleh karena itu, proses pemindaian (*sweep*) berjalan otomatis:

- **Server memegang kendali waktu.** Perintah `serve` memulai jadwal pemindaian di dalam FastAPI *lifespan* dan menghentikannya saat sistem dimatikan — diatur via `THESISRADAR_SCHEDULE_AT` (default `08:00`), `THESISRADAR_SCHEDULE_DAYS` (default `mon,tue,wed,thu,fri`), zona waktu `Asia/Jakarta`.
- **Fungsi waktu menerima "now" sebagai argumen** (`schedule.due_at(now, when, days)`), sehingga pengujian dilakukan dengan hitungan matematika pasti, bukan dengan menidurkan sistem (*sleep*) sampai pagi.
- **Timer menunggu dengan `threading.Event`, bukan `time.sleep`** — pemanggilan `stop()` selesai seketika (~0 ms), dan memanggil `start()` dua kali tidak akan menimbulkan efek samping ganda (*no-op*).
- **Satu daemon thread**, dan proses pemindaian yang memicu *error* akan dilaporkan ke `on_error` alih-alih mematikan *thread*. *Scheduler* yang mati diam-diam jauh lebih berbahaya daripada tidak punya *scheduler* sama sekali.
- **Ringkasan digest dibuat dari tabel notifikasi yang tersimpan**, bukan dari nilai kembalian pemindaian sesaat — sehingga klik tombol manual maupun jadwal otomatis menghasilkan isi email yang konsisten. Transisi berstatus `ok` diabaikan (kembali ke `intact` bukanlah kabar darurat); status `info` tetap disimpan, karena pengecekan perdana adalah pesan bermanfaat pertama dari sistem.
- **Pengiriman bersifat best-effort.** Jika *relay* email tidak dapat dihubungi, sistem mencatat `emailed: false` beserta log kegagalan tanpa mematikan proses utama — pengecekan tetap berjalan, bukti tersimpan, dan sistem beroperasi normal seperti sebelum ada fitur email tanpa kehilangan siklus pemindaian.

Perintah `python -m thesisradar scheduler --now` adalah jalur demonstrasi: jalankan satu kali pemindaian, lalu tunggu. `Scheduler.run_once()` adalah pintu masuk terdokumentasi jika sistem ingin dipicu dari luar (misal: *systemd timer* atau `hermes cron`).

---

## 9. Antarmuka (Interfaces)

**CLI** — memanggil fungsi layanan yang sama persis dengan yang dipakai oleh *dashboard*:

| Perintah | Biaya | Fungsi |
| --- | --- | --- |
| `new --symbol X "<thesis>"` | 1–2 | memecah thesis menjadi claims, mencatat nilai baseline |
| `check X [--budget N]` | ~2–10 | mengukur data, menginterpretasi, menyimpan verdict |
| `check-all [--all]` | per thesis | memindai seluruh thesis yang dipantau |
| `queue` | 0 | daftar antrean kerja, diurutkan dari kondisi terburuk |
| `show X` | 0 | melihat detail satu thesis beserta bukti, histori, dan transcript |
| `draft` | ~6 | mengajukan usulan thesis yang sudah didukung oleh data laporan keuangan |
| `credits` | 0 | melihat rincian pemakaian kredit per endpoint, termasuk penghematan cache |
| `digest [--send]` | 0 | menyusun ringkasan digest tertunda; mengirimkannya via email |
| `scheduler` | per thesis | menjalankan pemindaian otomatis tanpa pengawasan sesuai jam dinding |
| `doctor` | ≤1 | memeriksa environment, status engine, email, dan buku kas kredit |
| `serve` | 0 | menjalankan web dashboard sekaligus mengaktifkan jadwal pemindaian |

**HTTP API** — 15 *route* JSON/SSE, ditambah dua *route* file statis untuk menyajikan *dashboard*:

- *Pembacaan* (`GET`): `health`, `stats`, `queue`, `thesis/{id}`, `check/{id}`, `notifications`, `credits`, `job`, `draft`, dan `events` — yang terakhir berupa *stream* SSE berisi *live transcript* dari proses yang sedang aktif untuk dirender di panel *dashboard*.
- *Penulisan* (`POST`): `thesis` (buat baru), `thesis/{id}/check`, `check-all`, `watch`, `notifications/read`.

**Dashboard** — Dibangun dengan React 19 + TypeScript + Vite, menyediakan empat halaman domain utama dan **tanpa kolom chat**:

1. **Queue** — daftar antrean kerja diurutkan dari status terburuk, lengkap dengan *watermark*, ringkasan statistik, dan jadwal pengiriman email.
2. **Compose** — area penulisan *statement* thesis (masukan teks biasa, keluaran berupa daftar *claims*), serta saran draf dari model yang bisa diedit atau disetujui pengguna.
3. **Thesis workspace** — berkas detail: pita perubahan (*change strip*), tabel *claims*, tabel *evidence* (pencarian, baris yang bisa diperluas, tombol salin perintah `curl`), serta *transcript* terstruktur dengan opsi melihat data mentah.
4. **Notifications** — hanya menampilkan riwayat transisi status.

Komponen `DecisionBadge` menampilkan layer mana yang mengambil keputusan — *"decided by Jev from measured data; no agent turn needed"*, *"decided by the model alone; confidence is capped"*, atau *"no interpretation layer was available"*.

---

## 10. Konfigurasi

File `.env` (mode perizinan file 600, diabaikan oleh git; tidak boleh di-*commit*):

```
SECTORS_API_KEY=                  # wajib diisi
SECTORS_API_BASE=https://api.sectors.app
THESISRADAR_HOME=.thesisradar
THESISRADAR_ENGINE=auto           # auto | hermes | direct
THESISRADAR_MODEL=
THESISRADAR_CHECK_BUDGET=25

# Layer Keputusan
THESISRADAR_JEV_BASE=https://mot.coddx.store/v1
THESISRADAR_JEV_KEY=
THESISRADAR_JEV_MODEL=jev-1.13-free
THESISRADAR_JEV_TIMEOUT=30

# Jadwal Otomatis
THESISRADAR_SCHEDULE_AT=08:00
THESISRADAR_SCHEDULE_DAYS=mon,tue,wed,thu,fri

# Konfigurasi Email
THESISRADAR_SMTP_HOST=
THESISRADAR_SMTP_PORT=587         # 587 STARTTLS, 465 implicit TLS
THESISRADAR_SMTP_USER=
THESISRADAR_SMTP_PASSWORD=
THESISRADAR_SMTP_FROM=            # default sama dengan SMTP_USER
THESISRADAR_SMTP_TO=              # pisahkan dengan koma jika lebih dari satu
THESISRADAR_SMTP_TLS=1            # 0 = implicit TLS saat koneksi awal
```

Setiap lapisan sistem memiliki mekanisme *fallback* resmi, sehingga aplikasi tetap dapat beroperasi normal hanya dengan bermodalkan `SECTORS_API_KEY`.

---

## 11. Verifikasi dan Pengujian

```bash
python tools/verify_pipeline.py     # pengujian end-to-end, tanpa jaringan, TANPA kredit, tanpa model
python tools/verify_endpoints.py    # validasi path client + parameter terhadap dokumen OpenAPI aktif
python tools/verify_endpoints.py --live
python tools/api_smoke.py [--write] # seluruh HTTP route yang dipakai dashboard
cd web && npm run build             # tsc --noEmit && vite build
```

Skrip `verify_pipeline.py` adalah pengujian yang paling utama. Skrip ini membuat *stub* pada lapisan transmisi Sectors (sehingga fungsi *parser* data riil tetap diuji) dan lapisan keputusan Jev, lalu memvalidasi **perilaku nyata sistem (*observable behaviour*)** terhadap angka-angka yang hasilnya sudah diketahui pasti sejak awal:

- *Claim* dengan metrik tumbuh 17% harus lolos dari batas *threshold* 10%;
- Metrik yang turun dua kuartal berturut-turut harus dilaporkan berstatus `weakening`;
- Lonjakan data akibat *restatement* harus ditolak, bukan dilaporkan sebagai penurunan riil;
- Perubahan status menghasilkan tepat satu notifikasi, dan status yang tidak berubah tidak menghasilkan notifikasi apa pun;
- Jadwal pemindaian mengirim tepat satu email jika ada perubahan nyata, tidak mengirim apa pun jika data stagnan, dan tetap aman jika server email menolak koneksi;
- Ketika seluruh *claims* sudah dapat diputuskan dari angka terukur, **engine sama sekali tidak dipanggil**;
- Jika lapisan keputusan *error*, agent tetap mengambil alih keputusan seperti biasa.

Rangkaian tes ini dirancang ketat dan sulit dikelabui: membuat *stub* pada fungsi `quarterly()` alih-alih lapisan transportasinya akan menyembunyikan logika *flattening*, dan data time-series yang tiba-tiba kosong bisa salah disangka sebagai *bug* aplikasi.

---

## 12. Batasan Sistem secara Terbuka

- Data kuartalan berasal langsung dari API sebagaimana dilaporkan per kuartal; sistem tidak mengubah ulang (*restate*) angka-angka tersebut, dan akan menolak perbandingan jika mendeteksi adanya patahan data akibat *restatement*.
- API tidak menyediakan rasio NIM, NPL, atau CAR secara langsung. Thesis yang menyebut rasio-rasio tersebut akan dipetakan ke metrik laporan terdekat **dan hasil tools akan menyatakannya secara transparan**, alih-alih menggantinya secara diam-diam.
- Pengaman teks (*prose guardrail*) memeriksa **angka**, bukan narasi klaim. Kalimat yang tidak memuat angka sama sekali tingkat kebenarannya bergantung pada bukti pendukung di bawahnya — dan kalimat tanpa angka akan langsung melewati pengecekan model.
- Sistem penjadwalan berjalan *in-process* dan *in-memory*: jadwal aktif selama `serve` (atau `scheduler`) menyala, dan tidak mengetahui proses yang berjalan di komputer lain. Sumber data riwayat yang valid adalah tabel `notifications`, bukan riwayat pengiriman *digest*.
- Pengiriman email bersifat searah dan *best-effort*. Tidak ada antrean coba-ulang (*retry queue*) maupun tanda terima baca.
- **Tanpa engine dan tanpa layer keputusan, sistem tetap menghasilkan verdict** hanya dari hasil pengukuran aritmatika (`decision_path: measurement`, `confidence: 0.0`, ringkasan diawali *"Measured without an agent"*). Untuk *claim* yang hanya bisa dinilai oleh model — misalnya valuasi komparatif — sistem akan mengembalikan status `needs_review`. Pembagian tugasnya sangat lugas: **AI memutuskan claim kualitatif dan konteks narasi; hitungan aritmatika memutuskan claim kuantitatif.**

---

## 13. Peta File

```
thesisradar/
  config.py     environment, path direktori, deteksi fitur (has_key, jev_configured, email_configured)
  sectors.py    Sectors REST client: disk cache, credit ledger, batas budget, pembatasan rentang tanggal
  metrics.py    istilah analis → field API; perhitungan YoY, tren, threshold, discontinuity bands
  thesis.py     dekomposisi thesis menjadi claims (dibantu model + fallback offline)
  tools.py      sepuluh tools milik agent (JSON Schema) + fungsi execute()
  engines.py    antarmuka Engine: hermes | direct
  jev.py        Jev (TypeSafe System One) client — layer keputusan dan prose guardrail
  audit.py      alur utama: measure → decide → interpret → guard → persist
  store.py      SQLite: theses, claims, checks, claim_results, evidence, changes, notifications, runs
  transcript.py mengubah transcript mentah menjadi segmen berstruktur typed; tautkan bukti ke segmen
  service.py    operasi bersama untuk CLI dan server; penanganan jobs, jadwal pemindaian, riwayat digest
  schedule.py   pengatur jadwal: parse_when, parse_days, due_at, dengan satu daemon thread
  mailer.py     pembuat ringkasan digest: baris notifikasi → satu email teks biasa
  server.py     JSON API + SSE live transcript + siklus hidup schedule lifespan
  cli.py        antarmuka terminal
web/            dashboard React 19 + TypeScript + Vite (hasil build siap pakai sudah di-commit)
tools/          skrip verifikasi dan pengujian
```

**Prinsip Utama:** bagian inti *agent*, *client* Sectors, dan modul penyimpanan data sengaja dibangun murni menggunakan **standard-library Python**. Komponen-komponen ini dapat dijalankan langsung di *interpreter* polos, di dalam *virtual environment* Hermes, serta di lingkungan CI tanpa risiko ketidakcocokan dependensi. File `requirements.txt` hanya memuat pustaka `fastapi` + `uvicorn` untuk kebutuhan server web.
