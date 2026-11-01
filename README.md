# PES SE2026 — Data Pendukung

Portal data hasil SE2026 sebagai bahan pendukung kegiatan PES SE2026 BPS Kabupaten Bulungan, menggunakan Flask, SQLAlchemy, SQLite, OpenPyXL, Jinja, dan JavaScript ringan. Tiga layar utama: daftar SLS, daftar assignment, dan rincian menurut blok form SE2026. Seluruh data tetap lokal secara default.

Antarmuka menggunakan narasi PES SE2026, daftar wilayah/objek ringkas, live search, dan pembaca satu blok form aktif dengan navigasi kanan–kiri. Daftar objek memuat 12 baris per halaman; rincian ART/usaha dibaca melalui pemilih nama. Panduan desain dan alur terakhir tersedia di [UI_UX_PES.md](docs/UI_UX_PES.md). Angka cakupan dan catatan pemeriksaan menunjukkan kondisi data sumber SE2026 yang digunakan untuk mendukung kegiatan PES.

Nominal pendapatan, pengeluaran/biaya, dan nilai aset ditampilkan sebagai kisaran acuan pada seluruh mode akses, termasuk admin. Nominal tepat tidak dikirim ke browser. Jumlah aset dan NIK/KK tetap ditampilkan sesuai sumber; nilai nol dibedakan dari isian kosong. Workbook dan database sumber tetap menyimpan nilai asli.

## Menjalankan di Windows

Python 3.11+ diperlukan. Dari folder proyek:

```powershell
.\start.ps1
```

Atau jalankan manual:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe setup_local.py
.\.venv\Scripts\python.exe run_local.py
```

Buka http://127.0.0.1:6502 dan masuk menggunakan email petugas. PPL melihat dua SLS alokasinya; PML melihat gabungan alokasi PPL yang diawasi; admin mengakses seluruh wilayah. NIK/KK tetap lengkap dan nominal uang tetap disamarkan. Excel tidak disajikan melalui web. Logo resmi BPS dicatat di [LOGO.md](docs/LOGO.md). Secret lokal acak disimpan di `instance/secret.key`; untuk deployment gunakan environment `SECRET_KEY`. File `.env` dipakai Compose; peluncuran Python langsung memakai environment proses atau secret lokal.

Login aktif secara default (`AUTH_REQUIRED=1`), termasuk pada launcher Windows dan konfigurasi Compose. Pada pemasangan kosong, setup membuat admin awal acak di berkas privat jika belum ada admin. Impor alokasi mengaktifkan daftar akun baru dan menonaktifkan akun lama di luar daftar tersebut. Panduan alokasi, cakupan peran, dan distribusi kredensial ada di [LOGIN_ALOKASI.md](docs/LOGIN_ALOKASI.md).

## Perintah administrasi

Gunakan Python virtual environment untuk setiap perintah:

```powershell
.\.venv\Scripts\python.exe -m flask --app wsgi init-db
.\.venv\Scripts\python.exe -m flask --app wsgi import-excel "." --report-dir docs
.\.venv\Scripts\python.exe -m flask --app wsgi import-allocations "FILE_ALOKASI.xlsx" --check
.\.venv\Scripts\python.exe -m flask --app wsgi import-allocations "FILE_ALOKASI.xlsx" --admin-email EMAIL_ADMIN --credentials-file private\akun_petugas_PES_SE2026.xlsx
.\.venv\Scripts\python.exe -m flask --app wsgi set-password EMAIL_PETUGAS --credentials-file private/akun_petugas_PES_SE2026.xlsx
```

Password admin diminta tersembunyi. Akun PPL/PML dibuat dari workbook alokasi dengan password unik; server menyimpan hash. Berkas distribusi petugas berada di `private/`, tidak dikirim oleh web, dan tidak mencakup password admin. Impor yang diulang menolak penimpaan akun atau berkas kredensial. Perintah `set-password` mengubah satu password dan membatalkan sesi lama akun tersebut. Semua peran tetap melihat nominal dalam bentuk kisaran.

Impor data pendataan membutuhkan 13 nama file sesuai `portal/catalog.py`; workbook alokasi diproses terpisah. File audit tambahan tidak digabung karena relasinya belum diverifikasi. Lihat [analisis data](docs/ANALISIS_DATA.md), [kamus kolom](docs/data_dictionary.json), dan [arsitektur](docs/ARSITEKTUR.md). Laporan metadata tidak memuat identitas responden. Menu Dataset tetap tersembunyi dan endpoint administrasinya khusus admin. Log server tidak memuat kata sandi atau isi pendataan.

## Pembaruan dataset

1. Backup database aktif terlebih dahulu.
2. Simpan satu paket lengkap 13 workbook baru dalam folder privat tersendiri. Jangan menimpa sumber saat impor berlangsung.
3. Jalankan `import-excel` dengan folder baru. Setiap file divalidasi sebelum commit; kegagalan mempertahankan snapshot lama. Hash identik menjadi no-op. Akun dan penugasan pengguna tidak dihapus.
4. Periksa ringkasan jumlah, baris tanpa pasangan, duplikasi, kode wilayah, dan panel Dataset. Semua baris sumber tetap disimpan; yang ambigu tidak di-JOIN.
5. Periksa penugasan jika daftar kode wilayah berubah. Akun petugas tidak otomatis mendapat akses ke wilayah baru.

## Pengujian

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_real_data.py
```

Tests memakai data sintetis, termasuk tiga roster ART dan dua roster usaha pada satu keluarga untuk membuktikan tidak ada perkalian baris. Pemeriksaan data asli mencetak agregat saja dan memakai database sementara. Hasil validasi aktual dicatat di `docs/VALIDASI.md`.

## Docker Compose

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
# Isi SECRET_KEY di .env dengan hasil generator. Jangan commit .env.
docker compose up -d --build
docker compose exec portal flask --app wsgi init-db
docker compose exec portal flask --app wsgi import-excel /data --report-dir /app/instance/reports
# Pembuatan akun hanya diperlukan jika AUTH_REQUIRED=1.
```

Sumber Excel dimount read-only pada `/data`; database memakai volume `portal_data`. Container tidak memuat Excel atau database produksi pada image. Port hanya terikat `127.0.0.1`. Health endpoint `/health` hanya menyatakan proses dan koneksi database tersedia; readiness `/ready` memeriksa versi schema, dataset, wilayah, dan admin aktif. Login aktif secara default pada Compose.

Untuk Traefik yang sudah tersedia, isi `PORTAL_HOST`, nama network, resolver TLS pada `.env`, lalu gunakan `docker compose -f compose.yml -f compose.traefik.yml up -d`. Proxy harus satu-satunya jalur akses jaringan ke aplikasi; header proxy dipercaya hanya ketika `TRUST_PROXY=1`. `COOKIE_SECURE=1` untuk HTTPS, `0` untuk HTTP lokal. HTTPS dan firewall dikelola administrator sesuai lingkungan. Konfigurasi dasar tidak menerbitkan layanan ke internet.

## Backup dan restore

Backup SQLite yang konsisten, termasuk ketika server sedang berjalan:

```powershell
.\.venv\Scripts\python.exe -m flask --app wsgi backup-db "C:\LokasiPrivat\portal-2026-10-31.sqlite3"
```

Folder tujuan harus sudah ada dan file tujuan belum ada. Simpan backup dalam lokasi terenkripsi/terbatas. Backup berisi seluruh data pribadi dan akun; jangan unggah ke repositori. Simpan juga secret konfigurasi secara terpisah. Untuk Docker, gunakan `docker compose exec portal flask --app wsgi backup-db /app/instance/backup.sqlite3` lalu `docker compose cp portal:/app/instance/backup.sqlite3` ke lokasi privat. Pilih nama baru tiap backup.

Restore lokal: hentikan server, simpan salinan database aktif untuk rollback, ganti `instance/portal.sqlite3` dari backup, lalu jalankan server lagi. Pada Docker hentikan proses aplikasi sebelum mengganti file di volume (misalnya melalui container sekali jalan yang memasang volume yang sama), kemudian start kembali. Jangan menyalin database mentah saat sedang ditulis. Uji login, panel dataset, dan pembatasan wilayah setelah restore. Skema versi awal dibuat dengan `init-db`; upgrade ini memakai `migrate-db` aditif dengan marker versi. Backup selalu dilakukan sebelum migrasi. Migrasi berikutnya yang mengubah struktur kolom memerlukan skrip versi baru.

## Batas informasi sumber

Label dan pilihan jawaban kini mengikuti metadata SQL Lab serta form referensi SE2026 7.1.2 yang diberikan pengguna. Lihat [pemetaan label](docs/MAPPING_LABEL.md), [cakupan pemetaan](docs/CAKUPAN_METADATA.json), dan katalog `portal/data/field_metadata.json`. Katalog dibundel dalam aplikasi; sumber PDF/XLSX/HTML referensi tidak diperlukan saat server berjalan. Untuk membangun ulang katalog, pasang `requirements-dev.txt`, lalu jalankan `scripts/build_metadata_catalog.py --metadata "path-metadata.xlsx" --form "path-SE2026.html" --pdf "path-panduan.pdf"` dan mulai ulang server.

Label asli Excel diprioritaskan. Pilihan yang belum memiliki definisi, termasuk beberapa hasil KBLI dinamis atau referensi nama ART tanpa pasangan, tetap menampilkan kode sumber. Aturan skip tidak dijalankan ulang; kosong tidak otomatis dianggap Tidak/Tidak berlaku. Tautan FASIH dan hak akses foto masih belum diverifikasi. Daftar indikator bukan penetapan bahwa data salah. BKU tanpa roster UMKM dapat memiliki rincian pada instrumen lain. Versi pertama hanya membaca data; pencatatan kegiatan PES dan perubahan pendataan belum dibuat sesuai ruang lingkup.

Susunan detail kini mengikuti blok asli form SE2026, termasuk SE2026-P dan SE2026-L Blok I–IV. Lihat [BLOK_FORM.md](docs/BLOK_FORM.md) untuk pembagian, urutan, penggabungan sumber, dan bagian form yang tidak tercakup pada ekstraksi.


## Pembaruan audit 1 November 2026

Rincian implementasi dan batas pengujian: [IMPLEMENTASI_AUDIT_2026-11-01.md](docs/IMPLEMENTASI_AUDIT_2026-11-01.md). Password yang sudah didistribusikan tetap berlaku. Sesi sebelum upgrade harus login ulang.

- Instalasi yang dapat diulang: `python -m pip install -r requirements.lock.txt`; pengembangan memakai `requirements-dev.lock.txt`. Docker memakai lockfile runtime. Workflow GitHub disiapkan untuk tes backend/browser dan pemindaian dependency terpisah; workflow baru berjalan setelah proyek dipasang di GitHub.
- Migrasi: backup dahulu, lalu `python -m flask --app wsgi migrate-db` sebelum menjalankan container versi baru. Launcher lokal menjalankan migrasi aditif sebelum melayani request.
- `/health` untuk proses/koneksi; `/ready` mengembalikan 503 sampai schema, dataset, wilayah, dan admin siap. Compose memakai `/ready`.
- Cookie memakai token sesi yang dapat dicabut server. Batas sesi absolut delapan jam dan idle sekitar 30 menit (pembaruan aktivitas maksimal setiap lima menit). Logout mencabut sesi saat ini. Reset password/pembaruan alokasi mencabut sesi akun terkait.
- Pembaruan alokasi akun yang sudah ada: `python -m flask --app wsgi update-allocations FILE.xlsx` menampilkan pratinjau; tambahkan `--apply` untuk menerapkan. Perintah menolak akun baru/peran berbeda dan tidak mengubah password.
- `python scripts/backup_local.py` membuat backup ke folder `Backups` di sebelah folder Web, kemudian memulihkan salinan ke database sementara dan memeriksa integritas/jumlah tabel. `--verify FILE.sqlite3` hanya memeriksa backup yang dipilih. Backup tidak menimpa atau menghapus file lama.
- `powershell -NoProfile -File scripts/register_backup.ps1` mendaftarkan backup harian pukul 07.00 sebagai pengguna Windows saat ini, ketika pengguna sedang masuk. Task yang sudah ada tidak ditimpa. Retensi operasional: simpan sedikitnya 30 harian dan 12 bulanan; evaluasi/hapus salinan lama secara manual setelah backup lain lolos verifikasi. Secret konfigurasi dan workbook distribusi disimpan terpisah dalam tempat terbatas; backup database tidak menyertakannya.
- CSS dipisah menjadi fondasi `app.css`, tata letak `layouts.css`, kontrol `controls.css`, dan pembaca `reader.css`, dengan urutan cascade dipertahankan. Aset publik berversi memakai cache; halaman data selalu `no-store`.


## Komitmen kerahasiaan setelah login

Setiap sesi login wajib menyetujui dialog ?Komitmen kerahasiaan data? sebelum membuka data, termasuk melalui tautan langsung atau fetch blok. Narasi mengikuti teks yang disetujui pengguna; tombol utama ?Saya memahami dan berkomitmen?. Tombol Keluar, ?, dan Escape mencabut sesi lalu kembali ke login. Klik backdrop tidak menutup dialog. Tanpa JavaScript, formulir persetujuan dan keluar tetap tersedia.

Persetujuan disimpan pada sesi bertanda tangan dan dihapus ketika login baru/logout. AuditEvent `privacy_commitment_v1` menyimpan waktu dan ID akun tanpa data responden. Versi narasi ada pada `portal/commitment.py`; perubahan versi akan meminta persetujuan lagi. Tidak ada perubahan password, alokasi, data sumber, atau schema database.


## Deploy server pesse.databenuanta.id

Bundle server dan alur build GitHub untuk repository `pradanain/pesse2026` dijelaskan pada [DEPLOY_SERVER.md](docs/DEPLOY_SERVER.md). Gunakan `compose.server.yml` untuk Cloudflare Tunnel ? Traefik `web:80` pada network `proxy`. Paket data/akun/secret terpisah dari kode dan tidak masuk GitHub/image. Paket SERVER-READY-AMD64 dapat langsung diekstrak lalu dijalankan dengan `sh deploy.sh`, tanpa menghasilkan akun/secret lagi.
