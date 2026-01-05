#!/usr/bin/env python3
"""
TCG Pocket Pack Finder - GitHub Sync Version
Saves your collection to a private GitHub Gist for cross-device sync.

Setup:
1. Create a GitHub Personal Access Token (with 'gist' scope):
   https://github.com/settings/tokens/new?scopes=gist
2. Set your token below or as environment variable GITHUB_TOKEN
"""

import requests
import json
import os
from collections import defaultdict
from pathlib import Path

# Configuration
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")  # Or paste token here
GIST_ID = ""  # Leave empty to create new, or paste existing gist ID

API_BASE = "https://api.tcgdex.net/v2/en"
CACHE_FILE = "tcg_cards_cache.json"


def github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }


def load_collection_from_gist():
    """Load collection from GitHub Gist."""
    global GIST_ID

    if not GITHUB_TOKEN:
        print("No GitHub token - using local storage only")
        return load_local_collection()

    if GIST_ID:
        try:
            r = requests.get(
                f"https://api.github.com/gists/{GIST_ID}",
                headers=github_headers(),
                timeout=10
            )
            if r.status_code == 200:
                content = r.json()["files"]["tcg_collection.json"]["content"]
                return set(json.loads(content).get("owned", []))
        except Exception as e:
            print(f"Could not load from Gist: {e}")

    return load_local_collection()


def save_collection_to_gist(owned):
    """Save collection to GitHub Gist (private)."""
    global GIST_ID

    # Always save locally as backup
    save_local_collection(owned)

    if not GITHUB_TOKEN:
        print("Saved locally (no GitHub token)")
        return

    data = {
        "description": "TCG Pocket Collection (Private)",
        "public": False,
        "files": {
            "tcg_collection.json": {
                "content": json.dumps({"owned": list(owned)}, indent=2)
            }
        }
    }

    try:
        if GIST_ID:
            # Update existing gist
            r = requests.patch(
                f"https://api.github.com/gists/{GIST_ID}",
                headers=github_headers(),
                json=data,
                timeout=10
            )
        else:
            # Create new gist
            r = requests.post(
                "https://api.github.com/gists",
                headers=github_headers(),
                json=data,
                timeout=10
            )
            if r.status_code == 201:
                GIST_ID = r.json()["id"]
                print(f"Created private Gist: {GIST_ID}")
                print("Save this ID to sync across devices!")

        if r.status_code in (200, 201):
            print("Synced to GitHub!")
        else:
            print(f"GitHub sync failed: {r.status_code}")
    except Exception as e:
        print(f"GitHub sync error: {e}")


def load_local_collection():
    """Load from local file."""
    p = Path("my_collection.json")
    if p.exists():
        with open(p) as f:
            return set(json.load(f).get("owned", []))
    return set()


def save_local_collection(owned):
    """Save to local file."""
    with open("my_collection.json", "w") as f:
        json.dump({"owned": list(owned)}, f)


def fetch_json(url, params=None):
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_one_star_cards():
    """Fetch One Star cards (cached)."""
    cache = Path(CACHE_FILE)
    if cache.exists():
        with open(cache) as f:
            return json.load(f)

    print("Fetching cards from TCGdex API...")
    cards = []

    series = fetch_json(f"{API_BASE}/series/tcgp")
    for s in series.get("sets", []):
        print(f"  {s['name']}...")
        try:
            set_data = fetch_json(f"{API_BASE}/sets/{s['id']}")
            for c in set_data.get("cards", []):
                try:
                    card = fetch_json(f"{API_BASE}/cards/{c['id']}")
                    if card.get("rarity") == "One Star":
                        cards.append({
                            "id": c["id"],
                            "name": card.get("name", "?"),
                            "boosters": card.get("boosters", [])
                        })
                except:
                    pass
        except:
            pass

    with open(cache, "w") as f:
        json.dump(cards, f)
    print(f"Cached {len(cards)} cards")
    return cards


def recommend(cards, owned):
    """Get pack recommendations."""
    packs = defaultdict(list)
    for c in cards:
        if c["id"] not in owned:
            for b in c.get("boosters", []):
                packs[b.get("name", "Unknown")].append(c)
    return sorted(packs.items(), key=lambda x: -len(x[1]))


def main():
    global GIST_ID

    print("=" * 50)
    print("TCG POCKET - One Star Pack Finder")
    print("GitHub Sync Edition")
    print("=" * 50)

    # Check for saved Gist ID
    gist_file = Path(".gist_id")
    if gist_file.exists():
        GIST_ID = gist_file.read_text().strip()

    cards = get_one_star_cards()
    owned = load_collection_from_gist()

    print(f"\nLoaded {len(owned)} cards from collection")

    while True:
        recs = recommend(cards, owned)
        missing = len(cards) - len(owned)

        print(f"\n{'=' * 50}")
        print(f"Progress: {len(owned)}/{len(cards)} | Missing: {missing}")
        print("-" * 50)

        if recs:
            print("Best packs to open:")
            for i, (pack, mc) in enumerate(recs[:5], 1):
                names = ", ".join(c["name"] for c in mc[:3])
                if len(mc) > 3:
                    names += f" +{len(mc)-3} more"
                print(f"  {i}. {pack} ({len(mc)} missing)")
                print(f"      {names}")
            print(f"\n>>> RECOMMENDATION: {recs[0][0]} <<<")
        else:
            print("Congratulations! You have all One Star cards!")

        print("\n[a]dd  [r]emove  [l]ist  [s]ync to GitHub  [q]uit")
        cmd = input("> ").strip().lower()

        if cmd == "q":
            save = input("Save before exit? (y/N): ").strip().lower()
            if save == "y":
                save_collection_to_gist(owned)
                if GIST_ID:
                    gist_file.write_text(GIST_ID)
            break

        elif cmd == "s":
            save_collection_to_gist(owned)
            if GIST_ID:
                gist_file.write_text(GIST_ID)

        elif cmd == "a":
            query = input("Card name or ID: ").strip().lower()
            matches = [c for c in cards
                      if query in c["id"].lower() or query in c["name"].lower()]
            if len(matches) == 1:
                owned.add(matches[0]["id"])
                print(f"Added: {matches[0]['name']}")
            elif len(matches) > 1:
                print("Multiple matches:")
                for i, c in enumerate(matches[:10], 1):
                    status = "[X]" if c["id"] in owned else "[ ]"
                    print(f"  {i}. {status} {c['name']} ({c['id']})")
                pick = input("Number to add (or Enter to cancel): ").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(matches):
                    c = matches[int(pick) - 1]
                    owned.add(c["id"])
                    print(f"Added: {c['name']}")
            else:
                print("Not found")

        elif cmd == "r":
            query = input("Card ID to remove: ").strip()
            for c in cards:
                if c["id"].lower() == query.lower():
                    owned.discard(c["id"])
                    print(f"Removed: {c['name']}")
                    break

        elif cmd == "l":
            print("\nMissing One Star cards:")
            for c in sorted(cards, key=lambda x: x["id"]):
                if c["id"] not in owned:
                    pks = ", ".join(b["name"] for b in c.get("boosters", []))
                    print(f"  {c['name']} ({c['id']})")
                    print(f"    Packs: {pks or 'Unknown'}")


if __name__ == "__main__":
    if not GITHUB_TOKEN:
        print("\nTip: Set GITHUB_TOKEN for cloud sync")
        print("Create token at: https://github.com/settings/tokens/new?scopes=gist")
        print("Then run: export GITHUB_TOKEN='your_token'\n")
    main()
