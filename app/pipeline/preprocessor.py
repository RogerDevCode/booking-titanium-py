import re
import unicodedata
import os
from typing import List, Tuple, Final
from symspellpy import SymSpell, Verbosity
from app.domain.models import (
    PreprocessorOutput, 
    SpellCorrection, 
    ModismMatch, 
    SecurityScanResult, 
    ExtractedEntities
)
from app.core.logging import logger

class ThreatScanner:
    """Scans for SQLi, XSS, and Prompt Injection."""
    
    PATTERNS: Final[dict[str, list[re.Pattern[str]]]] = {
        "prompt_injection": [
            re.compile(p, re.IGNORECASE) for p in [
                r"\b(?:ignora|olvida|desestima|cancela)\b.*\b(?:instrucciones|reglas|prompt|anterior)\b",
                r"\b(?:eres|actua como|simula ser)\b.*\b(?:un|una)\b.*\b(?:bot|ia|asistente|humano)\b",
                r"\b(?:ignore|forget|disregard|override)\b.{0,40}\b(?:instructions?|rules?|prompt|previous|above)\b",
            ]
        ],
        "sql_injection": [
            re.compile(p, re.IGNORECASE) for p in [
                r"\b(?:drop|delete|truncate|update|insert|alter)\b.*?(?:table|from|into|set|database|view)\b",
                r";\s*--",
                r"(?:'|\")\s*(?:or|and)\s*(?:'|\"|\d+|\w+)\s*=",
            ]
        ],
        "xss": [
            re.compile(p, re.IGNORECASE) for p in [
                r"(?:javascript:|vbscript:|data:text/html)",
                r"\b(?:onerror|onload|onclick)\s*=",
                r"<\s*script",
                r"<\s*iframe",
            ]
        ]
    }

    def scan(self, text: str) -> tuple[str, SecurityScanResult]:
        safe_text = unicodedata.normalize("NFKC", text)
        for threat_type, patterns in self.PATTERNS.items():
            for pattern in patterns:
                if pattern.search(safe_text):
                    logger.warning("Security threat detected", threat_type=threat_type)
                    return pattern.sub("[CENSURADO]", safe_text), SecurityScanResult(
                        threat_detected=True, 
                        threat_type=threat_type # type: ignore
                    )
        return safe_text, SecurityScanResult(threat_detected=False, threat_type="none")

class ModismMapper:
    """Handles Chilean medical slang."""
    
    MODISMS: Final[List[Tuple[str, str]]] = [
        ("sacar hora", "hacer una cita"),
        ("pedir hora", "solicitar cita"),
        ("tener hora", "tener cita"),
        ("dar hora", "dar cita"),
        ("hay hora", "hay disponibilidad"),
        ("al tiro", "de inmediato"),
        ("kanselame", "cancélame"),
        ("kiero", "quiero"),
        ("ora", "hora"),
        ("sita", "cita"),
        ("manana", "mañana"),
        ("bieres", "viernes"),
        ("pal", "para el"),
        ("pa", "para"),
        ("weon", ""),
        ("po", ""),
    ]

    def apply(self, text: str) -> tuple[str, List[ModismMatch]]:
        matches = []
        result = text
        for phrase, canonical in self.MODISMS:
            pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
            if pattern.search(result):
                matches.append(ModismMatch(phrase=phrase, canonical=canonical))
                result = pattern.sub(canonical if canonical else "", result)
        return re.sub(r"\s+", " ", result).strip(), matches

class SpellNormalizer:
    """Corrects Spanish spelling using SymSpell."""
    
    CUSTOM_WORDS: Final[List[str]] = [
        "quiero", "necesito", "puedo", "agendar", "cancelar", "reagendar", 
        "fonasa", "isapre", "isapres", "doctor", "doctora", "cita", "hora", "rut"
    ]

    def __init__(self):
        self._sym_spell = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
        dict_path = os.path.join(os.path.dirname(__file__), "es_50k.txt")
        if os.path.exists(dict_path):
            self._sym_spell.load_dictionary(dict_path, term_index=0, count_index=1)
        for word in self.CUSTOM_WORDS:
            self._sym_spell.create_dictionary_entry(word, 99999999)

    def correct(self, text: str) -> tuple[str, List[SpellCorrection]]:
        if text.startswith("/"):
            return text, []
        
        tokens = re.findall(r"\w+|\W+", text)
        corrections = []
        result_parts = []
        
        for token in tokens:
            if not re.match(r"^\w+$", token) or len(token) < 3:
                result_parts.append(token)
                continue
            
            suggestions = self._sym_spell.lookup(token.lower(), Verbosity.CLOSEST, max_edit_distance=2)
            if suggestions and suggestions[0].term != token.lower():
                corrections.append(SpellCorrection(original=token, corrected=suggestions[0].term))
                result_parts.append(suggestions[0].term)
            else:
                result_parts.append(token)
        
        return "".join(result_parts), corrections

class TextCleaner:
    @staticmethod
    def clean(text: str) -> str:
        text = re.sub(r'<[^>]*>', '', text) # Remove HTML
        text = "".join(ch for ch in text if unicodedata.category(ch)[0] != 'C') # Remove control chars
        return re.sub(r"\s+", " ", text).strip()

class PIIAnonymizer:
    """Masks PII like Chilean RUTs."""
    
    # Matches formats like: 12.345.678-9, 12345678-k, 123456789, 12 345 678 - 9
    RUT_PATTERN: Final[re.Pattern[str]] = re.compile(
        r'\b\d{1,2}[\.\s]*\d{3}[\.\s]*\d{3}[\-\s]*[0-9kK]\b'
    )
    
    @classmethod
    def mask(cls, text: str) -> str:
        return cls.RUT_PATTERN.sub('[RUT_OCULTO]', text)

# Cache the heavy components at the module level
_threat_scanner = None
_modism_mapper = None
_spell_normalizer = None
_cleaner = None
_pii_anonymizer = None

class MessagePreprocessor:
    """Orchestrates the full preprocessing pipeline."""
    
    def __init__(self):
        global _threat_scanner, _modism_mapper, _spell_normalizer, _cleaner, _pii_anonymizer
        
        if _threat_scanner is None:
            _threat_scanner = ThreatScanner()
            _modism_mapper = ModismMapper()
            _spell_normalizer = SpellNormalizer()
            _cleaner = TextCleaner()
            _pii_anonymizer = PIIAnonymizer()
            
        self.threat_scanner = _threat_scanner
        self.modism_mapper = _modism_mapper
        self.spell_normalizer = _spell_normalizer
        self.cleaner = _cleaner
        self.pii_anonymizer = _pii_anonymizer

    def preprocess(self, raw_text: str) -> PreprocessorOutput:
        # 1. Security Scan (Scan RAW text to catch XSS before cleaning)
        working, security_scan = self.threat_scanner.scan(raw_text)
        
        # 2. Basic Clean
        working = self.cleaner.clean(working)
        
        # 3. Modisms (Slang)
        working, modism_matches = self.modism_mapper.apply(working)
        
        # 4. Spell Correction
        working, spell_corrections = self.spell_normalizer.correct(working)
        
        # 5. Final Clean & PII Anonymization
        cleaned_text = self.cleaner.clean(working)
        cleaned_text = self.pii_anonymizer.mask(cleaned_text)
        
        # 6. Entities (Stub for now)
        extracted_entities = ExtractedEntities()
        
        # Confidence calculation
        word_count = max(len(raw_text.split()), 1)
        penalty = len(spell_corrections) / word_count * 0.3
        confidence = round(max(0.5, 1.0 - penalty), 3)

        return PreprocessorOutput(
            raw_text=raw_text,
            cleaned_text=cleaned_text,
            normalization_applied=bool(modism_matches or spell_corrections),
            spell_corrections=spell_corrections,
            modism_matches=modism_matches,
            confidence=confidence,
            extracted_entities=extracted_entities,
            security_scan=security_scan
        )
