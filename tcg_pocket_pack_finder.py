#!/usr/bin/env python3
"""
TCG Pocket Pack Finder

Connects to the TCGdex API to help you find which pack to open
to complete your 1-star card collection.

API Documentation: https://tcgdex.dev/tcg-pocket
"""

import requests
import json
from collections import defaultdict
from pathlib import Path

# TCGdex API base URL
API_BASE = "https://api.tcgdex.net/v2/en"

# File to store your collection
COLLECTION_FILE = "my_collection.json"


def fetch_tcg_pocket_sets():
    """Fetch all TCG Pocket sets from the API."""
    url = f"{API_BASE}/series/tcgp"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_set_details(set_id: str):
    """Fetch detailed information about a specific set including cards."""
    url = f"{API_BASE}/sets/{set_id}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_card_details(card_id: str):
    """Fetch detailed information about a specific card."""
    url = f"{API_BASE}/cards/{card_id}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def get_all_one_star_cards():
    """Get all One Star rarity cards from TCG Pocket."""
    print("Fetching TCG Pocket sets...")
    series_data = fetch_tcg_pocket_sets()

    all_one_star_cards = []
    sets_info = series_data.get("sets", [])

    for set_info in sets_info:
        set_id = set_info.get("id")
        print(f"  Fetching set: {set_info.get('name', set_id)}...")

        try:
            set_details = fetch_set_details(set_id)
            cards = set_details.get("cards", [])

            for card in cards:
                card_id = card.get("id")
                # Fetch full card details to get rarity and booster info
                try:
                    card_details = fetch_card_details(card_id)
                    rarity = card_details.get("rarity")

                    if rarity == "One Star":
                        all_one_star_cards.append({
                            "id": card_id,
                            "name": card_details.get("name", "Unknown"),
                            "set_id": set_id,
                            "set_name": set_details.get("name", set_id),
                            "rarity": rarity,
                            "boosters": card_details.get("boosters", []),
                            "image": card_details.get("image"),
                        })
                except requests.RequestException as e:
                    print(f"    Warning: Could not fetch card {card_id}: {e}")

        except requests.RequestException as e:
            print(f"  Warning: Could not fetch set {set_id}: {e}")

    return all_one_star_cards


def get_one_star_cards_fast():
    """
    Get all One Star rarity cards using the filter endpoint (faster).
    Falls back to detailed fetching if filter doesn't work.
    """
    print("Fetching One Star cards from TCG Pocket...")

    # Try using the rarities filter endpoint
    url = f"{API_BASE}/cards"
    params = {"rarity": "One Star"}

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        cards = response.json()

        # Filter to only TCG Pocket cards (set IDs starting with certain prefixes)
        # and enrich with booster information
        one_star_cards = []
        print(f"  Found {len(cards)} One Star cards, fetching details...")

        for i, card in enumerate(cards):
            card_id = card.get("id", "")
            # TCG Pocket cards are in sets like A1, A1a, A2, P-A, etc.
            if any(card_id.startswith(prefix) for prefix in ["A1", "A2", "A3", "A4", "P-A", "PROMO"]):
                try:
                    card_details = fetch_card_details(card_id)
                    one_star_cards.append({
                        "id": card_id,
                        "name": card_details.get("name", card.get("name", "Unknown")),
                        "set_id": card_id.rsplit("-", 1)[0] if "-" in card_id else card_id[:2],
                        "rarity": "One Star",
                        "boosters": card_details.get("boosters", []),
                        "image": card_details.get("image"),
                    })
                    if (i + 1) % 10 == 0:
                        print(f"    Processed {i + 1}/{len(cards)} cards...")
                except requests.RequestException:
                    pass

        return one_star_cards

    except requests.RequestException:
        print("  Filter endpoint not available, using detailed fetch...")
        return get_all_one_star_cards()


def load_collection() -> set:
    """Load your card collection from file."""
    path = Path(COLLECTION_FILE)
    if path.exists():
        with open(path) as f:
            data = json.load(f)
            return set(data.get("owned_cards", []))
    return set()


def save_collection(owned_cards: set):
    """Save your card collection to file."""
    with open(COLLECTION_FILE, "w") as f:
        json.dump({"owned_cards": list(owned_cards)}, f, indent=2)


def analyze_packs(one_star_cards: list, owned_cards: set) -> dict:
    """
    Analyze which packs have the most missing One Star cards.

    Returns a dict mapping pack names to their missing cards.
    """
    pack_missing_cards = defaultdict(list)

    for card in one_star_cards:
        card_id = card["id"]
        if card_id not in owned_cards:
            boosters = card.get("boosters", [])
            if boosters:
                for booster in boosters:
                    booster_name = booster.get("name", booster.get("id", "Unknown Pack"))
                    pack_missing_cards[booster_name].append(card)
            else:
                # Card has no booster info, group under set
                pack_missing_cards[f"Set: {card.get('set_id', 'Unknown')}"].append(card)

    return dict(pack_missing_cards)


def recommend_pack(pack_missing_cards: dict) -> tuple:
    """
    Recommend which pack to open based on missing cards.

    Returns (pack_name, missing_count, missing_cards)
    """
    if not pack_missing_cards:
        return None, 0, []

    # Sort by number of missing cards (descending)
    sorted_packs = sorted(
        pack_missing_cards.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )

    best_pack, missing_cards = sorted_packs[0]
    return best_pack, len(missing_cards), missing_cards


def display_recommendations(pack_missing_cards: dict, owned_cards: set, total_cards: int):
    """Display pack recommendations."""
    missing_count = total_cards - len(owned_cards)

    print("\n" + "=" * 60)
    print("TCG POCKET ONE STAR CARD COLLECTION TRACKER")
    print("=" * 60)
    print(f"\nCollection Progress: {len(owned_cards)}/{total_cards} One Star cards")
    print(f"Missing: {missing_count} cards")

    if missing_count == 0:
        print("\n🎉 Congratulations! You have all One Star cards!")
        return

    print("\n" + "-" * 60)
    print("PACK RECOMMENDATIONS (sorted by missing cards)")
    print("-" * 60)

    sorted_packs = sorted(
        pack_missing_cards.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )

    for i, (pack_name, missing_cards) in enumerate(sorted_packs[:10], 1):
        print(f"\n{i}. {pack_name}")
        print(f"   Missing {len(missing_cards)} One Star card(s):")
        for card in missing_cards[:5]:
            print(f"     - {card['name']} ({card['id']})")
        if len(missing_cards) > 5:
            print(f"     ... and {len(missing_cards) - 5} more")

    # Best recommendation
    best_pack, count, _ = recommend_pack(pack_missing_cards)
    print("\n" + "=" * 60)
    print(f"RECOMMENDATION: Open '{best_pack}' packs!")
    print(f"This pack has {count} missing One Star cards.")
    print("=" * 60)


def interactive_mode(one_star_cards: list):
    """Interactive mode to manage your collection."""
    owned_cards = load_collection()

    while True:
        pack_missing_cards = analyze_packs(one_star_cards, owned_cards)
        display_recommendations(pack_missing_cards, owned_cards, len(one_star_cards))

        print("\n" + "-" * 60)
        print("OPTIONS:")
        print("  [a] Add card to collection (by ID or name)")
        print("  [r] Remove card from collection")
        print("  [l] List all One Star cards")
        print("  [m] List missing cards")
        print("  [s] Save and exit")
        print("  [q] Quit without saving")
        print("-" * 60)

        choice = input("\nChoice: ").strip().lower()

        if choice == "a":
            card_input = input("Enter card ID or name: ").strip()
            found = False
            for card in one_star_cards:
                if card["id"].lower() == card_input.lower() or \
                   card["name"].lower() == card_input.lower():
                    owned_cards.add(card["id"])
                    print(f"Added: {card['name']} ({card['id']})")
                    found = True
                    break
            if not found:
                # Try partial match
                matches = [c for c in one_star_cards
                          if card_input.lower() in c["name"].lower() or
                             card_input.lower() in c["id"].lower()]
                if matches:
                    print("Did you mean one of these?")
                    for m in matches[:5]:
                        print(f"  - {m['name']} ({m['id']})")
                else:
                    print("Card not found.")

        elif choice == "r":
            card_input = input("Enter card ID to remove: ").strip()
            for card in one_star_cards:
                if card["id"].lower() == card_input.lower():
                    owned_cards.discard(card["id"])
                    print(f"Removed: {card['name']} ({card['id']})")
                    break

        elif choice == "l":
            print("\nAll One Star cards:")
            for card in sorted(one_star_cards, key=lambda x: x["id"]):
                status = "[X]" if card["id"] in owned_cards else "[ ]"
                print(f"  {status} {card['name']} ({card['id']})")

        elif choice == "m":
            print("\nMissing One Star cards:")
            missing = [c for c in one_star_cards if c["id"] not in owned_cards]
            for card in sorted(missing, key=lambda x: x["id"]):
                boosters = ", ".join(b.get("name", b.get("id", "?"))
                                    for b in card.get("boosters", []))
                print(f"  - {card['name']} ({card['id']}) - Packs: {boosters or 'Unknown'}")

        elif choice == "s":
            save_collection(owned_cards)
            print(f"Collection saved to {COLLECTION_FILE}")
            break

        elif choice == "q":
            print("Exiting without saving.")
            break


def main():
    """Main entry point."""
    print("=" * 60)
    print("TCG POCKET PACK FINDER - One Star Card Completion")
    print("=" * 60)
    print("\nFetching card data from TCGdex API...")
    print("(This may take a moment on first run)")
    print()

    # Cache file for card data
    cache_file = Path("one_star_cards_cache.json")

    if cache_file.exists():
        print("Loading cached card data...")
        with open(cache_file) as f:
            one_star_cards = json.load(f)
        print(f"Loaded {len(one_star_cards)} One Star cards from cache.")

        refresh = input("Refresh data from API? (y/N): ").strip().lower()
        if refresh == "y":
            one_star_cards = get_one_star_cards_fast()
            with open(cache_file, "w") as f:
                json.dump(one_star_cards, f, indent=2)
            print(f"Cached {len(one_star_cards)} cards.")
    else:
        one_star_cards = get_one_star_cards_fast()
        with open(cache_file, "w") as f:
            json.dump(one_star_cards, f, indent=2)
        print(f"Cached {len(one_star_cards)} cards.")

    if not one_star_cards:
        print("No One Star cards found. The API might have changed.")
        print("Check https://tcgdex.dev/tcg-pocket for updates.")
        return

    interactive_mode(one_star_cards)


if __name__ == "__main__":
    main()
