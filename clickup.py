"""
ClickUp integratie voor slimwerkentester@outlook.com
Leest gesorteerde emails uit Outlook klantmappen, maakt ClickUp taken aan.

Per email:
  - Klant  → folder in ClickUp (aanmaken indien nodig)
  - Project → lijst binnen die folder (aanmaken indien nodig)
  - Email  → taak met label 'email'
  - Acties  → losse taken met label 'actie', geëxtraheerd door AI

Gebruik:
    python clickup.py          # verwerk alle klantmappen
    python clickup.py --dry-run  # toon wat er zou gebeuren zonder te schrijven
"""

import os
import json
import re
import argparse
from bs4 import BeautifulSoup
from openai import OpenAI
from composio import ComposioToolSet
from dotenv import load_dotenv
import requests

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────
COMPOSIO_KEY   = os.getenv("COMPOSIO_API_KEY")
CONN_ID        = os.getenv("COMPOSIO_CONNECTED_ACCOUNT_ID")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
CLICKUP_KEY    = os.getenv("CLICKUP_API_KEY")
CLICKUP_SPACE  = "901510293981"  # [DEMO] Email Automatisering
CLICKUP_INBOX  = "901521652289"  # 📥 Inbox (ongesorteerd)

SYSTEM_FOLDERS = {
    "Inbox", "Drafts", "Sent Items", "Deleted Items",
    "Junk Email", "Archive", "Outbox", "Conversation History",
    "Archiveren", "Concepten", "Verzonden items", "Verwijderde items",
    "Ongewenste e-mail", "Postvak UIT", "Postvak IN", "Gesprekgeschiedenis",
}

# Domeinen waarvan mails nooit naar ClickUp gaan (automatische notificaties)
SKIP_DOMAINS = {
    "microsoft.com", "notificationmail.microsoft.com",
    "accountprotection.microsoft.com", "linkedin.com",
    "no-reply.com",
}

toolset = ComposioToolSet(api_key=COMPOSIO_KEY)
cu_headers = {"Authorization": CLICKUP_KEY, "Content-Type": "application/json"}


# ─── Outlook helpers ──────────────────────────────────────────────────────────
def composio_call(action, params):
    return toolset.execute_action(
        action=action,
        params=params,
        connected_account_id=CONN_ID,
    )


def get_client_folders():
    """Haal klantmappen op uit Outlook: [{name, id}]"""
    result = composio_call("OUTLOOK_OUTLOOK_LIST_MAIL_FOLDERS", {"user_id": "me"})
    data = result.get("data", {})
    items = data.get("value") or data.get("response_data", {}).get("value", [])
    return [f for f in items if f["displayName"] not in SYSTEM_FOLDERS]


def get_emails_in_folder(folder_id):
    """Haal ongelezen emails op uit een Outlook map."""
    result = composio_call("OUTLOOK_OUTLOOK_LIST_MESSAGES", {
        "user_id": "me",
        "folder": folder_id,
        "is_read": False,
        "top": 50,
        "select": ["id", "subject", "from", "body", "bodyPreview", "receivedDateTime"],
    })
    data = result.get("data", {})
    return data.get("value") or data.get("response_data", {}).get("value", [])


def mark_as_read(message_id):
    """Markeer email als gelezen — deduplicatie voor volgende run (ook in Modal)."""
    composio_call("OUTLOOK_OUTLOOK_UPDATE_EMAIL", {
        "user_id": "me",
        "message_id": message_id,
        "is_read": True,
    })


def extract_text(html):
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)


# ─── AI: projecten detecteren + acties extraheren ─────────────────────────────
def extract_projects_and_actions(subject, body_text, sender, existing_lists):
    """
    Detecteer alle projecten in de email en bijbehorende acties.
    Map elk project naar een bestaande ClickUp lijst als die semantisch past.

    existing_lists: dict {naam: list_id} van bestaande lijsten voor deze klant
    Returns: [{"lijst": "naam", "is_nieuw": bool, "acties": [...]}]
    """
    ai = OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

    bestaande_namen = list(existing_lists.keys()) if existing_lists else []

    prompt = f"""Analyseer deze zakelijke email. Detecteer alle projecten en bijbehorende acties.
Map elk project naar de meest passende bestaande ClickUp lijst als die semantisch overeenkomt.

AFZENDER: {sender}
ONDERWERP: {subject}
BODY:
{body_text[:3000]}

BESTAANDE CLICKUP LIJSTEN VOOR DEZE KLANT:
{json.dumps(bestaande_namen, ensure_ascii=False)}

Geef een JSON-antwoord met exact dit formaat:
{{
  "projecten": [
    {{
      "lijst": "naam van bestaande lijst OF nieuwe naam als er geen match is",
      "is_nieuw": false,
      "acties": ["→ Actie 1", "→ Actie 2"]
    }}
  ]
}}

Regels:
- Eén email kan meerdere projecten bevatten — splits ze op
- Map naar een BESTAANDE lijst als de inhoud semantisch overeenkomt:
  bijv. "landingspagina", "homepage", "webpagina" → "Website Redesign"
  bijv. "hosting probleem", "server down" → "Hosting & Beheer"
- Gebruik een NIEUWE naam ALLEEN als er echt geen bestaande lijst past
- is_nieuw = false als je een bestaande lijst gebruikt, true als je een nieuwe maakt
- Acties: alleen concrete uitvoerbare taken, begin met "→ ", voeg deadline toe indien vermeld
- Geen acties → lege lijst
- Als de email geen enkel project of actie bevat: geef één item met lijst "Overig" en lege acties
- Geef ALLEEN geldige JSON terug, geen extra tekst."""

    response = ai.chat.completions.create(
        model="anthropic/claude-sonnet-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.choices[0].message.content.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return json.loads(match.group()).get("projecten", [])
    return []


# ─── ClickUp helpers ──────────────────────────────────────────────────────────
def get_clickup_folders():
    """Haal bestaande ClickUp klantfolders op: {naam_lower: {id, name}}"""
    r = requests.get(
        f"https://api.clickup.com/api/v2/space/{CLICKUP_SPACE}/folder?archived=false",
        headers=cu_headers,
    )
    folders = {}
    for f in r.json().get("folders", []):
        folders[f["name"].lower()] = {"id": f["id"], "name": f["name"], "lists": {
            lst["name"].lower(): lst["id"] for lst in f.get("lists", [])
        }}
    return folders


def ensure_clickup_folder(client_name, cu_folders):
    """Zorg dat ClickUp folder bestaat voor klant. Geeft folder dict terug."""
    key = client_name.lower()
    if key in cu_folders:
        return cu_folders[key]
    r = requests.post(
        f"https://api.clickup.com/api/v2/space/{CLICKUP_SPACE}/folder",
        headers=cu_headers,
        json={"name": client_name},
    )
    folder = r.json()
    entry = {"id": folder["id"], "name": folder["name"], "lists": {}}
    cu_folders[key] = entry
    print(f"  + ClickUp folder aangemaakt: {client_name}")
    return entry


def ensure_clickup_list(project_name, folder_entry):
    """Zorg dat ClickUp lijst bestaat voor project. Geeft list_id terug."""
    key = project_name.lower()
    if key in folder_entry["lists"]:
        return folder_entry["lists"][key]
    r = requests.post(
        f"https://api.clickup.com/api/v2/folder/{folder_entry['id']}/list",
        headers=cu_headers,
        json={"name": project_name},
    )
    lst = r.json()
    folder_entry["lists"][key] = lst["id"]
    print(f"  + ClickUp lijst aangemaakt: {project_name}")
    return lst["id"]


def add_tag(task_id, tag):
    requests.post(
        f"https://api.clickup.com/api/v2/task/{task_id}/tag/{tag}",
        headers=cu_headers,
    )


def create_email_task(list_id, subject, body_text, sender):
    """Maak email-taak aan in ClickUp met label 'email'."""
    r = requests.post(
        f"https://api.clickup.com/api/v2/list/{list_id}/task",
        headers=cu_headers,
        json={
            "name": subject,
            "description": f"Van: {sender}\n\n{body_text[:2000]}",
            "status": "to do",
            "notify_all": False,
        },
    )
    task = r.json()
    add_tag(task["id"], "email")
    return task


def create_action_task(list_id, action_text, email_subject):
    """Maak actie-taak aan in ClickUp met label 'actie'."""
    r = requests.post(
        f"https://api.clickup.com/api/v2/list/{list_id}/task",
        headers=cu_headers,
        json={
            "name": action_text,
            "description": f"Geëxtraheerd uit email: {email_subject}",
            "status": "to do",
            "notify_all": False,
        },
    )
    task = r.json()
    add_tag(task["id"], "actie")
    return task


def create_inbox_task(subject, sender):
    """Maak taak aan in ClickUp inbox voor niet-sorteerbare emails."""
    r = requests.post(
        f"https://api.clickup.com/api/v2/list/{CLICKUP_INBOX}/task",
        headers=cu_headers,
        json={
            "name": subject,
            "description": f"Van: {sender}\n\nKon niet automatisch worden ingedeeld.",
            "status": "to do",
            "notify_all": False,
        },
    )
    task = r.json()
    add_tag(task["id"], "email")
    return task


# ─── Hoofdlogica ──────────────────────────────────────────────────────────────
def process(dry_run=False):
    print(f"{'[DRY RUN] ' if dry_run else ''}ClickUp integratie gestart\n")

    outlook_folders = get_client_folders()
    cu_folders = get_clickup_folders()

    if not outlook_folders:
        print("Geen klantmappen gevonden in Outlook.")
        return

    total_emails = 0
    total_tasks = 0
    total_actions = 0

    for outlook_folder in outlook_folders:
        client_name = outlook_folder["displayName"]
        folder_id   = outlook_folder["id"]

        # Alleen ongelezen emails — gelezen = al verwerkt in ClickUp
        emails = get_emails_in_folder(folder_id)
        if not emails:
            continue

        print(f"📁 {client_name} — {len(emails)} nieuwe email(s)")

        for email in emails:
            msg_id      = email.get("id", "")
            subject     = email.get("subject", "(geen onderwerp)")
            sender_info = email.get("from", {}).get("emailAddress", {})
            sender_addr = sender_info.get("address", "")
            sender      = f"{sender_info.get('name', '')} <{sender_addr}>"
            body_html   = email.get("body", {}).get("content", "")
            body_text   = extract_text(body_html)

            # Sla automatische notificaties over
            domain = sender_addr.split("@")[-1].lower() if "@" in sender_addr else ""
            if domain in SKIP_DOMAINS:
                print(f"  ⏭ Overgeslagen (notificatie): {subject}")
                continue

            total_emails += 1

            # ClickUp folder ophalen/aanmaken — nodig voor bestaande lijsten als context
            folder_entry = ensure_clickup_folder(client_name, cu_folders)
            existing_lists = folder_entry["lists"]  # {naam: list_id}

            # Projecten + acties detecteren via AI, met bestaande lijsten als context
            try:
                projecten = extract_projects_and_actions(subject, body_text, sender, existing_lists)
            except Exception as e:
                print(f"  ✗ Projecten/acties extraheren mislukt: {e}")
                projecten = [{"lijst": "Overig", "is_nieuw": True, "acties": []}]

            totaal_acties = sum(len(p.get("acties", [])) for p in projecten)
            print(f"  ▶ {subject}")
            print(f"    Van: {sender}")
            print(f"    Projecten: {[p['lijst'] for p in projecten]} | Acties: {totaal_acties}")

            if dry_run:
                for p in projecten:
                    label = "(nieuw)" if p.get("is_nieuw") else "(bestaand)"
                    print(f"    → [DRY RUN] {client_name} / {p['lijst']} {label}")
                    for a in p.get("acties", []):
                        print(f"      - {a}")
                print()
                continue

            # Email-taak + actie-taken in ELK gedetecteerd project
            for p in projecten:
                lijst_naam = p["lijst"]
                list_id    = ensure_clickup_list(lijst_naam, folder_entry)

                # Email-taak in elk project (zodat de context overal aanwezig is)
                task = create_email_task(list_id, subject, body_text, sender)
                total_tasks += 1
                print(f"    → Email-taak: '{task['name']}' in [{lijst_naam}] [email]")

                # Actie-taken voor dit specifieke project
                for actie in p.get("acties", []):
                    create_action_task(list_id, actie, subject)
                    total_actions += 1
                    print(f"    → Actie: '{actie}' in [{lijst_naam}] [actie]")

            # Markeer als gelezen — deduplicatie voor volgende run (werkt ook in Modal)
            mark_as_read(msg_id)
            print(f"    ✓ Email gemarkeerd als gelezen in Outlook")
            print()

    if total_emails == 0:
        print("Alles al verwerkt — geen nieuwe emails gevonden.")
    else:
        print(f"Klaar. {total_emails} email(s) → {total_tasks} taken + {total_actions} acties aangemaakt in ClickUp.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Toon wat er zou gebeuren zonder te schrijven")
    args = parser.parse_args()
    process(dry_run=args.dry_run)
