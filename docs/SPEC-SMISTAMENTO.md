# Smistamento: specifica UX (per sviluppo e QA)

Plugin Roundcube 1.7.4 per la skin «Il Dispaccio» (palette Inchiostro). I riferimenti ai frame A–E rimandano ai wireframe di progetto, non pubblicati qui.
Versione 2, 4 ottobre 2026: **lo smistamento è fatto da un classificatore (OpenLaya), non da regole per mittente**. Niente toast, niente elenco mittenti.

## 1. Cos'è
L'utente sceglie le cartelle "attive". Le mail nuove che il classificatore riconosce come appartenenti a una cartella attiva vengono spostate lì all'arrivo. Il classificatore impara dalle mail già presenti in quelle cartelle. Per ogni cartella si può chiedere di segnare come lette le mail smistate e di ricevere un digest periodico in Posta in arrivo.
Correggere = spostare a mano: mettere una mail in una cartella attiva, o tirarla fuori, è il modo **silenzioso** di correggere il classificatore. Non compare mai nessun avviso.

## 2. Dove (frame A, C)
- **Impostazioni → Smistamento**: nuova sezione nella colonna delle Impostazioni (dopo Filtri).
- **Lista cartelle della posta**: dopo il nome di ogni cartella attiva compare il segno ↻ (icona `sync` di Font Awesome, 9 px, colore accento). Sulla riga selezionata il segno prende il colore del testo invertito. Le cartelle non attive non hanno segno.
- **Menu ⋮ di «Sezioni»** (riferito alla cartella selezionata): voce «Smistamento di questa cartella…», che apre Impostazioni → Smistamento con la riga di quella cartella evidenziata (scroll + flash del focus, senza animazioni lunghe). La voce compare per tutte le cartelle utente, attive o no. Non compare per Posta in arrivo, Bozze, Inviata, Spam, Cestino.

## 3. Impostazioni → Smistamento (frame A, B, E)
**Occhiello:** IMPOSTAZIONI · SMISTAMENTO
**Titolo:** Smistamento
**Intro (2 righe):**
> Le mail nuove vanno da sole nelle cartelle attive: lo smistamento impara da quelle che ci sono già.
> Se una mail finisce nel posto sbagliato, spostala a mano: anche così impara.

**Tabella**: una riga per ogni cartella utente (sottocartelle comprese, con il percorso «Progetti / 2026»). Escluse: Posta in arrivo, Bozze, Inviata, Spam, Cestino.

| Colonna | Controllo | Testi |
|---|---|---|
| Cartella | nome (maiuscolo, come nella lista cartelle) + ↻ se attiva | — |
| Attiva | interruttore | «SÌ» / «NO» accanto all'interruttore |
| Segna come lette | casella | «sì» / «no» |
| Digest | segmenti | «Spento» · «Giorno» · «Settimana» · «Mese» (default: Spento) |
| Esempi | testo | «248 mail» + stato (vedi sotto) |

- Riga **non attiva**: nome in grigio, nessun ↻, colonne Segna come lette e Digest in grigio e disattivate (i valori restano salvati), Esempi = «412 mail» + «non attiva».
- **Stati della colonna Esempi** (solo per le cartelle attive):
  - «pronta»: icona ✓, colore testo. Il classificatore smista verso questa cartella.
  - «in apprendimento…»: icona spinner statica, colore secondario. Addestramento in corso dopo l'attivazione o il riaddestramento; nel frattempo la cartella non riceve smistamenti.
  - «poche mail: servono almeno N»: icona ⚠, colore accento. Sotto la soglia **N** (segnaposto, da definire) la cartella resta attiva ma non riceve smistamenti. Lo stato si aggiorna da solo quando le mail arrivano a N.
- Il conteggio «N mail» = numero di messaggi nella cartella usati come esempi (formato italiano: «1.032 mail»).

**Blocco «Quando arriva il digest»** (unico, globale; niente orari per cartella):
- «Ora» [07:30 ▾]
- «Settimanale: ogni» [lunedì ▾]
- «Mensile: il» [1° del mese ▾] (valori 1°–28°, per evitare i mesi corti)
- Nota: «Stessa periodicità = un'unica mail, con una sezione per cartella. Nessuna mail nel periodo = nessun digest.»

**Pulsante:** «SALVA» (come gli altri form delle Impostazioni). Conferma standard di Roundcube: «Salvato.»

**Stati vuoti**
- Nessuna cartella utente: «Non hai ancora cartelle tue. Creane una in Impostazioni → Cartelle, poi torna qui.»
- Nessuna cartella attiva: tabella normale, sopra la tabella «Nessuna cartella attiva: accendi l'interruttore accanto a una cartella.»
- Cartella attiva vuota (0 mail): Esempi = «0 mail» + «poche mail: servono almeno N».
- Classificatore non raggiungibile: banner sopra la tabella «Lo smistamento è momentaneamente fermo: le mail restano in Posta in arrivo.» Gli interruttori restano modificabili.

**Mobile 390 px (frame E)**: una card per cartella. In alto nome + ↻ + interruttore; sotto la casella «Segna come lette», i segmenti del Digest a tutta larghezza, poi la riga «248 mail · ✓ pronta». Le cartelle spente si riducono a nome + interruttore + «412 mail · non attiva». Il blocco «Quando arriva il digest» e «SALVA» stanno sotto le card.
**Scuro (frame B)**: stesse regole, palette `html.dark-mode` della skin (selezione e segmento attivo in arancio `#FF8A3D` con testo `#0B1426`).

## 4. Lettura di una mail smistata (frame C)
Sotto l'intestazione (DA / A / DATA), sopra «Intestazioni · Scarica tutti gli allegati», una riga discreta in colore secondario:
> ↻ Smistata in **Fatture** · Cambia
- Compare solo sulle mail spostate dal classificatore, finché restano nella cartella in cui sono state smistate. Se l'utente la sposta, la riga sparisce.
- «Cambia» apre il selettore cartelle standard (= «Sposta in…»). Spostare la mail conta come correzione, **senza alcun messaggio**.
- Nessun toast, mai: né quando si sposta a mano dentro o fuori da una cartella attiva, né quando si usa «Cambia».

## 5. Digest (frame D)
- **Mittente:** «Il Dispaccio» <indirizzo di sistema, es. dispaccio@dominio>. Arriva in Posta in arrivo; non viene mai smistato a sua volta.
- **Segno distintivo nella lista:** icona giornale (`newspaper` di Font Awesome) in accento prima del mittente.
- **Oggetti:**
  - «Dispaccio del giorno · 4 ott · 9 mail»
  - «Dispaccio della settimana · 28 set–4 ott · 23 mail»
  - «Dispaccio del mese · settembre · 41 mail»
- **Unione:** tutte le cartelle con la stessa periodicità finiscono in **una sola mail**, con una sezione per cartella (in ordine alfabetico). Periodicità diverse = mail diverse: lunedì possono arrivare sia il giornaliero sia il settimanale.
- **Periodo:** giornaliero = il giorno prima (00:00–23:59); settimanale = da lunedì a domenica della settimana prima; mensile = il mese prima. Invio all'ora impostata.
- **Nessun digest vuoto:** se in nessuna cartella di quella periodicità è arrivato niente nel periodo, la mail non parte. Le sezioni vuote non compaiono.
- **Corpo HTML** (autonomo, leggibile in qualsiasi client; CSS inline, tabelle, larghezza massima 600 px):
  - testata «Il *Dispaccio*» (Fraunces se disponibile, poi `Georgia, serif`);
  - riga-data a doppio filetto: «SETTIMANA DAL 28 SETTEMBRE AL 4 OTTOBRE 2026 · 23 MAIL SMISTATE» (giorno: «GIORNO 4 OTTOBRE 2026 · 9 MAIL SMISTATE»; mese: «SETTEMBRE 2026 · 41 MAIL SMISTATE»);
  - per ogni cartella: titolo in maiuscoletto (accento) + numero a destra, poi righe «**Mittente** › oggetto · data» (`ui-monospace, Menlo, Consolas, monospace`);
  - ogni riga è un link che apre quella mail in Roundcube;
  - al massimo **10 righe** per sezione, poi il link «e altre 7 in Notifiche →» che apre la cartella;
  - piede: «Le mail sono nelle loro cartelle. Qui trovi il sommario della settimana.» + link «Gestisci lo smistamento» (→ Impostazioni → Smistamento). Per periodicità: «… della giornata.» / «… della settimana.» / «… del mese.»
- Versione text/plain inclusa (stesso contenuto, una riga per mail, URL in chiaro).

## 6. Regole
1. Lo smistamento lo decide il classificatore, una sola cartella di destinazione per mail. Se il classificatore non è abbastanza sicuro (soglia da definire), la mail resta in Posta in arrivo.
2. Il classificatore impara dalle mail presenti nelle cartelle attive. Spostare a mano dentro/fuori una cartella attiva aggiorna gli esempi al prossimo riaddestramento. **Nessun avviso in UI.**
3. Una cartella con meno di **N** mail è attiva ma non riceve smistamenti («poche mail: servono almeno N»).
4. «Segna come lette» vale **solo** per le mail smistate in automatico, non per quelle spostate a mano.
5. Digest uniti per periodicità; nessun digest vuoto; il digest stesso non viene smistato.
6. *(Proposta)* Spam e mail già spostate dai filtri dell'utente (managesieve) non passano dal classificatore: i filtri dell'utente hanno la precedenza.
7. *(Proposta)* Spegnere una cartella non sposta indietro nulla: le mail già smistate restano dove sono.
8. Non si possono attivare: Posta in arrivo, Bozze, Inviata, Spam, Cestino.
9. Le mail delle persone (classe «persone» di Laya, `X-Laya-Box: Imbox`) restano in Posta in arrivo, mai spostate, da leggere, mai nel digest. Non c'è una cartella Imbox. Riga di aiuto in Impostazioni: «Posta in arrivo: le mail delle persone e quelle di cui lo smistamento non è sicuro (o tutte, se è fermo).» Per l'addestramento Posta in arrivo è una classe fissa (vedi README del plugin, export `classes`). *(Deciso il 2026-10-04.)*

## 7. Note tecniche da verificare
I nomi di hook, container e keyword sotto sono indicativi: vanno verificati sul codice di Roundcube 1.7.4.
- **Classificazione all'arrivo, lato server**: un servizio OpenLaya classifica ogni nuova mail in INBOX e la sposta via IMAP (MOVE) nella cartella prevista, impostando una keyword IMAP (es. `$Smistata`, più eventualmente `$Smistata-Fatture`), oppure consegna con Sieve + flag. Da scegliere in base a latenza e affidabilità (Sieve extprograms vs IMAP IDLE/NOTIFY). Deve funzionare anche se la mail viene letta solo dal telefono.
- **Riga «Smistata in…»**: si mostra se il messaggio ha la keyword e si trova nella cartella indicata. Allo spostamento manuale, togliere la keyword.
- **Riaddestramento**: deciso, settimanale, lunedì notte sul server di posta, solo CPU (vedi SPEC-LAYA). *(Testo originale: periodico, frequenza da definire.)* Lo stato «in apprendimento…» copre il tempo di addestramento. Le correzioni manuali si ricavano dalla presenza/assenza delle mail nelle cartelle, non da eventi UI.
- **Soglia N**: segnaposto, da definire con test sul modello.
- **Preferenze**: per ogni cartella {attiva, segna_lette, digest} + globali {ora, giorno_settimana, giorno_mese}, salvate nelle preferenze utente di Roundcube e replicate dove le legge il servizio lato server (il digest e lo smistamento non dipendono dalla sessione web).
- **Digest generato lato server** (cron/servizio), non da Roundcube. Il link al messaggio: `?_task=mail&_mbox=<cartella>&_uid=<UID>&_action=show`, con fallback su ricerca per Message-ID se l'UID è cambiato (UIDVALIDITY). Da verificare il comportamento con la sessione scaduta (login e poi redirect).
- **Filtri dell'utente**: lo smistamento non scrive nello script managesieve dell'utente. Se si usa Sieve, uno script dedicato incluso (`include :personal "smistamento"`) e gestito solo dal servizio.
- **Rinomina/eliminazione di una cartella attiva**: aggiornare le preferenze (via hook `folder_update` / `folder_delete`).
- **Segno ↻ nella lista cartelle**: classe sul `li.mailbox` (es. `.smistamento-attiva`) e `::after` in CSS nella skin. Voce del menu ⋮ aggiunta con `add_button` nel container `mailboxoptions`.
- **Privacy**: il classificatore legge il contenuto delle mail; da chiarire dove gira OpenLaya (stesso server?) e cosa viene conservato.

## 8. Punti aperti
1. Valore di **N** e soglia di confidenza sotto la quale la mail resta in Posta in arrivo.
2. Frequenza del riaddestramento; serve un pulsante «Riaddestra ora»? (Oggi non previsto.)
3. Lunedì arrivano due digest (giornaliero + settimanale) alla stessa ora: va bene o si uniscono quel giorno?
4. Il digest deve contenere anche le mail già lette (per esempio quelle con «segna come lette»)? Proposta: sì, tutte quelle smistate nel periodo.
5. Mail spostate a mano in una cartella attiva: devono entrare nel digest? Proposta: no, solo quelle smistate in automatico.
6. Sottocartelle: si attivano una per una (proposta) o ereditano dalla cartella madre?
7. Serve uno storico/rapporto «cosa è stato smistato oggi» oltre al digest? (Non previsto in v1.)
8. Mail con più destinatari o liste: il classificatore vede solo la propria copia? Da verificare con le identità multiple.
