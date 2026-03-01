# Dennis' Email Automatisering

## Doel
Emails uit Outlook automatisch classificeren met AI en:
- Sorteren in klant-projectmappen (Project A, B, C)
- Omzetten naar ClickUp taken met deadline en prioriteit

## Architectuur

```
Outlook Inbox → AI Classificatie → Projectmappen / ClickUp Taken
```

### Stroom:
1. Outlook MCP Server leest de inbox elke 15 minuten (Modal cronjob)
2. AI leest de email, herkent het project, bepaalt de actie
3. Email wordt:
   - Verplaatst naar de juiste klant-projectmap, OF
   - Omgezet naar een ClickUp taak (met deadline + prioriteit)

## Technische stack

| Onderdeel        | Technologie                          |
|-----------------|--------------------------------------|
| Email bron       | Microsoft Outlook                    |
| MCP Server       | Composio Outlook MCP                 |
| AI Classificatie | Claude (claude-sonnet-4-6)           |
| Taakbeheer       | ClickUp API                          |
| Scheduler        | Modal cronjob (elke 15 min)          |

## MCP Server (Outlook)

```bash
npx @composio/mcp@latest setup \
  "https://mcp.composio.dev/partner/composio/outlook/mcp?customerId=0e1f9464-ce2b-465e-9419-8d083fc1eb09&agent=claude" \
  "outlook-029z4d-4" --client claude
```

## Bouwvolgorde

- [x] Fase 0: Project setup + documentatie
- [ ] Fase 1: Outlook MCP Server instellen en emails uitlezen
- [ ] Fase 2: AI classificatielogica bouwen
- [ ] Fase 3: Mappenstructuur aanmaken en emails sorteren
- [ ] Fase 4: ClickUp integratie (taken aanmaken met deadline + prioriteit)
- [ ] Fase 5: Scheduler instellen (Modal cronjob, elke 15 min)

## Bestanden in dit project

| Bestand          | Beschrijving                           |
|-----------------|----------------------------------------|
| `README.md`      | Dit document — projectoverzicht        |
| (toekomstig)     | `classify.py` — AI classificatielogica |
| (toekomstig)     | `clickup.py` — ClickUp taak aanmaken   |
| (toekomstig)     | `scheduler.py` — Modal cronjob config  |

## Contacten / Context

- **Aanvrager:** Dennis
- **Beheerder:** Bart Boonstra
