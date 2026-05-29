"""
Red Team: Docker + Scripts Infalibles

Verifica de forma estática y funcional:
1. docker-compose.yml — estructura, perfiles, watch, logging, dependencias
2. tdu.sh / tdd.sh — defensividad, set -e, guards, v2 de Docker Compose
3. Dockerfile — sin secretos bakeados, usuario no-root
"""
import subprocess
import yaml
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[2]
COMPOSE = ROOT / "docker-compose.yml"
TDU = ROOT / "tdu.sh"
TDD = ROOT / "tdd.sh"
DOCKERFILE = ROOT / "Dockerfile"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def compose_data() -> dict:
    with COMPOSE.open() as f:
        return yaml.safe_load(f)


def _run_script(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile tests
# ─────────────────────────────────────────────────────────────────────────────
class TestDockerfile:
    def _src(self) -> str:
        return DOCKERFILE.read_text()

    def test_no_env_file_copied(self) -> None:
        """
        RED TEAM: El Dockerfile NO debe copiar .env dentro de la imagen.
        Los secretos se inyectan en runtime vía env_file de docker-compose.
        """
        src = self._src()
        assert "COPY .env" not in src, (
            "VIOLATION: El Dockerfile copia .env → secretos bakeados en imagen. "
            "Usa env_file en docker-compose.yml en su lugar."
        )

    def test_non_root_user_created(self) -> None:
        """
        RED TEAM: El contenedor debe correr como usuario no-root (appuser).
        """
        src = self._src()
        assert "USER appuser" in src, (
            "VIOLATION: El Dockerfile no declara USER no-root. "
            "Correr como root en contenedor es un riesgo de seguridad crítico."
        )

    def test_uv_used_for_dependency_install(self) -> None:
        """
        RED TEAM: Las dependencias deben instalarse con `uv sync --frozen`
        para garantizar reproducibilidad exacta del entorno.
        """
        src = self._src()
        assert "uv sync --frozen" in src, (
            "VIOLATION: No se usa `uv sync --frozen`. "
            "Sin --frozen, la imagen puede instalar versiones distintas a uv.lock."
        )


# ─────────────────────────────────────────────────────────────────────────────
# docker-compose.yml tests
# ─────────────────────────────────────────────────────────────────────────────
class TestDockerCompose:
    def test_dev_profile_services_complete(self, compose_data: dict) -> None:
        """
        RED TEAM: El perfil dev debe incluir exactamente: api, worker, poller
        (más db y redis sin perfil).
        """
        services = compose_data["services"]
        dev_services = {
            name for name, cfg in services.items()
            if "dev" in cfg.get("profiles", [])
        }
        assert dev_services == {"api", "worker", "poller"}, (
            f"VIOLATION: Los servicios del perfil dev son incorrectos: {dev_services}"
        )

    def test_prod_profile_services_complete(self, compose_data: dict) -> None:
        """
        RED TEAM: El perfil prod debe incluir: api-prod, worker-prod, poller-prod.
        """
        services = compose_data["services"]
        prod_services = {
            name for name, cfg in services.items()
            if "prod" in cfg.get("profiles", [])
        }
        assert prod_services == {"api-prod", "worker-prod", "poller-prod"}, (
            f"VIOLATION: Los servicios del perfil prod son incorrectos: {prod_services}"
        )

    def test_infra_services_have_no_profile(self, compose_data: dict) -> None:
        """
        RED TEAM: db y redis NO deben tener perfil — deben levantarse siempre
        independientemente del entorno.
        """
        services = compose_data["services"]
        for name in ("db", "redis"):
            profiles = services[name].get("profiles", [])
            assert not profiles, (
                f"VIOLATION: El servicio '{name}' tiene perfil {profiles}. "
                "La infraestructura de base debe estar siempre disponible."
            )

    def test_infra_services_have_healthcheck(self, compose_data: dict) -> None:
        """
        RED TEAM: db y redis deben tener healthcheck configurado.
        Sin healthcheck, los servicios dependientes arrancan antes de que BD esté lista.
        """
        services = compose_data["services"]
        for name in ("db", "redis"):
            assert "healthcheck" in services[name], (
                f"VIOLATION: '{name}' no tiene healthcheck. "
                "Los servicios dependientes pueden arrancar con BD no lista."
            )

    def test_api_dev_has_develop_watch(self, compose_data: dict) -> None:
        """
        RED TEAM: El servicio `api` (dev) debe tener `develop.watch` configurado
        para auto-rebuild/sync cuando cambia el código fuente.
        """
        api = compose_data["services"]["api"]
        assert "develop" in api, (
            "VIOLATION: 'api' (dev) no tiene sección 'develop'. "
            "Sin develop.watch, los cambios de código requieren restart manual."
        )
        assert "watch" in api["develop"], (
            "VIOLATION: 'api' (dev) tiene 'develop' pero sin 'watch'. "
        )

    def test_worker_dev_has_develop_watch(self, compose_data: dict) -> None:
        """
        RED TEAM: El servicio `worker` (dev) también debe tener develop.watch.
        """
        worker = compose_data["services"]["worker"]
        assert "develop" in worker and "watch" in worker["develop"], (
            "VIOLATION: 'worker' (dev) no tiene develop.watch. "
            "Cambios en app/ no se reflejarán en el worker sin restart."
        )

    def test_prod_services_have_no_source_volume(self, compose_data: dict) -> None:
        """
        RED TEAM: Los servicios de prod (api-prod, worker-prod, poller-prod)
        NO deben montar .:/app. El código debe estar sellado en la imagen.
        """
        services = compose_data["services"]
        for name in ("api-prod", "worker-prod", "poller-prod"):
            volumes = services[name].get("volumes", [])
            source_mounts = [v for v in volumes if str(v).startswith(".:/app")]
            assert not source_mounts, (
                f"VIOLATION: '{name}' monta .:/app en producción. "
                "El código fuente no debe estar disponible fuera del contenedor en prod."
            )

    def test_prod_api_uses_multiple_workers(self, compose_data: dict) -> None:
        """
        RED TEAM: api-prod debe especificar --workers en su command.
        """
        cmd = compose_data["services"]["api-prod"].get("command", [])
        assert "--workers" in cmd, (
            "VIOLATION: api-prod no usa --workers. "
            "Un solo proceso uvicorn desperdicia los núcleos disponibles en prod."
        )

    def test_dev_api_uses_reload(self, compose_data: dict) -> None:
        """
        RED TEAM: api (dev) debe usar --reload para hot-reload.
        """
        cmd = compose_data["services"]["api"].get("command", [])
        assert "--reload" in cmd, (
            "VIOLATION: api (dev) no usa --reload. "
            "El workflow de desarrollo requiere hot-reload para ser productivo."
        )

    def test_poller_prod_points_to_api_prod(self, compose_data: dict) -> None:
        """
        RED TEAM: poller-prod debe apuntar a http://api-prod:..., no a http://api:...
        Si apunta al servicio dev, en prod el poller no puede alcanzar la API.
        """
        env = compose_data["services"]["poller-prod"].get("environment", [])
        webhook_url = next(
            (e for e in env if "API_WEBHOOK_URL" in str(e)), None
        )
        assert webhook_url is not None, (
            "VIOLATION: poller-prod no define API_WEBHOOK_URL."
        )
        url_value = webhook_url if isinstance(webhook_url, str) else str(webhook_url)
        assert "api-prod" in url_value, (
            f"VIOLATION: poller-prod apunta a '{url_value}' en lugar de 'api-prod'. "
            "En prod, el poller no puede alcanzar el servicio 'api' (perfil dev)."
        )

    def test_all_app_services_have_env_file(self, compose_data: dict) -> None:
        """
        RED TEAM: Todos los servicios de aplicación (no infra) deben tener env_file.
        Sin env_file, las variables del .env no se inyectan → errores silenciosos.
        """
        app_services = [
            "api", "api-prod", "worker", "worker-prod", "poller", "poller-prod"
        ]
        services = compose_data["services"]
        for name in app_services:
            assert "env_file" in services[name], (
                f"VIOLATION: '{name}' no tiene 'env_file' configurado. "
                "Las variables de entorno del .env no serán inyectadas."
            )

    def test_logging_configured_on_infra(self, compose_data: dict) -> None:
        """
        RED TEAM: db y redis deben tener logging driver con max-size configurado.
        Sin límite, los logs pueden saturar el disco del host.
        """
        services = compose_data["services"]
        for name in ("db", "redis"):
            assert "logging" in services[name], (
                f"VIOLATION: '{name}' no tiene configuración de logging. "
                "Los logs de PostgreSQL/Redis pueden llenar el disco sin límite."
            )


# ─────────────────────────────────────────────────────────────────────────────
# tdu.sh + tdd.sh script tests
# ─────────────────────────────────────────────────────────────────────────────
class TestShellScripts:
    def test_tdu_has_set_e_pipefail(self) -> None:
        """
        RED TEAM: tdu.sh debe iniciar con `set -euo pipefail`.
        Sin esto, un fallo en el build no detiene el script.
        """
        src = TDU.read_text()
        assert "set -euo pipefail" in src, (
            "VIOLATION: tdu.sh no usa 'set -euo pipefail'. "
            "Un fallo silencioso puede dejar el stack en estado parcial."
        )

    def test_tdd_has_set_e_pipefail(self) -> None:
        """
        RED TEAM: tdd.sh debe iniciar con `set -euo pipefail`.
        """
        src = TDD.read_text()
        assert "set -euo pipefail" in src, (
            "VIOLATION: tdd.sh no usa 'set -euo pipefail'."
        )

    def test_tdu_checks_docker_compose_v2(self) -> None:
        """
        RED TEAM: tdu.sh debe verificar que `docker compose` (v2) está disponible,
        no el wrapper deprecado `docker-compose` (v1).
        """
        src = TDU.read_text()
        assert "docker compose version" in src, (
            "VIOLATION: tdu.sh no verifica docker compose v2. "
            "En sistemas con solo docker-compose v1 fallará críticamente."
        )

    def test_tdd_checks_docker_compose_v2(self) -> None:
        src = TDD.read_text()
        assert "docker compose version" in src, (
            "VIOLATION: tdd.sh no verifica docker compose v2."
        )

    def test_tdu_checks_env_file_exists(self) -> None:
        """
        RED TEAM: tdu.sh debe verificar que .env existe antes de intentar levantar.
        """
        src = TDU.read_text()
        assert '".env"' in src or "[ ! -f" in src, (
            "VIOLATION: tdu.sh no verifica la existencia de .env. "
            "Sin .env, los contenedores arrancan sin variables de entorno."
        )

    def test_tdu_invalid_arg_exits_nonzero(self) -> None:
        """
        RED TEAM: tdu.sh debe fallar con código de salida != 0 ante un argumento inválido.
        """
        result = _run_script(TDU, "--arg-invalido-xyz")
        assert result.returncode != 0, (
            f"VIOLATION: tdu.sh terminó con código 0 ante argumento inválido. "
            f"stdout: {result.stdout!r}"
        )
        assert "Argumento desconocido" in result.stdout or "Argumento desconocido" in result.stderr

    def test_tdd_invalid_arg_exits_nonzero(self) -> None:
        """
        RED TEAM: tdd.sh debe fallar ante argumento inválido.
        """
        result = _run_script(TDD, "--arg-invalido-xyz")
        assert result.returncode != 0

    def test_tdu_help_exits_zero(self) -> None:
        """
        RED TEAM: --help debe salir con código 0 (no es un error).
        """
        result = _run_script(TDU, "--help")
        assert result.returncode == 0, (
            f"VIOLATION: tdu.sh --help salió con código {result.returncode}."
        )

    def test_tdd_help_exits_zero(self) -> None:
        result = _run_script(TDD, "--help")
        assert result.returncode == 0

    def test_tdu_uses_docker_compose_v2_syntax_in_commands(self) -> None:
        """
        RED TEAM: tdu.sh no debe invocar `docker-compose` (guion) como comando.
        Puede mencionar 'docker-compose.yml' o 'docker-compose-plugin' en comentarios,
        pero NO debe ejecutar el binario v1 deprecado.
        """
        import re
        src = TDU.read_text()
        # Detectar invocaciones reales del comando: docker-compose seguido de espacio/newline/tab/argumento
        # Excluir: docker-compose.yml (nombre de archivo) y docker-compose-plugin (nombre de paquete)
        bad_calls = re.findall(r'(?<![\w.])docker-compose(?![\.\-]\w)', src)
        assert not bad_calls, (
            f"VIOLATION: tdu.sh invoca 'docker-compose' (v1) {len(bad_calls)} vez/veces. "
            "Usa 'docker compose' (v2 plugin) en su lugar."
        )

    def test_tdd_uses_docker_compose_v2_syntax_in_commands(self) -> None:
        import re
        src = TDD.read_text()
        bad_calls = re.findall(r'(?<![\w.])docker-compose(?![\.\-]\w)', src)
        assert not bad_calls, (
            f"VIOLATION: tdd.sh invoca 'docker-compose' (v1) {len(bad_calls)} vez/veces. "
            "Usa 'docker compose' (v2 plugin) en su lugar."
        )

    def test_tdu_supports_prod_flag(self) -> None:
        """
        RED TEAM: tdu.sh debe reconocer --prod como argumento válido.
        """
        src = TDU.read_text()
        assert "--prod" in src, (
            "VIOLATION: tdu.sh no soporta --prod. "
            "No hay forma de levantar el stack en modo producción."
        )

    def test_tdu_supports_watch_flag(self) -> None:
        """
        RED TEAM: tdu.sh debe soportar --watch para activar docker compose watch.
        """
        src = TDU.read_text()
        assert "--watch" in src, (
            "VIOLATION: tdu.sh no soporta --watch. "
            "El auto-rebuild/sync al cambiar código no está disponible."
        )

    def test_tdd_supports_clean_flag_with_guard(self) -> None:
        """
        RED TEAM: tdd.sh con --clean debe pedir confirmación antes de borrar volúmenes.
        Un --clean sin confirmación puede destruir datos de producción accidentalmente.
        """
        src = TDD.read_text()
        assert "--clean" in src, (
            "VIOLATION: tdd.sh no soporta --clean."
        )
        # Debe haber un read o confirmación antes de ejecutar --volumes
        assert "read" in src, (
            "VIOLATION: --clean no pide confirmación antes de borrar volúmenes. "
            "Una ejecución accidental destruiría los datos de la BD."
        )

    def test_scripts_are_executable(self) -> None:
        """
        RED TEAM: Los scripts deben tener permisos de ejecución.
        Sin +x, deben ejecutarse explícitamente con bash (propenso a errores de usuario).
        """
        import os
        assert os.access(TDU, os.X_OK), (
            f"VIOLATION: {TDU.name} no tiene permisos de ejecución (+x)."
        )
        assert os.access(TDD, os.X_OK), (
            f"VIOLATION: {TDD.name} no tiene permisos de ejecución (+x)."
        )
