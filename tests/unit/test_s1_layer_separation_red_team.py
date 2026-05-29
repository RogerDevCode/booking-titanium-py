"""
Red Team: S-1 — Capa Repositorio (Separación de Responsabilidades)

Verifica que:
1. booking_flow.py NO contiene imports directos de db_client ni SQL crudo.
2. La función _get_doctor_id_for_booking usa exclusivamente booking_repo.
3. El import de booking_repo está en el top-level del módulo (no lazy/circular).
4. No existen funciones "helper" muertas que eludían la capa de servicio.
"""
import ast
import inspect
import importlib


def _get_booking_flow_source() -> str:
    import app.fsm.booking_flow as mod
    return inspect.getsource(mod)


def _get_booking_flow_ast() -> ast.Module:
    import app.fsm.booking_flow as mod
    src = inspect.getsource(mod)
    return ast.parse(src)


class TestS1LayerSeparation:
    """Garantiza que ningún SQL crudo escapa del repositorio hacia el FSM."""

    def test_no_raw_db_client_import_in_booking_flow(self) -> None:
        """
        S-1 RED TEAM: booking_flow no debe importar db_client directamente.
        Cualquier acceso a BD debe fluir por booking_repo o booking_service.
        """
        src = _get_booking_flow_source()
        # db_client no debe aparecer en absoluto dentro del módulo fsm
        assert "db_client" not in src, (
            "VIOLATION: booking_flow importa db_client directamente. "
            "Todo acceso a BD debe ir por booking_repo."
        )

    def test_no_raw_sql_strings_in_booking_flow(self) -> None:
        """
        S-1 RED TEAM: No deben existir strings con SELECT/INSERT/UPDATE/DELETE
        dentro del módulo fsm/booking_flow.py.
        """
        src = _get_booking_flow_source()
        forbidden_keywords = ["SELECT ", "INSERT INTO", "UPDATE ", "DELETE FROM"]
        for kw in forbidden_keywords:
            assert kw not in src, (
                f"VIOLATION: SQL crudo encontrado ('{kw}') en booking_flow.py. "
                "Debe delegarse al booking_repo."
            )

    def test_booking_repo_imported_at_module_level(self) -> None:
        """
        S-1 RED TEAM: booking_repo debe estar importado al inicio del módulo,
        NO dentro de funciones (lazy imports crean dependencias circulares ocultas).
        """
        tree = _get_booking_flow_ast()
        
        # Recopila todos los import statements al nivel raíz del módulo
        top_level_imports: list[str] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    top_level_imports.append(alias.name)

        assert "booking_repo" in top_level_imports, (
            "VIOLATION: booking_repo no está importado en el top-level de booking_flow.py. "
            "Un lazy import puede ocultar dependencias circulares y complica el mock en tests."
        )

    def test_no_dead_helper_functions_bypassing_repo(self) -> None:
        """
        S-1 RED TEAM: selected_specialty_name() era una función muerta que accedía
        a atributos de ORM directamente. Verificar que ya no existe.
        """
        src = _get_booking_flow_source()
        assert "def selected_specialty_name" not in src, (
            "VIOLATION: La función `selected_specialty_name` persiste. "
            "Era un helper muerto que evitaba la capa de servicio/repositorio."
        )

    def test_get_doctor_id_uses_repo_not_db_client(self) -> None:
        """
        S-1 RED TEAM: La función _get_doctor_id_for_booking debe delegar
        exclusivamente a booking_repo, sin acceder a db_client.
        """
        import app.fsm.booking_flow as mod
        src = inspect.getsource(mod._get_doctor_id_for_booking)
        assert "booking_repo" in src, (
            "VIOLATION: _get_doctor_id_for_booking no usa booking_repo."
        )
        assert "db_client" not in src, (
            "VIOLATION: _get_doctor_id_for_booking accede a db_client directamente."
        )
        # Verificar que NO hay import lazy dentro de la función
        assert "from app.db" not in src, (
            "VIOLATION: Import lazy de db dentro de la función — "
            "debe moverse al top-level del módulo."
        )

    def test_booking_repo_module_exists_and_is_coherent(self) -> None:
        """
        S-1 RED TEAM: El módulo booking_repo debe poder importarse sin errores
        y debe exponer el singleton `booking_repo`.
        """
        mod = importlib.import_module("app.db.repositories.booking_repo")
        assert hasattr(mod, "booking_repo"), (
            "VIOLATION: app.db.repositories.booking_repo no expone el singleton `booking_repo`."
        )
        repo = mod.booking_repo
        # Debe tener todos los métodos requeridos por el dominio
        required_methods = [
            "get_user_bookings_view",
            "cancel_booking_tx",
            "reschedule_booking_tx",
            "get_all_specialties",
            "get_providers_by_specialty",
            "get_available_slots",
            "create_booking_tx",
            "get_provider_id_by_booking",
        ]
        for method in required_methods:
            assert hasattr(repo, method), (
                f"VIOLATION: booking_repo no expone el método `{method}`. "
                "La capa de servicio no puede completar su contrato."
            )
