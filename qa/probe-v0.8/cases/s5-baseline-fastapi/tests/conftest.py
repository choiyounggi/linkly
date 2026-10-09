import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("ORDERHUB_DB", db_path)

    from orderhub import db as db_module
    from orderhub.app import app
    from orderhub.catalog import service as catalog_service
    from orderhub.orders import service as orders_service

    conn = db_module.connect(db_path)
    db_module.init_schema(conn)
    catalog_service.seed(conn)
    orders_service.seed_stock(conn)
    orders_service.seed_customers(conn)
    conn.close()

    with TestClient(app) as test_client:
        yield test_client, db_path


@pytest.fixture()
def db_conn(client):
    from orderhub.db import connect

    _, db_path = client
    conn = connect(db_path)
    yield conn
    conn.close()
