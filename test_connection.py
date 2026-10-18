
import os
from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()

print("Starting connection test...", flush=True)

try:
    db = FalkorDB(
        host=os.getenv("FALKORDB_HOST"),
        port=int(os.getenv("FALKORDB_PORT")),
        username=os.getenv("FALKORDB_USERNAME"),
        password=os.getenv("FALKORDB_PASSWORD"),
        ssl=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )

    print("Checking database...", flush=True)
    db.connection.ping()
    print("Connection successful!", flush=True)

except Exception as e:
    print("Connection failed:", repr(e), flush=True)

