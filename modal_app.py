"""
Modal scheduler: verwerkt Outlook emails naar ClickUp elke dag om 09:00 CET.
Draait classify + clickup logica op Modal cloud.

Deploy:  modal deploy modal_app.py
Run nu:  modal run modal_app.py
Logs:    modal app logs outlook-clickup
"""

import modal

# ─── Image met alle dependencies ──────────────────────────────────────────────
image = (
    modal.Image.debian_slim(python_version="3.11")
    .env({"PYTHONUNBUFFERED": "1"})  # direct stdout flush in Modal logs
    .pip_install([
        "openai",
        "composio-core",
        "requests",
        "python-dotenv",
        "beautifulsoup4",
    ])
)

# ─── Secrets uit Modal's beveiligde vault (nooit in broncode) ─────────────────
# Beheren via: modal secret create outlook-clickup-secrets KEY=value ...
# Of via: https://modal.com/secrets

app = modal.App("outlook-clickup", image=image)


# ─── Gedeelde code: classify + clickup logica inline ──────────────────────────
# Cron: "0 8 * * *" = 08:00 UTC = 09:00 CET (winter) / 10:00 CEST (zomer)
# Pas aan naar "0 7 * * *" in de zomer voor exact 09:00 CEST
@app.function(
    schedule=modal.Cron("0 8 * * *"),
    secrets=[modal.Secret.from_name("outlook-clickup-secrets")],
)
def verwerk_emails():
    """Hoofdtaak: classify → clickup. Draait dagelijks om 09:00 CET."""
    import os, json, re
    from bs4 import BeautifulSoup
    from openai import OpenAI
    from composio import ComposioToolSet
    import requests

    COMPOSIO_KEY = os.environ["COMPOSIO_API_KEY"]
    CONN_ID      = os.environ["COMPOSIO_CONNECTED_ACCOUNT_ID"]
    OR_KEY       = os.environ["OPENROUTER_API_KEY"]
    CU_KEY       = os.environ["CLICKUP_API_KEY"]
    CU_SPACE     = "901510293981"

    SYSTEM_FOLDERS = {
        "Inbox","Drafts","Sent Items","Deleted Items","Junk Email","Archive","Outbox",
        "Conversation History","Archiveren","Concepten","Verzonden items","Verwijderde items",
        "Ongewenste e-mail","Postvak UIT","Postvak IN","Gesprekgeschiedenis",
    }
    SKIP_DOMAINS = {
        "microsoft.com","notificationmail.microsoft.com",
        "accountprotection.microsoft.com","linkedin.com","no-reply.com",
    }

    toolset    = ComposioToolSet(api_key=COMPOSIO_KEY)
    cu_headers = {"Authorization": CU_KEY, "Content-Type": "application/json"}
    ai         = OpenAI(api_key=OR_KEY, base_url="https://openrouter.ai/api/v1")

    # ── Helpers ────────────────────────────────────────────────────────────────
    def composio(action, params):
        r = toolset.execute_action(action=action, params=params, connected_account_id=CONN_ID)
        d = r.get("data", {})
        return d.get("value") or d.get("response_data", {}).get("value") or d.get("response_data") or d

    def extract_text(html):
        if not html:
            return ""
        return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)

    def classify(sender_name, sender_email, subject, body, known_clients):
        known = ", ".join(known_clients) if known_clients else "(geen)"
        prompt = f"""Je bent een email-sorteerder voor slimwerkentester@outlook.com.
AFZENDER: {sender_name} <{sender_email}>
ONDERWERP: {subject}
BODY:
{body[:3000]}
BESTAANDE KLANTMAPPEN: {known}

Geef JSON: {{"action":"skip"/"sort","client":"naam of null","project":"projectnaam","reason":"uitleg"}}
- skip: nieuwsbrief, automatische notificatie, spam
- sort: zakelijke of persoonlijke mail van extern bedrijf/contact
- client: uit emaildomein (geen bedrijfsdomein → afzendernaam)
- Alleen geldige JSON."""
        r = ai.chat.completions.create(
            model="anthropic/claude-sonnet-4-5", max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = r.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group()) if m else {"action": "skip", "reason": "parse fout"}

    def extract_projects(subject, body, sender, existing_lists):
        namen = list(existing_lists.keys())
        prompt = f"""Analyseer deze zakelijke email. Detecteer alle projecten en bijbehorende acties.
Map elk project naar de meest passende bestaande ClickUp lijst als die semantisch overeenkomt.

AFZENDER: {sender}
ONDERWERP: {subject}
BODY:
{body[:3000]}

BESTAANDE CLICKUP LIJSTEN: {json.dumps(namen, ensure_ascii=False)}

Geef JSON:
{{"projecten":[{{"lijst":"naam bestaande of nieuwe lijst","is_nieuw":false,"acties":["→ Actie"]}}]}}

Regels:
- Map semantisch: "landingspagina"→"Website Redesign", "hosting probleem"→"Hosting & Beheer"
- is_nieuw=true alleen als geen bestaande lijst past
- Acties: uitvoerbaar, begin met "→ ", deadline indien vermeld
- Geen inhoud → {{"projecten":[{{"lijst":"Overig","is_nieuw":false,"acties":[]}}]}}
- Alleen geldige JSON."""
        r = ai.chat.completions.create(
            model="anthropic/claude-sonnet-4-5", max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = r.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group()).get("projecten", []) if m else []

    # ── ClickUp helpers ────────────────────────────────────────────────────────
    def get_cu_folders():
        r = requests.get(f"https://api.clickup.com/api/v2/space/{CU_SPACE}/folder?archived=false", headers=cu_headers)
        folders = {}
        for f in r.json().get("folders", []):
            folders[f["name"].lower()] = {
                "id": f["id"], "name": f["name"],
                "lists": {lst["name"].lower(): lst["id"] for lst in f.get("lists", [])}
            }
        return folders

    def ensure_folder(name, cu_folders):
        key = name.lower()
        if key in cu_folders:
            return cu_folders[key]
        r = requests.post(f"https://api.clickup.com/api/v2/space/{CU_SPACE}/folder", headers=cu_headers, json={"name": name})
        f = r.json()
        entry = {"id": f["id"], "name": f["name"], "lists": {}}
        cu_folders[key] = entry
        return entry

    def ensure_list(name, folder_entry):
        key = name.lower()
        if key in folder_entry["lists"]:
            return folder_entry["lists"][key]
        r = requests.post(f"https://api.clickup.com/api/v2/folder/{folder_entry['id']}/list", headers=cu_headers, json={"name": name})
        lst = r.json()
        folder_entry["lists"][key] = lst["id"]
        return lst["id"]

    def add_tag(task_id, tag):
        requests.post(f"https://api.clickup.com/api/v2/task/{task_id}/tag/{tag}", headers=cu_headers)

    def create_task(list_id, name, desc, tag):
        r = requests.post(f"https://api.clickup.com/api/v2/list/{list_id}/task", headers=cu_headers,
                          json={"name": name, "description": desc, "status": "to do", "notify_all": False})
        t = r.json()
        add_tag(t["id"], tag)
        return t

    # ── Stap 1: classify + sorteren ───────────────────────────────────────────
    print("=== STAP 1: Classify ===")
    folders_raw = composio("OUTLOOK_OUTLOOK_LIST_MAIL_FOLDERS", {"user_id": "me"})
    client_folders = {f["displayName"]: f["id"] for f in (folders_raw or []) if f.get("displayName") not in SYSTEM_FOLDERS}
    known_clients = list(client_folders.keys())

    # Bijhouden welke emails in stap 1 gesorteerd zijn → stap 2 verwerkt die ook
    nieuw_gesorteerd = []  # [{msg_id, client, body_text, subject, sender}]
    s1_gesorteerd = s1_overgeslagen = 0

    for src_folder in ["inbox", "junkemail"]:
        msgs_raw = toolset.execute_action(
            action="OUTLOOK_OUTLOOK_LIST_MESSAGES",
            params={"user_id": "me", "folder": src_folder, "is_read": False, "top": 50,
                    "select": ["id", "subject", "from", "body", "receivedDateTime"]},
            connected_account_id=CONN_ID,
        )
        msgs_d = msgs_raw.get("data", {})
        msgs = msgs_d.get("value") or msgs_d.get("response_data", {}).get("value", [])

        for msg in msgs:
            addr_info = msg.get("from", {}).get("emailAddress", {})
            sender_email = addr_info.get("address", "")
            sender_name  = addr_info.get("name", "")
            subject      = msg.get("subject", "")
            body_html    = msg.get("body", {}).get("content", "")
            body_text    = extract_text(body_html)[:3000]
            msg_id       = msg["id"]

            print(f"  ▶ {subject} ({sender_email})")
            try:
                result = classify(sender_name, sender_email, subject, body_text, known_clients)
            except Exception as e:
                print(f"    ✗ Classify fout: {e}")
                s1_overgeslagen += 1
                continue

            if result["action"] == "skip":
                print(f"    → Skip: {result.get('reason','')}")
                s1_overgeslagen += 1
                continue

            client = result.get("client")
            if not client:
                print("    → Geen klantnaam, overgeslagen")
                s1_overgeslagen += 1
                continue

            # Zorg voor klantmap in Outlook
            if client not in client_folders:
                new_folder = composio("OUTLOOK_CREATE_MAIL_FOLDER", {"displayName": client, "user_id": "me"})
                folder_id = (new_folder or {}).get("id") or (new_folder or {}).get("response_data", {}).get("id")
                client_folders[client] = folder_id
                known_clients.append(client)
                print(f"    + Outlook map aangemaakt: {client}")

            composio("OUTLOOK_OUTLOOK_MOVE_MESSAGE", {
                "message_id": msg_id,
                "destination_id": client_folders[client],
                "user_id": "me",
            })
            s1_gesorteerd += 1
            print(f"    → Gesorteerd naar: {client} | project: {result.get('project','?')}")

            # Bewaar voor directe verwerking in stap 2 (vermijdt Outlook API latency)
            nieuw_gesorteerd.append({
                "msg_id": msg_id, "client": client,
                "subject": subject, "sender": f"{sender_name} <{sender_email}>",
                "body_text": body_text,
            })

    print(f"\nStap 1 klaar: {s1_gesorteerd} gesorteerd, {s1_overgeslagen} overgeslagen")

    # ── Stap 2: ClickUp taken aanmaken ────────────────────────────────────────
    print("\n=== STAP 2: ClickUp ===")
    folders_raw2 = composio("OUTLOOK_OUTLOOK_LIST_MAIL_FOLDERS", {"user_id": "me"})
    client_folders2 = [f for f in (folders_raw2 or []) if f.get("displayName") not in SYSTEM_FOLDERS]
    cu_folders = get_cu_folders()

    total_emails = total_tasks = total_actions = 0

    # Combineer: bestaande ongelezen emails in klantmappen + net gesorteerde emails
    # (net gesorteerde emails zijn mogelijk nog niet zichtbaar via API vanwege latency)

    for ol_folder in client_folders2:
        client_name = ol_folder["displayName"]
        folder_id   = ol_folder["id"]

        msgs_raw = toolset.execute_action(
            action="OUTLOOK_OUTLOOK_LIST_MESSAGES",
            params={"user_id": "me", "folder": folder_id, "is_read": False, "top": 50,
                    "select": ["id", "subject", "from", "body", "receivedDateTime"]},
            connected_account_id=CONN_ID,
        )
        msgs_d = msgs_raw.get("data", {})
        api_emails = msgs_d.get("value") or msgs_d.get("response_data", {}).get("value", [])

        # Voeg net-gesorteerde emails toe die de API nog niet toont
        extra = [e for e in nieuw_gesorteerd if e["client"] == client_name]
        api_ids = {m["id"] for m in (api_emails or [])}
        ontbrekend = [e for e in extra if e["msg_id"] not in api_ids]

        emails_combined = list(api_emails or []) + [
            {"id": e["msg_id"], "subject": e["subject"],
             "from": {"emailAddress": {"address": e["sender"], "name": ""}},
             "body": {"content": e["body_text"]}, "_from_stap1": True}
            for e in ontbrekend
        ]

        if not emails_combined:
            print(f"  📁 {client_name}: geen ongelezen emails")
            continue

        print(f"📁 {client_name} — {len(emails_combined)} email(s)")

        for email in emails_combined:
            msg_id      = email.get("id", "")
            subject     = email.get("subject", "(geen onderwerp)")
            addr_info   = email.get("from", {}).get("emailAddress", {})
            sender_addr = addr_info.get("address", "")
            sender      = f"{addr_info.get('name','')} <{sender_addr}>"
            body_html   = email.get("body", {}).get("content", "")
            body_text   = extract_text(body_html)

            domain = sender_addr.split("@")[-1].lower() if "@" in sender_addr else ""
            if domain in SKIP_DOMAINS:
                print(f"  ⏭ Notificatie overgeslagen: {subject}")
                continue

            total_emails += 1
            folder_entry  = ensure_folder(client_name, cu_folders)
            existing_lists = folder_entry["lists"]

            try:
                projecten = extract_projects(subject, body_text, sender, existing_lists)
            except Exception as e:
                print(f"  ✗ Project/actie fout: {e}")
                projecten = [{"lijst": "Overig", "is_nieuw": False, "acties": []}]

            print(f"  ▶ {subject} — projecten: {[p['lijst'] for p in projecten]}")

            for p in projecten:
                list_id = ensure_list(p["lijst"], folder_entry)
                create_task(list_id, subject, f"Van: {sender}\n\n{body_text[:2000]}", "email")
                total_tasks += 1
                print(f"    → Email-taak in [{p['lijst']}]")

                for actie in p.get("acties", []):
                    create_task(list_id, actie, f"Geëxtraheerd uit email: {subject}", "actie")
                    total_actions += 1
                    print(f"    → Actie: {actie}")

            toolset.execute_action(
                action="OUTLOOK_OUTLOOK_UPDATE_EMAIL",
                params={"user_id": "me", "message_id": msg_id, "is_read": True},
                connected_account_id=CONN_ID,
            )
            print(f"    ✓ Gelezen gemarkeerd")

    print(f"\nKlaar: {total_emails} email(s) → {total_tasks} taken + {total_actions} acties")


@app.local_entrypoint()
def main():
    verwerk_emails.remote()
