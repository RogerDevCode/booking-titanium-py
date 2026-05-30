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
async def test_auth_login_and_admin_crud_flows(api_client, integration_container, clean_db_and_redis):
    db = integration_container.db_client
    
    # 1. Register a provider to link
    spec_id = 900
    await db.execute(
        f"INSERT INTO specialties (id, name) OVERRIDING SYSTEM VALUE VALUES ({spec_id}, 'Ophthalmology')"
    )
    prov_id = 950
    await db.execute(
        f"INSERT INTO providers (id, name, specialty_id, is_active) OVERRIDING SYSTEM VALUE VALUES ({prov_id}, 'Dr. Vision', {spec_id}, true)"
    )

    # 2. Register users
    auth_svc = integration_container.auth_service
    await auth_svc.register_web_user(
        email="admin@test.com",
        password="AdminPassword123!",
        role="admin"
    )
    await auth_svc.register_web_user(
        email="provider@test.com",
        password="DoctorPassword123!",
        role="provider",
        provider_id=prov_id
    )

    # 3. Test Login (Admin)
    res_login = await api_client.post("/api/v1/auth/login", json={
        "email": "admin@test.com",
        "password": "AdminPassword123!"
    })
    assert res_login.status_code == 200
    admin_token = res_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Test Login (Provider)
    res_login_prov = await api_client.post("/api/v1/auth/login", json={
        "email": "provider@test.com",
        "password": "DoctorPassword123!"
    })
    assert res_login_prov.status_code == 200
    provider_token = res_login_prov.json()["access_token"]
    provider_headers = {"Authorization": f"Bearer {provider_token}"}

    # 4. CRUD Specialties
    # Provider cannot create specialty (403)
    res_create_spec_fail = await api_client.post("/api/v1/admin/specialties", json={
        "name": "Pediatrics",
        "description": "Children medicine"
    }, headers=provider_headers)
    assert res_create_spec_fail.status_code == 403

    # Admin can create specialty
    res_create_spec = await api_client.post("/api/v1/admin/specialties", json={
        "name": "Pediatrics",
        "description": "Children medicine"
    }, headers=admin_headers)
    assert res_create_spec.status_code == 200
    assert "id" in res_create_spec.json()

    # Retrieve specialties
    res_list_spec = await api_client.get("/api/v1/admin/specialties", headers=provider_headers)
    assert res_list_spec.status_code == 200
    names = [s["name"] for s in res_list_spec.json()]
    assert "Pediatrics" in names

    # 5. Patient Search
    # Setup some patient users in DB
    patient_id_1 = 12345
    patient_id_2 = 67890
    await db.execute(
        "INSERT INTO users (id, first_name, last_name, phone, rut) VALUES ($1, $2, $3, $4, $5)",
        patient_id_1, "Gabriel", "Boric", "+56911111111", "11.111.111-1"
    )
    await db.execute(
        "INSERT INTO users (id, first_name, last_name, phone, rut) VALUES ($1, $2, $3, $4, $5)",
        patient_id_2, "Michelle", "Bachelet", "+56922222222", "22.222.222-2"
    )

    # Search patients by name
    res_search_name = await api_client.get("/api/v1/admin/patients?query=Gabriel", headers=provider_headers)
    assert res_search_name.status_code == 200
    patients = res_search_name.json()
    assert len(patients) == 1
    assert patients[0]["first_name"] == "Gabriel"

    # Search patients by RUT
    res_search_rut = await api_client.get("/api/v1/admin/patients?query=22.222.222-2", headers=provider_headers)
    assert res_search_rut.status_code == 200
    patients_rut = res_search_rut.json()
    assert len(patients_rut) == 1
    assert patients_rut[0]["first_name"] == "Michelle"

    # 6. Dashboard stats and RLS
    # Setup slots for Dr. Vision
    slot_id_1 = 8001
    await db.execute(
        f"INSERT INTO slots (id, provider_id, start_time, end_time, is_available) "
        f"OVERRIDING SYSTEM VALUE VALUES ({slot_id_1}, {prov_id}, '2030-05-30 10:00:00+00', '2030-05-30 10:30:00+00', true)"
    )
    # Book slot
    await db.execute(
        f"INSERT INTO bookings (id, user_id, slot_id, status) OVERRIDING SYSTEM VALUE VALUES (501, {patient_id_1}, {slot_id_1}, 'CONFIRMED')"
    )

    # Fetch stats as Admin (global override)
    res_stats_admin = await api_client.get("/api/v1/dashboard/stats", headers=admin_headers)
    assert res_stats_admin.status_code == 200
    stats_admin = res_stats_admin.json()
    # Should see the active providers
    assert stats_admin["active_providers"] == 1
    
    # Fetch stats as Provider (RLS-enforced: only sees their own stats)
    res_stats_prov = await api_client.get("/api/v1/dashboard/stats", headers=provider_headers)
    assert res_stats_prov.status_code == 200
    stats_prov = res_stats_prov.json()
    assert stats_prov["appointments_today"] == 0 # because date is 2030-05-30, not today
