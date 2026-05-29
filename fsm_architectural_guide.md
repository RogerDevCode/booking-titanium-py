# Guía Arquitectónica y Patrón FSM de Titanium Booking

Este documento está diseñado como una referencia técnica y conceptual completa (para consumo por humanos y LLMs) que explica el funcionamiento de los menús, la máquina de estados finitos (FSM), el flujo de información en Titanium Booking y expone un **patrón de diseño de FSM infalible** para evitar fugas de estado u operaciones huérfanas.

---

## 1. Arquitectura de Ingress y Procesamiento Asíncrono

El bot opera bajo una arquitectura dirigida por eventos asíncronos con aislamiento transaccional completo:

```mermaid
flowchart TD
    User((Usuario Telegram)) -->|1. Mensaje / Callback| Ingress[FastAPI Webhook /api/v1/webhook]
    Ingress -->|2. Validar Idempotencia y Rate Limit| Redis[(Redis)]
    Ingress -->|3. Encolar Trabajo| Queue[(Arq Queue)]
    Queue -->|4. Desencolar| Worker[ARQ Worker]
    
    subgraph Pre-Flight I/O (Fuera de Tx)
        Worker --> Prep[Preprocessor: Modismos/Security/PII]
        Worker --> Class[Classifier: NLU Intent]
    end
    
    subgraph Transaction Boundary (Lock FSM)
        Worker --> Lock[Chat Redis Lock]
        Lock --> DBRead[DB: Get state]
        DBRead --> Router{FSM Router}
        Router --> Handler[State Handler]
        Handler --> DBWrite[DB: Set state]
        Handler --> Outbox[DB: Queue Outbox Message]
    end
    
    Worker --> Flush[Flush Outbox: HTTP Send]
    Flush -->|5. Telegram API| User
```

### 1.1 Ingress & Idempotencia (FastAPI Webhook)
Toda interacción de Telegram (un mensaje de texto o el clic de un botón inline) ingresa vía `POST` a `/api/v1/webhook.py`.
- **Idempotencia O(1)**: Antes de procesar, se valida `webhook_seen:{update_id}` en Redis mediante `SET NX EX = 3600`. Si ya fue procesado, se descarta silenciosamente respondiendo 200 OK.
- **Rate Limiting**: Se aplica un bucket por ventana fija de 60s en Redis para el `chat_id` mediante incrementos atómicos (`pipe.incr` + `pipe.expire`). Si supera 10 msgs/min, se devuelve un 200 OK de inmediato sin encolar el trabajo.
- **Encolamiento**: El payload se inserta en ARQ (Redis) para ser ejecutado asíncronamente por el worker, liberando la conexión de Telegram en milisegundos.

---

## 2. Preprocesamiento e Clasificación (Pre-Flight I/O)

El Worker (`tasks.py`) extrae el trabajo y ejecuta el preprocesamiento fuera de cualquier transacción de base de datos para no bloquear conexiones de pool:

1. **Security Scan**: Se filtran ataques de inyección SQL, inyecciones de scripting (XSS) y patrones comunes de Prompt Injection (Jailbreak).
2. **Normalización y Modismos**: Se mapea jerga local médica chilena ("sacar hora" -> "hacer una cita") y se aplican reglas de SymSpell para ortografía tolerante a errores de escritura.
3. **PII Masking**: Cualquier documento identificador (RUT Chileno) es ofuscado a `[RUT_OCULTO]` antes de cruzar boundaries a APIs de IA.
4. **Intent Classifier**: Cuando el FSM está en estado `IDLE` (Menú Principal), un motor híbrido (Layer 0: exactitud numérica/texto, Layer 1: similitud de coseno TF-IDF, Layer 2: LLM fallback con timeout) clasifica la intención del usuario. Este intent se deposita en el contexto temporal `state.context["preflight"]`.

---

## 3. La Máquina de Estados (FSM) y Aislamiento por Lock

Para prevenir condiciones de carrera (por ejemplo, el usuario haciendo doble clic rápido en un botón o mandando mensajes simultáneos), el procesamiento del FSM sigue las siguientes directrices:

### 3.1 Redis Distributed Lock
Antes de leer el estado del usuario, el worker adquiere un candado asíncrono sobre el `chat_id` del usuario en Redis. Ningún otro worker puede procesar mensajes de este usuario simultáneamente.

### 3.2 Postgres SSOT (Single Source of Truth)
El estado de la conversación reside en la tabla `conversation_states`:
```sql
CREATE TABLE conversation_states (
    chat_id BIGINT PRIMARY KEY,
    state VARCHAR(50) NOT NULL, -- Enum FSMState
    active_flow VARCHAR(50),
    context JSONB NOT NULL,
    booking_draft JSONB NOT NULL,
    message_id BIGINT, -- ID del último menú con botones inline enviado
    version INT DEFAULT 0,
    updated_at TIMESTAMP
);
```

### 3.3 El Router Central (`FSMRouter`)
El enrutador despacha la petición al handler asociado al `FSMState` actual.
```python
class FSMRouter:
    def __init__(self):
        self._handlers = {
            FSMState.IDLE: idle_handler,
            FSMState.SELECTING_SPECIALTY: selecting_specialty_handler,
            FSMState.SELECTING_DOCTOR: selecting_doctor_handler,
            FSMState.SELECTING_TIME: selecting_time_handler,
            FSMState.CONFIRMING_BOOKING: confirming_booking_handler,
            # ...
        }
```

---

## 4. Patrón de Diseño para el Manejo y Desactivación de Menús

Para lograr un sistema visualmente limpio y libre de comportamientos erráticos por clics antiguos ("Ghost Menus"), implementamos el **rastreo bidireccional y limpieza del Outbox**.

### 4.1 Identificación de Menús Alfabéticos
Cada menú tiene una letra mayúscula asignada que define inequívocamente su contexto en el flujo conversacional. Esto permite al desarrollador (o a la IA) guiar al usuario mediante referencias claras en el texto:
- `[A]` **Menú Principal**: Estado `IDLE`.
- `[B]` **Seleccionar Especialidad**: Estado `SELECTING_SPECIALTY`.
- `[C]` **Seleccionar Médico**: Estado `SELECTING_DOCTOR`.
- `[D]` **Seleccionar Horario**: Estado `SELECTING_TIME`.
- `[E]` **Confirmar Reserva**: Estado `CONFIRMING_BOOKING`.
- `[F]` **Mis Horas**: Estado `VIEWING_BOOKINGS`.
- `[G]` **Cancelar Cita**: Estado `CANCELLING_BOOKING`.
- `[H]` **Reagendar Cita**: Estado `RESCHEDULING_BOOKING`.
- `[I]` **Información**: Estado `WAITING_FAQ`.
- `[J]` **Mis Datos (Perfil)**: Estado `UPDATING_PROFILE`.

### 4.2 Desactivación de Teclados (Previene Ghost Clicks)
1. **Envío con Registro**: Cuando un menú con botones inline es enviado a Telegram por `flush_outbox` en [sender.py](file:///home/manager/Sync/python_proyects/booking-titanium/app/telegram/sender.py), la API de Telegram devuelve el `message_id` del mensaje enviado. Inmediatamente, actualizamos la tabla `conversation_states` guardando dicho `message_id`.
2. **Desactivación en Próximo Mensaje**: Al inicio del procesamiento del worker en [tasks.py](file:///home/manager/Sync/python_proyects/booking-titanium/app/worker/tasks.py), si se detecta un `state.message_id` guardado en la FSM del usuario, se realiza una llamada a `edit_message_reply_markup(chat_id, message_id, {"inline_keyboard": []})`.
3. **Resultado**: El menú principal o submenu anterior queda **desactivado visualmente** (los botones inline desaparecen del mensaje anterior del historial de chat) antes de procesar el nuevo estado. Si el usuario hace clic en un botón viejo justo antes de que se borre, el worker captura que `callback_data == "ignore"` o que ya se desactivó, descartando la acción y evitando la corrupción del FSM.

---

## 5. Propuesta de Patrón de Diseño FSM Infalible (State Transition Table)

El principal error de las máquinas de estado conversacionales es el acoplamiento directo entre el análisis sintáctico (ej. validar si el usuario escribió "volver") y las transiciones lógicas. Para mitigar esto de forma permanente, proponemos la adopción de una **State Transition Table (STT) Declarativa**:

### 5.1 Definición Declarativa del Grafo
En lugar de programar transiciones imperativas (`state.state = FSMState.X`), se define una matriz de transiciones válidas:

```python
from dataclasses import dataclass
from typing import Dict, Set, Tuple

class FSMTransitionError(Exception):
    pass

# Matriz estática de transiciones permitidas (Grafo Dirigido)
FSM_TRANSITIONS: Dict[FSMState, Set[FSMState]] = {
    FSMState.IDLE: {
        FSMState.SELECTING_SPECIALTY, 
        FSMState.VIEWING_BOOKINGS, 
        FSMState.CANCELLING_BOOKING, 
        FSMState.RESCHEDULING_BOOKING, 
        FSMState.WAITING_FAQ, 
        FSMState.UPDATING_PROFILE
    },
    FSMState.SELECTING_SPECIALTY: {
        FSMState.IDLE,                  # Cancelar/Home
        FSMState.SELECTING_DOCTOR       # Siguiente
    },
    FSMState.SELECTING_DOCTOR: {
        FSMState.IDLE,                  # Cancelar/Home
        FSMState.SELECTING_SPECIALTY,   # Retroceder (Back)
        FSMState.SELECTING_TIME         # Siguiente
    },
    FSMState.SELECTING_TIME: {
        FSMState.IDLE,
        FSMState.SELECTING_DOCTOR,
        FSMState.CONFIRMING_BOOKING
    },
    FSMState.CONFIRMING_BOOKING: {
        FSMState.IDLE,
        FSMState.SELECTING_TIME
    },
    FSMState.VIEWING_BOOKINGS: {
        FSMState.IDLE,
        FSMState.CANCELLING_BOOKING,
        FSMState.RESCHEDULING_BOOKING
    },
    # ...
}
```

### 5.2 Transición Controlada por Guardias (Failsafe)
Cualquier cambio de estado debe ser procesado únicamente a través de un método de transición en la entidad `ConversationState` que valide si la arista existe en el grafo:

```python
@dataclass
class ConversationState:
    chat_id: int
    state: FSMState = FSMState.IDLE
    # ...
    
    def transition_to(self, new_state: FSMState) -> None:
        """
        Valida que la transición del estado actual al nuevo sea permitida en el grafo.
        Previene regresiones ilógicas causadas por condiciones de carrera o clics viejos.
        """
        if new_state == self.state:
            return  # Sin cambios
            
        allowed = FSM_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise FSMTransitionError(
                f"Transición inválida detectada: {self.state.value} -> {new_state.value}"
            )
        
        logger.info("FSM state transition", chat_id=self.chat_id, old=self.state.value, new=new_state.value)
        self.state = new_state
```

### 5.3 Beneficios de la STT Declarativa
1. **Zero State Corruption**: Si un usuario interactúa con un botón obsoleto y el FSM de alguna forma lo procesa, la FSM lanzará un error de transición controlada en lugar de continuar en un estado corrupto (ej: ingresar especialidades cuando se espera confirmación).
2. **Defensa Temprana**: El error es atrapado por el middleware general del worker, restaurando el estado del usuario al menú principal [A] y disculpándose con un mensaje descriptivo sin romper la base de datos.
3. **Análisis Estático**: Permite a tests como `test_fsm_static_graph.py` comprobar matemáticamente la conectividad de todo el grafo (ausencia de ciclos huérfanos, nodos sin aristas, etc.) leyendo únicamente la matriz `FSM_TRANSITIONS`.
