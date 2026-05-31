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
async def test_waitlist_management_endpoints(api_client, integration_container, clean_db_and_redis):
    db = integration_container.db_client
    auth_svc = integration_container.auth_service
    
    # 1. Setup specialties & two providers
    await db.execute("INSERT INTO specialties (id, name) OVERRIDING SYSTEM VALUE VALUES (1, 'Dentistry')")
    await db.execute("INSERT INTO providers (id, name, specialty_id) OVERRIDING SYSTEM VALUE VALUES (10, 'Dr. Smile', 1)")
    await db.execute("INSERT INTO providers (id, name, specialty_id) OVERRIDING SYSTEM VALUE VALUES (20, 'Dr. Grin', 1)")
    
    # 2. Setup patients/users
    await db.execute("INSERT INTO users (id, first_name, last_name, phone, email, rut) VALUES (1001, 'Alice', 'Smith', '+123', 'alice@test.com', '1-1')")
    await db.execute("INSERT INTO users (id, first_name, last_name, phone, email, rut) VALUES (1002, 'Bob', 'Jones', '+456', 'bob@test.com', '2-2')")
    
    # 3. Add to waitlist
    await db.execute("INSERT INTO waitlist (id, user_id, provider_id, status) OVERRIDING SYSTEM VALUE VALUES (5001, 1001, 10, 'ACTIVE')")
    await db.execute("INSERT INTO waitlist (id, user_id, provider_id, status) OVERRIDING SYSTEM VALUE VALUES (5002, 1002, 10, 'ACTIVE')")
    # Add a fulfilled and an expired entry for Dr. Smile stats
    await db.execute("INSERT INTO waitlist (id, user_id, provider_id, status) OVERRIDING SYSTEM VALUE VALUES (5003, 1001, 10, 'FULFILLED')")
    await db.execute("INSERT INTO waitlist (id, user_id, provider_id, status) OVERRIDING SYSTEM VALUE VALUES (5004, 1002, 10, 'EXPIRED')")
    
    # Waitlist for Dr. Grin
    await db.execute("INSERT INTO waitlist (id, user_id, provider_id, status) OVERRIDING SYSTEM VALUE VALUES (6001, 1001, 20, 'ACTIVE')")
    
    # 4. Setup web portal credentials (JWT)
    # Admin user
    await auth_svc.register_web_user(email="admin@waitlist.com", password="Password123!", role="admin")
    res_admin = await api_client.post("/api/v1/auth/login", json={"email": "admin@waitlist.com", "password": "Password123!"})
    admin_headers = {"Authorization": f"Bearer {res_admin.json()['access_token']}"}
    
    # Provider 10 (Dr. Smile) user
    await auth_svc.register_web_user(email="smile@waitlist.com", password="Password123!", role="provider", provider_id=10)
    res_smile = await api_client.post("/api/v1/auth/login", json={"email": "smile@waitlist.com", "password": "Password123!"})
    smile_headers = {"Authorization": f"Bearer {res_smile.json()['access_token']}"}
    
    # Provider 20 (Dr. Grin) user
    await auth_svc.register_web_user(email="grin@waitlist.com", password="Password123!", role="provider", provider_id=20)
    res_grin = await api_client.post("/api/v1/auth/login", json={"email": "grin@waitlist.com", "password": "Password123!"})
    grin_headers = {"Authorization": f"Bearer {res_grin.json()['access_token']}"}
    
    # 5. Verify access control (403 Forbidden checks)
    # Dr. Grin trying to fetch Dr. Smile's waitlist
    res_forbidden = await api_client.get("/api/v1/provider/10/waitlist", headers=grin_headers)
    assert res_forbidden.status_code == 403
    
    # Dr. Smile trying to fetch Dr. Grin's waitlist stats
    res_forbidden_stats = await api_client.get("/api/v1/provider/20/waitlist/stats", headers=smile_headers)
    assert res_forbidden_stats.status_code == 403
    
    # Smile doctor deleting Grin's waitlist entry
    res_forbidden_del = await api_client.delete("/api/v1/provider/20/waitlist/6001", headers=smile_headers)
    assert res_forbidden_del.status_code == 403
    
    # 6. Fetch Active Waitlist
    # Smile doctor fetching their waitlist (should return active entries: 5001 and 5002)
    res_active = await api_client.get("/api/v1/provider/10/waitlist", headers=smile_headers)
    assert res_active.status_code == 200
    active_list = res_active.json()
    assert len(active_list) == 2
    
    ids = [entry["id"] for entry in active_list]
    assert 5001 in ids
    assert 5002 in ids
    
    # Validate patient details are included
    patient_names = {entry["first_name"] for entry in active_list}
    assert "Alice" in patient_names
    assert "Bob" in patient_names
    
    # 7. Delete Waitlist Entry
    # Smile doctor deletes entry 5001
    res_del = await api_client.delete("/api/v1/provider/10/waitlist/5001", headers=smile_headers)
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "success"
    
    # Confirm it is no longer active
    res_active_after = await api_client.get("/api/v1/provider/10/waitlist", headers=smile_headers)
    assert len(res_active_after.json()) == 1
    assert res_active_after.json()[0]["id"] == 5002
    
    # Deleting it again should return 404 (not found or already processed/inactive)
    res_del_fail = await api_client.delete("/api/v1/provider/10/waitlist/5001", headers=smile_headers)
    assert res_del_fail.status_code == 404
    
    # 8. Fetch Stats
    # Smile doctor gets stats: total = 4, active = 1 (after delete, wait, status of 5001 is now EXPIRED, so active=1, expired=2, fulfilled=1, total=4)
    # Let's check calculations:
    # 5001: ACTIVE -> EXPIRED
    # 5002: ACTIVE
    # 5003: FULFILLED
    # 5004: EXPIRED
    # So: active=1, expired=2, fulfilled=1, notified=0, total=4
    # Conversion rate: 1 / 4 * 100 = 25%
    res_stats = await api_client.get("/api/v1/provider/10/waitlist/stats", headers=smile_headers)
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["total"] == 4
    assert stats["active"] == 1
    assert stats["expired"] == 2
    assert stats["fulfilled"] == 1
    assert stats["conversion_rate"] == 25.0
    
    # 9. Admin Access (Admin should bypass restriction and access successfully)
    res_admin_stats = await api_client.get("/api/v1/provider/10/waitlist/stats", headers=admin_headers)
    assert res_admin_stats.status_code == 200
    assert res_admin_stats.json()["total"] == 4
