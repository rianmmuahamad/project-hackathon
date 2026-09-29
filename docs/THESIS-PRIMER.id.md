# The Thesis Primer

Jika konsep dasar di balik project ini belum pernah dijelaskan kepadamu, mulailah dari sini. Dokumen ini sama sekali tidak membahas kode teknis. Ini adalah penjelasan tentang pola pikir dan filosofi investasi yang mendasari sistem ini.

---

## Bagian 1 — Apa Itu "Thesis"

Sebuah **investment thesis** adalah alasan tertulis kenapa kamu memiliki suatu instrumen investasi (saham).

Bukan soal harga saat ini. Bukan soal garis di grafik chart. Melainkan *alasan dasarnya*:

> "Saya beli dan pegang BBRI karena kreditnya tumbuh minimal 10% YoY dan pendapatan bunga bersihnya naik terus."

Kalimat di atas memiliki tiga karakteristik yang sangat penting:

1. **Tertulis jelas**, satu kali, dalam bahasa sehari-hari yang wajar.
2. **Mengandung fakta yang bisa dicek.** "Kredit tumbuh minimal 10% YoY" adalah angka pasti yang ada atau tidak ada di dalam laporan keuangan. Kalimat ini bukan angan-angan kosong seperti "SAHAM INI BAKAL TO THE MOON".
3. **Alasan tersebut bisa saja sudah tidak berlaku lagi, meskipun harga sahamnya di pasar terlihat baik-baik saja.**

Poin ketiga itulah letak akar masalah yang sebenarnya.

### Kenapa Sebuah Thesis Bisa Basi

Mari lihat contoh urutan kejadian nyata. Kamu membeli saham bank karena kreditnya tumbuh dua digit dan margin keuntungan perbankannya terus melebar. Enam bulan kemudian:

- Pertumbuhan kredit melambat jadi tinggal 4%;
- Peningkatan margin terhenti dan mendatar (*flatten*);
- Namun harga sahamnya justru *naik*, semata-mata karena seluruh sektor perbankan sedang terdorong naik.

Sebagian besar orang akan melihat portofolionya dan merasa tenang — portofolio berwarna hijau. Padahal *alasan awal* membelinya sudah gugur. Kamu saat ini memegang saham atas dasar alasan yang sudah tidak lagi kamu percayai, dan kamu tidak akan mau membelinya lagi hari ini dengan fakta baru tersebut. Tidak ada yang memberi tahumu. Kegagalan tanpa sadar seperti inilah yang ingin dicegah oleh produk ini.

### Perbedaan Antara Thesis dan Prediksi

Thesis itu **bukan** ramalan "harganya bakal naik". Harga saham adalah hasil akhir dari ribuan faktor, yang sebagian besarnya berada di luar kendali perusahaan. Thesis adalah pernyataan tegas mengenai **fakta-fakta bisnis fundamental** yang menjadi tumpuan posisimu.

Perbedaan inilah yang membuat masalah ini bisa dipecahkan oleh software. Tidak ada seorang pun yang bisa memverifikasi prediksi harga secara pasti. Namun setiap orang bisa mengecek apakah penyaluran kredit bank masih tumbuh 10% atau tidak.

---

## Bagian 2 — Apa Itu "Claim"

Untuk mengecek alasan yang tertulis, kamu memecahnya menjadi bagian-bagian pernyataan kecil yang disebut **claims**.

Sebagai contoh:

> "Beli BBRI karena kredit tumbuh minimal 10% YoY dan pendapatan bunga bersih naik terus, jadi laba masih akan naik dua kuartal ke depan."

Kalimat ini memuat **tiga claims terpisah**, bukan satu:

| # | Claim (kata demi kata dari thesis) | Fakta yang ditegaskan | Bisa dicek? |
| --- | --- | --- | --- |
| 1 | *kredit tumbuh minimal 10% YoY* | total kredit (gross loans) tumbuh ≥10% dibanding tahun lalu | Ya — ada angka dan threshold yang jelas |
| 2 | *pendapatan bunga bersih naik terus* | pendapatan bunga bersih (net interest income) konsisten naik | Ya — pergerakan arah tren dari waktu ke waktu |
| 3 | *laba masih akan naik dua kuartal ke depan* | laba bersih terus meningkat | Ya — sebuah arah, yang hasilnya dapat dibuktikan kemudian |

Dan kalimat berikut ini:

> "BMRI kredit tumbuh dua digit dan laba bersih naik, dan valuasi masih murah dibanding bank besar lain."

Kalimat ini **juga** memuat tiga claims — tetapi *claim* yang terakhir merupakan jenis yang *berbeda sifatnya*:

| # | Claim | Fakta yang ditegaskan | Bisa dicek? |
| --- | --- | --- | --- |
| 1 | *BMRI kredit tumbuh dua digit* | total kredit (gross loans) tumbuh ≥10% | Ya |
| 2 | *BMRI laba bersih naik* | laba bersih terus bertumbuh | Ya |
| 3 | *valuasi masih murah dibanding bank besar lain* | valuasinya murah **relatif terhadap bank sekelasnya (peers)** | **Tidak bisa hanya dengan satu angka** |

Claim nomor 3 bukanlah metrik angka tunggal. Ini adalah **penilaian relatif (relative judgement)**. Pernyataan ini butuh komparasi terhadap bank-bank lain, bukan sekadar melihat satu baris angka di laporan keuangan. Perbedaan mendasar inilah yang menjadi dasar desain sistem: dua *claim* pertama bisa diselesaikan secara matematis lewat aritmatika, sedangkan *claim* ketiga harus diputuskan lewat pertimbangan konteks dan bukti (*judgement over evidence*).

Oleh karena itu, setiap *claim* membawa sejumlah atribut data penting:

| Atribut | Makna | Contoh |
| --- | --- | --- |
| `metric` | angka laporan keuangan apa yang menyelesaikannya | `gross_loan` |
| `direction` | arah apa yang ditegaskan oleh thesis | `up` |
| `threshold` | batasan angka yang ditentukan oleh thesis, jika ada | `0.10` = 10% |
| `threshold_target` | apakah batasan tersebut menguji **tingkat pertumbuhan (growth rate)** atau **nilai level nominal**? | `growth` |
| `cadence` | rumpun data apa yang cocok untuk menyelesaikannya | `quarterly` |
| `baseline_value` / `baseline_date` | nilai angka pada saat thesis tersebut ditulis pertama kali | Rp1.580,42T per 2026-06-30 |

Pasangan data terakhir (`baseline`) inilah yang membuat perbandingan menjadi jujur: kamu selalu mengukur data terhadap **kondisi riil pada saat kamu menuliskan kalimat tersebut**, bukan terhadap tanggal acak yang dibuat-buat.

### Kenapa Perbedaan Target Threshold Sangat Krusial

Pernyataan "NIM di atas 5.8%" menetapkan sebuah **level nominal**. Sedangkan "Kredit tumbuh 10%" menetapkan sebuah **laju pertumbuhan (growth rate)**. Bentuk kalimatnya sekilas terdengar mirip, tapi cara mengujinya bertolak belakang. Jika kamu menguji angka nominal seolah-olah itu adalah laju pertumbuhan, *claim* tersebut tidak akan pernah bisa diuji dengan benar. Di dalam kode sistem, perbedaan ini dipisahkan secara tegas melalui atribut `threshold_target`.

---

## Bagian 3 — Apa Artinya "Mengukur" (Measuring) Sebuah Claim

Sekarang mari masuk ke bagian praktisnya. Ini adalah contoh hasil pengecekan nyata yang tersimpan di database untuk saham BBRI:

```
kredit tumbuh minimal 10% YoY
  gross_loan is +16.4% year-on-year
  and the last movements are all up, so the claim holds          → supported

pendapatan bunga bersih naik terus
  net_interest_income is +7.9% year-on-year
  and the last movements are all up, so the claim holds          → supported

laba masih akan naik dua kuartal ke depan
  earnings is +22.3% year-on-year
  but the recent movements (+6.9%, -0.9%, -0.3%)
  are not consistently up, so the claim no longer holds cleanly  → weakening
```

Perhatikan baik-baik *claim* nomor 3 di atas, karena seluruh filosofi produk ini terangkum dalam satu baris tersebut.

Pertumbuhan laba bersih tertulis **naik 22.3% secara tahunan (YoY)** — sebuah judul berita yang sepintas terdengar sangat menggembirakan (*bullish*). Namun jika diteliti lebih dalam, pergerakan tiga kuartal terakhirnya adalah **+6.9%, lalu −0.9%, lalu −0.3%**. Angka tahunannya masih terlihat positif semata-mata karena lonjakan tinggi yang terjadi dua belas bulan yang lalu; sedangkan inti yang ditegaskan di dalam thesis — bahwa laba *konsisten naik terus* — kenyataannya sudah terhenti.

**Itulah perbedaan mendasar antara sekadar angka mentah dan sebuah thesis investasi.** *Screener* saham biasa hanya akan menampilkan angka +22.3% dan kamu akan merasa aman. Namun pengujian thesis menunjukkan tren sebenarnya, dan tren tersebut membuktikan bahwa alasan dasarmu sudah tidak berlaku lagi.

### Empat Status Evaluasi

| Status | Arti |
| --- | --- |
| `supported` | data aritmatika dan pernyataan thesis berjalan selaras |
| `weakening` | angka metriknya masih terlihat aman, tetapi arah pergerakan yang ditegaskan thesis sudah mulai terhenti |
| `broken` | batasan threshold yang ditetapkan thesis tidak terpenuhi — gugur mutlak tanpa perlu interpretasi lagi |
| `unknown` | tidak dapat diputuskan hanya dari metrik tunggal ini, sehingga butuh penilaian bukti lebih lanjut |

Seluruh status *claim* ini kemudian digabungkan (*roll up*) menjadi satu kesimpulan akhir (*verdict*) untuk keseluruhan thesis — di mana **claim dengan kondisi terburuk yang menentukan hasil akhir**:

```
any claim broken     → broken
any claim weakening  → weakened
all supported        → intact
otherwise            → needs_review
```

---

## Bagian 4 — Kenapa Angka Bisa Menipu: Masalah Diskontinuitas (Discontinuity)

Ini adalah studi kasus paling krusial di seluruh project ini, dan ini merupakan kejadian *nyata*, bukan sekadar contoh rekaan.

Angka laporan `gross_loan` BMRI tercatat bergerak:

```
Rp1.850T  →  Rp1.568T     (−15.2% hanya dalam SATU kuartal)
```

Pembacaan awam: penyaluran kredit bank anjlok parah. Tandai thesis sebagai `broken`.

Pembacaan yang benar: **dasar pelaporan data seri tersebut telah diubah.** Terjadi penyajian kembali laporan (*restatement*). Bank tersebut tidak kehilangan 15% dari total portofolio kreditnya hanya dalam kurun waktu tiga bulan — angkanya disajikan ulang dengan definisi akuntansi yang baru.

Versi awal kode program kami sempat salah membaca hal ini. Program melaporkan "−1.5% YoY" dan menetapkan status thesis menjadi `broken`. Itu adalah contoh **jawaban salah yang disajikan dengan rasa percaya diri tinggi (*confidently wrong answer*)** — keluaran terburuk dari sebuah sistem otomatis, karena tampilannya terlihat meyakinkan.

Solusinya: setiap metrik sekarang dilengkapi batasan rentang wajar kuartalan yang asimetris (**asymmetric band**).

```python
"gross_loan": (0.20, 0.08)   # pertumbuhan +20% masih wajar; penurunan -8% sudah tidak masuk akal
"revenue":    (0.60, 0.45)
"provision":  (1.20, 0.90)   # provisi pencadangan kredit bisa berfluktuasi tajam di kedua arah
```

**Sengaja dibuat asimetris.** Buku kredit bank wajar bertumbuh 20% dalam satu kuartal. Namun portofolio kredit mustahil *menyusut* 20% tanpa adanya peristiwa yang luar biasa dahsyat. Ketika suatu pergerakan melompat di luar batas rentang ini, sistem akan **menolak melakukan perbandingan langsung**, mengubah status *claim* menjadi `unknown`, dan mencatat insiden tersebut sebagai *evidence* lengkap dengan tanggal dan batasan rentang yang dipakai.

Keluaran sistem menjadi: *"Data laporan gross_loan tidak konsisten: terjadi pergeseran −15.2% antara 2025-12-31 dan 2026-03-31, yang merupakan restatement pelaporan, bukan transaksi bisnis operasional."*

Pengakuan jujur "data ini tidak bisa dibandingkan secara langsung" jauh lebih berharga daripada angka keliru yang disajikan secara meyakinkan. Prinsip ini tertanam kuat di seluruh sistem.

---

## Bagian 5 — Tiga Pertanyaan, dan Siapa yang Menjawabnya

Setiap pengecekan menjawab tiga pertanyaan penting. Masing-masing dijawab oleh komponen yang paling ahli di bidangnya.

**Q1. Apa fakta yang dikatakan oleh angka-angka data?**
→ **Aritmatika.** Apakah kredit tumbuh 10%? Apakah laba naik tiga kuartal berturut-turut? Tidak ada model AI yang menyentuh tahap ini. Kita tidak bisa mempercayakan perhitungan persentase kepada language model.

**Q2. Apa *makna* dari angka-angka tersebut di kondisi ini?**
→ **Pertimbangan Konteks (Judgement).** Apakah penurunan −3% itu murni masalah internal perusahaan, atau hari itu IHSG memang anjlok 3%? Apakah penurunan harga saham itu nyata, atau akibat teknis penyesuaian *stock split*? Apakah cerita pergerakan ini punya pemicu waktu yang jelas — apakah terjadi saat ada berita faktual, atau narasinya cuma karangan pengamat setelah kejadian?
→ Di sinilah peran model AI dibutuhkan, karena ini bukan sekadar tugas mencari data di tabel.

**Q3. Apakah dasar pemikiran thesis-nya masih kokoh?**
→ **Verdict**, yang disimpulkan dari gabungan evaluasi seluruh *claims*.

### Contoh Nyata Analisis Konteks (Q2)

```
BBNI fell from 3860 to 3460 over 21 traded sessions, with 0 no-trade sessions,
no corporate actions and no suspensions — the price move is real, not a split,
dividend or halt artefact.                                    [−10.36%]

Foreign flow net selling across the window, with sell pressure dominating
buy days.                                  [−Rp178.4B net, 5 buy vs 15 sell days]

New since the watermark: a 2026-09-28 note on liquidity tightening (faster
credit growth than deposit growth), plus 2026-09-27 news naming BBNI among
top foreign net-sell stocks amid broad bank selling.
```

Tidak ada satu pun dari tiga paragraf di atas yang merupakan hitungan aritmatika murni. Namun ketiganya mengubah caramu memahami angka. Paragraf pertama memastikan bahwa penurunan harga saham ini asli, bukan distorsi teknis. Paragraf kedua menunjukkan arus dana memang sedang keluar. Paragraf ketiga memberikan alasan bertanggal yang masuk akal di balik pergerakan tersebut.

Dan yang paling krusial: paragraf terakhir juga **membantu memutuskan claim yang tidak bisa diselesaikan oleh rumus aritmatika**. Untuk kasus saham BMRI, *claim* terkait valuasi berhasil diputuskan:

```
unknown → supported
"what_changed news on 2026-09-27 reports BMRI and BBNI flagged as cheap stocks"
```

Itulah tugas LLM yang tidak bisa digantikan oleh algoritma kaku: mengambil pertimbangan penilaian relatif yang tidak punya metrik angka tunggal, lalu mencarikan bukti pendukung yang valid dari informasi yang ada.

---

## Bagian 6 — Kenapa Model Dilarang Keras Mengarang Data

Ketika sebuah model AI menulis analisis tentang uang dan investasimu, ada risiko model tersebut mengarang angka. Model bisa melakukannya dengan gaya bahasa yang sangat luwes, dan sering kali terdengar makin percaya diri justru saat sedang mengarang.

Oleh karena itu, sistem menerapkan **pengaman teks (guardrail on the prose)**: kode program akan mengekstrak setiap elemen angka dari teks narasi yang dibuat model, lalu meminta model keputusan khusus untuk memeriksa: *angka mana dari daftar ini yang sebenarnya TIDAK PERNAH dikembalikan oleh tools data?*

Ini bukan sekadar prompt basa-basi yang bertanya "kamu yakin?". Ini adalah pertanyaan *typed* terstruktur terhadap daftar kandidat angka yang diekstrak langsung oleh kode sistem.

Hasil pengujian terukur: lima kalimat jujur mendapat skor anomali sangat rendah (**0.07–0.09**); sedangkan empat angka karangan (*halusinasi*) mendapat skor tinggi (**0.64–1.00**). Kalimat yang tidak memuat angka sama sekali akan langsung melewati pengecekan ini.

Ketika pengaman ini mendeteksi anomali, sistem akan melakukan empat tindakan tegas sekaligus:

1. Menurunkan status evaluasi (`intact` → `weakened`),
2. Memberikan tanda peringatan visual di bagian awal ringkasan,
3. Menyimpan angka bermasalah tersebut ke tabel *evidence*, sehingga jejak audit mencatat jelas apa yang tertangkap,
4. Membatasi skor *confidence* — pernyataan yang tidak terverifikasi tidak berhak memiliki tingkat keyakinan tinggi.

Pilihan rancangan yang ditolak penting untuk diketahui agar kita paham kenapa pendekatan "coba tanya modelnya saja" itu keliru: pertanyaan dengan *framing* negatif ("apakah laporan ini mengutip angka yang tidak ada…") justru memberi skor tinggi pada kalimat jujur di angka **0.65–0.89** — bahkan kalimat tanpa angka sama sekali dinilai 0.76. Bertanya dengan sudut pandang *positif*, terhadap angka kandidat yang diekstrak langsung oleh kode, terbukti merupakan metode yang bekerja akurat.

---

## Bagian 7 — Kenapa Produk Ini Hanya Bersuara Saat Ada Perubahan

Pemberitahuan harian yang selalu berbunyi "semua aman" adalah jenis pesan yang pada akhirnya tidak akan dibaca oleh siapa pun. Pada saat benar-benar terjadi hal genting, pesan tersebut sudah terlanjur diabaikan karena dianggap angin lalu.

Oleh karena itu, produk ini dirancang untuk **lebih banyak diam**:

- Setiap pengecekan menyimpan titik waktu batas (**watermark**) — yaitu tanggal acuan untuk membaca data ke depan. Saat pengecekan ulang dilakukan, sistem hanya meminta data dari API yang *lebih baru dari tanggal tersebut*. Inilah alasan kenapa *change strip* ("sejak 22 Sep: …") benar-benar merupakan bukti faktual bukan rangkuman buatan, dan biaya pengecekan ulang menjadi sangat murah.
- Notifikasi **hanya menyala saat terjadi pergeseran status** — misalnya `weakened → broken`, bukan pesan rutin "sudah dicek, kondisi masih aman".
- Ringkasan email sengaja meniadakan laporan transisi yang kembali ke status `intact`. Kondisi kembali normal bukanlah kabar darurat.
- Pengecekan yang seluruh *claims*-nya berhasil diputuskan lewat data angka **sama sekali tidak akan memanggil model AI**. Hasil uji coba pada pipeline stub: selesai dalam **74.7 ms, tanpa pemanggilan model sama sekali**, dengan jalur keputusan `decision_path: jev`. Inilah alasan utama kenapa sistem ini mampu dijalankan secara rutin dan terjadwal dengan sangat hemat biaya.

Dan rutinitas terjadwal itulah tujuan utamanya: proses pemindaian berjalan otomatis berdasarkan waktu jam dinding (`08:00`, hari kerja, waktu Jakarta) tanpa perlu ditunggui manusia. Kamu akan mendapatkan informasi penting melalui email, tanpa harus repot mengingat-ingat untuk membuka dan *login* ke aplikasi.

---

## Bagian 8 — Cara Membaca Lembar Keputusan (Verdict)

Berikut adalah contoh hasil pengecekan nyata yang disalin langsung dari database tanpa perubahan:

```
BMRI · weakened · confidence 0.84 · decided by Jev and the agent
watermark 2026-09-28

claims
  unknown     BMRI kredit tumbuh dua digit
  weakening   BMRI laba bersih naik
  supported   valuasi masih murah dibanding bank besar lain

changes since 2026-09-28
  data     BMRI fell from 4230 to 4020 over 21 sessions, 0 no-trade sessions
                                                          −4.96%
  data     Foreign flow net outflow over 21 days, sell days dominating
                                                          −Rp1.45T, 6 buy vs 14 sell days
  context  2026-09-28 headline: Foreign Net Sell Widens, dragging BMRI and TL…
           IHSG −1.5% on 2026-09-28, weekly net sell Rp4.39T

evidence
  latest_quarterly_report = 2026-06-30        /v2/financials/quarterly/BMRI/
  last_traded_session = 2026-09-28            /v2/daily/BMRI/
  gross_loan discontinuity = Rp1,568.08T from Rp1,849.9…   as_of 2026-03-31
                                              /v2/financials/quarterly/BMRI/
```

Satu contoh di atas telah merangkum cara kerja hampir keseluruhan produk ini. Mari kita bedah dalam empat tahap pembacaan:

**1. Claim berstatus `unknown` membuktikan pengaman diskontinuitas berfungsi.** *Claim* *"kredit tumbuh dua digit"* menghasilkan status `unknown`, bukan `broken` — karena pada tabel *evidence* terdapat baris bernama `gross_loan discontinuity`, yang mendokumentasikan lonjakan data dari Rp1.849,9T ke Rp1.568,08T pada 2026-03-31. Sistem menolak membandingkan data yang terdistorsi oleh penyajian kembali (*restatement*), alih-alih menyimpulkan penurunan palsu. Poin pada Bagian 4 di atas tercermin langsung pada baris ini.

**2. Claim valuasi berstatus `supported` membuktikan model AI menjalankan tugasnya dengan tepat.** Ini adalah jenis *claim* yang tidak memiliki metrik angka tunggal — sebuah penilaian komparatif. Rumus matematika tidak bisa memutuskannya. *Agent* menyelesaikannya dari berita bertanggal faktual, dan alasannya dinyatakan secara transparan: *"what_changed news on 2026-09-27 reports BMRI and BBNI flagged as cheap stocks."* Tipe *claim* ketiga pada Bagian 2 berhasil diselesaikan.

**3. Pita perubahan (change strip) menyajikan penyebab bertanggal dan angka pergerakan yang terukur.** Bukan sekadar narasi hampa seperti "sentimen sedang melemah" — melainkan judul berita lengkap dengan tanggalnya, pelemahan indeks sebesar −1.5%, dan nilai penjualan bersih asing mingguan sebesar Rp4,39T. Ini adalah penerapan praktis dari prinsip pada Bagian 7.

**4. Setiap angka memiliki sumber endpoint.** Tidak ada data di dalam kesimpulan tersebut yang anonim atau tanpa jejak asal-usul. Kamu bisa menjalankan ulang pemanggilan API-nya sendiri kapan saja, dan itulah fungsi utama dari tabel bukti (*evidence table*).

---

## Bagian 9 — Hal-Hal yang Sengaja Tidak Dilakukan oleh Produk Ini

- **Sistem ini tidak menyuruhmu untuk membeli atau menjual saham.** Produk ini hanya melaporkan apa yang berubah dan seberapa tinggi tingkat keyakinan datanya.
- **Sistem ini tidak mengeksekusi order transaksi.** Sama sekali tidak ada jalur pembuatan pesanan perdagangan di dalam kodenya.
- **Sistem ini tidak memprediksi pergerakan harga.** Thesis adalah tentang fakta-fakta fundamental bisnis perusahaan, dan itulah satu-satunya hal yang diukur oleh sistem ini.
- **Sistem ini tidak menutupi data yang jelek atau rusak.** Ketika data tidak konsisten, atau metrik yang dicari tidak ditemukan, atau teks buatan model mengutip hal yang mengada-ada, sistem akan menyatakannya secara terbuka — di ringkasan, di tampilan layar, maupun di dalam rekaman bukti yang tersimpan.

Kesimpulan satu kalimat untuk keseluruhan produk ini:

> **Kamu menuliskan alasan kenapa kamu membeli dan memiliki suatu saham. Sistem ini akan memberitahumu saat alasan tersebut sudah tidak lagi berlaku.**

---

## Glosarium (Glossary)

| Istilah | Makna |
| --- | --- |
| **Thesis** | Alasan tertulis kenapa kamu memiliki suatu saham. |
| **Claim** | Satu fakta tunggal yang dapat diuji secara independen di dalam sebuah thesis. Thesis dengan 3 claims berarti memuat 3 pengecekan terpisah. |
| **Metric** | Angka laporan keuangan yang menjadi rujukan untuk menyelesaikan sebuah claim — misalnya `gross_loan`, `earnings`, `net_interest_income`. |
| **Threshold** | Batasan minimal/maksimal yang ditentukan sendiri di dalam thesis ("minimal 10%"). Jika angka gagal melewatinya, status langsung `broken`, tanpa perlu interpretasi lagi. |
| **Cadence** | Rumpun frekuensi data yang dipakai untuk menyelesaikan claim: quarterly, price, flow, insider, news, corporate action, valuation. |
| **Baseline** | Nilai angka metrik tepat pada hari saat thesis pertama kali ditulis — titik pembanding yang jujur. |
| **Watermark** | Batas tanggal acuan bagi pengecekan untuk membaca data ke depan. Membuat pengecekan ulang sangat hemat biaya dan menjaga catatan perubahan tetap faktual. |
| **Verdict** | Kesimpulan akhir dari keseluruhan thesis: `intact` / `weakened` / `broken` / `needs_review`. |
| **Restatement** | Data laporan keuangan yang disajikan kembali menggunakan dasar definisi yang berbeda. Dideteksi dan ditolak perbandingannya, bukan ditelan mentah-mentah. |
| **Discontinuity band** | Rentang batas perubahan kuartalan yang masih masuk akal untuk suatu metrik, yang sengaja dirancang asimetris. |
| **Evidence** | Setiap angka data yang mendasari kesimpulan, lengkap beserta asal endpoint dan parameternya. |
| **Decision path** | Layer mana yang mengambil keputusan akhir: `measurement`, `jev`, `jev+agent`, `agent`, atau `agent_unverified`. |
| **Guardrail** | Mekanisme pengujian untuk memastikan tidak ada angka dalam teks model yang absen dari tabel bukti riil. |
