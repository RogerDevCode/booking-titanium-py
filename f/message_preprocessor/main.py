# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pydantic>=2.10.0",
#   "beartype>=0.19.0",
#   "symspellpy>=6.9.0",
#   "rapidfuzz>=3.5.2",
#   "jellyfish>=1.0.3",
#   "dateparser>=1.2.0"
# ]
# ///
from __future__ import annotations

import importlib.resources
import os
import re
import unicodedata
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict
from symspellpy import SymSpell, Verbosity  # type: ignore[import-untyped]

from ..internal._wmill_adapter import log
from ..nlu._datetime_resolver import ResolverResult, resolve_datetime

# =====================================================================
# CONSTANTS & REGEXES
# =====================================================================

_STRIP_CATEGORIES: frozenset[str] = frozenset({"Cc", "Cf"})

URL_REGEX: Final[re.Pattern[str]] = re.compile(r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+")
PHONE_REGEX: Final[re.Pattern[str]] = re.compile(r"(?:\+?56)?\s*9\s*\d{4}\s*\d{4}")
RUT_REGEX: Final[re.Pattern[str]] = re.compile(r"\b(\d{1,2}(?:\.\d{3}){2}-[\dkK]|\d{7,8}-[\dkK])\b")

EMOJI_DICT: Final[dict[str, str]] = {
    "👍": "[aprobacion]",
    "👎": "[desaprobacion]",
    "😊": "[sonrisa]",
    "😂": "[risa]",
    "😔": "[tristeza]",
    "😡": "[enojo]",
    "🙏": "[por_favor]",
    "❌": "[cancelar]",
    "✅": "[confirmar]",
    "⏰": "[reloj]",
    "📅": "[calendario]",
    "📞": "[telefono]",
}

_PROMPT_INJECTION_PATTERNS = [
    r"\b(?:ignora|olvida|desestima|cancela)\b.*\b(?:instrucciones|reglas|prompt|anterior)\b",
    r"\b(?:eres|actua como|simula ser)\b.*\b(?:un|una)\b.*\b(?:bot|ia|asistente|humano)\b",
    r"\b(?:system prompt|developer prompt|system message)\b",
    r"\b(?:olvida todo|nuevo objetivo|nueva directiva)\b",
    r"\b(?:ignore|forget|disregard|override)\b.{0,40}\b(?:instructions?|rules?|prompt|previous|above)\b",
    r"\b(?:you are now|act as|pretend to be|roleplay as|simulate being|from now on you)\b",
    r"\b(?:jailbreak|dan mode|developer mode|god mode|unrestricted mode)\b",
    r"\b(?:new instruction|new directive|new goal|new objective|new persona)\b",
    r"\b(?:ignore all|forget all|disregard all)\b",
]

_COMMAND_INJECTION_PATTERNS = [
    r"(?:\.\./\.\./|/etc/passwd|/bin/sh|/bin/bash|cmd\.exe|powershell)",
    r"(?:\$\(|`|;.*\||\|\||&&)",
    r"\b(?:curl|wget|nc|bash|sh|rm|del|chmod|chown)\s+-",
]

_XSS_PATTERNS = [
    r"(?:javascript:|vbscript:|data:text/html)",
    r"\b(?:onerror|onload|onclick|onmouseover|onfocus|onblur)\s*=",
]

_SQL_PATTERNS = [
    r"\b(?:drop)(?:\s+|/\*.*?\*/)+(?:table|database|schema|view|index|user|role)\b",
    r"\b(?:delete)(?:\s+|/\*.*?\*/)+(?:from)\b",
    r"\b(?:truncate)(?:\s+|/\*.*?\*/)+(?:table)\b",
    r"\b(?:insert)(?:\s+|/\*.*?\*/)+(?:into)\b",
    r"\b(?:update)(?:\s+|/\*.*?\*/)+.*?(?:\s+|/\*.*?\*/)+(?:set)\b",
    r"\b(?:select)(?:\s+|/\*.*?\*/)+.*?(?:\s+|/\*.*?\*/)+(?:from)\b",
    r"\b(?:alter)(?:\s+|/\*.*?\*/)+(?:table|database|schema|user|role)\b",
    r"\b(?:grant)(?:\s+|/\*.*?\*/)+(?:all|select|insert|update|delete)\b",
    r"\b(?:revoke)(?:\s+|/\*.*?\*/)+(?:all|select|insert|update|delete)\b",
    r";\s*--",  
    r"--\s*(?:drop|delete|select|insert|update|truncate|alter|grant|revoke)\b",
    r";\s*(?:drop|delete|truncate|update|insert|alter|grant|revoke)\b",
]

_COMPILED_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "prompt_injection": [re.compile(p, re.IGNORECASE) for p in _PROMPT_INJECTION_PATTERNS],
    "command_injection": [re.compile(p, re.IGNORECASE) for p in _COMMAND_INJECTION_PATTERNS],
    "xss": [re.compile(p, re.IGNORECASE) for p in _XSS_PATTERNS],
    "sql_injection": [re.compile(p, re.IGNORECASE) for p in _SQL_PATTERNS],
}

_MODISMS: Final[tuple[tuple[str, str], ...]] = (
    ("sacar hora", "hacer una cita"),
    ("pedir hora", "solicitar cita"),
    ("tener hora", "tener cita"),
    ("dar hora", "dar cita"),
    ("hay hora", "hay disponibilidad"),
    ("al tiro", "de inmediato"),
    ("kanselame", "cancélame"),
    ("kansela", "cancela"),
    ("kambiar", "cambiar"),
    ("konsulta", "consulta"),
    ("kiero", "quiero"),
    ("orita", "ahora"),
    ("ora", "hora"),
    ("sita", "cita"),
    ("truno", "turno"),
    ("bieres", "viernes"),
    ("vierne", "viernes"),
    ("savado", "sabado"),
    ("lune", "lunes"),
    ("manana", "mañana"),
    ("mñn", "mañana"),
    ("pal", "para el"),
    ("pa", "para"),
    ("prox", "próximo"),
    ("weon", ""),
    ("weón", ""),
    ("po", ""),
)

_CUSTOM_WORDS: Final[tuple[str, ...]] = (
    "quiero", "quieres", "queremos", "quisiera", "quisiero", "necesito", "necesitas", "necesitamos",
    "puedo", "puedes", "podemos", "podría", "podrias", "tengo", "tienes", "tiene", "tenemos",
    "debo", "debes", "debemos", "viene", "vienen", "oiga", "oye", "haga", "hagame", "dígame", "digame",
    "confirmame", "hola", "buenos", "buenas", "dias", "días", "gracias", "favor", "posible",
    "sabado", "miercoles", "proxima", "proximas", "proximos", "agendar", "cancelar", "cancelarme",
    "reagendar", "reprogramar", "disponibilidad", "agenda", "turno", "consulta", "médico", "médica",
    "doctor", "doctora", "cita", "hora", "reserva", "especialista", "próximo", "próxima", "urgente",
    "urgentes", "inmediato", "inmediata", "inmediatos", "solicitar", "cancélame", "fonasa", "isapre",
    "isapres", "banmedica", "banmédica", "colmena", "consalud", "masvida", "vidatres", "redbanc",
    "webpay", "copago", "arancel", "reembolso", "boleta", "bono", "tramo", "samu", "telemedicina",
    "teleconsulta", "interconsulta", "ecografia", "ecografía", "hemograma", "glicemia", "dislipidemia",
    "kinesiologia", "kinesiología", "recordatorio", "recordatorios",
)

_MIN_WORD_LEN: Final[int] = 3
_TITLES: Final[frozenset[str]] = frozenset({"dr", "dra", "doctor", "doctora", "don", "doña", "dona", "sr", "sra", "srta", "sta"})
MODULE: Final[str] = "spell_normalizer"
_sym_spell: SymSpell | None = None

# =====================================================================
# MODELS
# =====================================================================

class SpellCorrection(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    original: str
    corrected: str

class ModismMatch(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    phrase: str
    canonical: str

class SecurityScanResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    threat_detected: bool = False
    threat_type: Literal["sql_injection", "xss", "command_injection", "prompt_injection", "none"] = "none"

class ExtractedEntities(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    urls: list[str] = []
    phones: list[str] = []
    ruts: list[str] = []

class PreprocessorInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    raw_text: str

class PreprocessorOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    raw_text: str
    cleaned_text: str
    normalization_applied: bool
    spell_corrections: list[SpellCorrection]
    modism_matches: list[ModismMatch]
    confidence: float
    extracted_entities: ExtractedEntities | None = None
    datetime_resolution: ResolverResult | None = None
    security_scan: SecurityScanResult


# =====================================================================
# CORE LOGIC
# =====================================================================

def _remove_invisible_chars(text: str) -> str:
    return "".join(c for c in text if unicodedata.category(c) not in _STRIP_CATEGORIES)

def _remove_html_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)

def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def clean_text(text: str) -> str:
    working = unicodedata.normalize("NFKC", text)
    working = _collapse_whitespace(working)
    working = _remove_invisible_chars(working)
    working = _remove_html_tags(working)
    return _collapse_whitespace(working)

def _validate_rut(rut: str) -> bool:
    clean_rut = rut.replace(".", "").replace("-", "").upper()
    if len(clean_rut) < 8:
        return False
    body = clean_rut[:-1]
    dv = clean_rut[-1]
    if not body.isdigit():
        return False
    try:
        s = sum(int(d) * ((i % 6) + 2) for i, d in enumerate(reversed(body)))
        expected_dv = str((11 - (s % 11)) % 11)
        if expected_dv == "10":
            expected_dv = "K"
        return expected_dv == dv
    except Exception:
        return False

def extract_entities(text: str) -> tuple[str, ExtractedEntities]:
    entities = ExtractedEntities()
    urls = URL_REGEX.findall(text)
    if urls:
        entities.urls = urls
        text = URL_REGEX.sub("[URL]", text)
    phones = PHONE_REGEX.findall(text)
    if phones:
        entities.phones = [p.replace(" ", "") for p in phones]
        text = PHONE_REGEX.sub("[TELEFONO]", text)
    ruts_raw = RUT_REGEX.findall(text)
    valid_ruts: list[str] = []
    for r in ruts_raw:
        if _validate_rut(r):
            valid_ruts.append(r)
            text = text.replace(r, "[RUT]")
    if valid_ruts:
        entities.ruts = valid_ruts
    for emoji, desc in EMOJI_DICT.items():
        if emoji in text:
            text = text.replace(emoji, f" {desc} ")
    text = re.sub(r"\s+", " ", text).strip()
    return text, entities

def scan_threats(text: str) -> tuple[str, SecurityScanResult]:
    safe_text = unicodedata.normalize("NFKC", text)
    for threat_type, patterns in _COMPILED_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(safe_text):
                safe_text = pattern.sub("[CENSURADO]", safe_text)
                return safe_text, SecurityScanResult(threat_detected=True, threat_type=threat_type)  # type: ignore
    return safe_text, SecurityScanResult(threat_detected=False, threat_type="none")

def apply_modism_map(text: str) -> tuple[str, list[ModismMatch]]:
    matches: list[ModismMatch] = []
    result = text
    for phrase, canonical in _MODISMS:
        pattern = re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
        if not pattern.search(result):
            continue
        matches.append(ModismMatch(phrase=phrase, canonical=canonical))
        replacement = canonical if canonical else ""
        result = pattern.sub(replacement, result)
    result = re.sub(r"\s+", " ", result).strip()
    return result, matches

def _get_checker() -> SymSpell:
    global _sym_spell
    if _sym_spell is not None:
        return _sym_spell
    sym_spell = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    try:
        dict_resource = importlib.resources.files(__package__).joinpath("es_50k.txt")
        with importlib.resources.as_file(dict_resource) as dict_path:
            if os.path.exists(dict_path):
                sym_spell.load_dictionary(str(dict_path), term_index=0, count_index=1)
            else:
                log("CRITICAL_MISSING_DICTIONARY", error="es_50k.txt not found. SymSpell running degraded.", module=MODULE)
    except Exception as e:
        log("CRITICAL_MISSING_DICTIONARY", error=f"Failed to load es_50k.txt: {e}. SymSpell running degraded.", module=MODULE)
    for word in _CUSTOM_WORDS:
        sym_spell.create_dictionary_entry(word, 99999999)
    _sym_spell = sym_spell
    return sym_spell

def apply_spell_correction(text: str) -> tuple[str, list[SpellCorrection]]:
    if text.startswith("/"):
        return text, []
    checker = _get_checker()
    tokens = re.findall(r"\w+|\W+", text)
    corrections: list[SpellCorrection] = []
    result_parts: list[str] = []
    prev_word_lower: str | None = None
    for token in tokens:
        if not re.match(r"^\w+$", token):
            result_parts.append(token)
            continue
        word_lower = token.lower()
        prev = prev_word_lower
        prev_word_lower = word_lower
        if word_lower in _TITLES or prev in _TITLES:
            result_parts.append(token)
            continue
        if len(word_lower) < _MIN_WORD_LEN:
            result_parts.append(token)
            continue
        suggestions = checker.lookup(word_lower, Verbosity.CLOSEST, max_edit_distance=2)
        if not suggestions:
            result_parts.append(token)
            continue
        suggestion = suggestions[0].term
        if suggestion == word_lower:
            result_parts.append(token)
            continue
        corrections.append(SpellCorrection(original=token, corrected=suggestion))
        result_parts.append(suggestion)
    return "".join(result_parts), corrections

def _preprocess(raw_text: str) -> PreprocessorOutput:
    working, extracted_entities = extract_entities(raw_text)
    working = clean_text(working)
    working, security_scan = scan_threats(working)
    working, modism_matches = apply_modism_map(working)
    working, spell_corrections = apply_spell_correction(working)
    cleaned_text = clean_text(working)
    normalization_applied = bool(modism_matches or spell_corrections)
    dt_res = resolve_datetime(cleaned_text)
    word_count = max(len(raw_text.split()), 1)
    penalty = len(spell_corrections) / word_count * 0.3
    confidence = round(max(0.5, 1.0 - penalty), 3)
    return PreprocessorOutput(
        raw_text=raw_text,
        cleaned_text=cleaned_text,
        normalization_applied=normalization_applied,
        spell_corrections=spell_corrections,
        modism_matches=modism_matches,
        confidence=confidence,
        extracted_entities=extracted_entities,
        datetime_resolution=dt_res,
        security_scan=security_scan,
    )

def main(data: dict[str, Any]) -> dict[str, Any]:
    import asyncio
    import time
    from ..internal._wmill_adapter import log

    async def _run() -> dict[str, Any]:
        start = time.perf_counter()
        validated = PreprocessorInput.model_validate(data)
        result = _preprocess(validated.raw_text)
        elapsed_ms = (time.perf_counter() - start) * 1000
        log("LATENCY_INTAKE", elapsed_ms=elapsed_ms, module="message_preprocessor")
        output: dict[str, Any] = result.model_dump()
        return output

    return asyncio.run(_run())
