# NGO Privacy Helper

A free desktop app for Windows and macOS that lets NGO staff use AI tools without exposing the people they serve, and protect sensitive files with their own keys.

Everything happens on the staff member's computer. There is no server, no account and no internet connection involved.

## What it does

| Section | What staff do |
|---|---|
| **Hide Details** | Paste a case note, or open a Word, Excel, CSV or text file. Personal details and protected topics (see the list below) are found and listed for review. Untick anything that is safe, select anything missed, then copy the safe version, or save it as a Word, Excel, CSV or text file (the same type as the original) to upload to any AI tool. |
| **Restore Details** | Paste the AI's reply. Codes such as `[PERSON_1]` are replaced with the real details again. Works days later, because the codes are kept in the key vault. |
| **Protect Files** | Drop any file to encrypt it (`.nph`), or lock a PDF with a password that opens in any PDF reader. Drop a protected file to open it again. Every file gets its own key. |
| **Safe Photos** | Open a photo to remove the hidden details phones record, such as the GPS location, camera and date. Drag across faces, name tags or signs to blur them, then save a safe copy. |
| **Shortcuts in other apps** | Copy text in Word, email or a browser and press the Hide shortcut. A small window shows the copied text. **Hide Details** replaces what was found with codes, leaving possible names unticked for staff to check, and **Copy Safe Version** copies the result. Copy the AI's reply and press the Restore shortcut to fill the real details back in. Each person picks their own keys after creating their master password, or later in **Settings › Shortcuts**. |
| **Keys** | Every key, PDF password and hidden-details record, listed by file name and searchable. Copy, export, import, or show the protected file in Finder or File Explorer. Set a delete date so a key is destroyed when it is no longer needed. |

Example:

```
Original:  Hadiza Ibrahim (0803 555 1234) at Zamfara Shelter needs clean water.
Sent:      [PERSON_1] ([PHONE_1]) at [PLACE_1] needs clean water.
```

## What counts as personal and protected data

The app looks for every category of personal data that can be recognised in text. It follows the **Nigeria Data Protection Act 2023**, the **GDPR** (Articles 4, 9 and 10), the **HIPAA Safe Harbor** list of 18 identifiers, and humanitarian data guidance. Each group can be switched off in **Settings › Hiding**.

### Personal identifiers (hidden by default)

| Group | What is found | How it is checked |
|---|---|---|
| **Names** | Names from the NGO's own records (including first names or surnames on their own), names after titles (Mr, Mrs, Ms, Dr, Mallam, Alhaji, Alhaja, Hajiya, Chief, Pastor, Engr and others), names after "my name is" | Your records are matched exactly. Other capitalised names are listed unticked for staff to confirm |
| **Phone numbers** | Nigerian mobiles (0803…, +234 803…), international numbers, grouped numbers | Pattern |
| **Email addresses** | Any email address | Pattern |
| **Government and organisation IDs** | NIN, BVN, Nigerian passport, driver's licence, voter number (VIN), tax ID (TIN), UNHCR and refugee case numbers, US Social Security numbers, UK National Insurance numbers. Also any number written after a label such as *passport*, *case*, *file*, *ref*, *patient*, *hospital*, *MRN*, *member*, *beneficiary*, *household*, *ration card* or *tag* | Pattern. Labelled numbers must contain a digit, and a plain year is ignored |
| **Bank and payment details** | Nigerian bank accounts (NUBAN), IBANs, payment card numbers | IBANs must pass the mod-97 check, and card numbers the Luhn check |
| **Dates** | Dates in any common format, including dates of birth | Pattern |
| **Addresses and locations** | Street addresses ("No. 12 Adeola Odeku Street"), GPS coordinates, UK postcodes, US ZIP codes, plus codes, and places from the NGO's records (camps, shelters, villages) | Pattern and your records |
| **Vehicle plates** | Nigerian number plates | Pattern |
| **Online identifiers** | Web links, social media handles, IP addresses, phone IMEIs, device MAC addresses | IP addresses must be valid |

### Protected topics (listed for staff to decide)

These are the *special categories* that the law treats as sensitive: **NDPA 2023 section 30**, **GDPR Articles 9 and 10**, and safeguarding practice. They are highlighted and listed but **not ticked automatically**. The AI often needs the topic ("needs legal aid for an asylum case") once the person is hidden, so a staff member decides each time. The status bar warns when protected topics are left visible.

| Topic | Examples of what is flagged |
|---|---|
| Health | HIV status, TB, pregnancy, miscarriage, disability, mental health, fistula, sickle cell, medication |
| Sexual life or orientation | LGBTQ+ terms, sexual orientation, gender identity, sex work |
| Violence and abuse | rape, sexual assault, defilement, FGM, domestic violence, GBV, child or forced marriage, trafficking |
| Religion or belief | Muslim, Christian, Catholic, Ahmadiyya, Shia, Sunni, apostate |
| Ethnic origin | Hausa, Fulani, Yoruba, Igbo, Kanuri, Tiv, Ijaw, Rohingya, tribe, indigene |
| Political opinion | party membership, named parties, activist, separatist |
| Criminal record | arrested, convicted, detained, criminal record, ex-combatant, named armed groups |
| Immigration status | asylum seeker, undocumented, deported, stateless, IDP |
| Biometric or genetic | fingerprints, biometrics, iris scan, DNA, genotype, blood group |
| Trade union | trade union, union member, NLC, ASUU |

Spreadsheet columns with headings such as *religion*, *ethnicity*, *diagnosis*, *HIV status*, *disability* or *incident* are suggested as **hide the whole value**.

### Details that can still identify someone

Hiding the name is not always enough. The app also warns about:

- **Descriptions in text** that point to one person: "the only blind woman in the camp", "the village head", "wife of the chief imam". They are listed unticked under *Identifying description* for staff to decide, like protected topics.
- **Spreadsheet rows that stand out.** After the columns are chosen, the app counts rows whose mix of visible columns (age, sex, number of children and so on) is shared by fewer than 3 people. Staff see which columns make people stand out and can choose **Change Columns** to hide one of them.

### What cannot be found automatically

Voice recordings, handwriting, faces in photos (staff mark them by hand in Safe Photos), and identifying descriptions worded in ways the app's list does not cover cannot be recognised automatically. This is why **a person always reviews** the highlighted text before anything is copied. The full catalogue is in [`privacy_helper/core/pii.py`](privacy_helper/core/pii.py).

### How details are found

Spreadsheets have no fixed layout, so the app does not rely on column names alone.

1. **The NGO's own records.** When a spreadsheet is opened, staff confirm which columns hold names, places, phones and so on. Suggestions are pre-filled from column names and contents. Every value in those columns is then hidden wherever it appears, including inside free-text notes. This also covers Hausa, Yoruba, Igbo and other names that general-purpose name detectors miss.
2. **Fixed patterns.** Every identifier in the table above, with validity checks where they exist.
3. **Possible names.** Names after titles such as Mr, Mrs, Mallam, Alhaji or Hajiya are ticked automatically. Other capitalised word pairs are listed unticked for staff to confirm.
4. **Staff review.** Nothing leaves the app until a person has seen the highlighted text.

Settings hold an organisation-wide "always hide" list and a "never hide" list.

## Security design

- **Key vault.** One file in the user's app-data folder, readable only by that user. It is encrypted with AES-256-GCM under a key derived from the master password with scrypt (N=2^17, r=8, p=1). It is written atomically and the previous copy is kept, so a crash cannot lose keys. After a password change, the kept copy is re-saved under the new password. Only one copy of the app runs per user, so two windows can never overwrite each other's keys.
- **Auto-lock.** The vault locks after a period of no activity (10 minutes by default). Open text and the key list are cleared from the screen. Locking waits for any file being encrypted to finish.
- **Delete dates.** In **Settings › Security**, hidden-details records and file keys can be destroyed automatically after a number of days (off by default). Once a hidden-details record is gone, the AI's replies can no longer be filled in, so the people in them stay hidden for good. Once a file key is gone, that file can never be opened. Expired keys are destroyed when the vault is next unlocked, from the vault and from its kept previous copy. Backups made earlier still hold them.
- **Safe photos.** A photo is redrawn into a brand-new image, so EXIF, GPS, XMP and PNG text are not carried over. The phone's rotation is applied first. Blurred areas become about 6 × 6 blocks. The original is never changed.
- **Encrypted files (`.nph`).** Each file has its own random 256-bit key. Contents are encrypted with AES-256-GCM in 1 MB chunks. Each chunk is authenticated together with the file header, its position and an end-of-file flag, so tampering, reordering or truncation is detected. The format is byte-identical on Windows and macOS.
- **Locked PDFs.** Standard PDF AES-256 encryption with a random 20-character password and a separate random owner password.
- **Keys are saved before files are written.** A protected file can never exist without its key. Originals are never changed or deleted.
- **Safe Word copies.** These are written as new documents, not edited copies, so tracked changes, comments and author properties from the original cannot leak.
- **Sharing.** To let a colleague open a file, send the file and, separately (by phone or SMS), its key (`NPHKEY1:…`) or PDF password.
- **Clipboard.** Copied keys and passwords are removed from the clipboard after 60 seconds. On Windows they are also kept out of clipboard history and cloud clipboard sync.
- **Shortcuts in other apps.** The app registers only the two shortcuts staff choose, using `RegisterHotKey` on Windows and `RegisterEventHotKey` on macOS. It installs no keyboard hook, never sees other keys, never reads other apps' windows, and needs no Accessibility or administrator permission. Text is read from the clipboard only when a shortcut is pressed. A shortcut must use two modifier keys, so it cannot take a common key such as Ctrl+L away from other apps. If the app is locked, the window asks for the master password first. Each quick hide is saved in the key vault like any other. The safe version replaces the real text on the clipboard. The restored text is removed after 60 seconds and, on Windows, kept out of clipboard history. While shortcuts are on, closing the window keeps the app running in the menu bar or notification area. Choose Quit there to close it.
- **Untrusted files.** File names inside encrypted files are cleaned, so they cannot write outside the chosen folder. Damaged files are rejected before memory is used. Spreadsheets are parsed with `defusedxml`.
- **Checks on every change.** The tests (including tamper, wrong-key and false-alarm cases), the `ruff` linter with security rules, and `pip-audit` for known vulnerabilities in dependencies run on Windows and macOS for every push. Dependabot proposes dependency updates, and is held to Qt 6.8 for compatibility.

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
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .                              # lint, including security rules
.venv/bin/python run.py                                       # run the app
.venv/bin/python packaging/build.py                           # build the installer for this OS
```

PyInstaller cannot cross-build. Build the Windows installer on Windows (needs [Inno Setup 6](https://jrsoftware.org/isdl.php)) and the macOS disk image on a Mac. The **Build installers** GitHub Action does all three (Windows, Apple Silicon, Intel) on demand, or when a `v*` tag is pushed.

After editing `packaging/icon.svg`, run `python packaging/make_icons.py`.

## Project layout

```
privacy_helper/
  core/        PII catalogue, masking, key vault, file encryption, PDF lock, file reading (no UI code)
  ui/          one module per section, plus settings and the lock screen
  app.py       main window, menus, auto-lock, files opened from Finder or File Explorer, menu bar icon
  hotkeys.py   shortcuts that work in other apps (Windows and macOS system calls)
packaging/     PyInstaller recipe, Windows installer script, icons, build script
tests/         core tests (pytest)
```

## Known limits

- Protected-topic lists are in English, with Nigerian terms. Add local-language words to **Always hide** in Settings.
- Name detection is rule-based. It does not use a machine-learning model, which would add several hundred MB to the download. The NGO's own records and staff review cover most of the gap.
- Restore works on pasted text and on `.txt` and `.docx` files. Word formatting is not kept in safe copies, by design.
- Copying text puts it on the clipboard before the app sees it, so Windows clipboard history (Win+V) and Apple's Universal Clipboard may keep the original. Turn both off on shared computers.
- Shortcut letters follow their position on a US keyboard. On AZERTY or QWERTZ keyboards a shortcut may use a different letter from the one shown.
- Unsigned builds show a security warning on first launch. Code signing costs about USD 100 to 300 a year on Windows and USD 99 a year for Apple.
