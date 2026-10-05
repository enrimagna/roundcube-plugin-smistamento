# Installare Smistamento: istruzioni per un agente

Questo file è un prompt completo. Copialo tutto e dallo all'agente (es. Grok Build) che lavora sul server.
Repository: https://github.com/enrimagna/roundcube-plugin-smistamento (release `v1.2.0`, file `smistamento.zip`).

---

## Prompt

Sei un agente che installa il plugin Roundcube **Smistamento** su un server di posta di produzione.
Lavora per passi, nell'ordine. Dopo ogni passo controlla il risultato prima di andare avanti. Se un
controllo fallisce, fermati e riferisci all'umano: non improvvisare correzioni su servizi di posta.

### Cosa installi

- Un plugin Roundcube che scrive, per ogni utente, uno script Sieve gestito (`smistamento`) via
  ManageSieve. Lo script sposta le mail in base agli header `X-Laya-Box` / `X-Laya-Box-Conf`.
- Un blocco Dovecot che esegue quello script **dopo** i filtri dell'utente (`type = after`).
- Uno script Python (`smistamento-server.py`) lanciato da cron: digest e export delle classi.
- La gestione dello spam di Laya (etichetta `Junk`): in Impostazioni › Smistamento ogni utente ha
  l'interruttore «Lo smistamento gestisce lo spam» (acceso di default) e due soglie: **Soglia Spam 0,40**
  e **Soglia Cestino 0,80**. Confidenza sotto 0,40 → resta in Posta in arrivo; da 0,40 a sotto 0,80 →
  cartella Spam (l'utente la controlla, e serve ad allenare lo smistamento); da 0,80 in su → Cestino (o
  eliminazione, se l'utente sceglie «Elimina definitivamente»); senza confidenza → Spam. Lo spam segnato
  dal server (`X-Spam-Flag: YES`, MalwareBazaar) non passa da qui: resta come oggi.
- Il **riassunto con AI** nel digest («In breve», via OpenRouter): **facoltativo e spento di default**.
  Ogni utente lo accende da sé in Impostazioni › Smistamento › «Quando arriva il digest» › «Riassunto»,
  con la **sua** chiave OpenRouter. Tu prepari solo il posto dove stanno le impostazioni: la cartella
  `/var/lib/smistamento/llm` (un file per utente, montata in lettura/scrittura nel container) e il
  file-chiave `/etc/smistamento/llm.key` (cifra le chiavi degli utenti, montato in sola lettura). Non
  accendere il riassunto per nessuno e non inserire chiavi OpenRouter.

**Fuori dal tuo compito:** il servizio Laya che scrive gli header `X-Laya-Box` sulle mail in arrivo.
Senza Laya il plugin funziona, ma nessuna mail viene spostata (resta tutto in Posta in arrivo). Non
installare, configurare o simulare Laya in produzione.
Anche il training settimanale di Laya (lunedì 03:30, sul server di posta) è lato Laya: tu installi solo
l'export `classes` delle 03:00 (passo 7).

### Il server

- Roundcube **1.7.x** in `/opt/roundcube`, in un **container rootless** (podman o docker rootless).
- Dovecot **2.4** + Pigeonhole **sull'host**, con utenti virtuali.
- Possibile script Sieve `before` già presente (es. MalwareBazaar → Junk): **resta com'è**.

### Segnaposto

Ricavali dal server (passo 1) e scrivili nel rapporto. Se uno non si ricava con certezza, chiedi all'umano.

| Segnaposto | Cosa è | Come ricavarlo |
|---|---|---|
| `<rc-config>` | file di configurazione Roundcube letto dal container (es. `/opt/roundcube/config/config.inc.php` o un file in `config/`) | compose file / mount del container |
| `<rc-container>` | nome del container Roundcube | `podman ps` / `docker ps` (utente rootless) |
| `<rc-plugins-in-container>` | cartella plugin dentro il container (immagine ufficiale: `/var/www/html/plugins`) | `exec ... ls` |
| `<container-host-ip>` | indirizzo con cui il container raggiunge Dovecot sull'host | **lo stesso host già usato da `$config['imap_host']`** (con slirp4netns spesso `10.0.2.2`) |
| `<webmail-url>` | URL pubblico della webmail, con `/` finale | config / reverse proxy |
| `<laya-heads-dir>` | cartella sull'host per i file delle teste di Laya, coppie `<indirizzo>.json` + `<indirizzo>.npz` (default `/laya/heads`) | chiedi all'umano se non esiste |
| `<test-user>` | casella di prova autorizzata dall'umano per il test di consegna | **chiedi all'umano** |
| `<www-data-uid>` / `<www-data-gid>` | uid/gid **sull'host** che corrispondono a `www-data` (33/33) del container | rootless: inizio del range in `/etc/subuid` / `/etc/subgid` dell'utente del container + 32 (es. `100000:65536` → `100032`); verifica al passo 4. Se il container usa un'altra mappatura (es. podman `--userns=keep-id`), chiedi |

### Regole di stop (valgono sempre)

1. **Mai aprire la porta 4190 al pubblico.** ManageSieve ascolta solo su `127.0.0.1`. Nessuna regola
   firewall, nessun port forward, nessun `0.0.0.0` / `*` / `::`.
2. **Mai cancellare mail degli utenti**, cartelle, o script Sieve esistenti (`roundcube`, script
   `before`, `.dovecot.sieve`, script personali). Non attivare/disattivare script degli utenti.
3. **Chiedi all'umano prima di riavviare Dovecot o Postfix** (o qualsiasi cosa che interrompa la
   consegna). `doveadm reload` / `systemctl reload dovecot` vanno bene; `restart` no, senza permesso.
4. Riavviare il container Roundcube interrompe solo la webmail per pochi secondi: avvisa l'umano e fallo
   una volta sola, quando serve (passo 4).
5. Prima di toccare un file di configurazione, fai il backup (passo 2). Se `doveconf -n` dà errore dopo
   una modifica, ripristina il backup e fermati.
6. Non mettere password, chiavi o token in file, log o nel rapporto. Il plugin usa le credenziali della
   sessione webmail dell'utente: non serve nessuna password nella config. Il contenuto di
   `/etc/smistamento/llm.key` non va mai stampato né copiato nel rapporto.
7. Il test di consegna (passo 9) solo sulla `<test-user>` indicata dall'umano.

### Passo 1: controlli iniziali (solo lettura)

```bash
# Dovecot e Pigeonhole
doveconf -n | head -n 5                      # versione 2.4.x
doveconf -n > /tmp/doveconf-before.txt       # stato attuale, per confronto
doveconf -n | grep -nE 'protocols|sieve|managesieve|lmtp' || true
ls /usr/lib/dovecot/modules /usr/lib64/dovecot/modules 2>/dev/null | grep -i sieve   # Pigeonhole presente
ss -ltnp | grep -E ':4190\b' || echo "4190 non in ascolto"

# userdb iterabile (serve a --all-users)
doveadm user '*' | head -n 3

# Python per lo script server
python3 --version                            # 3.8 o più

# Roundcube (come utente che possiede il container rootless)
ls -la /opt/roundcube
podman ps 2>/dev/null || docker ps
# trova compose file, mount della config e dei plugin:
ls /opt/roundcube; grep -nE 'volumes|config|plugins|/laya' /opt/roundcube/*compose*.y*ml 2>/dev/null
# versione Roundcube e plugin dentro il container
<runtime> exec <rc-container> sh -c 'grep -m1 RCMAIL_VERSION /var/www/html/program/include/iniset.php; ls <rc-plugins-in-container> | grep -E "managesieve|smistamento"'
# config attuale (cerca imap_host, plugins, managesieve_*)
grep -nE "imap_host|default_host|\['plugins'\]|managesieve_" <rc-config>
```

Annota: versione Dovecot, se `sieve` è già nei protocolli, se esistono già `sieve_script personal` e
script `before`, come il container raggiunge l'IMAP (`<container-host-ip>`), se il plugin `managesieve`
è già attivo. Se Dovecot non è 2.4 o Roundcube non è 1.7, fermati e chiedi.

### Passo 2: backup

```bash
TS=$(date +%Y%m%d-%H%M%S)
sudo mkdir -p /root/backup-smistamento-$TS
sudo cp -a /etc/dovecot /root/backup-smistamento-$TS/dovecot
sudo cp -a /opt/roundcube/config /root/backup-smistamento-$TS/roundcube-config 2>/dev/null || sudo cp -a <rc-config> /root/backup-smistamento-$TS/
sudo cp -a /opt/roundcube/*compose*.y*ml /root/backup-smistamento-$TS/ 2>/dev/null || true
sudo crontab -l > /root/backup-smistamento-$TS/root-crontab.txt 2>/dev/null || true
ls -la /root/backup-smistamento-$TS
```

Scrivi il percorso del backup nel rapporto.

### Passo 3: scaricare il plugin

```bash
cd /tmp
curl -fsSLO https://github.com/enrimagna/roundcube-plugin-smistamento/releases/download/v1.2.0/smistamento.zip
unzip -o smistamento.zip -d /tmp/smistamento-release      # crea /tmp/smistamento-release/smistamento/
ls /tmp/smistamento-release/smistamento/smistamento.php
```

### Passo 4: plugin dentro Roundcube

Il plugin deve finire in `<rc-plugins-in-container>/smistamento/` (cioè `.../plugins/smistamento/smistamento.php`).
Scegli il modo coerente con come è già fatto il container:

- **Se i plugin aggiuntivi sono già montati da `/opt/roundcube`** (es. `/opt/roundcube/plugins/...`):
  copia lì la cartella e aggiungi il mount solo se manca.
- **Altrimenti** aggiungi al compose un bind mount in sola lettura:
  `- /opt/roundcube/plugins/smistamento:<rc-plugins-in-container>/smistamento:ro`

```bash
sudo mkdir -p /opt/roundcube/plugins
sudo cp -a /tmp/smistamento-release/smistamento /opt/roundcube/plugins/
# proprietario: lo stesso utente rootless che possiede /opt/roundcube
sudo chown -R --reference=/opt/roundcube /opt/roundcube/plugins/smistamento
```

File della testa di Laya (per la riga «Smistamento aggiornato …»), in sola lettura nel container:

```bash
sudo mkdir -p <laya-heads-dir>
# nel compose del container Roundcube, sotto volumes:
#   - <laya-heads-dir>:/laya/heads:ro
```

Riassunto con AI (facoltativo per gli utenti, ma il posto va preparato): cartella delle impostazioni
per utente, in lettura/scrittura per `www-data` del container, e file-chiave condiviso, in sola lettura:

```bash
sudo install -d -m 0755 /var/lib/smistamento
sudo install -d -m 0700 -o <www-data-uid> -g <www-data-gid> /var/lib/smistamento/llm
sudo install -d -m 0750 -o root -g <www-data-gid> /etc/smistamento
sudo sh -c 'umask 027; openssl rand -base64 48 > /etc/smistamento/llm.key'
sudo chown root:<www-data-gid> /etc/smistamento/llm.key && sudo chmod 0640 /etc/smistamento/llm.key
sudo stat -c '%a %U:%G %n' /var/lib/smistamento/llm /etc/smistamento/llm.key   # 700 <www-data-uid>:… e 640 root:<www-data-gid>
# nel compose del container Roundcube, sotto volumes (stesso percorso dentro e fuori):
#   - /var/lib/smistamento/llm:/var/lib/smistamento/llm
#   - /etc/smistamento/llm.key:/etc/smistamento/llm.key:ro
```

Il file-chiave si crea **una volta**: se lo rigeneri, le chiavi già salvate dagli utenti non si aprono più
e vanno reinserite. Non stamparne il contenuto.

Se hai cambiato il compose, ricrea il container **una volta** (avvisa l'umano: la webmail si ferma per
pochi secondi). Poi controlla:

```bash
<runtime> exec <rc-container> ls <rc-plugins-in-container>/smistamento/smistamento.php /laya/heads
<runtime> exec -i <rc-container> php -l < /opt/roundcube/plugins/smistamento/smistamento.php
# riassunto con AI: www-data del container scrive nella cartella e legge il file-chiave
<runtime> exec -u 33 <rc-container> sh -c 'touch /var/lib/smistamento/llm/.probe && rm /var/lib/smistamento/llm/.probe && test -r /etc/smistamento/llm.key && ! test -w /etc/smistamento/llm.key && echo LLM-MOUNT OK'
```

Se non stampa `LLM-MOUNT OK`, i proprietari non corrispondono a `www-data` del container: ricontrolla
`<www-data-uid>` / `<www-data-gid>` (non allargare i permessi a 0777/0644) e, se non è chiaro, chiedi.

### Passo 5: configurazione Roundcube

Aggiungi in fondo a `<rc-config>` (o in un file incluso dalla config). Se `managesieve` è già attivo,
**non duplicare** il plugin: aggiorna solo le chiavi `managesieve_*` indicate.

```php
// --- Smistamento ---------------------------------------------------------------------------
$config['plugins'][] = 'managesieve';            // solo se non c'è già
$config['plugins'][] = 'smistamento';

// «Filtri» (managesieve, Roundcube 1.7): porta e TLS stanno DENTRO l'host.
// managesieve_port e managesieve_usetls non esistono più: non usarli.
$config['managesieve_host'] = 'tls://<container-host-ip>:4190';   // tls:// = STARTTLS
$config['managesieve_conn_options'] = ['ssl' => ['verify_peer' => false, 'verify_peer_name' => false]]; // se il cert non è valido per <container-host-ip>
$config['managesieve_filename_exceptions'] = ['smistamento'];       // nasconde lo script gestito in «Filtri»

// Smistamento: chiavi proprie. Qui l'host va SENZA schema; STARTTLS con usetls = true.
// (Nel plugin smistamento, «tls://» davanti all'host vuol dire TLS implicito: non usarlo con la 4190.)
$config['smistamento_managesieve_host'] = '<container-host-ip>';
$config['smistamento_managesieve_port'] = 4190;
$config['smistamento_managesieve_usetls'] = true;
$config['smistamento_managesieve_conn_options'] = ['ssl' => ['verify_peer' => false, 'verify_peer_name' => false]];
$config['smistamento_min_conf'] = '0.80';
$config['smistamento_inbox_labels'] = ['Imbox'];                    // mail delle persone: restano in Posta in arrivo
$config['smistamento_head_file'] = '/laya/heads/%u.json';           // %u = indirizzo completo; mount :ro

// Spam di Laya: etichette e default sono configurabili. Questi sono i default del plugin: scrivili
// solo se l'umano vuole valori diversi.
// $config['smistamento_spam_labels'] = ['Junk'];                   // [] = niente gestione spam (niente riga, niente regola)
// $config['smistamento_spam_default'] = ['active' => true, 'threshold' => '0.40', 'trash_threshold' => '0.80', 'action' => 'trash'];
//   active = interruttore; threshold = Soglia Spam; trash_threshold = Soglia Cestino (deve essere più alta);
//   action = 'trash' (Sposta nel Cestino) | 'discard' (Elimina definitivamente). Valori da '0.10' a '0.95'.

// Riassunto con AI nel digest (facoltativo, spento di default per ogni utente). Senza queste due righe
// il blocco «Riassunto» non compare. Nessuna chiave OpenRouter qui: ogni utente mette la sua.
$config['smistamento_llm_dir'] = '/var/lib/smistamento/llm';        // montata rw, stesso percorso
$config['smistamento_llm_keyfile'] = '/etc/smistamento/llm.key';    // montato :ro
// $config['smistamento_llm_default_model'] = 'google/gemini-2.5-flash-lite';   // default del plugin
```

Le altre chiavi (`smistamento_label_map`, orari del digest, …) sono in `config.inc.php.dist` del plugin,
con i default già giusti. Lo spam usa la cartella Spam e il Cestino speciali di Roundcube (`junk_mbox`,
`trash_mbox`): se l'utente non ha una cartella Spam, la riga Spam non compare. Non copiare `config.inc.php.dist` come `config.inc.php` se non serve.

Controllo sintassi:

```bash
<runtime> exec -i <rc-container> php -l < <rc-config>
```

### Passo 6: Dovecot

Crea un file nuovo, per esempio `/etc/dovecot/conf.d/95-smistamento.conf` (usa la cartella `conf.d`
che `dovecot.conf` include davvero; se non c'è un include, chiedi all'umano dove metterlo).
Adatta, senza duplicare quello che c'è già (controlla `/tmp/doveconf-before.txt`):

```
# --- Smistamento ---------------------------------------------------------------------------

# Aggiungi "sieve" ai protocolli GIÀ presenti: non togliere nulla.
# Esempio, se oggi è "imap lmtp":
protocols = imap lmtp sieve

service managesieve-login {
  inet_listener sieve {
    address = 127.0.0.1          # SOLO loopback. Mai 0.0.0.0, *, ::
    port = 4190
  }
}

protocol lmtp {
  mail_plugins {
    sieve = yes
  }
}

# Filtri dell'utente (Roundcube «Filtri»). Se esiste già un sieve_script personal, NON ridefinirlo.
sieve_script personal {
  driver = file
  path = ~/sieve
  active_path = ~/.dovecot.sieve
}

# Script gestito da Smistamento: gira DOPO i filtri dell'utente, solo se non hanno già spostato la mail.
sieve_script smistamento {
  type = after
  driver = file
  path = ~/sieve/smistamento.sieve
}
```

- Lo script `before` esistente (es. MalwareBazaar) **non va toccato**: continua a girare per primo.
- Se `protocols` è definito in un altro file, modifica quella riga lì invece di ridefinirla qui.
- Se `sieve` era già tra i protocolli con un listener diverso, fermati e chiedi.

Controlla e ricarica:

```bash
sudo doveconf -n > /tmp/doveconf-after.txt && echo CONFIG OK
diff /tmp/doveconf-before.txt /tmp/doveconf-after.txt
sudo doveadm reload                     # oppure: sudo systemctl reload dovecot  (NON restart)
sleep 2
ss -ltnp | grep -E ':4190\b'            # deve mostrare SOLO 127.0.0.1:4190
```

Se `doveconf -n` dà errore: ripristina dal backup, `doveadm reload`, fermati e riferisci.
Se dopo il reload la 4190 non è in ascolto, **non** fare restart: chiedi all'umano.

Firewall: controlla che non ci siano regole che espongono la 4190 (`sudo nft list ruleset | grep 4190`,
`sudo ufw status | grep 4190`, `sudo iptables -S | grep 4190`). Non aggiungerne.

Raggiungibilità dal container (deve rispondere il banner ManageSieve):

```bash
<runtime> exec <rc-container> php -r '$s=fsockopen("<container-host-ip>",4190,$e,$m,5); echo $s?fgets($s):"ERR $m","\n";'
```

### Passo 7: script server e cron

```bash
sudo install -m 0755 /tmp/smistamento-release/smistamento/server/smistamento-server.py /usr/local/sbin/smistamento-server.py
sudo install -m 0644 /tmp/smistamento-release/smistamento/server/texts.json /usr/local/sbin/texts.json
sudo install -d -m 0750 /var/lib/smistamento/digest /var/lib/smistamento/classes
sudo /usr/local/sbin/smistamento-server.py show --all-users | head -n 20     # non deve dare errori
```

Lo script legge le impostazioni del riassunto da `/var/lib/smistamento/llm` e il file-chiave da
`/etc/smistamento/llm.key` (i suoi default, `--llm-dir` / `--llm-keyfile`). Chiama OpenRouter solo per gli
utenti che hanno acceso il riassunto e salvato una chiave; se la chiamata fallisce, il digest parte lo
stesso senza «In breve». Host e container devono poter uscire verso `openrouter.ai:443`; se il firewall in
uscita lo blocca, dillo all'umano (non aprirlo tu). In `/var/lib/smistamento/digest` può comparire
`<utente>.summary.json` (0600): è un riassunto tenuto da parte per un digest non salvato, senza chiavi.

`/etc/cron.d/smistamento`:

```
# Smistamento: digest (ogni 15 minuti, all'ora scelta da ogni utente) e export classi per Laya (lunedì 03:00)
*/15 * * * *  root  /usr/local/sbin/smistamento-server.py digest --all-users --base-url <webmail-url> >> /var/log/smistamento.log 2>&1
0 3 * * 1     root  /usr/local/sbin/smistamento-server.py classes --all-users --out-dir /var/lib/smistamento/classes >> /var/log/smistamento.log 2>&1
```

Il mittente del digest di default è `Il Dispaccio <dispaccio@<dominio dell'utente>>` (`--sender` per cambiarlo).
Il digest si salva con `doveadm save` in Posta in arrivo e non passa da Sieve.

### Passo 8: verifiche nella webmail

Con un utente reale (chiedi all'umano di fare il login, o usa `<test-user>`):

1. Login: la webmail si apre, nessun errore. Log errori Roundcube senza righe `smistamento` o `managesieve`.
2. **Impostazioni › Smistamento**: c'è la tabella con le cartelle dell'utente (mai Posta in arrivo, Bozze,
   Inviata, Spam, Cestino). Attiva una cartella, Salva: «Salvato correttamente».
   Sul server: `sudo doveadm sieve list -u <test-user>` mostra `smistamento` (non attivo: è giusto).
3. **Impostazioni › Filtri**: si vedono i set esistenti (di solito `roundcube`) con i filtri di prima.
   `smistamento` **non** compare. Se la lista è vuota con un solo «>», il plugin managesieve non si
   connette: ricontrolla `managesieve_host` (porta dentro l'host) e il passo 6.
4. Nella lista cartelle, la cartella attivata ha il segno ↻.
5. **Spam**, stessa pagina sotto le cartelle: interruttore «Lo smistamento gestisce lo spam» acceso, riga
   Spam con «Soglia Spam» 0,40, «Soglia Cestino» 0,80 e «Sposta nel Cestino» scelto. Prova a mettere la
   Soglia Spam uguale o più alta della Soglia Cestino e Salva: la pagina non salva e dice «La soglia Spam
   deve essere più bassa della soglia Cestino.». Rimetti 0,40 / 0,80 e Salva.
6. **Riassunto con AI**, stessa pagina, dentro «Quando arriva il digest»: c'è il sotto-blocco «Riassunto»
   con l'interruttore «Riassunto con AI» **spento** e, sotto, la riga «Con il riassunto attivo, il testo
   delle mail del digest viene inviato a OpenRouter e al modello scelto.». **Non** deve comparire «Il
   riassunto con AI non è configurato su questo server.» (se compare: mount o permessi del passo 4, o le
   due chiavi del passo 5). Non accenderlo e non salvare chiavi: lo fa ogni utente, se vuole.
   Sul server, per tutti gli utenti, nessun file acceso:
   ```bash
   sudo sh -c 'grep -l "\"active\": true" /var/lib/smistamento/llm/*.json 2>/dev/null || echo "nessun riassunto acceso"'
   sudo /usr/local/sbin/smistamento-server.py digest --user <test-user> --to-date --dry-run --base-url <webmail-url>   # nessuna chiamata a OpenRouter (dry-run non la fa mai)
   ```
   Facoltativo, solo se l'umano te lo chiede e fa lui il login: con la sua chiave, «Prova» accanto al campo
   deve rispondere «Chiave valida»; dopo Salva la pagina mostra «salvata · ••••» + le ultime 4 cifre, e la
   chiave non compare in `sudo doveadm sieve get -u <utente> smistamento` né in
   `/var/lib/smistamento/llm/<utente>.json` (lì c'è solo un valore cifrato `smi1.…`).

### Passo 9: test di consegna (solo `<test-user>`)

Prima, in Impostazioni › Smistamento di `<test-user>`, attiva una cartella di prova (es. `Feed`).
Poi consegna una mail con gli header di Laya passando da Sieve (dovecot-lda esegue Sieve; `doveadm save` no):

```bash
LDA=$(ls /usr/libexec/dovecot/dovecot-lda /usr/lib/dovecot/dovecot-lda 2>/dev/null | head -n1)
printf 'From: Prova <prova@example.org>\nTo: <test-user>\nSubject: Prova smistamento\nMessage-ID: <smistamento-test-%s@example.org>\nX-Laya-Box: Feed\nX-Laya-Box-Conf: 0.95\n\nProva.\n' "$(date +%s)" \
  | sudo "$LDA" -d <test-user>
printf 'From: Persona <persona@example.org>\nTo: <test-user>\nSubject: Prova persone\nMessage-ID: <smistamento-test-p-%s@example.org>\nX-Laya-Box: Imbox\nX-Laya-Box-Conf: 0.95\n\nProva.\n' "$(date +%s)" \
  | sudo "$LDA" -d <test-user>
sudo doveadm fetch -u <test-user> 'mailbox hdr.subject' HEADER Subject 'Prova '
```

Atteso: «Prova smistamento» in `Feed`, «Prova persone» in `INBOX`.

Spam (con l'interruttore acceso e le soglie di default 0,40 / 0,80 della `<test-user>`):

```bash
printf 'From: Spam <spam@example.org>\nTo: <test-user>\nSubject: Prova spam medio\nMessage-ID: <smistamento-test-s5-%s@example.org>\nX-Laya-Box: Junk\nX-Laya-Box-Conf: 0.50\n\nProva.\n' "$(date +%s)" \
  | sudo "$LDA" -d <test-user>
printf 'From: Spam <spam@example.org>\nTo: <test-user>\nSubject: Prova spam alto\nMessage-ID: <smistamento-test-s9-%s@example.org>\nX-Laya-Box: Junk\nX-Laya-Box-Conf: 0.90\n\nProva.\n' "$(date +%s)" \
  | sudo "$LDA" -d <test-user>
sudo doveadm fetch -u <test-user> 'mailbox hdr.subject' HEADER Subject 'Prova spam'
```

Atteso: Junk 0,5 → «Prova spam medio» nella cartella Spam (`Junk`, o il nome della cartella Spam
dell'utente); Junk 0,9 → «Prova spam alto» nel Cestino (`Trash`, o il nome del Cestino dell'utente).
Se l'utente ha scelto «Elimina definitivamente», la 0,9 non c'è più: per il test lascia «Sposta nel
Cestino». Le mail di prova restano: non cancellarle tu, dillo all'umano.

Digest, prova a secco (non salva niente):

```bash
sudo /usr/local/sbin/smistamento-server.py digest --user <test-user> --to-date --dry-run --base-url <webmail-url>
```

Atteso: «would save …» se la cartella ha un digest attivo, oppure «nothing sorted …». Nessun traceback.

Export classi, prova:

```bash
sudo /usr/local/sbin/smistamento-server.py classes --user <test-user> --out-dir /tmp/smistamento-classes-test
cat /tmp/smistamento-classes-test/*.json     # prima classe: INBOX, "role": "inbox", "label": "Imbox"; poi, con l'interruttore spam acceso, "role": "spam", "label": "Junk"
```

### Passo 10: rollback (solo se qualcosa non va o se l'umano lo chiede)

```bash
# Roundcube: togli il blocco «Smistamento» da <rc-config> (o ripristina il backup), poi:
<runtime> exec -i <rc-container> php -l < <rc-config>
# Dovecot: togli /etc/dovecot/conf.d/95-smistamento.conf (spostalo nel backup, non cancellarlo) e
# ripristina eventuali righe modificate (protocols), poi:
sudo doveconf -n >/dev/null && sudo doveadm reload
# Cron:
sudo mv /etc/cron.d/smistamento /root/backup-smistamento-<TS>/
# Riassunto con AI: togli le due chiavi smistamento_llm_* (il blocco «Riassunto» sparisce) e i due volumi
# dal compose. Lascia /var/lib/smistamento/llm e /etc/smistamento/llm.key: senza, le chiavi salvate
# dagli utenti non si recuperano più. Spostali nel backup solo se l'umano lo chiede.
```

Gli script `smistamento` già scritti nelle home degli utenti **restano**: senza il blocco
`sieve_script smistamento` Dovecot non li esegue. Non cancellarli.

### Rapporto finale per l'umano

Scrivi: valori dei segnaposto usati, percorso del backup, file modificati/creati, diff di `doveconf -n`,
output di `ss -ltnp | grep 4190`, esito dei passi 8 e 9 (spam e riassunto con AI compresi: `LLM-MOUNT OK`,
permessi di `/var/lib/smistamento/llm` e `/etc/smistamento/llm.key`, blocco «Riassunto» spento, mai il
contenuto del file-chiave), eventuali domande aperte. Ricorda che Laya
(scrittura degli header `X-Laya-Box`) non è installata: finché non c'è, le mail restano in Posta in arrivo.
