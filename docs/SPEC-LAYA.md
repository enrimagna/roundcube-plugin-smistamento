# Laya — spec dello smistatore

Non è lo spam. Lo spam è postscreen e Spamhaus, prima del dialogo. Laya sceglie la cartella dopo che la mail è già accettata. Non si installa nel test e non entra nel taglio. Si accende quando lo storico c'è.

## Posto nella catena

```
Internet :25
  postscreen + Spamhaus ZEN
  policyd-spf
  Postfix
  LMTP
  Dovecot scrive la Maildir in INBOX
  Laya legge, scrive gli header, Sieve sposta
```

Submission 465 e 587 non ci passano: la posta tra utenti locali (inviata con autenticazione, o dal server stesso) non si classifica nemmeno alla consegna. Niente `content_filter`. Se Laya è giù, la mail resta in INBOX. Mai un 550 sullo score, mai una coda in attesa del modello.

## Modello

Un encoder condiviso, una testa per utente.

| Pezzo | Cosa è |
|---|---|
| Encoder | `laya-multilingual`, congelato, un processo sul server di posta |
| Testa | lineare `768 → N`, una per utente, file `/laya/heads/<indirizzo>.joblib` |
| N | numero di classi dell'utente, variabile |
| Classi | quelle del suo file `classes`, nello stesso ordine |
| Nel file | `W`, `b`, temperature, ordine delle etichette |

L'encoder non si riallena. Sul VPS arriva solo il file della testa (con il suo `report.json`).

Le classi le decide l'utente, non il modello. Sono il file che `smistamento-server.py classes` scrive per lui:

1. Prima, sempre, la classe fissa Posta in arrivo: `"mailbox": "INBOX"`, `"role": "inbox"`, `"label": "Imbox"`. Persone, mail a cui si risponde. Mai spostate.
2. Poi le sue cartelle attive, ciascuna con il suo `label`, nell'ordine del file.

Niente uscite fisse, niente mappatura a mano su un elenco comune. Un utente può avere Feed, Fatture, Paper Trail, Viaggi; un altro cartelle diverse. Accendere o spegnere una cartella in Impostazioni › Smistamento cambia le classi alla prossima esportazione.

Junk è una classe di Laya se la sua etichetta è configurata (`smistamento_spam_labels`, default `Junk`) e l'utente lascia acceso «Lo smistamento gestisce lo spam» (US-SMI-SPAM in SPEC-DELTA-LAYA). In quel caso il file `classes` la porta subito dopo Posta in arrivo, con `"role": "spam"` e la cartella Spam speciale come `mailbox`; se l'utente spegne l'interruttore la classe sparisce dal suo file. Laya scrive la confidenza come per le altre classi; cosa farne lo decidono le due soglie dell'utente nello script Sieve, non Laya: sotto la soglia Spam (default 0,40) resta in Posta in arrivo, tra la soglia Spam e la soglia Cestino (default 0,80) va nella cartella Spam, dove l'utente la controlla e da dove Laya impara, dalla soglia Cestino in su va nel Cestino o viene eliminata. Lo spam grosso continua a fermarlo il server prima di Laya (postscreen, Spamhaus, MalwareBazaar). Cestino, Bozze e Inviata non sono mai classi.

Niente Screener. Niente `screened.json`. Il mittente sconosciuto va in una delle classi dell'utente, o resta in Posta in arrivo; non c'è una coda umana.

Archive non la scrive Laya. È un namespace a parte, con una policy di età.

## Soglia minima

Sotto le 200 mail con etichetta (somma su tutte le classi dell'utente) la testa non si installa: resta il modello base e il plugin dice «Smistamento di base». La soglia è di Laya, non del plugin.

## Header

```
X-Laya-Box: <label dell'utente>
X-Laya-Box-Conf: 0.00–1.00
```

Il valore è il `label` della classe scelta, preso dalla testa di quell'utente (es. `Imbox`, `Feed`, `PaperTrail`, `Fatture`). Non è un elenco fisso. La confidenza ha sempre due decimali.

Sieve, dopo, `fileinto` sulla cartella e `stop`. `Imbox` non ha `fileinto`: resta INBOX a qualsiasi confidenza. Senza header, con confidenza sotto la soglia (`smistamento_min_conf`, oggi 0.80), o con un label che non è più di una cartella attiva, resta INBOX.

## Training

Due fasi, due macchine.

**Primo giro, una volta sola, sul PC di training** *(decisione del 5 ottobre 2026)*. Lo storico, circa 5 GB, dopo la migrazione dal server precedente: per ogni utente, le mail già presenti nelle sue cartelle attive sono gli esempi di quella classe, e le mail in INBOX quelli di `Imbox`. Il PC di training serve solo a questo: riceve il file `classes` di ogni utente, esportato sul server di posta, e rimanda al server di posta solo la testa e il suo `report.json` (servono ai controlli prima di installarla).

**Poi ogni settimana, il lunedì notte, sul server di posta (dove gira Laya): il training incrementale** (le correzioni nuove si aggiungono allo storico, vedi «Lunedì notte»). Niente copie verso il PC di training. L'encoder gira già lì, quindi niente ricodifica.

### Alla consegna

Laya salva per ogni mail, nell'archivio di quell'utente (es. `/var/lib/laya/emb/<indirizzo>.*`):

- `Message-ID`;
- label proposto e confidenza;
- l'embedding a 768 dimensioni (float16 va bene, circa 1,5 KB a mail).

Se a una mail manca l'embedding (Laya era giù, archivio perso), al training si ricodificano solo quelle: per circa 150 mail sono minuti di CPU.

### Lunedì notte

1. 03:00: `smistamento-server.py classes --all-users` scrive `/var/lib/smistamento/classes/<indirizzo>.json`.
2. 03:30: il training di Laya, un utente alla volta, a bassa priorità (`nice`, `ionice`).
3. Per ogni mail consegnata da almeno 7 giorni, `doveadm` cerca dove sta:
   - in una sola cartella, diversa dalla proposta: quella cartella è l'etichetta;
   - riportata in Posta in arrivo: etichetta `Imbox`;
   - in due cartelle, o mai toccata: esclusa;
   - in una cartella non attiva, o che non è nel file `classes`: esclusa.
4. Si riallena la testa **da zero**, `768 → N` con le classi del file, nel suo ordine, su tutto lo storico più le correzioni nuove (non solo l'ultima settimana). L'encoder no.
5. Controllo prima di installare: una parte degli esempi resta fuori come validazione. La testa nuova si installa solo se il suo errore su quella parte non è peggiore di quello della testa in uso. Altrimenti resta la vecchia e si scrive nel log.
6. Installazione atomica: scrittura in un file temporaneo, poi rename su `/laya/heads/<indirizzo>.joblib`. La testa precedente resta come `<indirizzo>.joblib.prev`, per il rollback. L'mtime del file è la data «Smistamento aggiornato» nel plugin.

### Costi

| Cosa | Quanto |
|---|---|
| CPU | solo CPU; da pochi secondi a meno di un minuto per utente |
| RAM | qualche centinaio di MB, per poco |
| Disco | 75–150 MB ogni 50.000 mail; meno di 0,5 MB a settimana per 100–150 spostamenti |

**Da scrivere, lato Laya:** l'archivio di consegna (`Message-ID`, label proposto, confidenza, embedding), lo script del lunedì (raccolta etichette con `doveadm`, riallenamento, controllo sulla validazione, installazione atomica con `.prev`) e la riga di cron delle 03:30. Il plugin e `smistamento-server.py` non li fanno: danno solo il file `classes` delle 03:00.

## Casi

- **Cartella appena attivata**: fino al prossimo riallenamento non ha esempi e Laya non la propone. I primi esempi sono gli spostamenti a mano dell'utente in quella cartella, oppure un bootstrap dalle mail che ci sono già.
- **Cartella rinominata**: il plugin riscrive lo script Sieve e il label diventa il nome nuovo. La testa conosce ancora quello vecchio, che non corrisponde più a nessuna cartella: quelle mail restano in INBOX fino al prossimo riallenamento.
- **Cartella spenta**: esce dal file `classes` alla prossima esportazione. Fino al riallenamento Laya può ancora proporla; Sieve non la trova attiva e la mail resta in INBOX.

## Cosa non è

Rspamd. ClamAV. Uno score che rifiuta in SMTP. Una seconda testa per il phishing. Il controllo hash MalwareBazaar, che è un altro passo e scrive `X-Malware-Bazaar`.
