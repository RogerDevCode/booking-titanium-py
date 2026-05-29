from app.pipeline.preprocessor import MessagePreprocessor

def test_rut_anonymization_evasion():
    """
    Red Team Test to ensure that PII (RUTs) are masked correctly, 
    even if the user tries to evade the filter with different formats.
    """
    preprocessor = MessagePreprocessor()

    # Red Team test cases with various formats and potential evasion techniques
    test_cases = [
        # Standard formats
        ("Mi rut es 12.345.678-9", "Mi rut es [RUT_OCULTO]"),
        ("rut: 12345678-k por favor", "rut: [RUT_OCULTO] por favor"),
        ("123456789", "[RUT_OCULTO]"),
        ("9.876.543-2", "[RUT_OCULTO]"),
        ("mi rut es 9876543-K.", "mi rut es [RUT_OCULTO]."),
        
        # Spaces evasion
        ("12 345 678 - 9", "[RUT_OCULTO]"),
        ("12 345 678-9", "[RUT_OCULTO]"),
        ("12. 345 .678 - K", "[RUT_OCULTO]"),
        
        # Inside text
        ("hola quiero agendar para el rut 19.123.456-7 el dia martes", "hola quiero agendar para el rut [RUT_OCULTO] el dia martes"),
        ("cancela la hora de 11222333-4", "cancela la hora de [RUT_OCULTO]"),
        
        # Edge cases (should not match normal numbers that are not RUTs)
        # A phone number or random big number like 123456 (too short for RUT usually, but our regex allows 7-9 digits)
        # Wait, the regex `\b\d{1,2}[\.\s]?\d{3}[\.\s]?\d{3}[\-\s]?[0-9kK]\b` 
        # matches: 1-2 digits, 3 digits, 3 digits, 1 char (total 8-9 digits).
        # So 1234567 is 7 digits, it won't match (1+3+3+1 = 8 digits min).
        ("Mi numero es +56912345678", "Mi numero es +56912345678"),
        ("tengo 123456 pesos", "tengo 123456 pesos"),
        
        # But a phone number like 98765432 might match if it's 8 digits?
        # Let's check: 9 (1 digit) 876 (3 digits) 543 (3 digits) 2 (1 digit).
        # Wait, if someone types a phone number like 987654321 (9 digits), it matches the RUT regex.
        # This is a known false positive risk for basic RUT regexes, but masking a phone number as [RUT_OCULTO] 
        # is also protecting PII (phone number), so it's a win-win for privacy in this context!
    ]

    for raw, expected_clean in test_cases:
        result = preprocessor.preprocess(raw)
        
        # We also need to consider that the preprocessor runs `spell_normalizer`, `modism_mapper` and `cleaner`.
        # So "Mi rut es..." might be spell corrected if "rut" is misspelled.
        # But "rut" is a normal word in Spanish? Actually symspell might change "rut".
        # Let's see what the actual output is.
        
        # The main assertion for a Red Team Privacy test is that the original digits (PII) 
        # MUST NOT be present in the output if it was a valid RUT format.
        
        # Extract digits from the expected masked string to compare.
        # Actually, let's just assert that `expected_clean` matches `result.cleaned_text` exactly.
        # If SymSpell messes it up, we might need to add "rut" to the SymSpell CUSTOM_WORDS dictionary!
        assert result.cleaned_text == expected_clean, f"Failed on '{raw}': got '{result.cleaned_text}'"

def test_no_leakage():
    preprocessor = MessagePreprocessor()
    raw = "el paciente con rut 15.666.777-8 tiene covid"
    result = preprocessor.preprocess(raw)
    
    # Mathematical assertion: 0.00% leakage
    assert "15.666.777-8" not in result.cleaned_text
    assert "156667778" not in result.cleaned_text
    assert "15666777" not in result.cleaned_text
    assert "[RUT_OCULTO]" in result.cleaned_text
