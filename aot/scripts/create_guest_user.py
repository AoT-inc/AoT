# coding=utf-8
import os
import sys
import bcrypt

# Append parent directory to path to allow importing aot
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.databases.models import User
from aot.databases.utils import session_scope
from aot.databases import set_uuid
from aot.config import AOT_DB_PATH

def set_password(new_password):
    if isinstance(new_password, str):
        new_password = new_password.encode('utf-8')
    return bcrypt.hashpw(new_password, bcrypt.gensalt()).decode('utf-8')

def create_guest_user(username='aot-guest', password='n7@K2pW9'):
    try:
        with session_scope(AOT_DB_PATH) as db_session:
            # Check if exists
            existing = db_session.query(User).filter(User.name == username).first()
            if existing:
                print(f"User '{username}' already exists. Updating password and role.")
                existing.password_hash = set_password(password)
                existing.role_id = 4
            else:
                new_user = User()
                new_user.unique_id = set_uuid()
                new_user.name = username
                new_user.password_hash = set_password(password)
                new_user.email = f"{username}@aotinc.co.kr"
                new_user.role_id = 4  # Guest
                new_user.theme = '/static/css/bootstrap-4-themes/aot.css'
                new_user.landing_page = 'live'
                new_user.index_page = 'landing'
                new_user.language = 'ko'
                db_session.add(new_user)
        print(f"User '{username}' successfully created/updated.")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    username = 'aot-guest'
    password = 'n7@K2pW9'
    if len(sys.argv) > 1:
        username = sys.argv[1]
    if len(sys.argv) > 2:
        password = sys.argv[2]
    
    create_guest_user(username, password)
