# NGO Privacy Helper

A free desktop app for Windows and macOS that lets NGO staff use AI tools without exposing the people they serve, and protect sensitive files with their own keys.

Everything happens on the staff member's computer. There is no server, no account and no internet connection involved.

## What it does

| Section | What staff do |
|---|---|
| **Hide Details** | Paste a case note, or open a Word, Excel, CSV or text file. Names, phone numbers, places, emails, ID and account numbers and dates are found and listed for review. Untick anything that is safe, select anything missed, then copy the safe version into any AI tool. |
| **Restore Details** | Paste the AI's reply. Codes such as `[PERSON_1]` are replaced with the real details again. Works days later, because the codes are kept in the key vault. |
| **Protect Files** | Drop any file to encrypt it (`.nph`), or lock a PDF with a password that opens in any PDF reader. Drop a protected file to open it again. Every file gets its own key. |
| **Keys** | Every key, PDF password and hidden-details record, listed by file name and searchable. Copy, export, import, or show the protected file in Finder or File Explorer. |

Example:

```
Original:  Hadiza Ibrahim (0803 555 1234) at Zamfara Shelter needs clean water.
Sent:      [PERSON_1] ([PHONE_1]) at [PLACE_1] needs clean water.
```

### How details are found

Spreadsheets have no fixed layout, so the app does not rely on column names alone.

1. **The NGO's own records.** When a spreadsheet is opened, staff confirm which columns hold names, places, phones and so on. Suggestions are pre-filled from column names and contents. Every value in those columns is then hidden wherever it appears, including inside free-text notes. This also covers Hausa, Yoruba, Igbo and other names that general-purpose name detectors miss.
2. **Fixed patterns.** Nigerian and international phone numbers, emails, 11-digit NIN/BVN, 10-digit NUBAN account numbers and dates.
3. **Possible names.** Names after titles such as Mr, Mrs, Mallam, Alhaji or Hajiya are ticked automatically. Other capitalised word pairs are listed unticked for staff to confirm.
4. **Staff review.** Nothing leaves the app until a person has seen the highlighted text.

Settings hold an organisation-wide "always hide" list and a "never hide" list.

## Security design

- **Key vault.** One file in the user's app-data folder, encrypted with AES-256-GCM under a key derived from the master password with scrypt (N=2^17, r=8, p=1). It is written atomically and the previous copy is kept, so a crash cannot lose keys. The vault locks after a period of no activity (10 minutes by default) and clears open text from the screen.
- **Encrypted files (`.nph`).** Each file has its own random 256-bit key. Contents are encrypted with AES-256-GCM in 1 MB chunks. Each chunk is authenticated together with the file header, its position and an end-of-file flag, so tampering, reordering or truncation is detected. The format is byte-identical on Windows and macOS.
- **Locked PDFs.** Standard PDF AES-256 encryption with a random 20-character password and a separate random owner password.
- **Keys are saved before files are written.** A protected file can never exist without its key. Originals are never changed or deleted.
- **Safe Word copies.** These are written as new documents, not edited copies, so tracked changes, comments and author properties from the original cannot leak.
- **Sharing.** To let a colleague open a file, send the file and, separately (by phone or SMS), its key (`NPHKEY1:…`) or PDF password.

> If the master password is lost and there is no backup, protected files cannot be opened. Use **Settings › Security › Back Up Keys**.

## Compatibility

| | Supported |
|---|---|
| Windows | Windows 10 version 1809 or later, Windows 11, 64-bit |
| macOS | macOS 12 Monterey or later, Apple Silicon and Intel (separate downloads) |

The app is built on Qt 6.8 LTS on purpose: later Qt versions require macOS 14.4 or later and are dropping Windows 10, which would exclude many NGO computers.

## Installing

Download the installer for your computer from the releases page.

- **Windows.** Run `NGO-Privacy-Helper-…-Windows-Setup.exe`. Administrator rights are not needed. Until the app is code-signed, Windows may show *Windows protected your PC*. Choose **More info › Run anyway**.
- **macOS.** Open the `.dmg` and drag the app to Applications. Until the app is notarised by Apple, the first launch is blocked. Open **System Settings › Privacy & Security** and choose **Open Anyway**.

## Building from source

Requires Python 3.12.

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt     # Windows: .venv\Scripts\python
.venv/bin/python -m pytest -q tests
.venv/bin/python run.py                                       # run the app
.venv/bin/python packaging/build.py                           # build the installer for this OS
```

PyInstaller cannot cross-build. Build the Windows installer on Windows (needs [Inno Setup 6](https://jrsoftware.org/isdl.php)) and the macOS disk image on a Mac. The **Build installers** GitHub Action does all three (Windows, Apple Silicon, Intel) on demand, or when a `v*` tag is pushed.

After editing `packaging/icon.svg`, run `python packaging/make_icons.py`.

## Project layout

```
privacy_helper/
  core/        masking, key vault, file encryption, PDF lock, file reading (no UI code)
  ui/          one module per section, plus settings and the lock screen
  app.py       main window, menus, auto-lock, files opened from Finder or File Explorer
packaging/     PyInstaller recipe, Windows installer script, icons, build script
tests/         core tests (pytest)
```

## Known limits

- Name detection is rule-based. It does not use a machine-learning model, which would add several hundred MB to the download. The NGO's own records and staff review cover most of the gap.
- Restore works on pasted text and on `.txt` and `.docx` files. Word formatting is not kept in safe copies, by design.
- Unsigned builds show a security warning on first launch. Code signing costs about USD 100 to 300 a year on Windows and USD 99 a year for Apple.
