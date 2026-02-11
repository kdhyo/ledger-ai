from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import create_app


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
