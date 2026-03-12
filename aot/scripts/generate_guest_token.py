# coding=utf-8
import datetime
import secrets
import sys
import os

# Append current directory to path to allow importing aot
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.aot_flask.app import create_app
from aot.databases.models import User, GuestLoginToken
from aot.aot_flask.extensions import db

def generate_token(username='aot-guest', hours=24):
    app = create_app()
    with app.app_context():
        # Ensure the table is created
        db.create_all()
        
        user = User.query.filter_by(name=username).first()
        if not user:
            print(f"Error: User '{username}' not found.")
            return None

        token_str = secrets.token_urlsafe(32)
        expiration = datetime.datetime.utcnow() + datetime.timedelta(hours=hours)

        new_token = GuestLoginToken(
            token=token_str,
            user_id=user.id,
            expires_at=expiration
        )
        new_token.save()

        # Assuming the base URL
        base_url = "http://aot1.aotinc.co.kr/AoT/auto-login"
        print(f"\nGuest Login Token Generated:")
        print(f"User: {username}")
        print(f"Expires: {expiration} (UTC)")
        print(f"URL: {base_url}?token={token_str}")
        print("-" * 40)
        return token_str

if __name__ == "__main__":
    username = 'aot-guest'
    if len(sys.argv) > 1:
        username = sys.argv[1]
    
    generate_token(username)
