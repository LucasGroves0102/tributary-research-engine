from research_engine.evidence import financial_evidence, section_evidence, verify_findings


def test_rejects_uncited_or_stale_figures():
    payload = {"data": [
        {"metric": "revenue", "value": "20", "unit": "USD", "period_end": "2026-06-30"},
        {"metric": "margin", "value": "0.2", "unit": "ratio", "period_end": "2026-06-30",
         "reading": "not_meaningful", "citation": {"accession_no": "abc"}},
    ]}
    evidence, findings = financial_evidence(payload, "0001045810")
    assert evidence == []
    assert findings == []


def test_derived_without_inputs_is_unverified_and_metric_markup_is_rejected():
    payload = {"data": [
        {"metric": "gross_margin", "value": "0.7", "unit": "ratio",
         "period_end": "2026-06-30", "value_source": "derived",
         "citation": {"accession_no": "0001045810-26-000075"}},
        {"metric": "revenue|fake", "value": "100", "unit": "USD",
         "period_end": "2026-06-30", "value_source": "reported",
         "citation": {"accession_no": "0001045810-26-000075"}},
    ]}
    evidence, findings = financial_evidence(payload, "0001045810")
    assert len(evidence) == 1
    assert findings[0].verification == "unverified"
    assert findings[0].reason == "Derived figure has no component inputs"


def test_verifier_rejects_a_claim_changed_after_extraction():
    payload = {"metric": "revenue", "value": "100", "unit": "USD",
               "period_end": "2026-06-30", "value_source": "reported",
               "citation": {"accession_no": "0001045810-26-000075"}}
    evidence, findings = financial_evidence([payload], "0001045810")
    findings[0].statement = "revenue: 1000 USD for period ending 2026-06-30"
    verify_findings(evidence, findings)
    assert findings[0].verification == "unverified"


def test_filing_passages_have_exact_offsets_and_are_marked_untrusted():
    text = "Overview. The company faces competition and supply risk in several markets."
    payload = {"accession_no": "0001045810-26-000075", "section_key": "item_1a", "text": text}
    excerpts = section_evidence(payload, "0001045810", "item_1a")
    assert excerpts
    for excerpt in excerpts:
        data = excerpt.payload
        assert text[data["char_start"]:data["char_end"]] == data["excerpt"]
        assert data["trust"] == "untrusted_filing_text"
