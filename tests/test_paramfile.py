import pytest

import paramfile


def test_self_test():
    paramfile.self_test()


def test_number_is_arithmetic_only():
    assert paramfile.number("2*4000+1000") == 9000
    assert paramfile.number("-3/4") == -0.75
    for bad in ("__import__('os')", "open('x')", "2**10", "a+1"):
        with pytest.raises(ValueError):
            paramfile.number(bad)


def test_unknown_set_and_name(tmp_path):
    p = tmp_path / "params.txt"
    p.write_text("[A]\nX = 1 ; note\n[SET BIG]\nY = 2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        paramfile.values(str(p), "NOPE")
    with pytest.raises(ValueError):          # a set may only override names that exist
        paramfile.values(str(p), "BIG")
    with pytest.raises(KeyError):
        paramfile.set_value(str(p), "MISSING", 3)


def test_set_value_keeps_sets(tmp_path):
    p = tmp_path / "params.txt"
    p.write_text("[A]\nX = 10 ; [M] measured\n[SET S]\nX = 20\n", encoding="utf-8")
    assert paramfile.set_value(str(p), "X", 12) == "10"
    assert paramfile.values(str(p))["X"] == 12
    assert paramfile.values(str(p), "S")["X"] == 20
