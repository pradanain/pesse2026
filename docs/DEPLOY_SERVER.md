# Deploy PES SE2026 — pesse.databenuanta.id

Target: Linux Docker Compose, Traefik yang sudah berjalan di entrypoint `web` port 80, dan Cloudflare Tunnel yang sudah tersedia. Bundle tidak memasang Traefik/cloudflared baru dan tidak mengambil port host aplikasi.

## Dua paket yang dipisahkan

1. **GITHUB.zip**: ekstrak isinya ke repository. Berisi kode, Dockerfile, Compose server, pengujian, dan workflow. Aman dari workbook/database/secret aplikasi.
2. **PRIVATE-SERVER.tar.gz**: pindahkan langsung ke server melalui SCP/SFTP, lalu ekstrak ke root checkout. Berisi snapshot data lengkap, akun beserta hash password yang sama, secret khusus deployment yang telah dibuat, dan workbook distribusi akun. Jangan unggah ke GitHub, GitHub Release, atau registry image, termasuk pada repository privat.

Kode image tidak memuat data responden atau kredensial. `.gitignore` dan `.dockerignore` menutup direktori privat, snapshot, dan artefak release. Pembangun bundle juga memakai daftar berkas yang diizinkan. Konfigurasi di `deploy.env.example` tidak berisi secret.

## Langsung jalan dengan build di server

Ekstrak kode dan paket privat pada direktori yang sama, misalnya `/opt/pesse2026`. Tidak perlu mengimpor Excel, membuat admin, mengganti password, atau menghasilkan secret.

```sh
cd /opt/pesse2026
tar -xzf /lokasi/PESSE2026-PRIVATE-SERVER-TIMESTAMP.tar.gz
sh deploy.sh
```

Default network adalah `proxy`, entrypoint `web`. Jika server memakai nama lain, isi `TRAEFIK_NETWORK` dan `TRAEFIK_ENTRYPOINT` di `deploy.env` sebelum deploy. Script menolak melanjutkan bila network tidak ditemukan; ia tidak mengubah Traefik yang sudah berjalan. Docker Engine dan Compose harus sudah tersedia.

Service initialize memverifikasi checksum dan integritas seed, menyalin data hanya ketika volume kosong, memasang pemilik UID 10001, dan menjalankan migrasi aditif. Volume yang sudah berisi data tidak ditimpa. Pasangan database/secret yang tidak lengkap ditolak. Aplikasi berjalan sebagai non-root, filesystem image read-only, tanpa port host, dengan cookie Secure dan login wajib.

## Build otomatis di GitHub, lalu pull

Upload isi paket kode ke branch default `main` atau `master`. Workflow **Build portal image** menjalankan tes, lalu membangun Linux AMD64/ARM64 dan mengirim image ke:

```text
ghcr.io/pradanain/pesse2026:latest
ghcr.io/pradanain/pesse2026:sha-...
```

Nama owner/repository otomatis diubah ke huruf kecil. Tidak perlu membuat Docker Hub atau menambahkan password registry pada Actions; workflow menggunakan GITHUB_TOKEN dengan izin packages:write. URL tepat image juga ditampilkan pada Summary workflow.

Repository tujuan: https://github.com/pradanain/pesse2026 . Nama image berikut sudah diisi sebagai default; server cukup menjalankan `sh deploy.sh` setelah workflow berhasil:

```text
PORTAL_IMAGE=ghcr.io/pradanain/pesse2026:latest
```

Untuk image GHCR privat, server perlu login GHCR dengan akun/token yang berhak membaca package. Alternatifnya, atur visibilitas **image kode** menjadi public agar pull tidak memerlukan login; data dan akun tetap berada di paket privat. Jika GitHub organisasi membatasi Actions/packages, izin tersebut perlu disesuaikan oleh pemilik organisasi.

## Cloudflare Tunnel dan Traefik

Pasang public hostname pada tunnel yang sudah ada:

| Pengaturan | Nilai |
|---|---|
| Public hostname | `pesse.databenuanta.id` |
| Service type | HTTP |
| Service URL | `http://traefik:80` |
| HTTP Host Header bila origin menggantinya | `pesse.databenuanta.id` |

`traefik` pada URL adalah nama DNS/container Traefik yang dapat dijangkau cloudflared; bila nama container berbeda, pakai nama tersebut. Cloudflared dan Traefik harus saling terhubung pada network yang benar. Traefik memakai Docker provider dan entrypoint port 80; label aplikasi memasang Host rule serta target internal 8000. Router ini tidak memasang TLS/ACME di origin karena TLS publik ditangani Cloudflare. Pastikan tidak ada redirect HTTPS global pada entrypoint origin yang menyebabkan loop.

Akses publik memakai **HTTPS** dan aktifkan pengalihan HTTP ke HTTPS pada Cloudflare. Middleware origin menetapkan X-Forwarded-Proto=https dan host publik; Flask mempercayai satu hop Traefik. Origin Traefik hanya diakses jalur tunnel/jaringan tepercaya. Untuk alamat klien yang akurat pada limiter IP, atur trusted forwarded headers Traefik sesuai alamat/subnet cloudflared; jangan mengaktifkan kepercayaan header global pada origin publik. Header CF-Connecting-IP diteruskan Cloudflare, tetapi bukan pengganti pembatasan akses origin.

## Pemeriksaan dan pembaruan

```sh
docker compose --env-file deploy.env -f compose.server.yml ps
docker compose --env-file deploy.env -f compose.server.yml logs --tail=50 portal initialize backup
curl -I https://pesse.databenuanta.id/login
curl https://pesse.databenuanta.id/ready
```

`/ready` harus menghasilkan 200 dengan status ready. Coba login PPL/PML/admin memakai akun yang sama, setujui dialog kerahasiaan, dan periksa alokasi. Tidak ada login otomatis atau pengabaian dialog.

Update kode: pilih tag image yang dituju, lalu jalankan `sh deploy.sh`; named volume `pesse2026_portal_data` dipertahankan. Seed tidak menggantikan database aktif. Jangan menjalankan `docker compose down -v` karena opsi tersebut menghapus volume. Simpan tag image sebelumnya untuk rollback kode; jika update berikutnya mengubah schema secara tidak kompatibel, pulihkan pasangan database/secret dari backup yang sesuai sebelum rollback.

Service backup berjalan segera lalu setiap 24 jam, memakai backup SQLite konsisten dan uji restore pada database sementara. Hasil berada pada `private/backups`; kegagalan dicatat dan proses diulang melalui restart policy. Backup tidak menghapus salinan lama. Pantau kapasitas disk dan pindahkan backup terverifikasi ke media terpisah. Simpan `private/seed/secret.key` serta workbook distribusi secara terpisah; secret dan database harus dipulihkan bersama. Tidak ada secret yang perlu dibuat ulang di server.

## Referensi konfigurasi

- [GitHub: publish Docker image ke GHCR](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)
- [Traefik: routing Docker](https://doc.traefik.io/traefik/master/reference/routing-configuration/other-providers/docker/)
- [Traefik: middleware headers](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/headers/)
- [Cloudflare: HTTP headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/)

Domain, tunnel, network server, dan workflow GitHub memerlukan pemeriksaan di lingkungan tujuan. Hasil tes lokal tidak menyatakan hostname publik sudah aktif atau image sudah dipublikasikan ke GHCR.


## Paket server offline siap jalan (AMD64)

Paket SERVER-READY-AMD64.tar.gz menyertakan kode, seed privat, konfigurasi, dan image lokal yang telah dibangun. Paket ini **hanya untuk server**, jangan unggah ke GitHub. Jalankan:

```sh
mkdir -p /opt/pesse2026
cd /opt/pesse2026
tar -xzf /lokasi/PESSE2026-SERVER-READY-AMD64-TIMESTAMP.tar.gz
sh deploy.sh
```

Script otomatis memuat image yang disertakan dan tidak membutuhkan GitHub login/build atau menghasilkan secret/password. Pastikan network `proxy` dan entrypoint `web` sudah tersedia. Untuk menarik versi GitHub sesudahnya, gunakan `sh deploy.sh --pull`. Paket offline ini hanya AMD64; server ARM64 dapat menggunakan image multi-platform hasil workflow GitHub atau `PORTAL_IMAGE=pesse-se2026:local` untuk build pada server.
