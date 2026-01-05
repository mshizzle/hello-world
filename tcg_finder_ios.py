#!/usr/bin/env python3
"""
TCG Pocket Pack Finder - iOS Version
Simplified for running on iSH, Pyto, or a-Shell
"""

import requests
import json
from collections import defaultdict
from pathlib import Path

API_BASE = "https://api.tcgdex.net/v2/en"
COLLECTION_FILE = "my_tcg_collection.json"
CACHE_FILE = "tcg_cards_cache.json"

def fetch_json(url, params=None):
    """Fetch JSON from API."""
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def get_one_star_cards():
    """Fetch all One Star cards from TCG Pocket."""
    cache = Path(CACHE_FILE)
    if cache.exists():
        with open(cache) as f:
            return json.load(f)

    print("Fetching cards from API (first run)...")
    cards = []

    # Get all TCG Pocket sets
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
                except: pass
        except: pass

    with open(cache, "w") as f:
        json.dump(cards, f)
    print(f"Cached {len(cards)} One Star cards.")
    return cards

def load_collection():
    """Load owned cards."""
    p = Path(COLLECTION_FILE)
    if p.exists():
        with open(p) as f:
            return set(json.load(f).get("owned", []))
    return set()

def save_collection(owned):
    """Save owned cards."""
    with open(COLLECTION_FILE, "w") as f:
        json.dump({"owned": list(owned)}, f)

def recommend(cards, owned):
    """Get pack recommendations."""
    packs = defaultdict(list)
    for c in cards:
        if c["id"] not in owned:
            for b in c.get("boosters", []):
                packs[b.get("name", "Unknown")].append(c)
    return sorted(packs.items(), key=lambda x: -len(x[1]))

def main():
    print("=" * 50)
    print("TCG POCKET - One Star Pack Finder")
    print("=" * 50)

    cards = get_one_star_cards()
    owned = load_collection()

    while True:
        recs = recommend(cards, owned)
        missing = len(cards) - len(owned)

        print(f"\nProgress: {len(owned)}/{len(cards)} | Missing: {missing}")
        print("-" * 50)

        if recs:
            print("Best packs to open:")
            for i, (pack, missing_cards) in enumerate(recs[:5], 1):
                print(f"  {i}. {pack} ({len(missing_cards)} missing)")
            print(f"\n>>> OPEN: {recs[0][0]} <<<")
        else:
            print("You have all One Star cards!")

        print("\n[a]dd card  [l]ist missing  [s]ave  [q]uit")
        cmd = input("> ").strip().lower()

        if cmd == "q":
            break
        elif cmd == "s":
            save_collection(owned)
            print("Saved!")
        elif cmd == "a":
            name = input("Card name or ID: ").strip().lower()
            for c in cards:
                if name in c["id"].lower() or name in c["name"].lower():
                    owned.add(c["id"])
                    print(f"Added: {c['name']}")
                    break
            else:
                print("Not found")
        elif cmd == "l":
            for c in cards:
                if c["id"] not in owned:
                    pks = ", ".join(b["name"] for b in c.get("boosters", []))
                    print(f"  {c['name']} ({c['id']}) - {pks}")

if __name__ == "__main__":
    main()
