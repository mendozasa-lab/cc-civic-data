"""
manage_named_staff.py — Search persons and add to NAMED_STAFF in auto_map_speakers.py.

Search mode (no --person-id):
    python manage_named_staff.py --search "zanoni"

Add mode:
    python manage_named_staff.py --person-id 820 --title "City Manager"
"""

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase_client import get_client

load_dotenv()

AUTO_MAP_PATH = Path(__file__).parent / "auto_map_speakers.py"


def search_persons(query: str) -> None:
    client = get_client()
    result = client.table("persons").select(
        "person_id, person_full_name"
    ).ilike("person_full_name", f"%{query}%").order("person_full_name").execute()

    if not result.data:
        print(f"No persons found matching '{query}'")
        return

    print(f"Found {len(result.data)} match(es) for '{query}':\n")
    print(f"  {'person_id':<12} {'person_full_name'}")
    print(f"  {'-'*12} {'-'*40}")
    for p in result.data:
        print(f"  {p['person_id']:<12} {p['person_full_name']}")

    print("\nTo add one of these to NAMED_STAFF, re-run with:")
    print(f"  --person-id <id> --title \"Their Title\"")


def load_current_named_staff() -> list[dict]:
    """Parse the current NAMED_STAFF list from auto_map_speakers.py."""
    source = AUTO_MAP_PATH.read_text(encoding="utf-8")
    # Find the NAMED_STAFF block
    m = re.search(r'NAMED_STAFF\s*=\s*\[(.*?)\]', source, re.DOTALL)
    if not m:
        raise RuntimeError("Could not find NAMED_STAFF in auto_map_speakers.py")
    block = m.group(1)
    # Extract each dict entry
    entries = re.findall(
        r'\{"person_id":\s*(\d+),\s*"person_full_name":\s*"([^"]+)",\s*"title":\s*"([^"]+)"\}',
        block
    )
    return [{"person_id": int(pid), "person_full_name": name, "title": title}
            for pid, name, title in entries]


def add_to_named_staff(person_id: int, title: str) -> None:
    client = get_client()

    # Look up the person
    result = client.table("persons").select(
        "person_id, person_full_name"
    ).eq("person_id", person_id).single().execute()

    if not result.data:
        sys.exit(f"No person found with person_id={person_id}")

    person = result.data
    full_name = person["person_full_name"]

    # Check for duplicates
    current = load_current_named_staff()
    for entry in current:
        if entry["person_id"] == person_id:
            print(f"person_id={person_id} ({entry['person_full_name']}) is already in NAMED_STAFF.")
            sys.exit(0)

    # Build new entry line
    new_entry = f'    {{"person_id": {person_id}, "person_full_name": "{full_name}", "title": "{title}"}},'

    # Insert before the closing ] of NAMED_STAFF
    source = AUTO_MAP_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r'(NAMED_STAFF\s*=\s*\[)(.*?)(\])', re.DOTALL)
    m = pattern.search(source)
    if not m:
        sys.exit("Could not find NAMED_STAFF in auto_map_speakers.py")

    block = m.group(2)
    new_block = block.rstrip()
    # Add a trailing newline + new entry
    if new_block and not new_block.endswith(','):
        new_block += ','
    new_block += f"\n{new_entry}\n"

    new_source = source[:m.start(2)] + new_block + source[m.end(2):]
    AUTO_MAP_PATH.write_text(new_source, encoding="utf-8")

    print(f"Added to NAMED_STAFF: person_id={person_id} | {full_name} | {title}")
    print(f"Updated: {AUTO_MAP_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Search persons and manage NAMED_STAFF")
    parser.add_argument("--search", metavar="NAME", help="Search persons by name")
    parser.add_argument("--person-id", type=int, help="Person ID to add to NAMED_STAFF")
    parser.add_argument("--title", help="Title/role for the person (e.g. 'City Manager')")
    args = parser.parse_args()

    if args.person_id:
        if not args.title:
            sys.exit("Error: --title is required when adding a person")
        # Also show search results if --search was provided alongside
        if args.search:
            search_persons(args.search)
            print()
        add_to_named_staff(args.person_id, args.title)
    elif args.search:
        search_persons(args.search)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
