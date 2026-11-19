# GitHub Release Tracker

Aplikasi Windows portable berukuran kecil untuk memantau release terbaru dari proyek yang Anda ikuti di GitHub, GitLab, Gitea, dan Forgejo, dan memberi tahu kalau ada release baru. Aplikasi ini juga bisa memeriksa apakah release itu sudah ada di folder unduhan Anda. Tanpa akun, tanpa login, dan tanpa token untuk proyek publik.

🇬🇧 [Read in English](README.md)

<!-- Tambahkan screenshot Anda sendiri di sini, misalnya simpan sebagai docs/screenshot.png lalu pakai:
![Screenshot](docs/screenshot.png)
-->

## Fitur

- Tambah proyek dengan menempel URL-nya: URL GitHub atau `owner/repo`, proyek GitLab (termasuk yang dihosting sendiri), atau proyek Gitea atau Forgejo seperti yang ada di Codeberg
- Tempel beberapa alamat sekaligus. Tiap alamat langsung muncul di daftar dan terisi setelah pencariannya selesai, jadi jendela tidak perlu menunggu
- Lihat nama proyek, repository, release saat ini, tanggal rilis, dan status sekilas
- **Check for updates** menyegarkan semua proyek; proyek dengan release lebih baru disorot sebagai `Update available: v1.0 -> v1.1`
- **Mark as seen** menghapus sorotan setelah Anda selesai menangani update
- Klik dua kali pada proyek untuk membuka halaman release-nya di browser
- **Folder unduhan** (Settings): arahkan aplikasi ke folder tempat Anda menyimpan unduhan. Tiap proyek lalu menampilkan `Up to date 🟢 (latest)`, `Up to date 🟢 (Pre-release available)`, `Needs update 🟡`, atau `Not downloaded 🔴`, berdasarkan file di folder itu
- **Pemeriksaan SHA-256**: sebuah file dianggap file release kalau SHA-256-nya sama, jadi file yang namanya diubah tetap ditemukan, dan file yang rusak atau diubah menampilkan `(hash mismatch)`. Matikan pemeriksaan ini di Settings kalau Anda hanya ingin membandingkan nama
- Klik kanan proyek > **Change folder...** untuk memindai folder lain khusus untuk proyek itu. **Rescan files** membaca ulang folder tanpa memakai jaringan
- **Check for updates** memeriksa sampai 6 proyek sekaligus
- **Ganti nama proyek** agar mudah dibaca: arahkan kursor ke baris lalu klik pensil (atau tekan **F2**, atau klik kanan > Rename). *Reset name* mengembalikan nama dari GitHub. Nama buatan Anda tersimpan dan ikut di Export
- Klik header **Project**, **Repository**, **Published**, atau **Status** untuk mengurutkan (klik lagi untuk membalik; panah menunjukkan arahnya)
- **Import / Export** daftar proyek sebagai file `.json` (gabungkan atau ganti saat import)
- Mode **terang / gelap**: klik tombol bulan / matahari (awalnya mengikuti tema Windows Anda)
- Semua kolom ikut melebar atau menyempit secara proporsional saat jendela diubah ukurannya (seret batas kolom untuk mengubah proporsinya)
- Ikon kecil pada tombol, garis pemisah tipis antar baris dan kolom, dan ikon aplikasi sendiri
- Nomor versi di judul jendela; **Settings > About** juga menampilkannya
- Menu klik kanan di kotak teks (Cut / Copy / Paste / Select all), dan klik kanan pada status bar untuk menyalin pesannya
- Portable: satu file `.exe`, tanpa installer, tanpa entri registry

Aplikasi ini hanya membaca informasi release. Ia tidak pernah mengunduh atau memasang apa pun. Satu-satunya yang dibacanya di PC Anda adalah folder unduhan yang Anda pilih (nama file, ukuran, dan untuk pemeriksaan SHA-256, isi file). Tidak ada isi folder itu yang dikirim ke mana pun.

## Bahan yang perlu disiapkan

Pilih baris yang sesuai dengan tujuan Anda.

| Saya ingin... | Yang dibutuhkan |
|---|---|
| **Langsung memakai aplikasi** (`.exe` dari [Releases](https://github.com/santosasarno-code/github-release-tracker/releases)) | Windows 10 atau 11 dan koneksi internet. **Tidak perlu yang lain**: Python *tidak* diperlukan. |
| **Menjalankan dari source** (`github_release_tracker.py`) | Windows 10/11 dan **Python 3.10 atau lebih baru** dari [python.org](https://www.python.org/downloads/windows/). Tidak perlu paket tambahan. |
| **Membuat `.exe` sendiri** (`build.bat`) | Python yang sama, dengan opsi **"Add python.exe to PATH"** dicentang saat instalasi, dan koneksi internet (skrip mengunduh PyInstaller). |

### Detail Python (hanya untuk menjalankan dari source atau membuat exe)

- **Versi:** kodenya memakai Python standar dan sintaksnya jalan mulai Python 3.6, tetapi yang disarankan hanya versi baru. Versi yang sudah diuji: **3.10 dan 3.12** (tes GUI otomatis di Linux) dan **3.8** (hanya tes logika, GUI-nya tidak bisa diuji). Gunakan 3.10 atau lebih baru.
- **tkinter harus ikut terpasang.** Installer dari python.org menyertakannya secara bawaan (opsi "tcl/tk and IDLE"). Cek dengan:
  ```
  python -c "import tkinter; print('tkinter OK')"
  ```
  Kalau muncul `No module named tkinter`, jalankan lagi installer Python, pilih *Modify*, lalu centang **tcl/tk and IDLE**.
- **Tidak perlu `pip install`** untuk menjalankan dari source: aplikasi hanya memakai library standar Python. PyInstaller hanya dibutuhkan untuk membuat exe, dan `build.bat` memasangnya otomatis.
- Python dari sumber lain (misalnya Microsoft Store) belum diuji; installer python.org adalah yang disarankan.

## Cara cepat memulai

### Memakai `.exe`

1. Unduh `GitHubReleaseTracker.exe` dari [halaman Releases](https://github.com/santosasarno-code/github-release-tracker/releases).
2. Taruh di folder mana saja (boleh di flashdisk) lalu jalankan.
3. Tempel URL proyek seperti `https://github.com/owner/repo` (atau dari GitLab, Codeberg, dan sebagainya) lalu klik **Add project**.
4. Nanti, klik **Check for updates**.

> **Windows mungkin memberi peringatan** ("Windows protected your PC") atau antivirus menandai file ini. Ini sering terjadi pada file tunggal buatan PyInstaller, dan aplikasi ini tidak ditandatangani digital. Kalau Anda tidak mau memercayai `.exe` unduhan, baca source-nya (hanya satu file Python) dan buat sendiri dengan langkah di bawah.

#### Memeriksa file unduhan Anda

Mulai v1.1.0, `.exe` di halaman Releases dibuat oleh **workflow GitHub Actions** "Build Windows exe" di mesin Windows milik GitHub, dari source di repository ini. Catatan release memuat tautan ke log build publik dari run yang sama, jadi Anda bisa melihat bagaimana file itu dibuat. (v1.0.0 dan v1.0.1 dibuat oleh pembuatnya di PC pribadinya dengan `build.bat`.) Pembuatnya tetap mengunduh hasilnya lalu melampirkannya ke Release secara manual.

Hash SHA-256 dari `.exe` tiap release dicantumkan di catatan release tersebut. Untuk memastikan unduhan Anda utuh, buka PowerShell di folder file tersebut lalu jalankan:

```
Get-FileHash .\GitHubReleaseTracker.exe -Algorithm SHA256
```

Hash-nya harus sama dengan yang tertulis di catatan release. Ini membuktikan file Anda sama dengan yang dipublikasikan, bukan bahwa file itu aman; yang benar-benar bisa Anda periksa adalah source code-nya. Kalau Anda membuat `.exe` sendiri, hash-nya akan berbeda: build di mesin yang berbeda tidak identik byte demi byte.

### Menjalankan dari source

```
python github_release_tracker.py
```
(atau `py github_release_tracker.py`)

### Membuat `.exe` sendiri

1. Pasang Python (lihat di atas) dan unduh repository ini.
2. Klik dua kali `build.bat`.
3. Aplikasi portable Anda muncul di `dist\GitHubReleaseTracker.exe`.

Cara manual:
```
pip install pyinstaller
pyinstaller --onefile --windowed --icon icon.ico --name GitHubReleaseTracker github_release_tracker.py
```

`build.bat` juga memeriksa Python dan tkinter, memasang ikon, dan menulis file catatan release siap tempel berisi SHA-256 (`dist\release-notes-vX.Y.Z.md`). Untuk pemelihara: lihat [RELEASING.md](RELEASING.md) untuk daftar langkah merilis dan [CHANGELOG.md](CHANGELOG.md) untuk perubahan tiap versi.

## Cara kerjanya

- Aplikasi membaca feed release publik tiap proyek, `https://github.com/<owner>/<repo>/releases.atom`. Ini tidak perlu login dan tidak memakai batas permintaan API GitHub.
- Kalau feed gagal atau proyek tidak punya release, aplikasi beralih ke API GitHub (yang membolehkan sekitar 60 permintaan per jam tanpa token). Kalau proyek sama sekali tidak punya GitHub Release, yang ditampilkan adalah git tag terbaru.
- Saat Anda menambah proyek, release yang ada saat itu dianggap sudah dilihat. Hanya release yang terbit sesudahnya yang ditandai sebagai update.
- Deteksi update membandingkan identitas release (dan tag), bukan nomor versi, jadi tag tidak biasa seperti `nightly` atau `build-123` tetap bisa. Efek sampingnya: release yang dihapus lalu dibuat ulang bisa muncul sebagai update.
- Proyek GitLab, Gitea, dan Forgejo dibaca lewat API publik host-nya, satu permintaan per proyek. Untuk alamat yang dihosting sendiri, aplikasi mencari tahu jenis servernya. Proyek privat, atau server yang membatasi permintaan anonim, membutuhkan token akses: klik kanan proyek > *Set access token for this host...*. Token hanya dikirim ke host pemiliknya.
- Aplikasi hanya menghubungi host dari proyek yang Anda tambahkan: `github.com` dan `api.github.com` untuk proyek GitHub, dan host proyek itu sendiri (misalnya `gitlab.com` atau `codeberg.org`) untuk yang lain.

### Cara folder unduhan dibandingkan

- Aplikasi memindai folder beserta sub-foldernya (sedalam 3 tingkat) lalu membandingkan file dengan release terbaru tiap proyek. Release terbaru yang ditemukan menentukan statusnya. Daftar file dan nilai SHA-256 disimpan untuk 8 release terbaru.
- Sebuah file masuk ke sebuah release dengan dua cara. **SHA-256**: file punya hash yang sama dengan file release, apa pun namanya. **Nama**: nama file (atau nama foldernya) memuat nama proyek dan versi release, misalnya `ShareX-16.0.1-setup.exe` untuk release `v16.0.1`. Pemeriksaan nama dipakai untuk release yang tidak punya checksum pembanding.
- API GitHub mencantumkan SHA-256 untuk file release. GitLab, Gitea, dan Forgejo tidak, jadi aplikasi membaca file checksum yang dilampirkan pada release (`SHA256SUMS`, `checksums.txt`, atau `file.zip.sha256`) atau baris checksum di teks release.
- File dengan nama yang cocok tetapi SHA-256 berbeda tidak dihitung. File itu mungkin tidak lengkap, rusak, diubah, atau arsip source. Statusnya lalu berakhir dengan `(hash mismatch)`.
- Hanya file yang ukurannya sama dengan file release yang dibaca. Hash tiap file diingat di `hash_cache.json` sampai file itu berubah.
- Pre-release: GitHub ditanyai lewat API-nya (satu panggilan per proyek, hanya saat ada kemungkinan perubahan). Gitea dan Forgejo melaporkan penandanya sendiri. GitLab tidak punya penanda itu, jadi di sana nama tag seperti `-beta` atau `-rc1` yang menentukan.

## Data Anda

- Daftar Anda disimpan di `projects.json` **di sebelah file `.exe`**. Kalau folder itu hanya-baca (misalnya `Program Files`), aplikasi memakai `%APPDATA%\GitHubReleaseTracker`.
- **Export** menulis file `.json` terpisah untuk cadangan atau pindah ke PC lain. **Import** membacanya kembali (dan juga bisa membaca `projects.json` dari build lama).
- **Nama kustom ikut terbawa di file.** Kalau Anda mengganti nama proyek lalu membagikan hasil Export, **Import** di PC orang lain menampilkan nama Anda untuk proyek yang belum mereka punya. Untuk proyek yang sudah mereka punya, **Merge** membiarkan entri dan nama mereka apa adanya (nama Anda tidak diterapkan); **Replace** mengganti seluruh daftar mereka dengan isi file, termasuk namanya. File hasil Export v1.1.0 tetap bisa di-import di versi lama, tetapi nama kustomnya dibuang.
- Di Settings ada kolom token GitHub (opsional). Token **tidak diperlukan** untuk pemakaian normal. Kalau Anda mengisinya, token disimpan **sebagai teks biasa** di `projects.json`, jadi jangan bagikan atau unggah file itu. File hasil Export tidak pernah berisi token. Hal yang sama berlaku untuk token akses host lain yang Anda atur.
- **Jangan buka daftar yang berisi proyek GitLab, Gitea, atau Forgejo di versi lama** (v1.1.1 atau sebelumnya). Versi lama membaca setiap entri sebagai proyek GitHub, jadi entri itu akan menunjuk ke host yang salah.
- `hash_cache.json` (di sebelah `projects.json`) mengingat SHA-256 file unduhan Anda, jadi file besar hanya dibaca sekali. Aman untuk dihapus.
- `projects.lock` (juga di sebelah `projects.json`) mencegah salinan kedua aplikasi membuka data yang sama, karena dua salinan akan saling menimpa perubahan.

## Keterbatasan

- Hanya Windows (dibuat untuk Windows 10/11).
- Feed tidak memberi tahu release mana yang pre-release, jadi label `(pre-release)` tidak tampil untuk hasil dari feed. Mode "stable only" (klik kanan proyek, hapus centang *Include pre-releases*) memakai API dan batas permintaannya.
- Feed adalah halaman publik GitHub, bukan API resmi; GitHub bisa mengubah atau membatasinya.
- Repository privat tidak didukung tanpa token.
- GitLab tidak menerbitkan penanda pre-release, ukuran file, maupun checksum, dan Gitea serta Forgejo tidak menerbitkan checksum. Di host-host itu status bergantung pada nama tag, nama file, dan file checksum yang dilampirkan pada release. Release tanpa file checksum hanya dicocokkan lewat nama.
- Dukungan untuk GitLab, Gitea, dan Forgejo sejauh ini baru diuji dengan server simulasi, belum dengan server sungguhan.
- Hanya satu salinan aplikasi yang bisa berjalan per folder data.
- Tanggal "Published" berasal dari waktu update di feed, jadi mengedit release di GitHub bisa mengubahnya.
- Deskripsi proyek (tampil di status bar saat dipilih) dibaca sekali ketika proyek ditambahkan dan tidak diperbarui lagi. Kalau API GitHub sedang tidak tersedia saat itu, proyek menampilkan "No description, website, or topics provided." walaupun repository-nya sebenarnya punya deskripsi.
- Garis antar baris dan kolom serta pensil rename adalah widget kecil yang digambar di atas daftar. Klik tepat pada garis setebal 1 piksel diteruskan ke barisnya, tetapi *klik dua kali* tepat di garis itu bisa gagal membuka halaman release.
- Ikon berukuran 16 px (24 px pada layar dengan skala 150% atau lebih). Tidak semua pengaturan layar Windows sudah diuji.

## File di repository ini

| File | Isinya |
|---|---|
| `github_release_tracker.py` | Seluruh aplikasi (satu file Python, hanya library standar). |
| `build.bat` | Membuat `dist\GitHubReleaseTracker.exe`. |
| `icon.ico` | Ikon aplikasi yang dipakai saat build. |
| `tools/` | Alat pemelihara: `release_info.py` (dipakai `build.bat`) dan `make_icons.py` (membuat ulang ikon; butuh Pillow, tidak diperlukan untuk memakai atau membuat aplikasi). |
| `CHANGELOG.md`, `RELEASING.md` | Daftar perubahan, dan cara menerbitkan release. |

## Pemecahan masalah

| Masalah | Yang dilakukan |
|---|---|
| `No module named tkinter` | Pasang ulang Python dari python.org dengan **tcl/tk and IDLE** dicentang. |
| `python` tidak dikenali | Pasang ulang Python dan centang **Add python.exe to PATH**, atau pakai `py` sebagai pengganti `python`. |
| "GitHub API rate limit reached" | Batas 60 per jam pada API cadangan tercapai. Tunggu sampai jam yang tertera, atau isi token di **Settings**. |
| "Not found" saat menambah proyek | Periksa ejaannya. Repository privat tidak didukung tanpa token. |
| Peringatan Windows SmartScreen / antivirus | Lihat catatan di bagian *Memakai `.exe`*. |
| Status berakhir dengan `(hash mismatch)` | Sebuah file di folder Anda bernama cocok tetapi SHA-256-nya berbeda dari file release. File itu mungkin tidak lengkap, rusak, atau diubah. Unduh ulang. |
| Proyek GitLab, Gitea, atau Forgejo menampilkan galat batas permintaan | Host membatasi permintaan anonim. Tunggu beberapa menit, atau klik kanan proyek lalu isi token akses untuk host itu. |
| "... is already running with this data folder" | Satu salinan aplikasi sudah terbuka. Cari di taskbar. Untuk salinan kedua dengan daftar sendiri, simpan di folder yang berbeda. |
| Proyek menampilkan "No releases published" | Repository belum punya GitHub Release maupun tag. |

## Lisensi

[MIT](LICENSE). Proyek ini tidak berafiliasi dengan atau didukung oleh GitHub.
