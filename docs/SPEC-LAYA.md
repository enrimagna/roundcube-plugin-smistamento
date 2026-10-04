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

Submission 465 e 587 non ci passano. Niente `content_filter`. Se Laya è giù, la mail resta in INBOX. Mai un 550 sullo score, mai una coda in attesa del modello.

## Modello

Un encoder condiviso, una testa per utente.

| Pezzo | Cosa è |
|---|---|
| Encoder | `laya-multilingual`, congelato, un processo sul server di posta |
| Testa | lineare `768 → N`, una per utente, file `/laya/heads/<indirizzo>.joblib` |
| N | numero di classi dell'utente, variabile |
| Classi | quelle del suo file `classes`, nello stesso ordine |
| Nel file | `W`, `b`, temperature, ordine delle etichette |

L'encoder non si riallena. Sul VPS arriva solo il file della testa.

Le classi le decide l'utente, non il modello. Sono il file che `smistamento-server.py classes` scrive per lui:

1. Prima, sempre, la classe fissa Posta in arrivo: `"mailbox": "INBOX"`, `"role": "inbox"`, `"label": "Imbox"`. Persone, mail a cui si risponde. Mai spostate.
2. Poi le sue cartelle attive, ciascuna con il suo `label`, nell'ordine del file.

Niente uscite fisse, niente mappatura a mano su un elenco comune. Un utente può avere Feed, Fatture, Paper Trail, Viaggi; un altro cartelle diverse. Accendere o spegnere una cartella in Impostazioni › Smistamento cambia le classi alla prossima esportazione.

Junk non è una classe di Laya. Spam e bulk li ferma il server (postscreen, Spamhaus, MalwareBazaar → Junk). Il plugin non lascia mai attivare Junk, Spam, Cestino, Bozze o Inviata, quindi non finiscono mai nel file `classes`.

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

Su una macchina di training separata, con GPU. Il primo giro è lo storico, circa 5 GB, dopo la migrazione dal server precedente: per ogni utente, le mail già presenti nelle sue cartelle attive sono gli esempi di quella classe, e le mail in INBOX quelli di `Imbox`.

Poi una volta a settimana, per utente:

1. Lunedì alle 03:00 sul server di posta: `smistamento-server.py classes --all-users` scrive `/var/lib/smistamento/classes/<indirizzo>.json`.
2. Si copiano sulla macchina di training il file `classes` e il log di consegna della settimana (`Message-ID` + proposta).
3. Per ogni mail consegnata da almeno 7 giorni, `doveadm` cerca dove sta:
   - in una sola cartella, diversa dalla proposta: quella cartella è l'etichetta;
   - riportata in Posta in arrivo: etichetta `Imbox`;
   - in due cartelle, o mai toccata: esclusa;
   - in una cartella non attiva, o che non è nel file `classes`: esclusa.
4. Si riallena solo la testa, `768 → N` con le classi del file, nel suo ordine. L'encoder no.
5. Si copia `/laya/heads/<indirizzo>.joblib` sul server di posta. L'mtime del file è la data «Smistamento aggiornato» nel plugin.

**Da scrivere, lato Laya:** il log di consegna (una riga per mail: `Message-ID`, utente, label proposto, confidenza) e lo script dei 7 giorni con `doveadm`. Il plugin e `smistamento-server.py` non li fanno.

## Casi

- **Cartella appena attivata**: fino al prossimo riallenamento non ha esempi e Laya non la propone. I primi esempi sono gli spostamenti a mano dell'utente in quella cartella, oppure un bootstrap dalle mail che ci sono già.
- **Cartella rinominata**: il plugin riscrive lo script Sieve e il label diventa il nome nuovo. La testa conosce ancora quello vecchio, che non corrisponde più a nessuna cartella: quelle mail restano in INBOX fino al prossimo riallenamento.
- **Cartella spenta**: esce dal file `classes` alla prossima esportazione. Fino al riallenamento Laya può ancora proporla; Sieve non la trova attiva e la mail resta in INBOX.

## Cosa non è

Rspamd. ClamAV. Uno score che rifiuta in SMTP. Una seconda testa per il phishing. Il controllo hash MalwareBazaar, che è un altro passo e scrive `X-Malware-Bazaar`.
