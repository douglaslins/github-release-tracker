# Releasing a new version

English first, Bahasa Indonesia below.

The `.exe` on the Releases page is built by hand on the author's own Windows PC with `build.bat`. This page is the checklist.

## Checklist

1. **Raise the version number** in `github_release_tracker.py`:

   ```python
   APP_VERSION = "1.1.1"
   ```

   Digits and dots only (`1.2.3`). The release tag must be this number with a `v` in front (`v1.1.1`).
   Rule of thumb: `1.1.1` = bug fix, `1.2.0` = new feature, `2.0.0` = big change.
2. **(Optional) Describe the change.** Add a section at the top of `CHANGELOG.md`:

   ```
   ## [1.1.1]
   - Fix: ...
   ```

   `build.bat` copies this section into the release notes file for you.
3. **Double-click `build.bat`.** It checks Python and tkinter, reads the version, builds `dist\GitHubReleaseTracker.exe` with the icon, and writes `dist\release-notes-v1.1.1.md` (your changelog section plus the SHA-256). It stops with a clear message if something is wrong, for example a version like `1.1` or `v1.1.1`.
4. **Test the exe.** Run `dist\GitHubReleaseTracker.exe`: the window title must say `v1.1.1`, adding a project and **Check for updates** must work.
5. **Upload the changed files to GitHub.** On the repository page: *Add file > Upload files*, drop the changed files (at least `github_release_tracker.py`, and `CHANGELOG.md` / README if you changed them), then *Commit changes*.
6. **Create the release.** *Releases > Draft a new release*:
   - **Choose a tag:** type `v1.1.1` and pick *Create new tag on publish*. It must match `APP_VERSION` exactly.
   - **Title:** `v1.1.1`
   - **Description:** paste the whole content of `dist\release-notes-v1.1.1.md`.
   - **Attach:** drag `dist\GitHubReleaseTracker.exe` into the files box.
   - For a test version use a tag like `v1.2.0-beta` and tick *Set as a pre-release*.
   - Click **Publish release**.
7. **Check it.** Download the exe from the release page, run `Get-FileHash .\GitHubReleaseTracker.exe -Algorithm SHA256` in PowerShell and compare it with the hash in the notes.

## Common mistakes

| Mistake | Result |
|---|---|
| Forgot to raise `APP_VERSION` | The exe's title shows the old version. Raise it, rebuild, and replace the file on the release. |
| Tag does not match `APP_VERSION` | Confusing for users. Delete the tag/release and create it again with the right tag. |
| Uploaded the exe from an earlier build | The hash in the notes will not match. Always take the notes file and the exe from the same `build.bat` run. |
| `projects.json` uploaded to GitHub | It can contain your token. It is in `.gitignore`; do not drag it in by hand. |

---

# Merilis versi baru

`.exe` di halaman Releases dibuat manual di PC Windows pemiliknya dengan `build.bat`. Ini daftar langkahnya.

## Daftar langkah

1. **Naikkan nomor versi** di `github_release_tracker.py`:

   ```python
   APP_VERSION = "1.1.1"
   ```

   Hanya angka dan titik (`1.2.3`). Tag release harus nomor yang sama dengan awalan `v` (`v1.1.1`).
   Patokan: `1.1.1` = perbaikan bug, `1.2.0` = fitur baru, `2.0.0` = perubahan besar.
2. **(Opsional) Tulis perubahannya.** Tambahkan bagian di paling atas `CHANGELOG.md`:

   ```
   ## [1.1.1]
   - Fix: ...
   ```

   `build.bat` menyalin bagian ini ke file catatan release secara otomatis.
3. **Klik dua kali `build.bat`.** Skrip memeriksa Python dan tkinter, membaca versi, membuat `dist\GitHubReleaseTracker.exe` lengkap dengan ikon, dan menulis `dist\release-notes-v1.1.1.md` (isi changelog ditambah SHA-256). Skrip berhenti dengan pesan jelas jika ada masalah, misalnya versi `1.1` atau `v1.1.1`.
4. **Uji exe-nya.** Jalankan `dist\GitHubReleaseTracker.exe`: judul jendela harus berisi `v1.1.1`, menambah proyek dan **Check for updates** harus berfungsi.
5. **Upload file yang berubah ke GitHub.** Di halaman repository: *Add file > Upload files*, jatuhkan file yang berubah (minimal `github_release_tracker.py`, dan `CHANGELOG.md` / README jika diubah), lalu *Commit changes*.
6. **Buat release.** *Releases > Draft a new release*:
   - **Choose a tag:** ketik `v1.1.1` lalu pilih *Create new tag on publish*. Harus sama persis dengan `APP_VERSION`.
   - **Title:** `v1.1.1`
   - **Description:** tempel seluruh isi `dist\release-notes-v1.1.1.md`.
   - **Lampiran:** seret `dist\GitHubReleaseTracker.exe` ke kotak file.
   - Untuk versi uji pakai tag seperti `v1.2.0-beta` dan centang *Set as a pre-release*.
   - Klik **Publish release**.
7. **Periksa.** Unduh exe dari halaman release, jalankan `Get-FileHash .\GitHubReleaseTracker.exe -Algorithm SHA256` di PowerShell, lalu cocokkan dengan hash di catatan.

## Kesalahan yang sering terjadi

| Kesalahan | Akibat |
|---|---|
| Lupa menaikkan `APP_VERSION` | Judul exe menampilkan versi lama. Naikkan, build ulang, lalu ganti file di release. |
| Tag tidak sama dengan `APP_VERSION` | Membingungkan pengguna. Hapus tag/release lalu buat ulang dengan tag yang benar. |
| Meng-upload exe dari build sebelumnya | Hash di catatan tidak cocok. Selalu ambil file catatan dan exe dari satu kali `build.bat`. |
| `projects.json` ikut ter-upload | Isinya bisa memuat token Anda. File itu ada di `.gitignore`; jangan diseret manual. |
