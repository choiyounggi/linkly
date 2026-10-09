import os
import sys

from orderhub.catalog import service as catalog_service
from orderhub.db import connect, init_schema
from orderhub.orders import service as orders_service


def main() -> None:
    db_path = os.environ.get("ORDERHUB_DB", "orderhub.db")
    conn = connect(db_path)
    init_schema(conn)
    catalog_service.seed(conn)
    orders_service.seed_stock(conn)
    orders_service.seed_customers(conn)
    conn.close()
    print(f"seeded {db_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
