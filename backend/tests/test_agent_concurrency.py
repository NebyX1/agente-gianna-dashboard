import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import AgentOperation, Ticket, TicketEvent


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URI", "").startswith("mariadb"), reason="InnoDB unique reservation requires MariaDB")
def test_concurrent_agent_identical_and_conflicting_identities(app, headers, payload):
    child = app.test_client().post("/api/v1/auth/agent-session", json={}, headers=headers["operator"]).json["data"]
    auth = {"Authorization":"Bearer " + child["access_token"], "X-Agent-Operation-ID":str(uuid4()), "Idempotency-Key":str(uuid4())}
    def send(body, h):
        with app.test_client() as client:
            r=client.post("/api/v1/tickets",json=body,headers=h)
            return r.status_code,r.json
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _:send(payload,auth),range(6)))
    assert {status for status,_ in results}=={201}
    receipts=[body["data"] for _,body in results]
    assert all(r==receipts[0] for r in receipts)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(send,{**payload,"description":"Carga distinta tras el envío concurrente"},auth),
                 pool.submit(send,payload,{**auth,"Idempotency-Key":str(uuid4())})]
        assert [f.result()[0] for f in futures]==[409,409]
    with app.app_context():
        assert len(db.session.scalars(select(Ticket)).all())==1
        assert len(db.session.scalars(select(AgentOperation)).all())==1
        assert len(db.session.scalars(select(TicketEvent)).all())==1
