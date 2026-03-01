# /clickup — Verwerk emails naar ClickUp

Je bent een e-mail verwerking agent. Voer onderstaande stappen exact en in volgorde uit.

---

## Stap 1: Haal ongelezen emails op uit Outlook klantmappen

```
cd "/Users/bartboonstra/Documents/SW COMM/AI APPS/OUTLOOK -> CLICKUP" && source venv/bin/activate && python3 -c "
import os, json
from composio import ComposioToolSet
from bs4 import BeautifulSoup
from dotenv import load_dotenv
load_dotenv()

SYSTEM_FOLDERS = {
    'Inbox','Drafts','Sent Items','Deleted Items','Junk Email','Archive','Outbox',
    'Conversation History','Archiveren','Concepten','Verzonden items','Verwijderde items',
    'Ongewenste e-mail','Postvak UIT','Postvak IN','Gesprekgeschiedenis',
}
SKIP_DOMAINS = {'microsoft.com','notificationmail.microsoft.com','accountprotection.microsoft.com','linkedin.com','no-reply.com'}

toolset = ComposioToolSet(api_key=os.getenv('COMPOSIO_API_KEY'))
conn_id = os.getenv('COMPOSIO_CONNECTED_ACCOUNT_ID')

def call(action, params):
    r = toolset.execute_action(action=action, params=params, connected_account_id=conn_id)
    d = r.get('data', {})
    return d.get('value') or d.get('response_data', {}).get('value') or d.get('response_data') or d

folders_raw = call('OUTLOOK_OUTLOOK_LIST_MAIL_FOLDERS', {'user_id': 'me'})
client_folders = [f for f in (folders_raw or []) if f.get('displayName') not in SYSTEM_FOLDERS]

result = []
for folder in client_folders:
    msgs_raw = toolset.execute_action(action='OUTLOOK_OUTLOOK_LIST_MESSAGES', params={'user_id':'me','folder':folder['id'],'is_read':False,'top':50,'select':['id','subject','from','body','receivedDateTime']}, connected_account_id=conn_id)
    msgs_d = msgs_raw.get('data', {})
    msgs = msgs_d.get('value') or msgs_d.get('response_data', {}).get('value', [])
    for m in msgs:
        addr = m.get('from',{}).get('emailAddress',{}).get('address','')
        domain = addr.split('@')[-1].lower() if '@' in addr else ''
        if domain in SKIP_DOMAINS:
            continue
        body_html = m.get('body',{}).get('content','')
        body_text = BeautifulSoup(body_html, 'html.parser').get_text(separator='\n', strip=True)[:3000]
        result.append({'msg_id': m['id'], 'client': folder['displayName'], 'subject': m.get('subject',''), 'sender': addr, 'sender_name': m.get('from',{}).get('emailAddress',{}).get('name',''), 'body': body_text})

print(json.dumps(result, ensure_ascii=False))
"
```

De output is een JSON-lijst van emails. Sla die in je werkgeheugen op.

---

## Stap 2: Analyseer elke email — detecteer projecten + acties

Analyseer voor **elke email** de volgende punten op basis van de inhoud:

**Projectdetectie (cruciaal):**
- Identificeer alle projecten die in de email worden besproken. Één email kan meerdere projecten bevatten.
- Gebruik de exacte naam die in de email staat (bijv. "Landingspagina", "KPN Video", "Website Redesign").
- Als het project niet duidelijk is of de actie nergens toe behoort: gebruik "Overig".

**Actie-extractie:**
- Extraheer alleen concrete, uitvoerbare actiepunten.
- Koppel elke actie aan het bijbehorende project.
- Voeg deadline toe als die vermeld staat.

Maak intern een structuur zoals:
```
email: "check dit"
client: "Grow Media"
projecten:
  - project: "Landingspagina"
    acties: ["Header 20px groter maken"]
  - project: "KPN Video"
    acties: ["Alle intro's ietsje korter maken"]
```

---

## Stap 3: Maak ClickUp taken aan via de API

Gebruik de volgende constanten:
- **Space ID:** `901510293981` ([DEMO] Email Automatisering)
- **Inbox lijst ID:** `901521652289` (voor niet-toewijsbare emails)
- **API key:** uit `.env` als `CLICKUP_API_KEY`

Per email:
1. **Zorg voor ClickUp folder** (klant): maak aan als niet bestaat
   - `POST https://api.clickup.com/api/v2/space/901510293981/folder`
   - Controleer eerst of de folder al bestaat: `GET https://api.clickup.com/api/v2/space/901510293981/folder?archived=false`

2. **Zorg voor ClickUp lijst** (project): maak aan per gedetecteerd project als niet bestaat
   - `POST https://api.clickup.com/api/v2/folder/{folder_id}/list`
   - Controleer eerst of de lijst al bestaat

3. **Maak email-taak aan** in de eerste projectlijst
   - Naam: onderwerp van de email
   - Beschrijving: `Van: {afzender}\n\n{body}`
   - Voeg tag `email` toe: `POST https://api.clickup.com/api/v2/task/{task_id}/tag/email`

4. **Maak actie-taken aan** in de juiste projectlijst
   - Naam: de actietekst
   - Beschrijving: `Geëxtraheerd uit email: {onderwerp}`
   - Voeg tag `actie` toe: `POST https://api.clickup.com/api/v2/task/{task_id}/tag/actie`

Gebruik overal `Authorization: {CLICKUP_API_KEY}` en `Content-Type: application/json` als headers.

---

## Stap 4: Markeer emails als gelezen in Outlook

Na succesvol aanmaken in ClickUp, markeer elke verwerkte email als gelezen:

```
cd "/Users/bartboonstra/Documents/SW COMM/AI APPS/OUTLOOK -> CLICKUP" && source venv/bin/activate && python3 -c "
import os
from composio import ComposioToolSet
from dotenv import load_dotenv
load_dotenv()
toolset = ComposioToolSet(api_key=os.getenv('COMPOSIO_API_KEY'))
conn_id = os.getenv('COMPOSIO_CONNECTED_ACCOUNT_ID')
msg_ids = {MSG_IDS_HIER}
for msg_id in msg_ids:
    toolset.execute_action(action='OUTLOOK_OUTLOOK_UPDATE_EMAIL', params={'user_id':'me','message_id':msg_id,'is_read':True}, connected_account_id=conn_id)
print('Klaar')
"
```

Vervang `{MSG_IDS_HIER}` door de daadwerkelijke lijst van `msg_id` values uit stap 1.

---

## Stap 5: Rapporteer resultaten

Geef een overzicht:
- Per klant: welke emails verwerkt
- Per email: welke projecten gedetecteerd, hoeveel taken aangemaakt
- Wat overgeslagen is en waarom
