import os
from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()


def get_graph():
    """Connect to FalkorDB and return the Company Brain graph."""
    db = FalkorDB(
        host=os.environ["FALKORDB_HOST"],
        port=int(os.environ["FALKORDB_PORT"]),
        username=os.environ["FALKORDB_USERNAME"],
        password=os.environ["FALKORDB_PASSWORD"],
        ssl=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )

    return db.select_graph(
        os.getenv("FALKORDB_GRAPH", "company_brain")
    )