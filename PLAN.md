# Piano di progetto — chess-llm-tutor

Contesto: progetto da portfolio, Python, alcune settimane part-time.

Il rischio principale in un progetto così non è tecnico, è di scope: c'è una
tentazione fortissima di aggiungere il fine-tuning, l'interfaccia web, il bot
che gioca. Il piano qui sotto è costruito perché alla fine di **ogni** settimana
esista qualcosa di mostrabile, e perché il progetto resti presentabile anche se
ti fermi in anticipo.

---

## Le domande di ricerca

Tre, in ordine di quanto sono interessanti se la risposta è "sì".

**RQ1 — La rappresentazione conta più della difficoltà?**
Stessa posizione, quattro descrizioni diverse (FEN nuda, diagramma ASCII, lista
esplicita dei pezzi, lista + mosse legali). Se la lista dei pezzi batte
nettamente la FEN, il collo di bottiglia è *percettivo* — il modello fatica a
decomprimere la notazione, non a vedere la tattica. È il risultato più
citabile del progetto perché ha implicazioni pratiche immediate su come si
scrivono i prompt.

**RQ2 — Dove si rompe la curva?**
Accuratezza per fascia di rating. L'ipotesi è che il crollo non sia graduale
ma netto attorno a una certa profondità di calcolo: i puzzle in cui la mossa
giusta è "visibile" (una cattura, uno scacco che vince materiale subito) vanno
bene, quelli che richiedono di vedere la risposta avversaria no.

**RQ3 — Riconoscere il motivo è più facile che trovare la mossa?**
Il modello dichiara anche il tema tattico. Se il tasso di temi corretti è molto
più alto di quello delle mosse corrette, significa che il modello *capisce* il
tipo di posizione ma non sa calcolare — e questo è esattamente ciò che
autorizza il design del tutor: gli chiedi di spiegare, non di calcolare.

---

## Settimana per settimana

### Settimana 1 — Dati e baseline

- `python scripts/download_puzzles.py --per-cell 25` → ~2.000 puzzle
- Far girare il benchmark con le sole baseline (`--dry-run`)
- Guardare a mano 20 puzzle del campione e verificare che siano sensati

Alla fine devi avere: la tabella di accuratezza di `random` e
`stockfish_d1/d2/d4` per fascia di rating. Non è ancora un risultato, ma è il
metro su cui appoggerai tutto il resto — e ti dice se il campione è bilanciato.

*Trappola:* se `random` risolve più del 5-8% hai probabilmente sbagliato a
estrarre la posizione dal dataset (vedi il README sul campo FEN).

### Settimana 2 — L'LLM entra in scena

- Primo run vero su un sottocampione di 200 puzzle, una sola rappresentazione
- Leggere **a mano** 30 risposte prima di guardare qualsiasi numero

Questa lettura manuale è il passaggio che quasi tutti saltano ed è il più
utile: scoprirai che una parte degli errori non sono errori tattici ma di
formato, di notazione ambigua, o il modello che descrive una posizione diversa
da quella che gli hai dato. Sistemare il parser *dopo* aver visto le risposte
reali è molto più efficace che immaginarsi i casi limite.

- Poi il run completo su tutte le rappresentazioni

### Settimana 3 — Analisi e grafici

- Accuratezza x rappresentazione, con barre d'errore (RQ1)
- Curva accuratezza x fascia di rating, una linea per rappresentazione (RQ2)
- Confronto tasso-mossa vs tasso-tema (RQ3)
- Heatmap per tema: dove il modello è cieco

Un grafico che vale la pena aggiungere: distribuzione della perdita in
centipawn quando il modello sbaglia. Dice se le mosse sbagliate sono "quasi
giuste" o catastrofiche, e sono due storie molto diverse.

### Settimana 4 — Il tutor

- Scaricare le tue partite, girare `analyse_pgn_file`, produrre il profilo
- Generare puzzle personalizzati dalle posizioni in cui hai sbagliato
- Generare le spiegazioni con la configurazione vincente del benchmark
- Un piccolo report HTML: "ecco i tuoi 10 errori peggiori del mese, ecco
  perché, ecco 10 puzzle costruiti sulle tue posizioni"

### Se avanza tempo

In ordine di rapporto valore/sforzo:

- **Self-consistency**: chiedere la mossa 5 volte e prendere la maggioranza.
  Costa poco da implementare e di solito il guadagno è notevole — misurarlo è
  un risultato in più quasi gratis.
- **Ablation sul prompt**: quanto vale il chain-of-thought esplicito? Vale la
  pena elencare le mosse legali? (`piece_list_moves` è già lì per questo.)
- **Confronto multi-modello**: stessa pipeline, modelli diversi. Facile, ma
  invecchia in fretta.
- Interfaccia web con `chessboard.js` per il tutor.

---

## Criteri di successo

Il progetto è riuscito se, alla fine, puoi scrivere queste tre frasi con dei
numeri veri dentro:

1. "La rappresentazione X supera la FEN di N punti percentuali (IC 95%: …)."
2. "L'accuratezza crolla da A% a B% attraversando la soglia dei ~R punti di
   rating."
3. "Il modello identifica il motivo tattico nel C% dei casi in cui non trova la
   mossa — per questo il tutor gli fa spiegare l'output del motore invece di
   calcolare."

Se hai queste tre, hai un progetto. Tutto il resto è contorno.

---

## Cosa NON fare

**Non addestrare una rete da zero.** Con qualche settimana part-time finirai
con un modello che gioca male e nessun risultato da raccontare. Se ti interessa
il lato training, la strada sensata è fine-tunare
[Maia](https://github.com/CSSLab/maia-chess) sulle tue partite — parti da pesi
già buoni e la domanda ("gioca come me?") è ben definita.

**Non costruire l'interfaccia prima dei risultati.** È la cosa più divertente
da fare e la meno informativa; e se la fai prima, finirai per progettare
l'esperimento attorno a quello che l'interfaccia sa già mostrare.

**Non fidarti delle varianti prodotte dall'LLM.** Ogni linea che finisce in un
output visibile all'utente deve venire dalla PV di Stockfish. È per questo che
`EXPLAIN_PROMPT` vieta esplicitamente di inventare varianti: senza quel
vincolo il tutor produce analisi eloquenti e sbagliate, che è il peggior
risultato possibile per uno strumento didattico.
