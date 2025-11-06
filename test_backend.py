import asyncio
import json
import httpx
import websockets

BASE_URL = "http://localhost:8000"

# --- Test User Credentials ---
USER_1 = {"username": "alice", "password": "TestPass123"}
USER_2 = {"username": "bob", "password": "TestPass123"}

async def test_backend():
    async with httpx.AsyncClient() as client:
        print("=== 1. Register Users ===")
        for user in [USER_1, USER_2]:
            try:
                res = await client.post(f"{BASE_URL}/auth/register", json=user)
                print(res.json())
            except Exception as e:
                print("Already registered:", e)

        print("\n=== 2. Login Users ===")
        tokens = {}
        for user in [USER_1, USER_2]:
            res = await client.post(f"{BASE_URL}/auth/login", json=user)
            data = res.json()
            tokens[user["username"]] = data
            print(f"{user['username']} tokens:", data)

        print("\n=== 3. Refresh Token ===")
        res = await client.post(f"{BASE_URL}/auth/refresh", json={"refresh_token": tokens['alice']['refresh_token']})
        print("New tokens:", res.json())

        print("\n=== 4. Create Group ===")
        headers = {"Authorization": f"Bearer {tokens['alice']['access_token']}"}
        group_payload = {"name": "friends", "member_usernames": ["bob"]}
        res = await client.post(f"{BASE_URL}/groups", json=group_payload, headers=headers)
        print("Group created:", res.json())

        print("\n=== 5. Check Chat History (should be empty) ===")
        res = await client.get(f"{BASE_URL}/chat/one_to_one/history/bob", headers=headers)
        print(res.json())

        print("\n=== 6. WebSocket Chat Test ===")

        async def ws_chat(user_token, messages_to_send):
            uri = f"ws://localhost:8000/ws/chat?token={user_token}"
            async with websockets.connect(uri) as ws:
                # Receive welcome
                welcome = await ws.recv()
                print("WS Welcome:", welcome)
                # Send messages
                for msg in messages_to_send:
                    await ws.send(json.dumps(msg))
                    # Receive back
                    response = await ws.recv()
                    print("WS Response:", response)

        # Prepare messages
        alice_msgs = [
            {"type": "one_to_one", "target": "bob", "content": "Hi Bob!"},
            {"type": "group", "target": "friends", "content": "Hello Group!"}
        ]
        bob_msgs = [
            {"type": "one_to_one", "target": "alice", "content": "Hey Alice!"}
        ]

        await asyncio.gather(
            ws_chat(tokens['alice']['access_token'], alice_msgs),
            ws_chat(tokens['bob']['access_token'], bob_msgs)
        )

if __name__ == "__main__":
    asyncio.run(test_backend())
