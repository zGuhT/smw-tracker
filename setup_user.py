"""
First-time setup — creates your user account and shows you the config.

Usage:
  python setup_user.py                          # Interactive setup
  python setup_user.py --username myname        # Non-interactive
  python setup_user.py --show                   # Show existing users and keys

After running this, you'll get:
  1. Your username and API key
  2. The exact commands to start the tracker with cloud sync
  3. The URL for your public profile
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    parser = argparse.ArgumentParser(description="SMW Tracker — User Setup")
    parser.add_argument("--username", "-u", help="Username to create")
    parser.add_argument("--display-name", "-d", help="Display name (defaults to username)")
    parser.add_argument("--show", "-s", action="store_true", help="Show existing users")
    parser.add_argument("--cloud-url", default="https://smwtracker.com", help="Cloud server URL")
    args = parser.parse_args()

    # Init DB
    from core.db import init_db
    init_db()

    from core.user_service import (
        create_user, get_all_users, get_or_create_default_user,
        get_user_by_username,
    )

    if args.show:
        _show_users()
        return

    if not args.username:
        print("╔══════════════════════════════════════╗")
        print("║   SMW Tracker — First-Time Setup     ║")
        print("╚══════════════════════════════════════╝")
        print()

        # Show existing users
        users = get_all_users()
        if users:
            print("Existing users:")
            for u in users:
                print(f"  • {u['username']} (id={u['id']})")
            print()

        username = input("Choose a username: ").strip().lower()
        if not username:
            print("Username cannot be empty.")
            return
        display_name = input(f"Display name [{username}]: ").strip() or username
    else:
        username = args.username.strip().lower()
        display_name = args.display_name or username

    # Check if exists
    existing = get_user_by_username(username)
    if existing:
        print(f"\nUser '{username}' already exists (id={existing['id']})")
        # Show their key
        from core import db
        full = db.fetchone("SELECT * FROM users WHERE id = ?", (existing["id"],))
        _print_config(full, args.cloud_url)
        return

    # Create the user
    user = create_user(username=username, display_name=display_name)
    print(f"\n✓ User created: {user['username']} (id={user['id']})")
    _print_config(user, args.cloud_url)


def _show_users():
    from core import db
    users = db.fetchall("SELECT id, username, display_name, api_key, created_at FROM users ORDER BY id")
    if not users:
        print("No users yet. Run: python setup_user.py")
        return

    print(f"{'ID':<5} {'Username':<20} {'Display Name':<20} {'API Key':<45} {'Created'}")
    print("─" * 115)
    for u in users:
        print(f"{u['id']:<5} {u['username']:<20} {(u['display_name'] or ''):<20} {u['api_key']:<45} {u['created_at']}")


def _print_config(user, cloud_url):
    api_key = user["api_key"]
    username = user["username"]

    print()
    print("═" * 60)
    print("  YOUR CONFIGURATION")
    print("═" * 60)
    print()
    print(f"  Username:     {username}")
    print(f"  API Key:      {api_key}")
    print(f"  Profile URL:  {cloud_url}/u/{username}")
    print(f"  Live URL:     {cloud_url}/live?user={user['id']}")
    print()
    print("── Environment Variable ──")
    print(f"  set SMW_API_KEY={api_key}")
    print()
    print("── Start Tracker (local + cloud sync) ──")
    print(f"  python run_tracker.py --cloud --api-key {api_key}")
    print()
    print("── Or with environment variable ──")
    print(f"  set SMW_API_KEY={api_key}")
    print(f"  python run_tracker.py --cloud")
    print()
    print("── Railway Environment Variable ──")
    print(f"  Add SMW_API_KEY={api_key} to your Railway service variables")
    print()
    print("═" * 60)


if __name__ == "__main__":
    main()
