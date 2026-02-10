import sys
import os
# Add AoT/ directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))

try:
    from aot.aot_flask.app import create_app
    print("Attempting to create app...")
    app = create_app()
    print("App created successfully.")
    
    client = app.test_client()
    
    print("Testing / route...")
    response = client.get('/', follow_redirects=True)
    print(f"/ status code: {response.status_code}")
    if response.status_code == 200:
        print("/ page access successful")
    else:
        print(f"/ page access failed with status {response.status_code}")
        
    print("Testing /login route...")
    response = client.get('/login', follow_redirects=True)
    print(f"/login status code: {response.status_code}")
    # It might redirect to /login_password
    if response.status_code == 200:
        print("Login page access successful")
        if b"Login" in response.data or b"login" in response.data:
             print("Login text found")
    else:
        print(f"Login page access failed with status {response.status_code}")

    print("Testing /map route (should redirect to login)...")
    response_map = client.get('/map', follow_redirects=False)
    print(f"/map status code: {response_map.status_code}")
    if response_map.status_code == 302:
        print(f"/map redirected to: {response_map.headers['Location']}")
    else:
        print(f"/map returned status {response_map.status_code}")

except Exception as e:
    print(f"Failed to create app or run tests: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
