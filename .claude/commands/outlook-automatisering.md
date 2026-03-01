# /outlook-automatisering — Verwerk emails van Outlook naar ClickUp

Voer de volgende twee stappen in volgorde uit:

## Stap 1: Outlook — classificeren en sorteren
```
cd "/Users/bartboonstra/Documents/SW COMM/AI APPS/OUTLOOK -> CLICKUP" && source venv/bin/activate && python classify.py
```

## Stap 2: ClickUp — taken aanmaken

Voer nu de `/clickup` skill uit (zie `.claude/commands/clickup.md`). Die skill doet de volledige verwerking met AI-gedreven projectdetectie: één email kan meerdere projecten bevatten en acties worden in de juiste projectlijst geplaatst.

Rapporteer daarna een gecombineerd overzicht:
- Hoeveel emails geclassificeerd en gesorteerd in Outlook
- Welke klantmappen aangemaakt of gebruikt
- Per email: welke projecten gedetecteerd, hoeveel taken aangemaakt per project
- Wat overgeslagen is en waarom
