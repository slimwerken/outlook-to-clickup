"""
Eenmalig uitvoeren om toegang tot de mailbox te autoriseren.
Gebruikt Microsoft device code flow — geen browser redirect nodig.
Token wordt opgeslagen in token_cache.json.

Gebruik: python3 setup_auth.py
"""

import msal
import requests

CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"  # Microsoft Office public client
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = [
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
]
TOKEN_CACHE = "token_cache.json"


def setup():
    cache = msal.SerializableTokenCache()

    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        token_cache=cache,
    )

    flow = app.initiate_device_flow(scopes=SCOPES)

    if "user_code" not in flow:
        print("Kon device flow niet starten:", flow)
        return

    print("\n" + flow["message"])
    print("\nWachten tot je ingelogd bent...")

    result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        token = result["access_token"]
        resp = requests.get(
            "https://graph.microsoft.com/v1.0/me/mailFolders?$top=3&$select=displayName",
            headers={"Authorization": "Bearer " + token},
        )
        if resp.status_code == 200:
            print("\nToken werkt! Mappen gevonden:")
            for f in resp.json().get("value", []):
                print("  -", f["displayName"])
        else:
            print("Token test mislukt:", resp.status_code, resp.text[:200])

        with open(TOKEN_CACHE, "w") as f:
            f.write(cache.serialize())
        print("\nToken opgeslagen in token_cache.json")
        print("Je kunt nu classify.py uitvoeren.")
    else:
        print("Authenticatie mislukt:", result.get("error_description", result))


if __name__ == "__main__":
    setup()
