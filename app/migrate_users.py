#!/usr/bin/env python3
"""
Migration script to update existing users to the new state/role system.

Run this script once after deploying the new schema to migrate existing users:
    python migrate_users.py

What this script does:
1. Sets state=ACTIVE for all existing users (grandfather them in)
2. Sets role=ADMIN for users with is_admin=True, else role=USER
3. Sets email_verified_at=created_at for existing users
4. Sets leaderboard_opt_in=False (users must opt-in themselves)
"""

import os
import sys

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from flask import Flask
from config import Config
from models import db, User, UserState, UserRole


def create_app():
    """Create a minimal Flask app for the migration."""
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    return app


def migrate_users():
    """Migrate existing users to the new state/role system."""
    app = create_app()

    with app.app_context():
        users = User.query.all()
        migrated_count = 0

        for user in users:
            changed = False

            # Set state to ACTIVE if not already set or is empty
            if not user.state or user.state not in [s.value for s in UserState]:
                user.state = UserState.ACTIVE.value
                changed = True

            # Set role based on is_admin flag
            if not user.role or user.role not in [r.value for r in UserRole]:
                if user.is_admin:
                    user.role = UserRole.ADMIN.value
                else:
                    user.role = UserRole.USER.value
                changed = True

            # Set email_verified_at if not set
            if user.email_verified_at is None:
                user.email_verified_at = user.created_at or datetime.utcnow()
                changed = True

            # Ensure leaderboard_opt_in is set to False if not set
            if user.leaderboard_opt_in is None:
                user.leaderboard_opt_in = False
                changed = True

            if changed:
                migrated_count += 1
                print(f"  Migrating user: {user.username}")
                print(f"    - state: {user.state}")
                print(f"    - role: {user.role}")
                print(f"    - is_admin: {user.is_admin}")
                print(f"    - leaderboard_opt_in: {user.leaderboard_opt_in}")

        db.session.commit()
        print(f"\nMigration complete! {migrated_count} users migrated.")


if __name__ == '__main__':
    print("Starting user migration...")
    print("=" * 50)
    migrate_users()
