import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.fixture
def api_app(integration_container):
    app.state.container = integration_container
    return app

@pytest.fixture
async def api_client(api_app):
    async with AsyncClient(transport=ASGITransport(app=api_app), base_url="http://testserver") as client:
        yield client

@pytest.mark.asyncio
async def test_notes_rest_endpoints(api_client, integration_container, clean_db_and_redis):
    """
    Integration test validating JWT authentication, encryption, RLS isolation,
    and CRUD endpoints for clinical notes.
    """
    db = integration_container.db_client
    auth_svc = integration_container.auth_service
    
    # 1. Setup specialties & two providers
    await db.execute("INSERT INTO specialties (id, name) OVERRIDING SYSTEM VALUE VALUES (1, 'Cardiology') ON CONFLICT DO NOTHING")
    await db.execute("INSERT INTO providers (id, name, specialty_id) OVERRIDING SYSTEM VALUE VALUES (10, 'Dr. A', 1) ON CONFLICT DO NOTHING")
    await db.execute("INSERT INTO providers (id, name, specialty_id) OVERRIDING SYSTEM VALUE VALUES (20, 'Dr. B', 1) ON CONFLICT DO NOTHING")
    await db.execute("INSERT INTO users (id, first_name) VALUES (1001, 'Patient A') ON CONFLICT DO NOTHING")
    
    # 2. Register web portal credentials (JWT)
    await auth_svc.register_web_user(email="dr.a@test.com", password="Password123!", role="provider", provider_id=10)
    res_a = await api_client.post("/api/v1/auth/login", json={"email": "dr.a@test.com", "password": "Password123!"})
    headers_a = {"Authorization": f"Bearer {res_a.json()['access_token']}"}
    
    await auth_svc.register_web_user(email="dr.b@test.com", password="Password123!", role="provider", provider_id=20)
    res_b = await api_client.post("/api/v1/auth/login", json={"email": "dr.b@test.com", "password": "Password123!"})
    headers_b = {"Authorization": f"Bearer {res_b.json()['access_token']}"}
    
    # 3. Create a note as Dr. A via POST
    note_payload = {
        "booking_id": None,
        "client_id": 1001,
        "content": "Diagnóstico confidencial de John Doe.",
        "tags": ["Importante", "Cardio"]
    }
    res_create = await api_client.post("/api/v1/provider/10/notes", json=note_payload, headers=headers_a)
    assert res_create.status_code == 200
    res_data = res_create.json()
    assert res_data["content"] == "Diagnóstico confidencial de John Doe."
    assert res_data["provider_id"] == 10
    assert len(res_data["tags"]) == 2
    
    note_id = res_data["id"]
    
    # Check that it is encrypted in DB
    raw_row = await db.fetchrow("SELECT content_encrypted FROM service_notes WHERE id = $1", note_id)
    assert raw_row is not None
    assert "confidencial" not in raw_row["content_encrypted"]
    
    # 4. Access control: Dr. B (provider 20) attempting to read Dr. A's note via GET (should return 403 Forbidden)
    res_forbidden_get = await api_client.get(f"/api/v1/provider/10/notes/{note_id}", headers=headers_b)
    assert res_forbidden_get.status_code == 403
    
    # Dr. B attempting to read notes list of provider 10
    res_forbidden_list = await api_client.get("/api/v1/provider/10/notes", headers=headers_b)
    assert res_forbidden_list.status_code == 403
    
    # 5. Access notes as Dr. A (provider 10)
    res_get = await api_client.get(f"/api/v1/provider/10/notes/{note_id}", headers=headers_a)
    assert res_get.status_code == 200
    assert res_get.json()["content"] == "Diagnóstico confidencial de John Doe."
    
    # 6. List notes as Dr. A
    res_list = await api_client.get("/api/v1/provider/10/notes", headers=headers_a)
    assert res_list.status_code == 200
    assert len(res_list.json()) == 1
    assert res_list.json()[0]["id"] == note_id
    
    # 7. List tags
    res_tags = await api_client.get("/api/v1/provider/10/tags", headers=headers_a)
    assert res_tags.status_code == 200
    tag_names = [t["name"] for t in res_tags.json()]
    assert "Importante" in tag_names
    assert "Cardio" in tag_names
    
    # 8. Delete note as Dr. A
    res_del = await api_client.delete(f"/api/v1/provider/10/notes/{note_id}", headers=headers_a)
    assert res_del.status_code == 200
    assert res_del.json() == {"status": "success"}
    
    # Assert note is deleted
    res_get_deleted = await api_client.get(f"/api/v1/provider/10/notes/{note_id}", headers=headers_a)
    assert res_get_deleted.status_code == 404
