# 📬 Outlook → AI → ClickUp Automatisering

**Laat AI je inbox opruimen en je taken aanmaken. Automatisch.**

> Gebouwd in de video: [Zo Automatiseer Je Outlook met Claude Code](https://www.youtube.com/watch?v=0W0zY4Bgnr0)
> Door Bart Boonstra — [Slim Werken Community](https://community.slimwerken.ai)

---

## Wat doet dit?

Je kent het: inbox vol, overal actie-items verstopt, en je moet zelf uitzoeken wat bij welke klant hoort. Dit project lost dat op.

Een AI leest je Outlook inbox, herkent automatisch welke klant een email stuurt, sorteert de mail in de juiste klantmap, en maakt taken aan in ClickUp — inclusief deadline en prioriteit. Elke dag, automatisch, via Modal.

```
┌─────────────────┐     ┌───────────────────────┐     ┌──────────────────────┐
│   📧 Outlook    │     │    🤖 AI Classificatie │     │   📋 ClickUp         │
│   Inbox + Spam  │────▶│   (Claude via          │────▶│   Klant → Folder     │
│                 │     │    OpenRouter)          │     │   Project → Lijst    │
└─────────────────┘     └───────────────────────┘     │   Email → Taak       │
                                │                      │   Actie → Subtaak    │
                                ▼                      └──────────────────────┘
                        ┌───────────────────────┐
                        │  📁 Outlook Mappen     │
                        │  Klant A / Klant B /.. │
                        └───────────────────────┘
```

**In gewoon Nederlands:**
1. Email komt binnen in Outlook
2. AI leest de email en bepaalt: welke klant? welk project? welke acties?
3. Email wordt verplaatst naar de juiste klantmap in Outlook
4. Taken worden aangemaakt in ClickUp (gesorteerd per klant en project)
5. Spam en nieuwsbrieven worden automatisch overgeslagen

---

## Wat leer je?

- Hoe je **Outlook koppelt aan AI** via de Composio MCP Server
- Hoe je **AI emails laat classificeren** met Claude (via OpenRouter)
- Hoe je **automatisch taken aanmaakt** in ClickUp via de API
- Hoe je dit **scheduled** zodat het elke dag vanzelf draait (Modal)
- Hoe je **Claude Code skills** bouwt (de drie "Lego blokken")

---

## Vereisten

| Wat                        | Waarvoor                                    |
|---------------------------|---------------------------------------------|
| **Claude Code abonnement** | Voor het bouwen en de skills                |
| **Outlook account**        | De mailbox die je wilt automatiseren        |
| **ClickUp account**        | Waar de taken naartoe gaan                  |
| **Modal account**           | Voor het automatisch draaien (gratis tier)  |
| **OpenRouter API key**      | AI classificatie (Claude via OpenRouter)    |
| **Composio account**        | Koppeling met Outlook (MCP Server)         |

---

## Quickstart

### 1. Clone het project

```bash
git clone https://github.com/slimwerken/outlook-to-clickup.git
cd outlook-to-clickup
```

### 2. Maak een virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Maak een `.env` bestand

```bash
cp .env.example .env  # of maak handmatig aan
```

Vul de volgende waardes in:

```env
COMPOSIO_API_KEY=jouw_composio_key
COMPOSIO_CONNECTED_ACCOUNT_ID=jouw_connection_id
OPENROUTER_API_KEY=jouw_openrouter_key
CLICKUP_API_KEY=jouw_clickup_key
```

### 4. Autoriseer Outlook

```bash
python setup_auth.py
```

Dit opent een device code flow — je logt in via je browser en het token wordt lokaal opgeslagen.

### 5. Test: classificeer emails

```bash
python classify.py --dry-run
```

Dit toont wat er zou gebeuren zonder iets te wijzigen. Tevreden? Draai zonder `--dry-run`:

```bash
python classify.py
```

### 6. Test: maak ClickUp taken aan

```bash
python clickup.py --dry-run
```

Zelfde verhaal — `--dry-run` om te kijken, zonder flag om het echt te doen:

```bash
python clickup.py
```

### 7. Deploy naar Modal (automatisch draaien)

```bash
modal deploy modal_app.py
```

Draait nu elke dag om 09:00 CET. Klaar.

---

## Hoe het werkt: de drie Lego blokken

Dit project is opgebouwd uit drie Claude Code skills die je los of samen kunt gebruiken:

### 🧱 Blok 1: `/mail` — Email classificatie
Leest je inbox en spam, laat AI bepalen wat waar hoort, en sorteert emails in klantmappen.

```
/mail  →  classify.py  →  Outlook mappen gesorteerd
```

### 🧱 Blok 2: `/clickup` — Taken aanmaken
Leest de gesorteerde klantmappen, detecteert projecten en acties met AI, en maakt taken aan in ClickUp.

```
/clickup  →  clickup.py  →  ClickUp taken aangemaakt
```

### 🧱 Blok 3: `/outlook-automatisering` — Alles samen
Draait eerst `/mail`, dan `/clickup`. Het complete proces in één commando.

```
/outlook-automatisering  →  classify.py + clickup.py  →  Inbox opgeruimd + taken klaar
```

---

## Bestanden

| Bestand            | Wat het doet                                                        |
|-------------------|---------------------------------------------------------------------|
| `classify.py`      | AI classificatie — leest inbox, sorteert in klantmappen            |
| `clickup.py`       | ClickUp integratie — maakt taken + acties aan per klant/project    |
| `modal_app.py`     | Modal scheduler — draait alles automatisch elke dag om 09:00 CET  |
| `setup_auth.py`    | Eenmalige Outlook autorisatie via device code flow                  |
| `requirements.txt` | Python dependencies                                                 |
| `.claude/commands/` | Claude Code skills (de drie Lego blokken)                          |

---

## Scheduling met Modal

Modal draait `modal_app.py` als een cronjob in de cloud. Standaard: elke dag om 09:00 CET.

```bash
# Deploy (eenmalig)
modal deploy modal_app.py

# Handmatig draaien (voor testen)
modal run modal_app.py

# Logs bekijken
modal app logs outlook-clickup
```

**API keys in Modal:** sla je op als Modal Secret (nooit in code):

```bash
modal secret create outlook-clickup-secrets \
  COMPOSIO_API_KEY=xxx \
  COMPOSIO_CONNECTED_ACCOUNT_ID=xxx \
  OPENROUTER_API_KEY=xxx \
  CLICKUP_API_KEY=xxx
```

---

## Beveiliging

- **API keys** staan in `.env` (lokaal) of Modal Secrets (cloud) — **nooit** in de code
- `.env` staat in `.gitignore` — wordt niet mee gecommit
- `token_cache.json` bevat je Outlook token — **deel dit nooit**
- Composio handelt OAuth af — je deelt nooit je wachtwoord met de code

> **Regel:** als een bestand API keys of tokens bevat, hoort het in `.gitignore`.

---

## Links

- **Video:** [Zo Automatiseer Je Outlook met Claude Code](https://www.youtube.com/watch?v=0W0zY4Bgnr0)
- **Community:** [community.slimwerken.ai](https://community.slimwerken.ai)
- **Vragen?** Stel ze in de community — daar helpen we je verder

---

## Licentie

MIT — gebruik het, pas het aan, maak het beter. Zie [LICENSE](LICENSE) voor details.
