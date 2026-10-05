# smistamento: plugin per Roundcube / Roundcube plugin

Impostazioni per lo smistamento automatico fatto dal server di posta, per la skin *Il Dispaccio*
(funziona anche con Elastic). Roundcube **1.7.x**, provato su 1.7.4 con Dovecot 2.4.2 + Pigeonhole.
Licenza **GPL-3.0-or-later**. [English below](#english).

> **Installazione con un agente (es. Grok Build):** usa [`INSTALL-AGENT.md`](INSTALL-AGENT.md), istruzioni passo passo
> pronte da incollare come prompt. Specifiche: [`docs/`](docs/).

## Italiano

### Cosa fa e cosa non fa
Il plugin **non classifica e non addestra niente**. La classificazione la fa un servizio sul server
(Laya), che scrive su ogni mail consegnata:

```
X-Laya-Box: <etichetta>        X-Laya-Box-Conf: 0.00–1.00
```

Il plugin trasforma le scelte dell'utente in uno **script Sieve gestito** (`smistamento`), caricato via
ManageSieve. Dovecot lo esegue **dopo** i filtri dell'utente. Lo script fa `fileinto` nella cartella e `stop`.

- **Impostazioni → Smistamento**: una riga per ogni cartella dell'utente. Posta in arrivo, Bozze,
  Inviata, Spam/Junk e Cestino non compaiono mai. Per ogni cartella ci sono:
  - **Attiva**. Se è spenta, Sieve non smista in quella cartella e la mail resta in Posta in arrivo
    (tooltip «Spenta: queste mail restano in Posta in arrivo»).
  - **Segna come lette** (`fileinto :flags "\\Seen"`).
  - **Digest** (Spento · Giorno · Settimana · Mese).

  Sotto la tabella c'è il blocco globale «Quando arriva il digest».
- **Mail delle persone** (la classe «persone» di Laya, etichetta `Imbox`, configurabile con
  `smistamento_inbox_labels`): restano in Posta in arrivo, da leggere, e non vanno mai nel digest. Non
  c'è una cartella apposta e non c'è niente da attivare: lo script Sieve fa `stop` su queste etichette
  prima di ogni altra regola, a qualsiasi confidenza. Una cartella chiamata «Imbox» è una cartella come
  le altre e non riceve mai queste etichette.
- **Spam** (la classe spam di Laya, etichetta `Junk`, configurabile con `smistamento_spam_labels`):
  sotto il blocco «Quando arriva il digest» c'è l'interruttore «Lo smistamento gestisce lo spam», acceso di default. Se è acceso
  compare la riga fissa della cartella Spam speciale, senza «Segna come lette» né «Digest», con:
  - **Soglia Spam** (default 0,40) e **Soglia Cestino** (default 0,80), da 0,10 a 0,95 a passi di
    0,05; la soglia Spam deve essere più bassa della soglia Cestino, altrimenti il salvataggio si ferma
    con «La soglia Spam deve essere più bassa della soglia Cestino.». La soglia generale
    `smistamento_min_conf` qui non vale;
  - **Dalla soglia Cestino in su**: «Sposta nel Cestino» (default) o «Elimina definitivamente: la mail
    viene cancellata subito e non si può recuperare.» (Sieve `discard`).

  Confidenza sotto la soglia Spam → resta in Posta in arrivo; dalla soglia Spam fino a sotto la soglia
  Cestino → cartella Spam (l'utente la controlla, e Laya ci si allena); dalla soglia Cestino in su →
  l'azione scelta; senza confidenza → cartella Spam. Se l'interruttore è spento la riga è nascosta, lo
  script non ha nessuna regola spam e la mail resta in Posta in arrivo; soglie e azione restano salvate.
  Default in `smistamento_spam_default`. Le impostazioni salvate con una sola soglia (versioni
  precedenti) si leggono così: la vecchia soglia diventa la soglia Spam, la soglia Cestino è 0,80 (o
  la vecchia soglia, se è più alta; in quel caso la soglia Spam scende di 0,05).
- Una riga di aiuto: «Posta in arrivo: le mail delle persone e quelle di cui lo smistamento non è
  sicuro (o tutte, se è fermo).»
- «Smistamento aggiornato sabato 3 ottobre» viene dalla data di modifica del file della testa
  dell'utente (`smistamento_head_file`, di solito `/laya/heads/%u.json`: il `.json` della coppia
  `.json` + `.npz` di Laya, che l'installazione scrive per ultimo). Se il file manca, la riga dice «Smistamento di base: si
  personalizza quando ci sono abbastanza mail». Se il percorso non è configurato, la riga non c'è.
- **Lista cartelle**: il segno ↻ appare dopo le cartelle attive. Nel menu ⋮ di «Sezioni», la voce
  «Smistamento di questa cartella…» compare solo sulle cartelle attive e apre la riga evidenziata.
- **Lettura**: «↻ Smistata in **Feed** · Cambia». Compare se la mail ha `X-Laya-Box` con confidenza
  sopra la soglia e si trova nella cartella a cui punta l'etichetta. «Cambia» apre un menu «Sposta in»
  con Posta in arrivo e le altre cartelle attive. Spostare è la correzione: Laya la impara dalla
  posizione della mail, senza nessun messaggio.
- **Digest**: un'icona giornale nella lista. Il digest lo genera `server/smistamento-server.py` sul
  server (vedi sotto), non Roundcube.

### Regole
1. Sono attivabili solo le cartelle dell'utente. Posta in arrivo, Bozze, Inviata, Spam/Junk e Cestino
   non lo sono mai (SPECIAL-USE, cartelle speciali di Roundcube e nomi comuni).
2. Senza header, con confidenza mancante o sotto `smistamento_min_conf`, o con un'etichetta di una
   cartella spenta o inesistente, la mail resta in Posta in arrivo.
3. Una mail con `X-Spam-Flag: YES` o `X-Malware-Bazaar: hit` non viene mai smistata da Smistamento,
   nemmeno dalla riga Spam: lo spam segnato dal server lo gestisce il server (il flag è un sì/no senza
   confidenza, e Cestino o eliminazione renderebbero irrecuperabili i suoi falsi positivi).
4. **Vincono i filtri dell'utente.** Pigeonhole esegue lo script `after` solo se lo script personale ha
   lasciato la mail in INBOX (keep implicito). Se un filtro fa `fileinto`, Smistamento non tocca la mail
   (provato in un ambiente di prova con Dovecot 2.4.2).
5. Il digest elenca solo le mail che Smistamento ha messo nella cartella (etichetta corrispondente) e
   che sono ancora lì. Le mail spostate in Spam o nel Cestino spariscono dal digest da sole. Posta
   in arrivo (quindi le mail delle persone), Spam e Cestino non compaiono mai. Un periodo senza mail non produce nessun digest. Le cartelle con la
   stessa periodicità finiscono in una sola mail.
6. Spegnere una cartella non sposta indietro niente.

### Tutto è per utente
- Le scelte stanno nelle preferenze Roundcube dell'utente e nel **suo** script Sieve
  (`~/sieve/smistamento.sieve` nella home Dovecot dell'utente). La seconda riga dello script contiene
  le impostazioni in JSON (`# smistamento-settings: {...}`): cartelle, etichette accettate, digest,
  ora, lingua, fuso orario.
- `smistamento-server.py classes` scrive un file per utente (`<indirizzo completo>.json`) con le classi
  di quell'utente: è l'input per l'addestramento di Laya, che gira ogni lunedì notte sul server di posta ed è
  lato Laya, fuori da qui. La prima
  classe è sempre Posta in arrivo, fissa, anche senza cartelle attive:
  `{"mailbox": "INBOX", "path": "INBOX", "role": "inbox", "label": "Imbox", "accepts": ["Imbox"]}`.
  Se l'utente lascia acceso «Lo smistamento gestisce lo spam», segue la classe spam:
  `{"mailbox": "Junk", "path": "Junk", "role": "spam", "label": "Junk", "accepts": ["Junk"]}` (la
  cartella Spam speciale dell'utente). Con l'interruttore spento non c'è.
  Seguono le cartelle attive con `"role": "folder"`. Così Laya ha sempre la classe «resta in Posta in
  arrivo»: una mail che l'utente riporta in Posta in arrivo vale come etichetta `Imbox`.
  La testa di Laya è per utente (`768 → N`) e le sue uscite sono queste classi, in quest'ordine:
  `X-Laya-Box` porta il `label` di una di esse. Training settimanale: vedi [`docs/SPEC-LAYA.md`](docs/SPEC-LAYA.md).
- Il file della testa ha un percorso per utente (`%u` = indirizzo completo). Anche lo stato del digest
  è un file per utente.
- Provato con due utenti: ognuno vede solo le sue cartelle. Un'etichetta `Feed` che è una classe del
  primo utente, per il secondo (che non ha Feed attiva) non vuol dire niente e la mail resta nella sua
  Posta in arrivo.

### Etichetta → cartella (un solo adattatore)
`lib/smistamento_labels.php` decide quali valori di `X-Laya-Box` corrispondono a una cartella. Lo usano
sia lo script Sieve sia la riga «Smistata in»:
1. `smistamento_label_map`: etichetta ⇒ cartella, esplicito (es. `'PaperTrail' => 'Paper Trail'`).
2. `smistamento_label_auto` (default sì): percorso completo («Progetti/2026»), nome della foglia se è
   unico («2026»), e le due forme senza spazi («PaperTrail»).

Il confronto non distingue maiuscole e minuscole. Laya dovrebbe scrivere il campo `label` del file
`classes` di quell'utente.

### Installazione (Roundcube)
1. Copiare `smistamento/` in `plugins/`, così da avere `plugins/smistamento/smistamento.php`.
2. Opzionale: `config.inc.php.dist` → `config.inc.php`. Le chiavi si possono mettere anche nella
   configurazione principale.
3. Abilitare il plugin: `$config['plugins'][] = 'smistamento';`
4. Con il plugin managesieve («Filtri»), nascondere lo script gestito:
   `$config['managesieve_filename_exceptions'] = ['smistamento'];`
5. Non servono tabelle SQL.

Configurazione di esempio (Roundcube in un container rootless, Dovecot sull'host).
`<container-host-ip>` è l'indirizzo con cui il container raggiunge il loopback dell'host (con
slirp4netns e `allow_host_loopback=true` di solito è `10.0.2.2`):
```php
$config['smistamento_managesieve_host'] = '<container-host-ip>'; // come l'IMAP del container
$config['smistamento_managesieve_port'] = 4190;
$config['smistamento_managesieve_usetls'] = true;
$config['smistamento_managesieve_conn_options'] = ['ssl' => ['verify_peer' => false, 'verify_peer_name' => false]]; // finché il cert è snakeoil
$config['smistamento_head_file'] = '/laya/heads/%u.json';   // + volume read-only in compose.yaml
$config['smistamento_llm_dir'] = '/var/lib/smistamento/llm';   // «Riassunto con AI»: volume rw, stesso percorso
$config['smistamento_llm_keyfile'] = '/etc/smistamento/llm.key'; // volume read-only (vedi «Riassunto con AI»)

// «Filtri» (plugin managesieve di Roundcube 1.7): porta e TLS stanno DENTRO managesieve_host.
// managesieve_port e managesieve_usetls non esistono più e vengono ignorati: con quelle chiavi il
// plugin va sulla 4190 senza TLS, non si connette e «Filtri» mostra una lista vuota.
$config['plugins'][] = 'managesieve';
$config['managesieve_host'] = 'tls://<container-host-ip>:4190'; // tls:// = STARTTLS; ssl:// = TLS implicito
$config['managesieve_conn_options'] = ['ssl' => ['verify_peer' => false, 'verify_peer_name' => false]]; // finché il cert è snakeoil
$config['managesieve_filename_exceptions'] = ['smistamento']; // nome esatto dello script, senza .sieve
```

Se «Filtri» mostra «Questa lista è vuota» con un solo «>» nella colonna dei set, il plugin managesieve non
si è connesso: nel log errori di Roundcube c'è «Unable to connect to managesieve on host:4190». Lo script
`smistamento` nascosto non c'entra: la lista dei set mostra gli altri script (di solito `roundcube`, attivo).

### Server (Dovecot 2.4 + Pigeonhole)
```
protocols = imap lmtp sieve

service managesieve-login {
  inet_listener sieve {
    address = 127.0.0.1      # solo loopback: il container lo raggiunge come <container-host-ip>
    port = 4190
  }
}

protocol lmtp {
  mail_plugins {
    sieve = yes
  }
}

sieve_script personal {          # filtri dell'utente (Roundcube «Filtri»), eseguiti per primi
  driver = file
  path = ~/sieve
  active_path = ~/.dovecot.sieve
}

sieve_script smistamento {       # lo script gestito, nella stessa cartella, eseguito DOPO
  type = after
  driver = file
  path = ~/sieve/smistamento.sieve
}
```
- Il blocco `sieve_script before` per MalwareBazaar (→ Junk) resta com'è e gira prima di tutto.
- La porta 4190 non va aperta al pubblico.
- Laya deve scrivere gli header **prima** di Sieve: consegna LMTP dopo il passaggio di Laya, oppure
  Laya come filtro prima di LMTP. Questa parte di integrazione è di Laya.
- Cron (root, sull'host):
  ```
  */15 * * * *  root  /usr/local/sbin/smistamento-server.py digest --all-users --base-url https://webmail.example.org/
  0 3 * * 1     root  /usr/local/sbin/smistamento-server.py classes --all-users --out-dir /var/lib/smistamento/classes
  ```
  Copiare `server/smistamento-server.py` e `server/texts.json` nella stessa cartella. Serve Python 3.8+,
  solo libreria standard. Usa `doveadm` da root, quindi niente password utente e niente login IMAP.
  `--all-users` richiede uno userdb iterabile (passwd-file va bene).
- Il digest si salva con `doveadm save` in INBOX e non passa da Sieve, quindi non viene mai smistato.
  Ha l'header `X-Dispaccio-Digest: day|week|month`.

### Riassunto con AI («In breve» nel digest, facoltativo)
Ogni utente può accendere, in Impostazioni › Smistamento › «Quando arriva il digest» › «Riassunto», un
riassunto scritto da un modello via **OpenRouter** in cima al digest («In breve»). Spento di default.
Campi: interruttore «Riassunto con AI», «Chiave API OpenRouter» (non si rivede dopo il salvataggio:
«salvata · ••••1234», Sostituisci / Rimuovi, «Prova»), «Modello» (default `google/gemini-2.5-flash-lite`),
«Prompt» (con `{mail}` e `{periodo}`, «Ripristina predefinito»). Con il riassunto attivo il testo delle
mail del digest va a OpenRouter e al modello scelto: mittente, oggetto, data, cartella e al massimo 1.500
caratteri di testo per mail (HTML tolto, citazioni e firme tagliate, niente allegati).

**Dove stanno le impostazioni.** Il digest lo fa `smistamento-server.py` sull'host (root, `doveadm`), il
plugin gira nel container di Roundcube: le preferenze di Roundcube e la sua `des_key` lo script non le
vede. Quindi:
- un file per utente, `<smistamento_llm_dir>/<utente>.json` (permessi 0600, scritto in modo atomico dal
  plugin), in una directory dell'host montata nel container **allo stesso percorso**; dentro: acceso/spento,
  modello, prompt (null = predefinito), chiave **cifrata**, ultime 4 cifre;
- la chiave API è cifrata con un **file-chiave condiviso** (`/etc/smistamento/llm.key`, almeno 32
  caratteri casuali), letto dal plugin (montato in sola lettura) e dallo script (root). Cifratura solo con
  la libreria standard da entrambe le parti: flusso HMAC-SHA256 + HMAC (encrypt-then-MAC), legata
  all'utente, quindi il valore di un utente non si apre sul file di un altro;
- la chiave non finisce mai nello script Sieve, nella riga JSON delle impostazioni, nelle preferenze, nella
  pagina (il campo non viene mai riempito), nei log o nei messaggi d'errore.

Sull'host (Docker rootless: l'uid/gid di `www-data` del container corrisponde sull'host a un subuid; si
trova con `docker exec <container> id www-data` e `/etc/subuid`, oppure creando un file dal container e
guardando `stat` sull'host):
```
install -d -m 0700 -o <uid host di www-data> -g <gid host di www-data> /var/lib/smistamento/llm
install -d -m 0750 -o root -g <gid host di www-data> /etc/smistamento
openssl rand -base64 48 > /etc/smistamento/llm.key
chown root:<gid host di www-data> /etc/smistamento/llm.key && chmod 0640 /etc/smistamento/llm.key
```
In `compose.yaml` del container Roundcube:
```yaml
    volumes:
      - /var/lib/smistamento/llm:/var/lib/smistamento/llm
      - /etc/smistamento/llm.key:/etc/smistamento/llm.key:ro
```
e in Roundcube `smistamento_llm_dir` / `smistamento_llm_keyfile` (vedi `config.inc.php.dist`). Lo script
usa gli stessi percorsi di default (`--llm-dir`, `--llm-keyfile`). Senza file-chiave valido il blocco dice
«Il riassunto con AI non è configurato su questo server.» Cambiare il file-chiave rende illeggibili le
chiavi salvate: gli utenti le devono rimettere. Il container deve poter uscire verso `openrouter.ai:443`
(per «Prova»), come l'host (per il digest).

**Generazione.** Un digest = una chiamata (anche se unisce più cartelle), mai senza digest, mai con
`--dry-run`. Timeout 30 s (`--llm-timeout`), 1 nuovo tentativo (`--llm-retries`) solo su timeout, rete,
429 e 5xx. Qualsiasi errore → il digest parte senza «In breve» e su stderr c'è una riga
`warning: <utente> <periodo>: summary skipped: invalid key (HTTP 401) (…); digest sent without it`, senza
chiave né testo delle mail. Se va bene: `<utente> week: summary by <modello> from N mail(s): X in + Y out
tokens, cost $Z`. Anche una risposta malformata, una connessione chiusa a metà o un errore imprevisto
nel passo del riassunto lasciano partire il digest (nel log solo la classe dell'errore). Con
`--all-users` l'errore di un utente non ferma gli altri: riga `error: <utente>: digest run failed (…)`,
uscita 1 alla fine; un digest che non si riesce a salvare non viene segnato come inviato e si riprova al
giro dopo; se il riassunto era già pronto, nel log c'è «summary ready, digest not saved» e il testo resta in
`<state-dir>/<utente>.summary.json` (0600, senza chiave), così il nuovo tentativo lo riusa senza
richiamare il modello (il file sparisce dopo il salvataggio). Con `--to-date` un digest non salvato non
salta gli altri digest dello stesso utente. URL dell'API: `--llm-base` / `smistamento_openrouter_base`, altrimenti la variabile
d'ambiente `SMISTAMENTO_OPENROUTER_BASE`, altrimenti `https://openrouter.ai/api/v1` (per le prove si punta
a un mock).

**Modello di default: `google/gemini-2.5-flash-lite`.** Il riassunto è quasi tutto input (fino a 40 mail ×
1.500 caratteri, ~15–20k token, ~300 in uscita): $0,10/M in + $0,40/M out ≈ $0,002 per digest, contro
$0,15/$0,15 di `mistralai/ministral-8b-2512` ≈ $0,003; contesto 1M contro 262K; nel bench sulle fatture è
stato il più preciso e il più economico (~$0,0016 a chiamata); buon italiano.

---

## English

### What it does (and does not)
The plugin does **no classification and no training**. A server-side service (Laya) stamps delivered
mail with `X-Laya-Box: <label>` and `X-Laya-Box-Conf: 0.00–1.00`. The plugin turns the user's choices
into a **managed Sieve script** (`smistamento`), uploaded over ManageSieve and run by Dovecot **after**
the user's own filters. Each rule does `fileinto` and `stop`.

- **Settings → Sorting**: one row per user folder. Inbox, Drafts, Sent, Junk/Spam and Trash are never
  listed. Each row has **Active** (off = mail stays in the Inbox), **Mark as read** (`:flags "\\Seen"`)
  and **Digest** (Off/Day/Week/Month). A global digest time block sits below the table.
- **Mail from people** (Laya's «persone» class, label `Imbox`, configurable via
  `smistamento_inbox_labels`) stays in the Inbox, unread, and is never in a digest. There is no people
  folder and no switch: the Sieve script `stop`s on these labels before any other rule, at any
  confidence. A folder named «Imbox» is an ordinary folder and never receives these labels.
- **Spam** (Laya's spam class, label `Junk`, configurable via `smistamento_spam_labels`): below the
  digest time block, a «Sorting handles spam» switch, on by default. When on, a fixed row for the special Junk
  folder (no Mark as read, no Digest) offers two thresholds, **Spam threshold** (default 0.40) and
  **Trash threshold** (default 0.80), 0.10–0.95 in steps of 0.05, the Spam one lower than the Trash one
  (otherwise saving stops with «The Spam threshold must be lower than the Trash threshold.»; the general
  `smistamento_min_conf` does not apply), and an action **at or above the Trash threshold**: «Move to
  Trash» (default) or «Delete permanently» (Sieve `discard`). Below the Spam threshold the mail stays in
  the Inbox; from the Spam threshold to below the Trash threshold it goes to Junk (the user can check it,
  and Laya trains on it); without a confidence it goes to Junk. When the switch is off the row is hidden,
  the script has no spam rule, the mail stays in the Inbox, and the saved thresholds and action are kept.
  Defaults: `smistamento_spam_default`. Settings saved with a single threshold (older versions) are read
  as: old threshold = Spam threshold, Trash threshold 0.80 (or the old value if higher; then the Spam
  threshold goes 0.05 lower).
  Server-flagged spam (`X-Spam-Flag`, malware) never goes through this row.
- One help line about the Inbox, and a «Sorting updated <day>» line taken from the mtime of the user's
  head file (or «basic sorting» if there is no file; no line if no path is configured).
- ↻ after active folders. The folder-menu entry appears on active folders only.
- In sorted mails: «↻ Sorted into **Feed** · Change». «Change» opens a move menu with the Inbox and the
  other active folders. Moving the mail is the silent correction.
- A newspaper icon marks digest mails. Digests are built server-side by `server/smistamento-server.py`.

### Rules
- Never sorted: no header, missing confidence or confidence below `smistamento_min_conf`, a label whose
  folder is inactive or unknown, `X-Spam-Flag: YES`, `X-Malware-Bazaar: hit`.
- The user's filters win: Pigeonhole only runs the `after` script while the implicit keep is still in
  effect (tested).
- Digests list only mail that Smistamento sorted into that folder and that is still there. They never
  list the Inbox (so never mail from people), Junk or Trash. No mail means no digest. Folders with the same frequency share one mail.

### Strictly per user
The settings live in the user's prefs and in the user's own Sieve script, with a JSON line that also
carries the accepted labels, digest settings, language and timezone. The `classes` export writes one
file per user (keyed by full address) for Laya's weekly training, which runs on the mail server on Monday night (Laya side). Its first class is always the
fixed Inbox class (`"mailbox": "INBOX", "role": "inbox", "label": "Imbox"`), then, while the user lets
Smistamento handle spam, the spam class (`"mailbox": "Junk", "role": "spam", "label": "Junk"`), then the active folders
(`"role": "folder"`), so Laya always learns «keep in the Inbox». Laya's head is per user (`768 → N`), its outputs are exactly these classes in this order, and
`X-Laya-Box` carries one of their `label`s. The head file and the digest
state are per user too. Tested with two users.

### Label → folder adapter
`lib/smistamento_labels.php` is the single place that maps labels to folders. It reads
`smistamento_label_map` (explicit) and `smistamento_label_auto` (full path, unique leaf, both without
spaces), compares case-insensitively, and is used for both the Sieve script and the «Sorted into» line.

### AI summary («In breve» at the top of the digest, optional)
Per user, off by default: Settings › Sorting › «When the digest arrives» › «Summary». Fields: «AI summary»
switch, «OpenRouter API key» (never shown again after saving: «saved · ••••1234», Replace / Remove, «Test»),
«Model» (default `google/gemini-2.5-flash-lite`), «Prompt» (placeholders `{mail}` and `{periodo}`,
«Restore default»). With the summary on, the digest's mails go to OpenRouter and the chosen model: sender,
subject, date, folder and at most 1,500 characters of cleaned text per mail (HTML stripped, quotes and
signatures trimmed, no attachments).

**Storage.** The digest is built by `smistamento-server.py` on the host (root, `doveadm`), the plugin runs in
the Roundcube container, so Roundcube prefs and `des_key` are out of the script's reach. Instead:
- one file per user, `<smistamento_llm_dir>/<user>.json` (mode 0600, written atomically by the plugin), in a
  host directory mounted into the container **at the same path**: on/off, model, prompt (null = default),
  the **encrypted** key and its last 4 characters;
- the API key is encrypted with a **shared key file** (`/etc/smistamento/llm.key`, at least 32 random
  characters), read by the plugin (mounted read-only, 0640 root:<www-data group>) and by the script (root).
  Standard library only on both sides: HMAC-SHA256 keystream + HMAC tag (encrypt-then-MAC), bound to the
  user;
- the key never goes into the Sieve script, the settings JSON line, the prefs, the page, the logs or error
  messages.

Host setup, compose volumes and the Roundcube keys: see the Italian section above and `config.inc.php.dist`
(`smistamento_llm_dir`, `smistamento_llm_keyfile`, `smistamento_openrouter_base`,
`smistamento_llm_default_model`, `smistamento_llm_test_timeout`). Script options: `--llm-dir`, `--llm-keyfile`,
`--llm-base` (else `$SMISTAMENTO_OPENROUTER_BASE`, else `https://openrouter.ai/api/v1`), `--llm-timeout 30`,
`--llm-retries 1`, `--llm-max-mails 40`.

**Generation.** One call per digest (merged folders included), never without a digest, never with
`--dry-run`. 30 s timeout, 1 retry on timeout, network errors, 429 and 5xx. Any failure → the digest goes
out without «In breve» and stderr gets a `summary skipped: <reason>` line with no key and no mail text. This
includes malformed answers, connections closed mid-answer and any unexpected error in the summary step
(only the error class is logged). With `--all-users` one user's failure never stops the others (exit status 1
at the end); a digest that could not be saved is not marked as sent and is retried on the next run. If its
summary was ready, the log says «summary ready, digest not saved» and the text is kept in
`<state-dir>/<user>.summary.json` (0600, no key) so the retry reuses it without calling the model again. Token
usage and cost are logged per digest when OpenRouter returns them.

**Default model `google/gemini-2.5-flash-lite`:** the job is input-heavy (~15–20k tokens in, ~300 out):
≈ $0.002 per digest vs ≈ $0.003 for `mistralai/ministral-8b-2512`, 1M vs 262K context, the most accurate and
cheapest in our invoice bench, good Italian.

### Install / server setup
Step-by-step instructions for a coding agent (Italian): [`INSTALL-AGENT.md`](INSTALL-AGENT.md).
See the Italian section for the configuration blocks. In short:
1. Copy the plugin to `plugins/smistamento` and enable it.
2. Hide the script from managesieve with `$config['managesieve_filename_exceptions'] = ['smistamento'];`
   In Roundcube 1.7 the managesieve plugin takes port and TLS inside the host string, e.g.
   `$config['managesieve_host'] = 'tls://<container-host-ip>:4190';` (STARTTLS). `managesieve_port` and
   `managesieve_usetls` no longer exist and are ignored. With them, «Filters» connects to 4190 without TLS,
   fails, and shows an empty list with a lone «>» in the filter-set column.
3. Enable ManageSieve on Dovecot 2.4.
4. Add the `sieve_script smistamento { type = after; path = ~/sieve/smistamento.sieve }` block.
5. Run `smistamento-server.py digest` from cron every 15 minutes and `classes` weekly.

No SQL tables are needed.
