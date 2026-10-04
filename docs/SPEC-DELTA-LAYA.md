# Smistamento — delta UX per Laya (finale)

Il resto di SPEC-SMISTAMENTO resta valido. Modello e training: SPEC-LAYA.

**Aggiornato il 2026-10-04 (decisioni del proprietario del progetto):**
- niente cartella Imbox: le mail delle persone (`X-Laya-Box: Imbox`) restano in Posta in arrivo;
- la testa di Laya è per utente, e le sue classi sono quelle del file `classes` di quell'utente: prima Posta in arrivo (`Imbox`), poi le sue cartelle attive. Niente righe fisse Imbox/Feed/Paper Trail/Junk;
- Junk non è una classe: lo spam lo ferma il server, e il plugin non lascia attivare Junk.

1. La tabella ha una riga per ogni cartella dell'utente, come in SPEC-SMISTAMENTO. Niente righe fisse, niente colonna «Cosa ci finisce».
2. Niente riga Imbox. In alto, la riga di aiuto: «Posta in arrivo: le mail delle persone e quelle di cui lo smistamento non è sicuro (o tutte, se è fermo).»
3. Default per una cartella nuova: spenta, lette no, digest spento. Le impostazioni di partenza per Feed (lette no + giornaliero) e Paper Trail (lette sì + settimanale) restano un esempio, non una regola.
4. Attiva spento = Sieve non smista in quella cartella e la mail resta in INBOX. Tooltip: «Spenta: queste mail restano in Posta in arrivo».
5. Sotto l'intro, una riga: «Smistamento aggiornato <giorno g mese>», presa dall'mtime della testa dell'utente (`/laya/heads/<indirizzo>.joblib`, percorso configurabile). Senza testa: «Smistamento di base: si personalizza quando ci sono abbastanza mail».
6. Intro: «Le mail nuove vanno da sole nelle cartelle attive. Se una finisce nel posto sbagliato, spostala: ogni settimana lo smistamento impara dai tuoi spostamenti.»
7. «Smistata in Feed · Cambia»: Cambia apre il menu Sposta, con Posta in arrivo + le cartelle attive. Il segno ↻ e la voce nel menu ⋮ compaiono solo sulle cartelle attive.
8. Il digest ha una sezione per ogni cartella attiva con quella periodicità. Mai Posta in arrivo, quindi mai le mail delle persone.
9. Le etichette persone stanno in `smistamento_inbox_labels` (default `['Imbox']`). Nell'export `classes` Posta in arrivo è sempre la prima classe: `"mailbox": "INBOX"`, `"role": "inbox"`, `"label": "Imbox"`.
