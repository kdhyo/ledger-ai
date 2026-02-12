from __future__ import annotations

from datetime import date as date_module

from fastapi.testclient import TestClient

from client.main import create_app


def test_e2e_flow(tmp_path):
    db_path = str(tmp_path / "ledger.db")
    app = create_app(db_path=db_path, use_fake_llm=True)
    client = TestClient(app)

    response = client.post("/chat", json={"message": "오늘 스타벅스 6500원"})
    assert response.status_code == 200
    body = response.json()
    assert "저장" in body["reply"]
    assert body["pending_confirm"] is None

    response = client.post("/chat", json={"message": "오늘 뭐 썼어?"})
    assert response.status_code == 200
    body = response.json()
    assert "스타벅스" in body["reply"]
    assert "6500" in body["reply"]

    response = client.post("/chat", json={"message": "방금거 7500원으로 바꿔줘"})
    assert response.status_code == 200
    body = response.json()
    assert "수정" in body["reply"]
    assert "7500" in body["reply"]

    response = client.post("/chat", json={"message": "그거 삭제해줘"})
    assert response.status_code == 200
    body = response.json()
    assert body["pending_confirm"] is not None
    token = body["pending_confirm"]["token"]

    response = client.post("/confirm", json={"token": token, "decision": "yes"})
    assert response.status_code == 200
    body = response.json()
    assert "삭제" in body["reply"]
    assert body["pending_confirm"] is None


def test_delete_by_item_does_not_fallback_to_last(tmp_path):
    db_path = str(tmp_path / "ledger.db")
    app = create_app(db_path=db_path, use_fake_llm=True)
    client = TestClient(app)

    response = client.post("/chat", json={"message": "오늘 스타벅스 6500원"})
    assert response.status_code == 200
    assert "저장" in response.json()["reply"]

    response = client.post("/chat", json={"message": "오늘 당근 5000원"})
    assert response.status_code == 200
    assert "저장" in response.json()["reply"]

    response = client.post("/chat", json={"message": "'에 당근' 아이템 지워줘"})
    assert response.status_code == 200
    body = response.json()
    assert body["pending_confirm"] is not None
    assert "당근" in body["reply"]
    assert "스타벅스" not in body["reply"]


def test_sum_by_date(tmp_path):
    db_path = str(tmp_path / "ledger.db")
    app = create_app(db_path=db_path, use_fake_llm=True)
    client = TestClient(app)

    response = client.post("/chat", json={"message": "2026-02-10 애플스토어 30000원"})
    assert response.status_code == 200
    assert "저장" in response.json()["reply"]

    response = client.post("/chat", json={"message": "2026-02-10 상추 5000원"})
    assert response.status_code == 200
    assert "저장" in response.json()["reply"]

    response = client.post("/chat", json={"message": "26년 2월 10일 총합을 알려줘"})
    assert response.status_code == 200
    body = response.json()
    assert "2026-02-10" in body["reply"]
    assert "35000" in body["reply"]


def test_insert_multiple_entries_in_one_message(tmp_path):
    db_path = str(tmp_path / "ledger.db")
    app = create_app(db_path=db_path, use_fake_llm=True)
    client = TestClient(app)

    response = client.post("/chat", json={"message": "오늘 당근 4000원, 양상추 3천원 샀어"})
    assert response.status_code == 200
    body = response.json()
    assert "2건 저장" in body["reply"]
    assert "당근 4000원" in body["reply"]
    assert "양상추 3000원" in body["reply"]

    today = date_module.today().isoformat()
    response = client.post("/chat", json={"message": "오늘 내역 보여줘"})
    assert response.status_code == 200
    body = response.json()
    assert today in body["reply"]
    assert "당근" in body["reply"]
    assert "4000" in body["reply"]
    assert "양상추" in body["reply"]
    assert "3000" in body["reply"]


def test_pending_state_is_isolated_by_session(tmp_path):
    db_path = str(tmp_path / "ledger.db")
    app = create_app(db_path=db_path, use_fake_llm=True)
    client = TestClient(app)

    session_a = "session-a"
    session_b = "session-b"

    response = client.post("/chat", json={"message": "오늘 커피 5000원", "session_id": session_a})
    assert response.status_code == 200
    assert "저장" in response.json()["reply"]

    response = client.post("/chat", json={"message": "그거 삭제해줘", "session_id": session_a})
    assert response.status_code == 200
    body = response.json()
    assert body["pending_confirm"] is not None
    token_a = body["pending_confirm"]["token"]

    response = client.post("/confirm", json={"token": token_a, "decision": "yes", "session_id": session_b})
    assert response.status_code == 200
    assert "확인할 항목이 없어요" in response.json()["reply"]

    response = client.post("/confirm", json={"token": token_a, "decision": "yes", "session_id": session_a})
    assert response.status_code == 200
    assert "삭제" in response.json()["reply"]
