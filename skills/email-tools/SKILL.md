---
name: email-tools
description: "Email: inbox triage, send/receive via Himalaya CLI."
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [email, imap, smtp, himalaya, triage, inbox]
trigger:
  - "Email inbox triage"
  - "Send email from terminal"
  - "IMAP/SMTP email"
  - "Reply to this mail / check my inbox"
---

# Email Tools

Class-level skill for mailbox work from the terminal: triage an inbox, draft and send mail.
Transport is the **Himalaya** CLI (IMAP/SMTP) — one tool for both reading and sending.

## When to Use

- "Check my inbox", "what needs a reply", "triage my mail"
- Send, reply to, or forward a message without leaving the terminal
- Diagnose IMAP/SMTP auth or folder-sync problems

## First: establish the account, then the commands

```bash
himalaya account list          # which accounts/backends are configured
himalaya folder list           # INBOX, Sent, Archive, ... (real names differ per provider)
himalaya --help                # authoritative flag list for the installed version
```

Config lives at `~/.config/himalaya/config.toml`; each account has `backend = "imap"`,
`email`, `imap.host/port`, `smtp.host/port`, and a password command (keyring or
`password.cmd`). Never hardcode the password in the file — use the command indirection.

Commands differ across Himalaya versions. Verify the exact spelling with `--help` before a
run; the shapes below are the stable ones:

```bash
himalaya envelope list                       # newest first, IDs are per-folder
himalaya envelope list -f INBOX -s 20
himalaya message read <id>
himalaya message reply <id>                  # opens editor
himalaya message forward <id>
himalaya template send < message.eml          # full MIME from stdin, no editor
```

## Triage discipline

1. **List before reading.** `envelope list` gives from/subject/date/flags; read bodies only for messages that matter. A 200-message inbox does not need 200 reads.
2. **Group by thread, not by message.** One decision per thread.
3. **Classify into: act now / needs a reply / read later / archive / spam.** Produce that classification as the deliverable — do not silently clean the mailbox.
4. **Unread is not urgency.** Sender + subject + date decide; newsletters and receipts are never "act now".
5. **No destructive changes without instruction.** Deleting, moving, or bulk-marking folders is a user decision; propose the list, then execute.
6. **Draft, then send.** Show the composed body (and recipients) before sending unless the user already said "send it".

## Sending

- Recipients: `To` explicit; `Cc`/`Bcc` only when asked. Verify the address domain before sending — one typo is unrecoverable.
- Attachments take absolute paths and must exist before composing; check size against the provider limit (usually 20–25 MB).
- Subject line states the ask; body states the action wanted in the first two sentences.
- Reply vs new thread: use `reply` so headers/threading stay intact; a fresh `send` with "Re: ..." breaks threading.
- Plain text by default; HTML only when the recipient needs formatting.

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `authentication failed` | wrong password / app-specific password missing | provider requires an app password (Gmail, Fastmail, iCloud) — generate one, store in keyring |
| `connection refused` / timeout | wrong port or TLS mode | IMAP 993 TLS, SMTP 465 TLS or 587 STARTTLS; match the provider's docs |
| Folder not found | provider-specific names | use `folder list` output verbatim (`[Gmail]/All Mail`, `INBOX.Sent`, ...) |
| Message ID not found | IDs are per-folder and shift after sync | re-list the folder, never reuse an ID from a previous run |
| Sent mail not in Sent | SMTP accepted but no APPEND to Sent | send with the account's save-copy flag or copy to Sent explicitly |
| Body encoding garbled | non-UTF-8 charset in the source | compose UTF-8, set the charset header, avoid mojibake in quoted text |

## Related skills

- `obsidian` — file triaged mail/tasks into the vault.
- `hermes-profile-ops` — if the mailbox is polled by a cron job, the job's prompt/toolset rules apply there.
