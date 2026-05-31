import pytest
from app.core.crypto import decrypt_data

@pytest.mark.asyncio
async def test_compliance_phi_plaintext_exposure(integration_container, clean_db_and_redis):
    """
    Red Team Test: Ensures clinical notes containing PHI (Protected Health Information)
    are NEVER stored in plaintext in the database columns.
    """
    db = integration_container.db_client
    provider_id = 10
    client_id = 1
    
    # 1. Insert parent foreign keys to meet integrity constraints
    await db.execute("INSERT INTO specialties (id, name) OVERRIDING SYSTEM VALUE VALUES (1, 'Cardiología') ON CONFLICT DO NOTHING")
    await db.execute("INSERT INTO providers (id, name, specialty_id) OVERRIDING SYSTEM VALUE VALUES ($1, 'Dr. Audit', 1) ON CONFLICT DO NOTHING", provider_id)
    await db.execute("INSERT INTO users (id, first_name) VALUES ($1, 'John') ON CONFLICT DO NOTHING", client_id)
    
    # 2. Create the note
    content = "Paciente con diagnóstico reservado y antecedentes de VIH y arritmia."
    note = await integration_container.note_service.create_note(
        provider_id=provider_id,
        booking_id=None,
        client_id=client_id,
        content=content,
        tag_names=["Confidencial"]
    )
    
    # 3. Query the raw database directly to verify encryption in repos
    raw_row = await db.fetchrow("SELECT content_encrypted FROM service_notes WHERE id = $1", note["id"])
    assert raw_row is not None
    ciphertext = raw_row["content_encrypted"]
    
    #Plaintext words MUST NOT be present in database record
    assert content not in ciphertext
    assert "VIH" not in ciphertext
    assert "arritmia" not in ciphertext
    
    # Verify decrypting recovers the original text
    decrypted = decrypt_data(ciphertext)
    assert decrypted == content

@pytest.mark.asyncio
async def test_service_notes_rls_isolation(integration_container, clean_db_and_redis):
    """
    Ensures Postgres RLS (Row Level Security) prevents provider A from reading
    or writing clinical notes belonging to provider B.
    """
    db = integration_container.db_client
    
    # 1. Setup providers
    await db.execute("INSERT INTO specialties (id, name) OVERRIDING SYSTEM VALUE VALUES (1, 'General') ON CONFLICT DO NOTHING")
    await db.execute("INSERT INTO providers (id, name, specialty_id) OVERRIDING SYSTEM VALUE VALUES (10, 'Dr. A', 1) ON CONFLICT DO NOTHING")
    await db.execute("INSERT INTO providers (id, name, specialty_id) OVERRIDING SYSTEM VALUE VALUES (20, 'Dr. B', 1) ON CONFLICT DO NOTHING")
    await db.execute("INSERT INTO users (id, first_name) VALUES (1, 'Patient') ON CONFLICT DO NOTHING")
    
    # 2. Dr A creates a note under RLS context 10
    async with db.transaction() as conn:
        await conn.execute("SELECT set_config('app.current_provider_id', '10', true)")
        await conn.execute("SELECT set_config('app.admin_override', 'false', true)")
        
        note = await integration_container.note_service.create_note(
            provider_id=10,
            booking_id=None,
            client_id=1,
            content="Nota confidencial del Dr. A",
            tag_names=["Confidencial"]
        )
        
    # 3. Dr B attempts to fetch the note under RLS context 20
    async with db.transaction() as conn:
        await conn.execute("SELECT set_config('app.current_provider_id', '20', true)")
        await conn.execute("SELECT set_config('app.admin_override', 'false', true)")
        
        # Service get_note
        fetched_note = await integration_container.note_service.get_note(provider_id=20, note_id=note["id"])
        assert fetched_note is None, "Dr. B was able to fetch Dr. A's clinical note!"
        
        # Service list_notes should not return Dr. A's note
        notes = await integration_container.note_service.list_notes(provider_id=20)
        assert len(notes) == 0 or all(n["id"] != note["id"] for n in notes)
