# Laya + Smistamento: production install spec

For implementation and operations. Version 2, 5 Oct 2026: the owner's decisions of 5 Oct 07:46 and
the 08:07 correction (no shadow mode) (§0) applied, Pigeonhole 2.4.2 behaviour verified (§1.4), code written and tested in a test environment (§2.7).

Based on SPEC-LAYA, SPEC-DELTA-LAYA (wins where the specs disagree), SPEC-SMISTAMENTO, the mail-server spec and QA notes (not published),
the plugin (this repository: README, `config.inc.php.dist`, `lib/smistamento_core.php`,
`server/smistamento-server.py`) and the training guide TRAINING-LAYA and its scripts (not published).

**Decision** = chosen here. **Open** = still needs an owner decision (§12). There are no metrics in this
spec: nobody has inspected the trained files yet. The numbers that count are the ones in each user's
`report.json` (§3.2).

---

## 0. Owner decisions (project owner, 5 Oct 2026 07:46, corrected 08:07, cache 08:12): they override the rest of this spec

| # | Decision | Applied in |
|---|---|---|
| 1 | The **initial training runs on the training PC**. The **Monday incremental training runs on the mail server**. | §3.1, §6, SPEC-LAYA «Training»; closes Open §12.1 |
| 2 | Encoder approved. The exact model, revision and fingerprint used are **recorded in §3.4**: placeholders that the owner fills in. | §3.4; closes Open §12.2 once filled in |
| 3 | Mail **between local users is not classified**. «Local» is defined in §1.5, together with how `laya-filter` detects it. | §1.5, §11.8; closes Open §12.6 |
| 4 | ~~Shadow mode on real mail after the MX cutover, no copy of incoming mail.~~ **Replaced by decision 5.** | — |
| 5 | **Correction, 5 Oct 08:07: no shadow mode at all.** From day one Laya moves mail at once for every user who has a head and agreed (`active`). The shadow phase, the `shadow` mode and the `X-Laya-Shadow-*` headers are gone from rollout, code, config and tests. Per-user activation/consent and the fallback without headers stay. Real mail reaches the mail server only after the MX cutover; nothing copies incoming mail. | §7, §8, §9, §10; closes Open §12.5 |
| 6 | **Embedding cache (08:12):** the owner copies the training PC's embedding cache to the mail server **once, himself**, so the first Monday run does not recompute the history. | §3.5, §8 phase 2; closes Open §12.11 |

---

## 1. Target architecture

```
Internet :25 → postscreen + Spamhaus → policyd-spf → Postfix → (MalwareBazaar content filter, port 25 only)
  → LMTP → Dovecot 2.4 / Pigeonhole, one Sieve run per recipient:
      1. before  "bazaar"   (exists: X-Malware-Bazaar: hit → Junk)
      2. before  "laya"     NEW: strip any X-Laya-* headers, then filter "laya-filter"
                            laya-filter: local mail (§1.5)? → no question, no header
                            laya-filter ──unix socket──► laya-serve (encoder + per-user heads)
                            ◄── X-Laya-Box / X-Laya-Box-Conf (active user) or nothing (off, no head, local, error)
      3. personal           the user's filters (Roundcube «Filtri»)
      4. after   "smistamento"  managed by the plugin: fileinto + stop, thresholds per user
  → Maildir
```

Everything at delivery runs on **the mail server**, on the host, next to Dovecot (SPEC-LAYA: «un
processo sul server di posta»; «Sul VPS arriva solo il file della testa»). Roundcube stays in its rootless container.
Training: the first run on **the training PC**, then the Monday incremental run on the mail server (§0 decision 1, §6).

### 1.1 How the headers get there before Sieve: **Decision: Pigeonhole `vnd.dovecot.filter`, in a global `before` script**

| Option | Verdict |
|---|---|
| **Sieve extprograms `filter`, global `before` script** | **Chosen.** Runs inside LMTP **once per recipient**, after alias expansion, with `USER` = the Dovecot username (the full address on the mail server, the mail-server spec) = the head file name. No change to the Postfix path, no `content_filter` (SPEC-LAYA: «Niente `content_filter`»). Runs before the user's filters and before the `smistamento` after-script, so both see the headers. Has a hard timeout in Dovecot (`sieve_filter_exec_timeout`), which laya-filter must never hit (§1.4 f). |
| Postfix milter | Rejected. A milter sees one message for all recipients, but every recipient needs headers from **their own** head. It also sits in the SMTP dialogue (SPEC-LAYA: never a 550 on the score, never a queue waiting on the model). |
| Postfix `content_filter` / LMTP proxy | Rejected. SPEC-LAYA says no `content_filter`; per-recipient splitting needs `*_destination_recipient_limit=1`; one more daemon in the delivery path. |
| Post-delivery IMAP move (IDLE/NOTIFY) | Rejected. The plugin's design (Sieve `fileinto` on headers, the «Smistata in» line, the digest) needs the headers *in* the stored message. |

**Security, mandatory:** any sender can put `X-Laya-Box: Junk` / `X-Laya-Box-Conf: 0.99` in a mail, and with
«Elimina definitivamente» that mail would be discarded. The `laya` before-script **always** deletes incoming
`X-Laya-*` headers first, even when Laya is down.

### 1.2 Global Sieve script `laya` (Decision)

`/etc/dovecot/sieve/laya.sieve`, owner root, 0644, precompiled with `sievec` (verified, §1.4 g: without the
`.svbin` LMTP logs two errors per delivery because it cannot write next to a global script):

```sieve
require ["editheader", "vnd.dovecot.filter"];
# Never trust X-Laya-* from outside: deleted here even when Laya is down or skipped.
# (deleteheader needs exact names; laya-filter also strips ANY X-Laya-* field.)
deleteheader "X-Laya-Box";
deleteheader "X-Laya-Box-Conf";
# `filter` is used as a TEST, not as an action: if laya-filter cannot run or exits non-zero the test is just
# false, the message stays as it is (already stripped above) and the script goes on. No runtime error.
if anyof (header :is "X-Spam-Flag" "YES", header :is "X-Malware-Bazaar" "hit") {
  # Server-flagged spam/malware is never sorted by Smistamento: no model, only strip any other X-Laya-* field.
  if filter "laya-filter" ["--strip-only"] {
  }
} else {
  if filter "laya-filter" {
  }
}
```

Dovecot 2.4 (add to the config of README «Server», **after** the existing bazaar `before` block). This is
`laya/dovecot/90-laya.conf`, verified on 2.4.2:

```
sieve_plugins {
  sieve_extprograms = yes
}
# Both extensions for GLOBAL scripts only: a user's own script (ManageSieve / Roundcube «Filtri») can neither
# add/delete headers nor run programs.
sieve_global_extensions {
  editheader = yes
  vnd.dovecot.filter = yes
}
sieve_filter_bin_dir = /usr/local/lib/dovecot/sieve-filter    # contains only laya-filter
sieve_filter_exec_timeout = 10s                               # Dovecot's kill; laya-filter stops itself at 5 s / 8 s
# Defence in depth: no global script may *add* these with addheader (filter output is not affected)
sieve_editheader_header X-Laya-Box {
  forbid_add = yes
}
sieve_editheader_header X-Laya-Box-Conf {
  forbid_add = yes
}
# Before-scripts run in the order they are DEFINED: keep this block AFTER the bazaar one.
sieve_script laya {
  type = before
  driver = file
  path = /etc/dovecot/sieve/laya.sieve
}
```

Do **not** add `forbid_delete` for the X-Laya headers: the `laya` script has to delete them.

### 1.3 Fallback (SPEC-LAYA: «Se Laya è giù, la mail resta in INBOX»)

`laya-filter` **never fails the delivery**. On any problem it writes the stripped input back to stdout and
exits 0: socket missing, laya-serve refusing connections, hanging past the **5 s** budget, crashing in the
middle of a request, a malformed reply (label that isn't one printable line, conf not `^(0\.[0-9]{2}|1\.00)$`),
no head, head refused, encoder mismatch, or an exception. The mail gets **no** `X-Laya-*` headers, so the managed
script's `not exists` rule keeps it in INBOX. Nothing is rejected or queued because of Laya. Errors go to
stderr, which ends up in the Dovecot log (`lmtp: Error: laya-filter: user=… fallback, mail delivered without
Laya headers: TimeoutError: timed out`).

Three layers, because Dovecot's own kill is not a safe fallback (§1.4 f):

| Layer | Limit | What happens |
|---|---|---|
| laya-filter socket budget | 5 s overall (connect + send + reply) | stripped mail, exit 0 |
| laya-filter hard self-limit (`SIGALRM`) | 8 s from start | stripped mail, exit 0. If stdin wasn't even read yet: exit 75, nothing printed, so the Sieve `filter` test is false and the message stays as it was (already stripped by `deleteheader`) |
| Dovecot `sieve_filter_exec_timeout` | 10 s | **must never be reached**: Dovecot 2.4.2 kills the filter, then the LMTP process panics and the delivery is aborted (the MTA retries later) |

If `laya-filter` itself cannot run (missing interpreter, exit ≠ 0), the `filter` *test* is false, Sieve goes on
with the unchanged message, and the four `deleteheader` lines have already removed the forged headers that
matter (verified, §2.7 F4).

### 1.4 Pigeonhole 2.4.2: verified behaviour (test environment, `dovecot/dovecot:2.4.2`, 5 Oct 2026)

Evidence: probe scripts, log excerpts and the end-to-end run are in the project test environment (not published). Docs: [sieve plugin 2.4.2](https://doc.dovecot.org/2.4.2/core/plugins/sieve.html),
[extprograms 2.4.2](https://doc.dovecot.org/2.4.2/core/plugins/sieve_extprograms.html),
[editheader 2.4.2](https://doc.dovecot.org/2.4.2/core/config/sieve/extensions/editheader.html),
[vnd.dovecot.filter spec](https://raw.githubusercontent.com/dovecot/pigeonhole/2.4.2/doc/rfc/spec-bosch-sieve-extprograms.txt).

| # | Question | Result | Evidence |
|---|---|---|---|
| a | Order of two `before` scripts | **The order in which the `sieve_script` blocks are defined in the config**, not the name. A `sieve_script_precedence` setting overrides it (lower first); a file driver pointing at a directory runs its `*.sieve` files in byte order of the name. So: put the `laya` block after the `bazaar` block | probe: blocks defined `zz` then `aa` → log `zz sees X-Order=[orig]`, then `aa sees X-Order=[zz]`. Doc: «The storages will be accessed in the order these storages are defined in the configuration, unless the order is overridden by the `sieve_script_precedence` setting» |
| b | Are `deleteheader`/`addheader`/`filter` changes in a before-script visible later? | **Yes**: to later before-scripts, the personal script, the after-scripts, **and** they are in the stored mail. An `X-Laya-Box` added by the filter is matched by the plugin's `header :is` rules | probe: `personal sees X-Laya-Box=[Feed] X-Order=[zz]`, `after1 sees X-Laya-Box=[Feed]`, stored mail has `X-Laya-Box: Feed` and no forged value. Test run: D1/D2 (filed into Feed by the real smistamento after-script) |
| c | Does a failing filter undo earlier edits? | **No**, when `filter` is used as a test. Exit ≠ 0 → test false, message = the version *before* the filter (with the earlier `deleteheader` applied), script continues. As an action the spec allows the whole script to fail with an implicit keep of the **original** message (forged headers back!): that's why `laya.sieve` uses the test form | probe mail 2: `Terminated with non-zero exit code 3`, `aa filter-fail FALSE`, stored mail without X-Laya-Box, with `X-Order: zz`. Spec §6.1/§8 |
| d | Do the after-scripts run when the user's filter files the mail? | **No**: a personal `fileinto` cancels the implicit keep and the chain stops there. User filters win (B6) | probe mail 3: no `after1` log line. Test run D5 («condominio» → Progetti although the label was Feed) |
| e | editheader settings | `editheader` is **not** enabled by default. `sieve_global_extensions { editheader = yes }` enables it for global scripts only. A user script that requires it is refused (`its use is restricted to global scripts`), so users can't forge X-Laya headers from their own filters. Protected headers in 2.4: `sieve_editheader_header <name> { forbid_add = yes / forbid_delete = yes }` (the 2.3 `sieve_editheader_protected` is gone). The 2.4.2 page still describes `forbid_add` as a space-separated list, but its example and the real 2.4.2 binary use the named block. `forbid_add` blocks `addheader` (sievec warns), not the filter output; `deleteheader` keeps working. Received/Auto-Submitted can never be deleted. `sieve_editheader_max_header_size` default 2k | `doveadm sieve put` → `failed to load Sieve capability 'editheader': its use is restricted to global scripts` (exit 65); `sievec` → `adding specified header field 'X-Laya-Box' is forbidden; modification will be denied` |
| f | extprograms (2.4 syntax) | `sieve_plugins { sieve_extprograms = yes }`, `sieve_global_extensions { vnd.dovecot.filter = yes }`, `sieve_filter_bin_dir`, `sieve_filter_exec_timeout` (default 10s), `sieve_filter_input_eol` (default `crlf`). The program sees only `HOME`, `USER` (Dovecot username), `SENDER` (envelope sender), `RECIPIENT`, `ORIG_RECIPIENT`, and gets the message with CRLF line ends. It runs as the mail user. stderr goes to the Dovecot log at Error level. **On the 10 s timeout Dovecot 2.4.2 kills the filter and then the LMTP process panics**: `Panic: output stream (temp iostream … program client seekable output) is missing error handling`, `child … killed with signal 6`. The LMTP session drops after DATA, the mail is not stored, and the MTA retries | probe env line: `USER=probe SENDER=ext@example.net RECIPIENT=probe ORIG_RECIPIENT=probe HOME=/srv/vmail/probe crlf=15 lf=15`. Test run F7 (aborted after 10.0 s, not stored) and F8 (laya-filter's own 8 s limit delivers) |
| g | sievec | Needed for global scripts in a root-owned directory: without `.svbin` the script still runs, but every delivery logs two errors (`… need to be pre-compiled using the sievec tool`). Re-run `sievec` after each edit of `laya.sieve` | probe log before/after `sievec` |

### 1.5 Local mail is not classified (Decision 3)

**Definition.** A mail is *local* when a local user wrote it to a local user. The recipient is always local,
because laya-filter runs at LMTP delivery. The filter therefore checks the sender, and needs **both**:

1. the envelope sender (`SENDER`, from Postfix's `MAIL FROM`) has a domain in `local_domains`
   (`/etc/laya/filter.conf`, e.g. `example.org` plus the other hosted domains), **and**
2. our own Postfix recorded, on the line it wrote when the mail entered it, either an **authenticated
   submission** or a **local pickup**:
   - `with ESMTPSA` / `with ESMTPA` (Postfix default for SASL logins on 587/465), or
     `(Authenticated sender: …)` if `smtpd_sasl_authenticated_header = yes`;
   - `(Postfix, from userid N)` for `sendmail` on the server (cron, the Smistamento digest).

**How laya-filter finds that line.** It reads the `Received` headers from the top. It skips Dovecot's own
`with LMTP` line and our content filter's re-injection lines (written `by <mta_hosts>`, with the client
`[127.0.0.1]`/`[::1]` taken from the connection, not from HELO). The next line is the entry line, and it must be
written `by <one of mta_hosts>` (`mta_hosts = mx.example.org`). It is local only if that line carries one of
the markers. Lines below the entry line are never read, because anyone can forge them.

**Consequences:**

- Mail from outside that only *claims* a local sender (forged `MAIL FROM`/`From:`, or a fake `ESMTPSA` line
  below the real one) is **classified** as usual (test run D6b). The worst case of a false «local» is «stays in
  INBOX», never a move.
- An authenticated user sending with a non-local envelope sender is classified.
- Bounces (`SENDER` empty) are classified.
- Postfix-generated mail picked up locally is not.
- The `X-Laya-*` stripping happens for local mail too.
- `local_domains` or `mta_hosts` empty → nothing is local (fail-safe: classify).

---

## 2. Inference service

### 2.1 Processes (Decision)

| Piece | What | Runs as |
|---|---|---|
| `laya-serve` | long-running systemd service; loads the encoder once and the heads on demand | user `laya` (system, no shell), `SupplementaryGroups=vmail` only to chgrp the socket |
| `laya-filter` | small Python stdlib client (`#!/usr/bin/python3 -IS`) run by Pigeonhole per recipient | the mail user (vmail, uid 5000) |
| socket | `/run/laya/laya.sock`, `laya:vmail`, 0660 (`RuntimeDirectory=laya`, 0755) | |

`laya-serve` imports the **same** `laya_text.py` as training (`--text-module-dir /opt/laya/training`, same
`PREPROC_VERSION`). The head math is the formula of `laya_head.classify` (§2.3) written out in `laya-serve.py`,
because the service also needs the embedding for the archive (§2.5). It is unit-tested against the same
rounding. Code: `laya/` (§2.7).

### 2.2 Protocol (Decision)

Request: one JSON line, then the raw message bytes (laya-filter sends the **already stripped** message, at most
the first 256 KB):

```
{"v":1,"user":"user@example.org","size":48211}\n<48211 bytes>
```

Reply: one JSON line:

```
{"label":"Feed","conf":"0.93","mode":"active"}     active user: laya-filter adds the headers
{"label":null,"reason":"off|no_head|bad_head|encoder_mismatch|bad_request|error"}
```

For `mode: active` laya-filter prepends `X-Laya-Box: <label>` and `X-Laya-Box-Conf: <conf>`, using the
message's own line ends, on top of the header (the same placement the test stub uses). It
accepts the reply only if `label` is one printable line (no CR/LF/control characters, ≤ 200 chars) and
`conf` matches `^(0\.[0-9]{2}|1\.00)$`. Anything else → fallback (§1.3). The service only reads the first
256 KB of a message (Decision: `laya_text` keeps 2,000 characters anyway).

### 2.3 Inference (as in TRAINING-LAYA §8)

```
x = encoder.encode(encoder_input(mail_to_text(raw)), normalize_embeddings=True)   # 768
p = softmax((x · W + b) / temperature);  k = argmax(p)
X-Laya-Box: labels[k]          X-Laya-Box-Conf: floor(p[k]·100)/100 formatted "%.2f"
```

- The conf is **always** `0.00`–`1.00` with two decimals and a dot. Sieve compares it as text (`i;octet`)
  against `"0.80"`, `"0.40"` and so on (`config.inc.php.dist`). Rounding down (Decision) means a value never
  passes a threshold it didn't reach.
- `labels[k]` is written exactly as stored in the head (= the `label` field of the user's `classes` file).
- Classes "muted" in the head (W = 0, b = −30) are never chosen in practice.
- Head reload: `stat` of `/laya/heads/<address>.joblib` on every request; reload when mtime, size or inode
  change (install and rollback need no restart). A 0-byte file is «no head». At load, laya-serve rechecks
  format, shapes, finite values, `preproc` and the encoder fingerprint; a refused head gives `bad_head` or
  `encoder_mismatch` and is logged once.
- Users: `/etc/laya/users.conf` (root:laya 0640), one line per Dovecot username with `active` or `off`
  (any other word, e.g. an old `shadow`, is logged and ignored = `off`); `* <mode>` sets the default. Users not listed (and no `*`) are `off`. Reread when it changes.

### 2.4 Latency and resources

Measured only with the fake encoder on the test environment (3–5 ms per request, meaningless for the real model). Budget
(Decision): laya-filter gives up on laya-serve at **5 s**, stops itself at **8 s** whatever happens, and Dovecot
kills it at **10 s**, which must never be reached (§1.4 f). The worst case adds 5 s to a delivery when
laya-serve hangs; when laya-serve is down it adds nothing (connection refused at once). One encoder
process serialises requests (`enc_lock`); LMTP concurrency queues on the socket. **Implementer:** the per-request
time is in the log (`ms=`); measure p50/p95 in the first week (§8). **Owner:** check the mail server's
RAM against the encoder (Open §12.4); the unit caps it at `MemoryMax=3G`, adjust after measuring.

### 2.5 Delivery archive (SPEC-LAYA «Alla consegna»)

With `--archive /var/lib/laya/emb`, laya-serve appends one line per classified mail to
`/var/lib/laya/emb/<address>.jsonl` (owner laya, 0600):
`{"ts", "mid_hash": sha1(Message-ID), "label", "conf", "mode" (always `active`), "encoder", "preproc", "emb_f16": base64 of the
768 float16 values}` (about 2 KB per mail). Decision, changed from version 1: the embedding stays in the same
line instead of a monthly `.npy` with a row index. One append per mail is atomic, and there is no second file to
keep in step. Same key (`mid_hash`), dtype and fingerprint as the training cache (TRAINING-LAYA §5).
**To write:** the reader in `laya-embed.py` (Monday run, §6). Until then the training cache recomputes what's
missing. Not needed for activation.

### 2.6 systemd unit

`laya/systemd/laya-serve.service`:

```ini
[Unit]
Description=Laya inference for Smistamento (laya-serve)
After=network.target
Before=dovecot.service
[Service]
Type=simple
User=laya
Group=laya
SupplementaryGroups=vmail
RuntimeDirectory=laya
RuntimeDirectoryMode=0755
# the encoder is a local directory: never reach the Hugging Face hub (PrivateNetwork=yes anyway)
Environment=HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
ExecStart=/opt/laya/venv/bin/python /opt/laya/serve/laya-serve.py \
  --socket /run/laya/laya.sock --socket-group vmail --socket-mode 0660 \
  --encoder /opt/laya/encoder/laya-multilingual --heads /laya/heads --users /etc/laya/users.conf \
  --text-module-dir /opt/laya/training --archive /var/lib/laya/emb
Nice=5
Restart=on-failure
RestartSec=5
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/laya/emb
PrivateTmp=yes
PrivateNetwork=yes
NoNewPrivileges=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_UNIX
MemoryMax=3G
[Install]
WantedBy=multi-user.target
```

`ProtectHome=yes`: laya-serve never reads the training files in a home; heads come from `/laya/heads` only.
Not tested under systemd on the test environment (containers). Check `systemd-analyze verify` on the mail server.

### 2.7 Code and test-environment run (version 2)

Package `laya/` (not published yet):

| File | Installed as |
|---|---|
| `laya-serve.py` | `/opt/laya/serve/laya-serve.py`; `--stub` = the fake encoder of `laya-embed.py --encoder fake-hash`, for tests only |
| `laya-filter` | `/usr/local/lib/dovecot/sieve-filter/laya-filter`, root 0755 |
| `laya-check-head.py` | `/opt/laya/training/laya-check-head.py` (§3.2, `--install`) |
| `sieve/laya.sieve`, `dovecot/90-laya.conf` | §1.2 |
| `etc/users.conf.example`, `etc/filter.conf.example` | `/etc/laya/` |
| `systemd/laya-serve.service` | §2.6 |
| `tests/test_laya.py` | 23 unit/integration tests (filter against a fake server; serve `--stub`; check-head) |
| test environment | not published: `deploy.sh`, `make-heads.sh`, `verify.py`, Pigeonhole probes |

Requirements: laya-filter = Python ≥ 3.9 stdlib only. laya-serve and laya-check-head = Python ≥ 3.9 + `numpy`
+ `joblib`; the real encoder also `sentence-transformers` + `torch` (CPU). All from `/opt/laya/venv`
(`requirements.lock`).

Test run, 5 Oct 2026 08:08. Separate test containers with Dovecot 2.4.2, the users' real Sieve scripts copied
from the Smistamento test instance, classes exported with `smistamento-server.py classes`, fake-encoder heads.
**23/23 PASS**:

- C1a: 12 broken heads rejected.
- C1b: 11/11 OK and installed for both users.
- C2: re-install keeps `.prev` with its old date.
- D1–D9: classification and filing; forged headers stripped; spam flag; Junk → Trash; user filter wins;
  local, spoofed-local and pickup mail; two recipients; user off.
- F1–F8: laya-serve down, hanging, crashing; laya-filter failing or hanging; hard limit; recovery; 0-byte head.

---

## 3. Trained files: where they are, where they go

### 3.1 Source (owner): initial training on the training PC (Decision 1)

The **first** training runs on **the training PC**, with the scripts and layout of TRAINING-LAYA. The training PC gets the
history and each user's classes file (exported on the mail server, §4). Then, into the **home of the install user on
the mail server**:

```
~/laya/work/<address>.joblib(.new)    the head (the guide writes <address>.joblib.new)
~/laya/work/<address>.report.json     its training report (check 10)
~/laya/classes/<address>.json         the classes export the head was trained on (for reference; check 3
                                      compares against TODAY's /var/lib/smistamento/classes/<address>.json)
```

On the mail server, outside the home, installed once (not per user):

```
/opt/laya/encoder/laya-multilingual/  the SAME encoder files as on the training PC (§3.4) + laya-multilingual.sha256
/opt/laya/requirements.lock           exact Python package versions (same as the training PC for encoder + numpy/joblib)
```

The weekly incremental run is on **the mail server** (§6) and never copies anything back to the training PC. The embedding
cache from the training PC (`~/laya/emb-cache/<address>.npz|.ids`) is not needed to install a head, but the Monday run
needs the history's embeddings: the owner copies it once (Decision 6, §3.5).

### 3.2 Pre-install checks for the files (run for every user; any failure = don't install that user)

| # | Check | Why (what the code expects) |
|---|---|---|
| 1 | `joblib.load` gives a `dict` with `format == "laya-head-v1"` | format of TRAINING-LAYA §8; `laya-install.sh` refuses other formats |
| 2 | `W` float32 shape `(768, N)`, `b` shape `(N,)`, `temperature` float > 0 | SPEC-LAYA: linear `768 → N` |
| 3 | `labels` == the `label` fields of **today's** `/var/lib/smistamento/classes/<address>.json`, same order, same spelling | SPEC-LAYA: «Classi: quelle del suo file `classes`, nello stesso ordine». A renamed or switched-off folder means retraining (or accept that those mails stay in INBOX, SPEC-LAYA «Casi») |
| 4 | `labels[0]` = the inbox label (`Imbox`, `smistamento_inbox_labels`) | the plugin `stop`s on that label: people's mail never moves |
| 5 | `Junk` is in `labels` (as `labels[1]`) **iff** the user has «Lo smistamento gestisce lo spam» on | SPEC-DELTA-LAYA US-SMI-SPAM §9. The label is `Junk` (`smistamento_spam_labels`), **not** the folder name (which may be «Spam») |
| 6 | labels are the `label` field, not `path` or `mailbox` (e.g. `PaperTrail`, not `Paper Trail`) | `lib/smistamento_labels.php` matches the Sieve `accepts` list (case-insensitive) |
| 7 | `encoder` == the fingerprint of the deployed encoder (`laya-multilingual@sha256:<16 hex>`, computed as in `laya-embed.py::encoder_id`) | a head is meaningless on another encoder; `laya-serve` refuses a mismatch (`reason: encoder_mismatch`) |
| 8 | `preproc` == `laya_text.PREPROC_VERSION` of the deployed `laya_text.py` (`laya-text-v1`) | train and inference text must be identical |
| 9 | `user` == the address in the file name == the Dovecot username (full address) | `smistamento_head_file = '/laya/heads/%u.joblib'`; in a test setup it may be a short name (`user`), in production `user@example.org` |
| 10 | `report.json`: `exit == 0`, `n_train + n_val ≥ 200`; read `muted`, `per_class`, `confusion`, `val_error_*` | SPEC-LAYA minimum of 200; accept rule «not worse than the head in use» |
| 11 | file non-empty (a **0-byte placeholder** file is not a head) | `laya-serve` treats 0 bytes as «no head» |

Check script: `laya/laya-check-head.py` (Python + numpy + joblib), written and tested in a test environment (§2.7, C1a/C1b/C2). It
runs 1–11 and prints one `OK`/`FAIL` line per check. Exit 0 = OK; 1 = a check failed, nothing installed;
2 = usage or I/O error. Details as implemented:

- 2 also requires every value of `W`/`b` and `temperature` to be finite, and the labels to be ≥ 2 distinct
  non-empty strings.
- 3/4/5 read the roles of today's classes file: the inbox label comes from `role: inbox`, and the spam label from
  `role: spam` (spam switch on ⇔ that class exists).
- 9 optionally runs `doveadm user <address>` (`--doveadm doveadm`).
- 10 is the **validation gate**:
  - `exit == 0`;
  - `n_train + n_val ≥ 200`;
  - the report belongs to this head (same user, labels, encoder, `n_train`/`n_val`);
  - `val_error_new < val_error_majority`;
  - `val_error_new ≤ val_error_old` when there was a head in use.
- With `--install` it replaces `laya-install.sh`. It copies to a temp file in the heads directory, then
  chmod 0644, fsync, mtime = now. It copies the head in use to `.prev` (temp + rename, keeping its date) and
  renames over `<address>.joblib`. Finally it copies head + report into `heads-archive/<address>/` (0600,
  keeps 8).

### 3.3 Destination (Decision, paths from SPEC-LAYA / README)

| Path | Owner / mode | Content |
|---|---|---|
| `/opt/laya/encoder/laya-multilingual/` | root, 0755 / files 0644, read-only | encoder + `.sha256`; never updated in place |
| `/opt/laya/venv/` | root | from `requirements.lock` |
| `/opt/laya/training/` | root | `laya_text.py`, `laya_head.py`, `laya-export.py`, `laya-embed.py`, `laya-train.py`, `laya-install.sh`, `laya-rollback.sh`, `laya-monday.sh` |
| `/opt/laya/training/laya-check-head.py` | root | §3.2 (from `laya/`) |
| `/opt/laya/serve/` | root | `laya-serve.py`, imports `laya_text` from `/opt/laya/training` |
| `/etc/laya/filter.conf` | root 0644 | laya-filter: socket, timeout, `local_domains`, `mta_hosts` (§1.5) |
| `/usr/local/lib/dovecot/sieve-filter/laya-filter` | root, 0755 | the only file in that directory |
| `/laya/heads/<address>.joblib` | root:root 0644, directory 0755 | the head in use (mtime = «Smistamento aggiornato») |
| `/laya/heads/<address>.joblib.prev` | same | previous head (SPEC-LAYA rollback) |
| `/var/lib/laya/heads-archive/<address>/<YYYYMMDD-HHMM>.{joblib,report.json}` | root 0600 / dir 0700 | every installed head + its report; keep 8 (Decision) |
| `/var/lib/laya/{train,emb-cache,emb}` | 0700 (train, emb-cache: root; emb: laya) | training work, embedding cache, delivery archive |
| `/etc/laya/users.conf` | root:laya 0640 | `active` / `off` per address |

Install, per user (checks 1–11, then atomic, `.prev`, mtime = now: TRAINING-LAYA §9), one command:

```bash
U=user@example.org
sudo /opt/laya/venv/bin/python /opt/laya/training/laya-check-head.py --user $U \
     --head ~installer/laya/work/$U.joblib.new --classes /var/lib/smistamento/classes/$U.json \
     --encoder /opt/laya/encoder/laya-multilingual --doveadm doveadm \
     --install --heads-dir /laya/heads --archive-dir /var/lib/laya/heads-archive
```

Run `smistamento-server.py classes --user $U` first (§4). Rollback stays `laya-rollback.sh`. Afterwards the
training files in the home can go (`shred -u ~/laya/work/*.jsonl`). The embedding cache goes to
`/var/lib/laya/emb-cache` as in §3.5.

Roundcube container: mount the **directory** read-only (`- /laya/heads:/laya/heads:ro`), never the single
file: a file bind mount stays on the old inode after the atomic rename.

### 3.4 Encoder record (Decision 2: encoder approved; the owner fills in)

The same encoder files on the training PC (training) and the mail server (inference). Every head carries the fingerprint in
`encoder`; check 7 and laya-serve compare it with the deployed files.

| Field | Value |
|---|---|
| Model (Hugging Face id) | `<TO FILL: e.g. intfloat/multilingual-e5-base>` |
| Revision (commit hash of the model repo) | `<TO FILL: 40-hex commit>` |
| Local directory name | `laya-multilingual` (`/opt/laya/encoder/laya-multilingual/`) |
| Fingerprint (`laya-embed.py::encoder_id`) | `laya-multilingual@sha256:<TO FILL: 16 hex>` |
| `laya-multilingual.sha256` (sha256sum of every file) | `<TO FILL: path + sha256 of the .sha256 file itself>` |
| Dimensions / prefix | 768 / `query: ` (`laya_text.ENCODER_PREFIX`) |
| `max_seq_length` | `<TO FILL: as used by laya-embed.py --max-len>` |
| sentence-transformers / torch versions | `<TO FILL: from requirements.lock>` |
| Recorded by / date | `<TO FILL>` |

Fingerprint command (on both machines, must print the same):

```bash
/opt/laya/venv/bin/python -c 'import sys; sys.path.insert(0,"/opt/laya/training"); import importlib.util as u; \
s=u.spec_from_file_location("e","/opt/laya/training/laya-embed.py"); m=u.module_from_spec(s); s.loader.exec_module(m); \
print(m.encoder_id("/opt/laya/encoder/laya-multilingual"))'
```

### 3.5 Embedding cache from the training PC (Decision 6, once, before the first Monday run)

the owner copies the cache that the initial training wrote on the training PC, so `laya-embed.py` on the mail server only
encodes mails that aren't in it yet.

| What | Value |
|---|---|
| Source (the training PC) | `~/laya/emb-cache/<address>.npz` and `<address>.ids`, one pair per user |
| Destination (the mail server) | `/var/lib/laya/emb-cache/` = `CACHE` default of `laya-monday.sh` and `--cache-dir` default of `laya-embed.py`/`laya-export.py`/`laya-train.py` |
| File names | `<address>` = the **Dovecot username** (full address), same name as the head (`safe()` rule: only `A-Za-z0-9@._+-`). If the training PC used other names, rename both files |
| Format | `<address>.npz`: `mid_hash` (`U40`, sha1 of the stripped `Message-ID`), `emb` (float16, N × 768, normalised), `meta` (JSON: `encoder` fingerprint, `preproc`, `dim`). `<address>.ids`: one `mid_hash` per line (laya-export.py skips those mails, so their text isn't re-exported) |
| Owner / mode | `root:root`, directory 0700, files 0600 (the Monday cron runs as root with `umask 077`). Derived from mail: same privacy class as the training data |
| Validity | only with the **same encoder fingerprint** (§3.4) and `preproc` `laya-text-v1`: on a mismatch `laya-embed.py` prints «cache di un altro encoder/preproc, la butto» and recomputes everything |

```bash
# on the mail server, after copying the files (e.g. rsync over SSH) to ~/emb-cache-copy/
sudo install -d -m 0700 -o root -g root /var/lib/laya/emb-cache
sudo install -m 0600 -o root -g root ~/emb-cache-copy/*.npz ~/emb-cache-copy/*.ids /var/lib/laya/emb-cache/
# check: every user with a classes file has a cache the Monday script will use (same lookup as laya-embed.py)
sudo /opt/laya/venv/bin/python - <<'PY'
import glob, importlib.util as u, json, os, sys
sys.path.insert(0, "/opt/laya/training")
s = u.spec_from_file_location("e", "/opt/laya/training/laya-embed.py"); e = u.module_from_spec(s); s.loader.exec_module(e)
import laya_text
enc = e.encoder_id("/opt/laya/encoder/laya-multilingual")
for cf in sorted(glob.glob("/var/lib/smistamento/classes/*.json")):
    user = os.path.basename(cf)[:-5]
    fn = os.path.join("/var/lib/laya/emb-cache", e.safe(user) + ".npz")
    cache, meta = e.load_cache(fn)
    ids = sum(1 for _ in open(fn[:-4] + ".ids")) if os.path.exists(fn[:-4] + ".ids") else 0
    ok = bool(meta) and meta["encoder"] == enc and meta["preproc"] == laya_text.PREPROC_VERSION and meta["dim"] == 768 and ids == len(cache) > 0
    print("OK  " if ok else "FAIL", user, len(cache), "embeddings,", ids, "ids,", meta)
PY
```

`FAIL` = missing file, other encoder/preproc, or `.ids` not matching the `.npz`: fix it before the first Monday
(otherwise that user's history is recomputed on CPU). The first Monday log must show, per user,
`N nuovi embedding, M in cache` with N = only the mails since the training.

---

## 4. Per-user classes export (exists, plugin side)

```
0 3 * * 1     root  /usr/local/sbin/smistamento-server.py classes --all-users --out-dir /var/lib/smistamento/classes
```

One `<address>.json` per user: `Imbox` (INBOX, `role: inbox`) first, then `Junk` (`role: spam`, the user's
special Spam folder) if the spam switch is on, then the active folders (`role: folder`). A user who never saved
Impostazioni › Smistamento gets only `Imbox`: nothing to train or sort. Run it by hand (`--user <address>`)
before every manual install so check 3 compares against today's settings.

---

## 5. Roundcube plugin + Dovecot (exists, as in README / INSTALL-AGENT)

Follow `INSTALL-AGENT.md` and README «Installazione», «Server». In short:

1. Plugin in `/opt/roundcube/plugins/smistamento/`, enabled. `managesieve` enabled with
   `managesieve_host = 'tls://<container-host-ip>:4190'`, `managesieve_filename_exceptions = ['smistamento']`.
2. `smistamento_managesieve_host = '<container-host-ip>'`, port 4190, `usetls = true`, conn_options verify off while the
   cert is snakeoil (the mail-server spec).
3. `smistamento_min_conf = '0.80'`, `smistamento_inbox_labels = ['Imbox']`, `smistamento_spam_labels = ['Junk']`,
   `smistamento_spam_default = ['active' => true, 'threshold' => '0.40', 'trash_threshold' => '0.80', 'action' => 'trash']`,
   `smistamento_label_map` only where the auto mapping isn't enough, `smistamento_head_file = '/laya/heads/%u.joblib'`.
4. Dovecot 2.4: `protocols = imap lmtp sieve`; ManageSieve on `127.0.0.1:4190` only (never public);
   `protocol lmtp { mail_plugins { sieve = yes } }`; `sieve_script personal` (`~/sieve`, `~/.dovecot.sieve`);
   `sieve_script smistamento { type = after; driver = file; path = ~/sieve/smistamento.sieve }`; the bazaar
   before-script unchanged; plus §1.2. `doveadm reload` (ask the owner before any `restart`).
5. Cron (root, host):

```
*/15 * * * *  root  /usr/local/sbin/smistamento-server.py digest --all-users --base-url https://webmail.example.org/
0 3 * * 1     root  /usr/local/sbin/smistamento-server.py classes --all-users --out-dir /var/lib/smistamento/classes
30 3 * * 1    root  nice -n 19 ionice -c3 /opt/laya/training/laya-monday.sh >> /var/log/laya/monday.log 2>&1
```

The 03:30 line only goes in at rollout phase 2 (§8).

### 5.1 OpenRouter (digest «In breve», US-SMI-DIGEST-LLM)

Optional, **off by default for every user**. Each user enters their **own** key in the UI. Ops only prepares
the storage:

```bash
sudo install -d -m 0700 -o <host uid of container www-data> -g <host gid> /var/lib/smistamento/llm
sudo install -d -m 0750 /etc/smistamento
sudo sh -c 'umask 027; openssl rand -base64 48 > /etc/smistamento/llm.key'
sudo chown root:<host gid of www-data> /etc/smistamento/llm.key && sudo chmod 0640 /etc/smistamento/llm.key
# compose volumes:  /var/lib/smistamento/llm:/var/lib/smistamento/llm   and   /etc/smistamento/llm.key:/etc/smistamento/llm.key:ro
```

```php
$config['smistamento_llm_dir'] = '/var/lib/smistamento/llm';
$config['smistamento_llm_keyfile'] = '/etc/smistamento/llm.key';
// default model google/gemini-2.5-flash-lite; API base default https://openrouter.ai/api/v1
```

The digest cron uses the same default paths (`--llm-dir`, `--llm-keyfile`), timeout 30 s, 1 retry. Egress to
`openrouter.ai:443` from the container («Prova») and the host. Never print or copy `llm.key`; rotating it
invalidates every saved key. Rule: a failed summary never blocks the digest. Not related to Laya.

---

## 6. Weekly retraining (SPEC-LAYA «Lunedì notte»)

On **the mail server** (Decision 1: the Monday incremental training; the first training was on the training PC, §3.1),
`laya-monday.sh` (TRAINING-LAYA §10): per user, `laya-export.py` → `laya-embed.py` (CPU,
`--device cpu`) → `laya-train.py` → install only on exit 0 (new validation error not worse than the head in
use). On top of the guide (Decision), the install step is `laya-check-head.py --install` instead of
`laya-install.sh`: checks 1–11, then the atomic install with `.prev` and the copy into `heads-archive`.
**To do (implementer):** change that one line in `laya-monday.sh`. `laya-serve` picks up the new head through the mtime. Log: `/var/log/laya/monday.log`
(logrotate weekly).

---

## 7. Users and modes (`/etc/laya/users.conf`)

| Mode | Headers written | Effect |
|---|---|---|
| `off` (or not listed) | none | not classified (laya-serve answers `off` without encoding); mail stays in INBOX; plugin unchanged |
| `active` | `X-Laya-Box` / `X-Laya-Box-Conf` | the user's managed Sieve script sorts **from the first delivery** (0.80; Spam 0.40 / Cestino 0.80; user filters win) |

There is **no shadow mode** (decision 5): no `shadow` value, no global switch, no `X-Laya-Shadow-*` headers.
`users.conf` is the per-user activation (consent). Local mail (§1.5) is never classified.

A user can only be `active` if: they saved Impostazioni › Smistamento (the managed script exists); their head
passed §3.2; they agreed (Laya reads their mail). Per SPEC-SMISTAMENTO the head is per user, and nothing
crosses users.

---

## 8. Rollout

| Phase | What | Exit condition |
|---|---|---|
| 0 | Plugin, Dovecot after-script, ManageSieve, classes + digest cron, OpenRouter storage (§5). No Laya. Users save their settings. Laya pipeline rehearsed on the test domains only (fallback, forged headers, latency) | QA.md scenarios pass on the mail server's test domain with stub-labelled test mails; QA §9 A1–A8 on the test domain |
| 1 | **After the MX cutover to the mail server.** Encoder, venv, `laya-serve`, `laya-filter`, `laya.sieve`; heads installed (§3); **every user with a head who agreed is `active` from day one** (decision 5). Recommend «Sposta nel Cestino», not «Elimina», for the first weeks | QA §9 A and B on real mail; latency measured (§2.4); no complaints for a week; the owner confirms or changes the thresholds after the first weeks |
| 2 | Embedding cache copied from the training PC and checked (§3.5), **before** the first run; then the 03:30 cron for `laya-monday.sh`; delivery archive (§2.5) | §3.5 check prints `OK` for every user; first Monday: `laya-embed.py` logs only the new mails as «nuovi embedding» (not the whole history), log clean, `report.json` per user, plugin date updated or «resta la vecchia» logged |

Before the MX cutover, the mail server only receives the test domains (the mail-server spec): real mail, and with it
real sorting, starts with the cutover. There is **no copy** of incoming mail (no BCC, no parallel feed, no
`always_bcc`). Users without a head or without consent stay `off` until they have both.

---

## 9. Acceptance checklist (QA)

Delivery and fallback (A):

- [ ] A1 `systemctl stop laya-serve` → new mail delivered **at once** (no wait), **no** `X-Laya-*` headers, in INBOX; Dovecot log has `laya-filter: user=… fallback … (FileNotFoundError|ConnectionRefusedError)`; restart → headers again
- [ ] A1b laya-serve hanging (`systemctl kill -s STOP laya-serve`, then `-s CONT`) → delivered after ~5 s, no headers, INBOX, log `TimeoutError`; never 10 s (§1.3)
- [ ] A2 incoming mail **with** forged `X-Laya-Box: Junk` + `X-Laya-Box-Conf: 0.99` (and any other `X-Laya-Whatever`, also folded or lower-case): stored without them; with Laya up it gets the real label only; with Laya down it stays in INBOX; with «Elimina definitivamente» it is **not** discarded
- [ ] A3 `X-Spam-Flag: YES` / `X-Malware-Bazaar: hit` → no Laya headers (forged ones stripped too), laya-serve not asked, never sorted
- [ ] A4 user with no head (or the 0-byte placeholder) → no headers; plugin «Smistamento di base…»
- [ ] A5 one mail to two local users → each gets the label of **their** head (or none)
- [ ] A6 user `off` (not in `users.conf`) with a head: no header, INBOX, laya-serve answers `off`
- [ ] A7 local mail (§1.5): a local user sends from Roundcube/587 to another local user → no header, INBOX, syslog `local mail from …: not classified`, laya-serve not asked. A mail from outside with a local `MAIL FROM`/`From:` → classified as usual
- [ ] A8 `laya-filter` broken (e.g. `chmod -x`) → mail still delivered to INBOX, forged `X-Laya-Box`/`-Conf` still removed (Sieve `deleteheader`); Dovecot log `Terminated with non-zero exit code` or `failed to execute`

Active user (B):

- [ ] B1 `X-Laya-Box-Conf` always matches `^(0\.[0-9]{2}|1\.00)$`
- [ ] B2 `X-Laya-Box` is always one of that user's head `labels`
- [ ] B3 active-folder label ≥ 0.80 → that folder (+ «Segna come lette» if set); < 0.80 → INBOX
- [ ] B4 `Imbox` at any conf → INBOX, never in a digest
- [ ] B5 `Junk`: < 0.40 → INBOX; 0.40–0.79 → Spam; ≥ 0.80 → Cestino (or gone with «Elimina»); switch off → INBOX
- [ ] B6 a personal filter beats Smistamento (e.g. «condominio» → Progetti)
- [ ] B7 label of an inactive or renamed folder → INBOX
- [ ] B8 «Smistata in X · Cambia» shows on sorted mail; moving it removes the line

Files and ops (C):

- [ ] C1 `laya-check-head.py` OK for every installed user; `labels` = today's `classes` file; a broken head (wrong label order, NaN, wrong encoder, report exit 2, 0 bytes) → `FAIL`, exit 1, head in use untouched
- [ ] C2 install → plugin shows «Smistamento aggiornato <today>» without restarting anything; `laya-serve` uses the new head (log)
- [ ] C3 `laya-rollback.sh` → old head back, plugin shows the old date, `laya-serve` reloads
- [ ] C4 permissions as in §3.3; `/run/laya/laya.sock` 0660 laya:vmail; 4190 not public
- [ ] C5 03:00 classes files fresh on Monday; 03:30 log has one line per user (phase 2)
- [ ] C6 digest: summary off by default; with a valid key «In breve» appears; with an invalid key or the mock down, the digest arrives without summary and the log has no key and no mail text

---

## 10. Rollback

| Level | Command | Effect |
|---|---|---|
| One user's head | `sudo /opt/laya/training/laya-rollback.sh <address> /laya/heads` | previous head (`.prev`) back with its mtime; older ones in `heads-archive` |
| One user's sorting | set `off` in `/etc/laya/users.conf` | no more moves for them; already-moved mail stays where it is (SPEC-SMISTAMENTO rule 7) |
| Laya globally | `systemctl stop laya-serve` | every mail delivered without headers → INBOX (fallback §1.3) |
| Remove Laya from delivery | remove the `sieve_script laya` block, `doveadm reload` | Sieve as before Laya; the forged-header stripping goes too (only safe if the after-script is also off, or nobody uses «Elimina») |
| Plugin | disable in Roundcube config; remove the `smistamento` after-script block | no sorting, no settings page; mail untouched |

---

## 11. Discrepancies to watch (trained files ↔ code)

1. **Labels vs folder names**: the head must carry the `label` (`PaperTrail`), not the folder (`Paper Trail`). The plugin matches the `accepts` list case-insensitively, so `paper trail` works only through the auto mapping.
2. **Spam label vs Spam folder**: the label is `Junk` (`smistamento_spam_labels`); the folder in `classes.mailbox` may be called «Spam». If `smistamento_spam_labels` is changed, every head with `Junk` is stale.
3. **Inbox label**: `Imbox` is configurable (`smistamento_inbox_labels`); the head must use the first value, as the classes file does.
4. **Conf format**: two decimals, dot, compared as strings (`i;octet`). `.93` and `0,93` sort *below* `"0.80"` and never pass; `0.9` or `1` pass only by luck. Always `"%.2f"`, `0.00`–`1.00`.
5. **Usernames**: `%u` / `USER` is the full address on the mail server but may be a short name in a test setup. The head file name must follow the environment.
6. **Classes drift**: a head trained on an older `classes` (renamed or switched-off folder, spam switch changed) still loads, but those labels never move mail. Check 3 catches it.
7. **Placeholder heads**: a 0-byte `/laya/heads/<user>.joblib` (e.g. in a test setup, only for the date line) is not a head.
8. **«Submission 465/587 non ci passano»** (SPEC-LAYA): resolved by Decision 3. Mail between local users is **not** classified; laya-filter recognises it as in §1.5. Mail to external recipients never reaches LMTP anyway. Watch out: if Postfix on the mail server is configured so that the entry `Received` line no longer says `ESMTPSA`/`ESMTPA` (e.g. a submission proxy in front), local mail gets classified. Harmless, but against the decision: adjust `mta_hosts`/markers.
9. **SPEC-LAYA chain** says «Dovecot scrive la Maildir in INBOX, Laya legge, scrive gli header, Sieve sposta». Here Laya acts during LMTP, before the write. Same effect, one write.

---

## 12. Open points

Status after version 2 (5 Oct 2026):

1. ~~**Where training runs**~~ **Decided** (§0.1): first training on the training PC, Monday incremental training on the mail server.
2. **Encoder**: approved (§0.2). **Owner:** fill in model, revision and fingerprint in §3.4 before phase 1.
3. ~~**Laya inference code doesn't exist**~~ **Written** (`laya/`, §2.7) and tested on the test environment with the fake encoder.
   Still untested: the real encoder in laya-serve (`RealEncoder`), and the systemd unit on a real host.
4. **Mail server capacity**: the VPS RAM/CPU vs the encoder resident in memory plus Roundcube; latency under load. Unmeasured.
5. ~~**Before cutover**~~ **Decided** (§0.5): no shadow phase; Laya goes active on real mail after the MX cutover, no copy of incoming mail.
6. ~~**Local-to-local submission**~~ **Decided** (§0.3): not classified; definition and detection in §1.5.
7. ~~**Pigeonhole behaviour**~~ **Verified** on 2.4.2 (§1.4). New finding: Dovecot's own filter timeout panics LMTP, hence laya-filter's 5 s / 8 s limits.
8. **Thresholds**: 0.80 / 0.40 / 0.80 are the plugin defaults. The owner watches the first weeks of active sorting (logs, «Smistata in», the digest) and adjusts; a calibration other than the head's single temperature is not planned.
9. **Delivery archive**: format decided and implemented (§2.5, one jsonl line with the float16 embedding). The reader in `laya-embed.py` is still to write.
10. **Consent and privacy** for the other mailboxes (Laya reads content; training material in someone's home). SPEC-SMISTAMENTO §7 «Privacy» is still open.
11. ~~**Embedding cache for the first Monday run**~~ **Decided** (§0.6): the owner copies the training PC's cache to the mail server once; step and check in §3.5.
