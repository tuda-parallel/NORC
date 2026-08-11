from compare_to_ground_truth import select_rule_based


def test_recommended_used_when_eligible():
    selected = select_rule_based({"PAPI_TOT_INS": 0.1, "PAPI_LD_INS": 0.2})
    assert selected["Total instructions"] == ("PAPI_TOT_INS", 0.1)
    assert selected["Load instructions"] == ("PAPI_LD_INS", 0.2)


def test_falls_back_to_best_alternative():
    selected = select_rule_based({"PAPI_BR_INS": 0.9, "PAPI_BR_CN": 0.3, "PAPI_BR_TKN": 0.6})
    assert selected["Branch instructions"] == ("PAPI_BR_CN", 0.3)


def test_category_dropped_when_nothing_eligible():
    selected = select_rule_based({"PAPI_INT_INS": 0.9})
    assert "Integer operations" not in selected


if __name__ == "__main__":
    test_recommended_used_when_eligible()
    test_falls_back_to_best_alternative()
    test_category_dropped_when_nothing_eligible()
    print("ok")
