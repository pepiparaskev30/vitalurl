# CheckMyURL

Εργαλείο της Διεύθυνσης Δίωξης Κυβερνοεγκλήματος για τον έλεγχο καταγγελλόμενων URL από αρχείο Excel.

Για κάθε URL ελέγχει αν ο ιστότοπος είναι ενεργός, εντοπίζει ανακατευθύνσεις (HTTP, meta refresh, JavaScript) και αποκωδικοποιεί Outlook Safe Links. Στο τέλος παράγει το ενημερωμένο αρχείο προς ΕΑΚ και στατιστικά ανά κατηγορία φορέα.

Δουλεύει με τη σελίδα (drag & drop) ή απευθείας μέσω API.

## Εκκίνηση με Docker

```bash
docker compose up -d --build
```

Άνοιγμα στον browser: http://127.0.0.1:8000

| Εντολή | Πότε |
|---|---|
| `docker compose logs -f` | προβολή logs |
| `docker compose restart` | μετά από αλλαγή στα JSON ρυθμίσεων |
| `docker compose up -d --build` | μετά από αλλαγή σε κώδικα ή UI |
| `docker compose down` | σταμάτημα |

## Εγκατάσταση χωρίς Docker (υπολογιστής / VM)

Απαιτείται **Python 3.10+**. Σε Ubuntu/Debian: `sudo apt install python3 python3-venv`

```bash
chmod +x checkmyurl.sh     # μόνο την πρώτη φορά
./checkmyurl.sh
```

Την πρώτη φορά το script δημιουργεί virtual environment (`.venv/`) και εγκαθιστά τα πακέτα. Στις επόμενες εκτελέσεις ξεκινά αμέσως — ξαναεγκαθιστά πακέτα μόνο αν αλλάξει το `requirements.txt`.

| Εντολή | |
|---|---|
| `./checkmyurl.sh` | εγκατάσταση (αν χρειάζεται) και εκκίνηση |
| `./checkmyurl.sh --install-only` | μόνο εγκατάσταση |
| `HOST=0.0.0.0 PORT=9000 ./checkmyurl.sh` | άλλη διεύθυνση / port |

Τερματισμός με **Ctrl+C**.

Σε Windows: χρήση μέσω Docker ή WSL.

## Χρήση

### Αρχείο εισόδου

Ένα `.xlsx` ή `.xlsm` με μία γραμμή ανά καταγγελία. Απαραίτητη είναι μόνο η στήλη με το URL. Οι επικεφαλίδες αντιστοιχίζονται αυτόματα στη μορφή της ΕΑΚ, ακόμα κι αν έχουν επιπλέον κατάληξη (π.χ. `URL ή ΙΡ ΑΝΑΚΑΤΕΥΘΥΝΣΗΣ (URLSCAN/WHEREGOES/VIRUSTOTAL)`), και όσες δεν αντιστοιχούν αγνοούνται. Αναγνωρίζονται defanged μορφές (`hxxps[://]`, `hxxps:[://]`, `[.]`, `[dot]`) και Outlook Safe Links.

### Βήματα

1. Σύρετε το αρχείο `.xlsx` στη σελίδα.
2. Επιλέξτε αν θα γίνει έλεγχος και ανίχνευση ανακατευθύνσεων.
3. Πατήστε **Έλεγχος**.
4. Κατεβάστε:
   - **Λήψη Excel** → `προς_ΕΑΚ_ΗΗ-ΜΜ-ΕΕΕΕ.xlsx`
   - **Λήψη στατιστικών** → `Στατιστικά_ΗΗ-ΜΜ-ΕΕΕΕ.xlsx`
   - **Λήψη CSV / JSON** → τα ίδια δεδομένα σε άλλη μορφή

Στο παραγόμενο αρχείο τα URL γράφονται σε **defanged** μορφή, ώστε να μην πατιούνται κατά λάθος.

## API

Όλα γίνονται και από terminal, χωρίς τη σελίδα.

Για τον έλεγχο ενός μεμονωμένου URL, δες την ενότητα **Cybercop** παρακάτω.

**Έλεγχος αρχείου**:

```bash
ID=$(curl -s -X POST "http://127.0.0.1:8000/api/check?check=true&redirects=true&max_rows=1000" \
          -F "file=@phishing.xlsx" | tee result.json | python3 -c "import sys,json;print(json.load(sys.stdin)['file_id'])")

curl -s -OJ "http://127.0.0.1:8000/api/download/$ID"          # προς_ΕΑΚ_ΗΗ-ΜΜ-ΕΕΕΕ.xlsx
curl -s -OJ "http://127.0.0.1:8000/api/download/$ID/stats"    # Στατιστικά_ΗΗ-ΜΜ-ΕΕΕΕ.xlsx
```

| Endpoint | |
|---|---|
| `POST /cybercop?url=…` | έλεγχος ενός URL, απάντηση σε JSON |
| `POST /api/check` | έλεγχος αρχείου Excel |
| `GET /api/download/{file_id}` | το αρχείο προς ΕΑΚ |
| `GET /api/download/{file_id}/stats` | τα στατιστικά |
| `GET /api/deep-modes` | ποιος τρόπος βαθέος ελέγχου είναι διαθέσιμος |
| `GET /docs` | αυτόματη τεκμηρίωση και δοκιμή στον browser |

## Cybercop — έλεγχος ενός URL

Endpoint για γρήγορο έλεγχο ενός συνδέσμου, χωρίς αρχείο Excel. Χρήσιμο για άμεση απάντηση σε ερώτημα συναδέλφου, για δοκιμή ενός ύποπτου συνδέσμου ή για κλήση από άλλο script.

```
POST /cybercop?url=<URL>&deep=<true|false>
```

| Παράμετρος | Default | |
|---|---|---|
| `url` | — | το URL, σε defanged ή κανονική μορφή. Δεκτά: `hxxps[://]`, `hxxps:[://]`, `[.]`, `[dot]`, Outlook Safe Links |
| `deep` | false | επιπλέον έλεγχος με headless browser ή urlscan, για ανακατευθύνσεις μέσω JavaScript |

### Παράδειγμα

```bash
curl -sg -X POST "http://127.0.0.1:8000/cybercop?url=hxxps:[://]example[.]com/login" | python3 -m json.tool
```

Το `-g` χρειάζεται επειδή τα `[ ]` είναι ειδικοί χαρακτήρες για το shell. Εναλλακτικά:

```bash
curl -s -X POST "http://127.0.0.1:8000/cybercop" \
     --get --data-urlencode "url=hxxps:[://]example[.]com/login"
```

### Απάντηση

```json
{
  "input": "hxxps:[://]example[.]com/login",
  "url": "https://example.com/login",
  "defanged": "hxxps[://]example[.]com/login",
  "status": "ACTIVE (REDIRECT → final.example)",
  "status_gr": "ΕΝΕΡΓΟ (ΑΝΑΚΑΤΕΥΘΥΝΣΗ → final.example)",
  "category": "active",
  "active": true,
  "redirected": true,
  "final_url": "https://final.example/x",
  "final_url_defanged": "hxxps[://]final[.]example/x",
  "chain": ["https://example.com/login", "https://final.example/x"],
  "chain_defanged": ["hxxps[://]example[.]com/login", "hxxps[://]final[.]example/x"],
  "hops": 1
}
```

| Πεδίο | |
|---|---|
| `input` | το URL όπως δόθηκε |
| `url` | μετά από refang και αποκωδικοποίηση Safe Link |
| `status` / `status_gr` | η κατάσταση στα αγγλικά και στα ελληνικά |
| `category` | `active`, `down` ή `error` (βλ. Καταστάσεις) |
| `active` | true μόνο αν ο ιστότοπος λειτουργεί |
| `redirected` / `hops` | αν υπήρξε ανακατεύθυνση και πόσα βήματα |
| `final_url` | ο τελικός προορισμός |
| `chain` | όλη η διαδρομή, από το αρχικό ως το τελικό URL |

Τα πεδία με κατάληξη `_defanged` είναι έτοιμα για αντιγραφή σε αναφορά ή email.

### Σφάλματα

| Κωδικός | |
|---|---|
| 400 | το URL δεν είναι έγκυρο μετά το refang |
| 200 με `"category": "down"` | ο ιστότοπος δεν απαντά — δες το `status` για τον λόγο |

Ο έλεγχος δοκιμάζει όλους τους User-Agents του `agents.json` και σταματά στον πρώτο που πάρει απάντηση, οπότε ένα URL που κρύβεται από desktop browser αλλά απαντά σε κινητό βγαίνει **ACTIVE**.

## Βαθύς έλεγχος (προαιρετικά)

Το `requests` δεν εκτελεί JavaScript, οπότε χάνει ανακατευθύνσεις που γίνονται από τη σελίδα. Η επιλογή **Βαθύς έλεγχος** ανοίγει τα URL σε πραγματικό browser, μόνο για τις γραμμές που είναι **Ενεργά** ή **Αβέβαιο**, έως `DEEP_LIMIT` γραμμές.

Τρεις τρόποι, κατά σειρά προτίμησης:

```bash
# Α. Τοπικός headless browser — τίποτα δεν φεύγει σε τρίτους, χωρίς όρια
pip install playwright && playwright install chromium

# Β. urlscan.io με κλειδί — νέο scan, report και screenshot
export URLSCAN_API_KEY="..."
export URLSCAN_VISIBILITY=unlisted   # ποτέ public σε URL ενεργής υπόθεσης

# Γ. Χωρίς τίποτα από τα παραπάνω: αναζήτηση σε υπάρχοντα scans του urlscan.io.
#    Δεν υποβάλλεται τίποτα, βρίσκει μόνο ό,τι έχει ήδη σκαναριστεί από άλλους.
```

Αν βρεθεί αλυσίδα που δεν είχε εντοπίσει ο απλός έλεγχος, γράφεται στη στήλη ανακατεύθυνσης του αρχείου.

## Καταστάσεις

| Ομάδα | Σημαίνει |
|---|---|
| Ενεργά | ο ιστότοπος λειτουργεί |
| Εκτός λειτουργίας | δεν υπάρχει DNS, 404, 410 ή σελίδα αναστολής |
| Αβέβαιο | 403, timeout, σφάλμα SSL κ.λπ. — μπορεί να λειτουργεί για πραγματικά θύματα |
| Χωρίς έλεγχο | κενό κελί ή απενεργοποιημένος έλεγχος |

Οι αιτήσεις προς τους ιστοτόπους γίνονται από τη σύνδεση του υπολογιστή που τρέχει την εφαρμογή.

## Ρυθμίσεις

Αρχεία στον φάκελο `src/` — αλλάζουν χωρίς αλλαγή κώδικα:

| Αρχείο | Περιεχόμενο |
|---|---|
| `agents.json` | User-Agents που δοκιμάζονται για κάθε URL |
| `dictionary.json` | αντιστοίχιση στηλών εισόδου → εξόδου |
| `status_gr.json` | ελληνική μετάφραση καταστάσεων |
| `brand_categories.json` | λέξεις-κλειδιά για τις κατηγορίες (Τράπεζες, E-shop, Ταχυδρομείο / Courier, Κρατικοί φορείς) |

Μεταβλητές περιβάλλοντος (στο `.env`, βλ. `.env.example`):

| Μεταβλητή | Default | |
|---|---|---|
| `WORKERS` | 20 | παράλληλοι έλεγχοι |
| `MAX_UPLOAD_MB` | 20 | μέγιστο μέγεθος αρχείου |
| `DEEP_MODE` | auto | βαθύς έλεγχος: auto, playwright, urlscan ή search |
| `DEEP_LIMIT` | 30 | μέγιστες γραμμές ανά βαθύ έλεγχο |
| `URLSCAN_API_KEY` | — | κλειδί urlscan.io |
| `URLSCAN_VISIBILITY` | unlisted | unlisted, private ή public |
| `HOST` | 127.0.0.1 | διεύθυνση (μόνο για `checkmyurl.sh`) |
| `PORT` | 8000 | port (μόνο για `checkmyurl.sh`) |

## Δομή

```
├── src/
│   ├── app.py          API (FastAPI)
│   ├── pipeline.py     ροή ελέγχου ενός αρχείου
│   ├── utilities.py    έλεγχος URL, refang/defang, Safe Links, ανακατευθύνσεις
│   ├── stats.py        στατιστικά ανά κατηγορία
│   ├── deepcheck.py    βαθύς έλεγχος (playwright / urlscan)
│   └── *.json          ρυθμίσεις
├── static/             UI (index.html, logo)
├── output/             παραγόμενα αρχεία
├── checkmyurl.sh       εγκατάσταση και εκκίνηση χωρίς Docker
├── Dockerfile
└── docker-compose.yml
```

Τα αρχεία στο `output/` δεν διαγράφονται αυτόματα.

## Ασφάλεια λειτουργίας

Το εργαλείο επισκέπτεται κακόβουλους ιστοτόπους, οπότε τρέχει:

- **εκτός του Δικτύου Σύζευξις**, ώστε οι αιτήσεις να μην ξεκινούν από το υπηρεσιακό δίκτυο,
- **σε απομονωμένο VM ή sandbox**, χωρίς πρόσβαση σε υπηρεσιακά συστήματα και αρχεία,
- **με δυναμική IP**, ώστε η διεύθυνση να μην γίνει flag από τους δράστες.

Το αρχείο εισόδου μεταφέρεται με **read-only shared folder** και το παραγόμενο κατεβαίνει από τον browser, ώστε να μην υπάρχει δίαυλος εγγραφής από το VM προς τον υπολογιστή.

Με βαθύ έλεγχο σε λειτουργία `playwright`, ο browser **εκτελεί** τον κώδικα της σελίδας — η απομόνωση γίνεται υποχρεωτική. Σε λειτουργία `urlscan`, τα scans πρέπει να είναι `unlisted` ή `private`: σε `public` είναι ορατά και στους δράστες.

---

© 2026 Ευτέρπη Γ. Παρασκευουλάκου
