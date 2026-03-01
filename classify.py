"""
Email classificatie engine voor slimwerkentester@outlook.com
Leest inbox + spam, classificeert met Claude AI, sorteert in klantmappen.
Project info wordt bewaard voor toekomstige ClickUp integratie (fase 4).

Gebruik:
    python classify.py          # verwerk nieuwe emails
    python classify.py --dry-run  # toon wat er zou gebeuren zonder te schrijven
"""

import os
import json
import re
import argparse
from bs4 import BeautifulSoup
from openai import OpenAI
from composio import ComposioToolSet
from dotenv import load_dotenv

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────
COMPOSIO_KEY  = os.getenv("COMPOSIO_API_KEY")
CONN_ID       = os.getenv("COMPOSIO_CONNECTED_ACCOUNT_ID", "c3881050-b0b5-4d48-bc6e-dbbfef18389a")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

# Systeepmappen — worden nooit als klantmap aangemaakt
SYSTEM_FOLDERS = {
    "Inbox", "Drafts", "Sent Items", "Deleted Items",
    "Junk Email", "Archive", "Outbox", "Conversation History",
    "Archiveren", "Concepten", "Verzonden items", "Verwijderde items",
    "Ongewenste e-mail", "Postvak UIT", "Gesprekgeschiedenis",
}

# Folders die we scannen op nieuwe mail
SOURCE_FOLDERS = ["inbox", "junkemail"]

toolset = ComposioToolSet(api_key=COMPOSIO_KEY)


# ─── Composio helper ──────────────────────────────────────────────────────────
def composio_call(action, params):
    """Voer een Composio Outlook actie uit."""
    return toolset.execute_action(
        action=action,
        params=params,
        connected_account_id=CONN_ID,
    )


# ─── Folder management ────────────────────────────────────────────────────────
def get_client_folders():
    """Haal bestaande klantmappen op: {naam: folder_id}"""
    result = composio_call("OUTLOOK_OUTLOOK_LIST_MAIL_FOLDERS", {"user_id": "me"})
    folders = {}
    data = result.get("data", {})
    items = data.get("value") or data.get("response_data", {}).get("value", [])
    for folder in items:
        name = folder["displayName"]
        if name not in SYSTEM_FOLDERS:
            folders[name] = folder["id"]
    return folders


def ensure_client_folder(client_name, existing_folders):
    """Zorg dat klantmap bestaat. Maakt aan indien nodig. Geeft folder_id terug."""
    if client_name in existing_folders:
        return existing_folders[client_name]

    result = composio_call("OUTLOOK_CREATE_MAIL_FOLDER", {
        "displayName": client_name,
        "user_id": "me",
    })
    data = result.get("data", {})
    folder_id = data.get("id") or data.get("response_data", {}).get("id")
    existing_folders[client_name] = folder_id
    print(f"  + Map aangemaakt: {client_name}")
    return folder_id


def move_email(message_id, folder_id):
    """Verplaats email naar klantmap."""
    composio_call("OUTLOOK_OUTLOOK_MOVE_MESSAGE", {
        "message_id": message_id,
        "destination_id": folder_id,
        "user_id": "me",
    })


# ─── Email ophalen ─────────────────────────────────────────────────────────────
def get_unread_emails():
    """Haal ongelezen emails op uit inbox + spam."""
    emails = []
    for folder in SOURCE_FOLDERS:
        result = composio_call("OUTLOOK_OUTLOOK_LIST_MESSAGES", {
            "user_id": "me",
            "folder": folder,
            "is_read": False,
            "top": 50,
            "select": ["id", "subject", "from", "body", "bodyPreview", "receivedDateTime"],
        })
        data = result.get("data", {})
        msgs = data.get("value") or data.get("response_data", {}).get("value", [])
        for msg in msgs:
            msg["_sourceFolder"] = folder
            emails.append(msg)
    return emails


def extract_text(html):
    """Zet HTML body om naar platte tekst."""
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)


# ─── AI Classificatie ─────────────────────────────────────────────────────────
def classify_email(email, existing_client_folders):
    """
    Vraag Claude om de email te classificeren.
    Geeft dict terug: {action, client, project, reason}
    action: "skip" | "sort"
    """
    ai = OpenAI(
        api_key=OPENROUTER_KEY,
        base_url="https://openrouter.ai/api/v1",
    )

    from_addr    = email.get("from", {}).get("emailAddress", {})
    sender_email = from_addr.get("address", "")
    sender_name  = from_addr.get("name", "")
    subject      = email.get("subject", "")
    body_html    = email.get("body", {}).get("content", "")
    body_text    = extract_text(body_html)[:3000]

    known_clients = ", ".join(existing_client_folders.keys()) if existing_client_folders else "(geen)"

    prompt = f"""Je bent een email-sorteerder voor het persoonlijke zakelijke Outlook account slimwerkentester@outlook.com.
Dit account heeft GEEN eigen bedrijfsdomein — er is dus nooit sprake van "interne mail" op basis van domein.
Elke email van een extern bedrijf of persoon is een klant of zakelijk contact.

AFZENDER: {sender_name} <{sender_email}>
ONDERWERP: {subject}
BODY:
{body_text}

BESTAANDE KLANTMAPPEN: {known_clients}

Analyseer deze email en geef een JSON-antwoord met exact dit formaat:
{{
  "action": "skip" of "sort",
  "client": "klantnaam of null",
  "project": "projectnaam",
  "reason": "korte uitleg"
}}

Regels:
- action = "skip" ALLEEN als: nieuwsbrief, automatische notificatie (bijv. Microsoft, LinkedIn updates), spam of reclame zonder persoonlijke boodschap
- action = "sort" als: zakelijke of persoonlijke mail van een extern bedrijf of contact — ook al is het een korte of informele mail
- client: haal uit het emaildomein (bijv. @growmedia.nl → "Grow Media", @bakker.nl → "Bakker"). Staat de klant al in BESTAANDE KLANTMAPPEN, gebruik dan exact die naam. Geen herkenbaar bedrijfsdomein (bijv. gmail.com, hotmail.com) → gebruik de afzendernaam als klantnaam.
- project: één projectnaam gebaseerd op de INHOUD van de mail. Wordt later gebruikt voor ClickUp. Totaal onduidelijk → "Overig".
- Geef ALLEEN geldige JSON terug, geen extra tekst."""

    response = ai.chat.completions.create(
        model="anthropic/claude-sonnet-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.choices[0].message.content.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"Onverwacht Claude-antwoord: {raw}")


# ─── Hoofdlogica ──────────────────────────────────────────────────────────────
def process(dry_run=False):
    print(f"{'[DRY RUN] ' if dry_run else ''}Email classificatie gestart\n")

    client_folders = get_client_folders()
    emails = get_unread_emails()

    if not emails:
        print("Geen nieuwe emails gevonden.")
        return

    print(f"{len(emails)} nieuwe email(s) gevonden.\n")

    for email in emails:
        subject = email.get("subject", "(geen onderwerp)")
        sender  = email.get("from", {}).get("emailAddress", {}).get("address", "?")
        print(f"▶ {subject}")
        print(f"  Van: {sender}")

        try:
            result = classify_email(email, client_folders)
        except Exception as e:
            print(f"  ✗ Classificatie mislukt: {e}\n")
            continue

        print(f"  Actie: {result['action']} | {result.get('reason', '')}")

        if result["action"] == "skip":
            print(f"  → Overgeslagen\n")
            continue

        client_name = result.get("client")
        project     = result.get("project", "Overig")

        if not client_name:
            print(f"  ✗ Geen klantnaam bepaald, overgeslagen\n")
            continue

        print(f"  Klant: {client_name} | Project (ClickUp): {project}")

        if dry_run:
            print(f"  → [DRY RUN] Zou verplaatsen naar map: {client_name}\n")
            continue

        folder_id = ensure_client_folder(client_name, client_folders)
        move_email(email["id"], folder_id)
        print(f"  → Verplaatst naar map: {client_name}\n")

    print("Klaar.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Toon wat er zou gebeuren zonder te schrijven")
    args = parser.parse_args()
    process(dry_run=args.dry_run)
