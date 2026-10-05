# Smistamento — delta UX per Laya (finale)

Il resto di SPEC-SMISTAMENTO resta valido. Modello e training: SPEC-LAYA.

**Aggiornato il 2026-10-04 (decisioni del proprietario del progetto):**
- niente cartella Imbox: le mail delle persone (`X-Laya-Box: Imbox`) restano in Posta in arrivo;
- la testa di Laya è per utente, e le sue classi sono quelle del file `classes` di quell'utente: prima Posta in arrivo (`Imbox`), poi le sue cartelle attive. Niente righe fisse Imbox/Feed/Paper Trail/Junk;
- ~~Junk non è una classe~~ → sostituito da US-SMI-SPAM (sotto): Laya può etichettare lo spam, e la cartella Spam ha una riga fissa in Impostazioni.

1. La tabella ha una riga per ogni cartella dell'utente, come in SPEC-SMISTAMENTO. Niente righe fisse, niente colonna «Cosa ci finisce».
2. Niente riga Imbox. In alto, la riga di aiuto: «Posta in arrivo: le mail delle persone e quelle di cui lo smistamento non è sicuro (o tutte, se è fermo).»
3. Default per una cartella nuova: spenta, lette no, digest spento. Le impostazioni di partenza per Feed (lette no + giornaliero) e Paper Trail (lette sì + settimanale) restano un esempio, non una regola.
4. Attiva spento = Sieve non smista in quella cartella e la mail resta in INBOX. Tooltip: «Spenta: queste mail restano in Posta in arrivo».
5. Sotto l'intro, una riga: «Smistamento aggiornato <giorno g mese>», presa dall'mtime della testa dell'utente (`/laya/heads/<indirizzo>.json`, il file della coppia `.json` + `.npz` scritto per ultimo; percorso configurabile). Senza testa: «Smistamento di base: si personalizza quando ci sono abbastanza mail».
6. Intro: «Le mail nuove vanno da sole nelle cartelle attive. Se una finisce nel posto sbagliato, spostala: ogni settimana lo smistamento impara dai tuoi spostamenti.»
7. «Smistata in Feed · Cambia»: Cambia apre il menu Sposta, con Posta in arrivo + le cartelle attive. Il segno ↻ e la voce nel menu ⋮ compaiono solo sulle cartelle attive.
8. Il digest ha una sezione per ogni cartella attiva con quella periodicità. Mai Posta in arrivo, quindi mai le mail delle persone.
9. Le etichette persone stanno in `smistamento_inbox_labels` (default `['Imbox']`). Nell'export `classes` Posta in arrivo è sempre la prima classe: `"mailbox": "INBOX"`, `"role": "inbox"`, `"label": "Imbox"`.

## US-SMI-SPAM — riga Spam configurabile (2026-10-04)

Come utente voglio decidere cosa succede allo spam che Laya riconosce, per non doverlo svuotare a mano.

1. **Interruttore di pagina** sotto il blocco «Quando arriva il digest» (ordine: cartelle, digest, Spam): «Lo smistamento gestisce lo spam», **acceso di default**. Inglese: «Sorting handles spam».
   - Acceso: sotto compare la riga **Spam** (la cartella Spam/Junk speciale di Roundcube) con Soglia Spam, Soglia Cestino e Dalla soglia Cestino in su.
   - Spento: la riga sparisce. Sieve non fa niente con l'etichetta spam: la mail segue le regole normali, cioè resta in Posta in arrivo (l'etichetta spam non è mai l'etichetta di una cartella). Soglie e azione salvate restano lì e tornano quando lo si riaccende.
2. La riga Spam non ha «Segna come lette» né «Digest»: lo spam non entra mai nel digest. Le altre cartelle speciali (Bozze, Inviata, Cestino) restano escluse.
3. Etichetta configurabile: `smistamento_spam_labels` (default `['Junk']`; `[]` = niente classe spam, niente interruttore, niente riga).
4. **Due soglie** per utente (US-SMI-SPAM2, 2026-10-04), da 0,10 a 0,95 a passi di 0,05: **Soglia Spam** (default **0,40**) e **Soglia Cestino** (default **0,80**). Inglese: «Spam threshold» / «Trash threshold». Non vale la soglia generale 0,80 delle altre cartelle, che resta separata.
   - confidenza < soglia Spam → resta in Posta in arrivo (Sieve `stop`, nessuna regola di cartella);
   - soglia Spam ≤ confidenza < soglia Cestino → cartella Spam (l'utente la controlla; serve ad allenare lo smistamento);
   - confidenza ≥ soglia Cestino → l'azione scelta;
   - etichetta spam senza confidenza → cartella Spam.
   - **Controllo al salvataggio**: la soglia Spam deve essere più bassa della soglia Cestino. Se non lo è, la pagina non salva e lo dice sotto la riga e nel messaggio: «La soglia Spam deve essere più bassa della soglia Cestino.» (inglese: «The Spam threshold must be lower than the Trash threshold.»). Il controllo c'è nella pagina e sul server. Con l'interruttore spento la riga è nascosta: se le soglie inviate non vanno bene si tengono quelle salvate e il resto si salva.
   - **Migrazione** delle impostazioni con una sola soglia (JSON `v: 1`, o preferenze vecchie): la vecchia soglia diventa la soglia Spam; la soglia Cestino è 0,80, o la vecchia soglia se è più alta. Se così le due soglie sarebbero uguali (vecchia soglia 0,80 o più), la soglia Spam scende di 0,05 e il punto da cui scatta l'azione resta quello di prima (es. 0,90 → Spam 0,85, Cestino 0,90).
5. **Dalla soglia Cestino in su** (inglese «At or above the Trash threshold»): «Sposta nel Cestino» (default) oppure «Elimina definitivamente: la mail viene cancellata subito e non si può recuperare.» (Sieve `discard`; la scelta è in arancio quando è selezionata). Inglese: «Move to Trash» / «Delete permanently: the mail is deleted at once and cannot be recovered.»
6. Nota sotto la riga: «Sotto la prima soglia la mail resta in Posta in arrivo. Tra le due soglie va nella cartella Spam, dove puoi controllarla: serve ad allenare lo smistamento. Dalla seconda soglia in su va nel Cestino o viene eliminata, come scegli qui.» Inglese: «Below the first threshold the mail stays in the Inbox. Between the two thresholds it goes to the Spam folder, where you can check it: it helps sorting learn. From the second threshold up it goes to the Trash or is deleted, as you choose here.»
7. I filtri dell'utente vincono (lo script Smistamento gira dopo i suoi filtri).
8. Ogni salvataggio riscrive lo script Sieve. Tutto per utente; default in `smistamento_spam_default` (`active` = interruttore, `threshold` = soglia Spam, `trash_threshold` = soglia Cestino, `action`). Nel JSON dello script (`v: 2`) la voce `spam` porta `threshold`, `trash_threshold` e `action`.
9. Export `classes`: con l'interruttore acceso, subito dopo Posta in arrivo c'è la classe spam: `"mailbox": "Junk"` (la cartella speciale), `"role": "spam"`, `"label": "Junk"`. Spento: niente classe spam (Laya non la addestra per quell'utente).
10. **Spam segnato dal server** (`X-Spam-Flag: YES`, `X-Malware-Bazaar: hit`): comportamento invariato, Smistamento non lo tocca e lo gestisce il server. Raccomandazione: lasciarlo fuori da soglie e azione. Il flag del server è un sì/no senza confidenza, quindi una soglia non ha senso; e mandare al Cestino o eliminare su un flag binario renderebbe irrecuperabili i falsi positivi del filtro server. Il malware va respinto o messo in quarantena dal server, non deciso dall'utente.

## US-SMI-DIGEST-LLM — «In breve»: riassunto con AI nel digest (2026-10-04)

Come utente voglio, in cima al digest, poche righe su cosa conta e cosa devo fare, per non dover aprire tutte le mail. Completa SPEC-SMISTAMENTO §5 (Digest). Facoltativo, per utente, **spento di default**.

1. **Dove:** Impostazioni › Smistamento, dentro «Quando arriva il digest», sotto la riga ora/settimanale/mensile: sotto-blocco **«Riassunto»** (titolino in maiuscoletto). Stesso stile dei blocchi vicini; a 390 px i campi stanno in una scheda (etichetta sopra il valore); tema scuro con le variabili della pagina.
2. **Interruttore «Riassunto con AI»** (inglese «AI summary»), spento di default. Sotto, sempre visibile: «Con il riassunto attivo, il testo delle mail del digest viene inviato a OpenRouter e al modello scelto.» (inglese «With the summary on, the text of the digest's mails is sent to OpenRouter and to the chosen model.»). Spento: i campi sotto si nascondono, i valori restano salvati.
3. **«Chiave API OpenRouter»**: campo password, mai precompilato. Dopo il salvataggio la chiave non si rivede: «salvata · ••••1234» (ultime 4 cifre) con **Sostituisci** (riapre il campo vuoto, con **Annulla**) e **Rimuovi** («La chiave verrà rimossa quando salvi.» + Annulla; vale con Salva). Acceso senza chiave: «Senza chiave il digest arriva senza riassunto.» La chiave è salvata **cifrata sul server**, mai nello script Sieve, nella riga JSON delle impostazioni, nelle preferenze di Roundcube, nella pagina, nei log o nei messaggi d'errore.
4. **«Prova»**, accanto alla chiave: una chiamata di prova (1 token) con la chiave scritta nel campo o, se il campo è vuoto, con quella salvata, e il modello del campo. Risposta sotto/accanto: «Chiave valida» oppure, in italiano semplice: «Chiave non valida: OpenRouter non la riconosce.» · «Credito esaurito: ricarica il conto su OpenRouter.» · «Modello sconosciuto: controlla l'id su openrouter.ai/models.» · «OpenRouter non ha risposto in tempo. Riprova tra poco.» · «Troppe richieste a OpenRouter. Riprova tra poco.» · «Impossibile raggiungere OpenRouter da questo server.» · «OpenRouter ha risposto con un errore (codice N).» Senza chiave: «Scrivi la chiave API per provarla.»
5. **«Modello»**: id OpenRouter (`fornitore/modello`), default **`google/gemini-2.5-flash-lite`** (`smistamento_llm_default_model`). Motivo: il riassunto di un digest è quasi tutto input (fino a 40 mail × 1.500 caratteri ≈ 15–20k token in, ~300 out): flash-lite costa $0,10/M in e $0,40/M out ≈ $0,002 per digest, contro $0,15/$0,15 di `mistralai/ministral-8b-2512` ≈ $0,003; contesto 1M contro 262K; nel bench sulle fatture è stato il più preciso e il più economico; buon italiano. Id non valido → la pagina non salva: «Il modello deve essere un id OpenRouter, per esempio google/gemini-2.5-flash-lite.»
6. **«Prompt»**: textarea precompilata col prompt predefinito nella lingua dell'utente; segnaposto `{mail}` (l'elenco delle mail) e `{periodo}` (il periodo del digest); aiuto «{mail} diventa l'elenco delle mail del digest, {periodo} il periodo che copre.»; pulsante **«Ripristina predefinito»**. Prompt vuoto o uguale al predefinito = segue il predefinito (e la sua traduzione). Senza `{mail}` le mail si aggiungono in fondo. Massimo 4.000 caratteri. Predefinito (italiano):

   > Questo è il digest di posta di {periodo}. Scrivi un riassunto «In breve» di 3–6 righe, in italiano.
   > - Prima le mail che chiedono un'azione: pagamenti, risposte, scadenze (con la data, se c'è).
   > - Poi le notizie davvero utili. Salta pubblicità e newsletter senza novità.
   > - Una riga per punto, che inizia con «- », testo semplice senza markdown.
   > Usa solo quello che c'è nelle mail: niente supposizioni, nessun importo o data inventati. Se non c'è niente di importante, scrivilo in una riga.
   >
   > Mail del digest:
   > {mail}

7. **Generazione** (server, `smistamento-server.py digest`): vedi SPEC-SMISTAMENTO §5, «In breve». Timeout 30 s + 1 nuovo tentativo; ogni errore → digest senza riassunto + riga nel log senza chiave né testo; token e costo nel log; nessuna chiamata senza digest o con l'interruttore spento; `--dry-run` non chiama mai.
8. **Dove stanno le impostazioni** (il digest lo fa lo script sull'host, il plugin gira nel container): un file per utente `<smistamento_llm_dir>/<utente>.json` (0600), in una directory dell'host montata nel container allo stesso percorso (default `/var/lib/smistamento/llm`). La chiave è cifrata con un file-chiave condiviso (`/etc/smistamento/llm.key`, ≥ 32 caratteri casuali, 0640 root:gruppo di www-data, montato in sola lettura nel container) e legata all'utente (la cifratura di un utente non si apre sul file di un altro). Dettagli e comandi: README, «Riassunto con AI».
9. URL dell'API: `smistamento_openrouter_base` / `--llm-base`, altrimenti `$SMISTAMENTO_OPENROUTER_BASE`, altrimenti `https://openrouter.ai/api/v1` (per le prove si può puntare a un mock compatibile).

