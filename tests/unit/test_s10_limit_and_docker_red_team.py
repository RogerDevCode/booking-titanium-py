"""
Red Team: S-10 — LIMIT configurable en get_available_slots + Perfiles Docker

Verifica que:
1. booking_repo.get_available_slots acepta y propaga correctamente `limit`.
2. booking_service.get_available_slots reenvía `limit` al repositorio.
3. La query SQL contiene el placeholder $2 (param) en lugar de un LIMIT hardcodeado.
4. El docker-compose.yml declara perfiles `dev` y `prod` separados.
5. El perfil prod usa --workers y el perfil dev usa --reload (hot-reload).
"""
import inspect
import re
from unittest.mock import patch
import pytest


class TestS10SlotLimit:
    """Garantiza que la capa de datos respeta el límite configurable de slots."""

    def test_booking_repo_get_available_slots_has_limit_param(self) -> None:
        """
        S-10 RED TEAM: get_available_slots debe aceptar `limit` como parámetro
        con valor por defecto de 15 (no hardcodeado a 10 ni sin límite).
        """
        from app.db.repositories.booking_repo import BookingRepository
        import inspect as ins
        sig = ins.signature(BookingRepository.get_available_slots)
        assert "limit" in sig.parameters, (
            "VIOLATION: get_available_slots no acepta parámetro `limit`. "
            "Sin él, una BD con 1000 slots disponibles los devuelve todos."
        )
        default = sig.parameters["limit"].default
        assert default == 15, (
            f"VIOLATION: El límite por defecto es {default}, debe ser 15. "
            "El valor anterior (10) era arbitrario; 15 permite 3 páginas de 5."
        )

    def test_booking_service_propagates_limit(self) -> None:
        """
        S-10 RED TEAM: booking_service.get_available_slots debe reenviar `limit`
        al repositorio, no usar un valor fijo.
        """
        from app.services.booking_service import BookingService
        import inspect as ins
        sig = ins.signature(BookingService.get_available_slots)
        assert "limit" in sig.parameters, (
            "VIOLATION: BookingService.get_available_slots no propaga `limit`. "
            "La capa de servicio silencia el control del caller."
        )

    def test_booking_repo_sql_uses_parametrized_limit(self) -> None:
        """
        S-10 RED TEAM: La query SQL en get_available_slots debe usar $2 (parametrizado)
        en lugar de LIMIT hardcodeado. Un LIMIT hardcodeado viola el principio abierto/cerrado.
        """
        from app.db.repositories.booking_repo import BookingRepository
        src = inspect.getsource(BookingRepository.get_available_slots)
        # Debe tener $2 como parámetro de LIMIT
        assert "$2" in src, (
            "VIOLATION: La query SQL usa un LIMIT hardcodeado en lugar de $2. "
            "Cambiar el límite requeriría una edición de código en lugar de un parámetro."
        )
        # No debe tener LIMIT seguido directamente de un número
        hardcoded = re.search(r"LIMIT\s+\d+", src)
        assert hardcoded is None, (
            f"VIOLATION: LIMIT hardcodeado detectado: '{hardcoded.group()}'. "
            "Reemplazar con el parámetro $2."
        )

    @pytest.mark.asyncio
    async def test_limit_is_forwarded_to_db_fetch(self) -> None:
        """
        S-10 RED TEAM: Simula una llamada con limit=3 y verifica que el valor
        llegue hasta db_client.fetch() como segundo argumento posicional.
        """
        from app.db.repositories.booking_repo import BookingRepository

        captured_args: list = []

        async def fake_fetch(query: str, *args):
            captured_args.extend(args)
            return []

        from unittest.mock import AsyncMock
        repo = BookingRepository(db=AsyncMock())
        with patch("app.db.repositories.booking_repo.db_client.fetch", side_effect=fake_fetch):
            await repo.get_available_slots("provider-xyz", limit=3)

        assert len(captured_args) == 2, (
            f"VIOLATION: db_client.fetch recibió {len(captured_args)} args, esperaba 2 "
            "(provider_id + limit)."
        )
        assert captured_args[1] == 3, (
            f"VIOLATION: El limit={captured_args[1]} llegó a fetch, pero se esperaba 3. "
            "El parámetro no se propaga correctamente."
        )

    @pytest.mark.asyncio
    async def test_default_limit_is_used_when_not_specified(self) -> None:
        """
        S-10 RED TEAM: Cuando no se especifica limit, debe usarse el valor default (15).
        """
        from app.db.repositories.booking_repo import BookingRepository

        captured_args: list = []

        async def fake_fetch(query: str, *args):
            captured_args.extend(args)
            return []

        from unittest.mock import AsyncMock
        repo = BookingRepository(db=AsyncMock())
        with patch("app.db.repositories.booking_repo.db_client.fetch", side_effect=fake_fetch):
            await repo.get_available_slots("provider-abc")

        assert captured_args[1] == 15, (
            f"VIOLATION: El default limit llegó como {captured_args[1]}, se esperaba 15."
        )


class TestS10DockerProfiles:
    """Garantiza que docker-compose.yml tiene perfiles dev/prod bien separados."""

    def _load_compose(self) -> str:
        from pathlib import Path
        p = Path(__file__).parents[2] / "docker-compose.yml"
        return p.read_text()

    def test_dev_profile_uses_reload_flag(self) -> None:
        """
        S-10 RED TEAM: El perfil dev debe usar --reload para hot-reloading.
        """
        src = self._load_compose()
        assert "--reload" in src, (
            "VIOLATION: No se encontró --reload en docker-compose.yml. "
            "El perfil dev debe permitir hot-reload para el workflow de desarrollo."
        )

    def test_prod_profile_uses_workers_flag(self) -> None:
        """
        S-10 RED TEAM: El perfil prod debe usar --workers para aprovechar multicore.
        """
        src = self._load_compose()
        assert "--workers" in src, (
            "VIOLATION: No se encontró --workers en docker-compose.yml. "
            "El perfil prod debe escalar horizontalmente en el mismo pod."
        )

    def test_dev_and_prod_profiles_declared(self) -> None:
        """
        S-10 RED TEAM: Ambos perfiles deben estar declarados explícitamente.
        """
        src = self._load_compose()
        assert 'profiles: ["dev"]' in src or "profiles:\n    - dev" in src, (
            "VIOLATION: El perfil 'dev' no está declarado en docker-compose.yml."
        )
        assert 'profiles: ["prod"]' in src or "profiles:\n    - prod" in src, (
            "VIOLATION: El perfil 'prod' no está declarado en docker-compose.yml."
        )

    def test_prod_does_not_mount_source_volume(self) -> None:
        """
        S-10 RED TEAM: El perfil prod NO debe montar .:/app (volumen de código fuente).
        Hacerlo expone código fuente y degrada el aislamiento del contenedor de producción.
        """
        src = self._load_compose()
        # Buscar la sección api-prod y asegurar que no monta .:/app
        prod_section_start = src.find("api-prod:")
        assert prod_section_start != -1, "No se encontró sección api-prod en docker-compose.yml"
        # Siguiente servicio o fin de archivo
        next_service = src.find("\n  ", prod_section_start + len("api-prod:") + 1)
        prod_section = src[prod_section_start:next_service] if next_service != -1 else src[prod_section_start:]
        assert ".:/app" not in prod_section, (
            "VIOLATION: El perfil prod monta .:/app. "
            "En producción el código debe estar dentro del contenedor, no montado."
        )
