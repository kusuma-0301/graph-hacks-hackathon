import os
import uvicorn
from dotenv import load_dotenv
from falkordb import FalkorDB

# Import FastAPI app
from app.api import app

load_dotenv()


def connect_to_database():
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

        graph = db.select_graph(os.getenv("FALKORDB_GRAPH", "company_brain"))
        print("Connected to FalkorDB successfully!")
        return graph

    except Exception as error:
        print("Database connection failed:", error)
        return None


if __name__ == "__main__":
    graph = connect_to_database()
    if graph:
        print("Your project is ready to start. Launching Company Brain FastAPI server...")
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
