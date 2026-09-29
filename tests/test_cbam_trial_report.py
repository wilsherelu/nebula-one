from nebula_one.exports.cbam_trial_report import render_cbam_trial_html


def test_cbam_report_contains_frozen_numbers_and_escapes_source_labels():
    report = render_cbam_trial_html({
        "specific_embedded_emissions": {"value": "1.950739734", "unit": "t CO2e/t product"},
        "attributed_emissions": {"direct": {"value": "0.001950739734", "unit": "t CO2e",
            "exchanges": [{"exchange_id": "<emission>", "emission_kind": "process",
                           "amount": "0.01", "unit": "kg CO2e"}]}},
        "method_package": {"ref": "reviewed@1", "content_sha256": "method-hash"},
        "source_snapshot": {"id": "snapshot-1", "content_sha256": "snapshot-hash"},
        "goods": {"aggregated_goods_category": "Crude steel", "cn_code": "7207"},
        "activity_level": {"value": "0.001", "unit": "t product"},
        "status": "trial_passed", "content_sha256": "result-hash",
        "coverage": {"open_items": []},
    })
    assert "1.950739734" in report and "snapshot-hash" in report
    assert "&lt;emission&gt;" in report and "<emission>" not in report
