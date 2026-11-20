"""Тесты share_calculator: все векторы при MIN_SHARE = 0 и 1."""
import random

import pytest

import app.services.share_calculator as sc
from app.core.errors import AppError
from app.services.share_calculator import OfferInput, calculate_shares, shares_valid


def _offers(spec):
    return [
        OfferInput(
            id=oid,
            share=share,
            is_fixed=(mark == "F"),
            is_new=(mark == "new"),
            is_pivot=(mark == "pivot"),
        )
        for oid, share, mark in spec
    ]


# (имя, вход, {MIN_SHARE: ожидаемые shares или код ошибки})
VECTORS = [
    ("V1",  [(1, 50, "F"), (2, 30, ""), (3, 20, "")],
     {0: [50, 30, 20], 1: [50, 30, 20]}),
    ("V2",  [(1, 50, "F"), (2, 30, ""), (3, 20, ""), (4, 0, "new")],
     {0: [50, 20, 13, 17], 1: [50, 20, 13, 17]}),
    ("V3",  [(1, 50, "F"), (2, 30, "")],
     {0: [50, 50], 1: [50, 50]}),
    ("V4",  [(1, 50, "F"), (2, 40, "pivot"), (3, 20, "")],
     {0: [50, 40, 10], 1: [50, 40, 10]}),
    ("V5",  [(1, 0, ""), (2, 0, ""), (3, 0, "")],
     {0: [34, 33, 33], 1: [34, 33, 33]}),
    ("V6",  [(1, 60, "F"), (2, 50, "F"), (3, 0, "")],
     {0: "FIXED_SUM_EXCEEDS_100", 1: "FIXED_SUM_EXCEEDS_100"}),
    ("V7",  [(1, 50, "F"), (2, 40, "F")],
     {0: "FIXED_SUM_MUST_BE_100", 1: "FIXED_SUM_MUST_BE_100"}),
    ("V8",  [(1, 50, "F"), (2, 50, "F")],
     {0: [50, 50], 1: [50, 50]}),
    ("V9",  [(1, 1, ""), (2, 2, ""), (3, 4, "")],
     {0: [14, 29, 57], 1: [15, 29, 56]}),
    ("V10", [(1, 30, "F"), (2, 0, ""), (3, 0, "")],
     {0: [30, 35, 35], 1: [30, 35, 35]}),
    ("V11", [(1, 37, "")],
     {0: [100], 1: [100]}),
    ("V12", [(1, 100, ""), (2, 0, "new")],
     {0: [50, 50], 1: [50, 50]}),
    ("V13", [(1, 1, ""), (2, 1, ""), (3, 1, "")],
     {0: [34, 33, 33], 1: [34, 33, 33]}),
    ("V14", [],
     {0: [], 1: []}),
    ("V15", [(1, 100, "F"), (2, 0, "new")],
     {0: [100, 0], 1: "INFEASIBLE_SHARES"}),
]


@pytest.mark.parametrize("min_share", [0, 1])
@pytest.mark.parametrize("name, spec, expected", VECTORS, ids=[v[0] for v in VECTORS])
def test_appendix_c(monkeypatch, min_share, name, spec, expected):
    monkeypatch.setattr(sc, "MIN_SHARE", min_share)
    want = expected[min_share]
    if isinstance(want, str):
        with pytest.raises(AppError) as e:
            calculate_shares(_offers(spec))
        assert e.value.code == want
        assert e.value.status == 422
    else:
        got = calculate_shares(_offers(spec))
        assert [s.share for s in got] == want
        assert [s.id for s in got] == [o[0] for o in spec]
        assert sum(s.share for s in got) == 100 or not got


@pytest.mark.parametrize("min_share, expected", [(0, [100, 0]), (1, "INFEASIBLE_SHARES")])
def test_explicit_min_share_has_priority(monkeypatch, min_share, expected):
    monkeypatch.setattr(sc, "MIN_SHARE", 1 - min_share)  # константа не та — проверяем аргумент
    spec = [(1, 100, "F"), (2, 0, "new")]
    if isinstance(expected, str):
        with pytest.raises(AppError) as e:
            calculate_shares(_offers(spec), min_share=min_share)
        assert e.value.code == expected
    else:
        assert [s.share for s in calculate_shares(_offers(spec), min_share=min_share)] == expected


@pytest.mark.parametrize("min_share", [0, 1])
def test_empty_list_is_allowed(monkeypatch, min_share):
    monkeypatch.setattr(sc, "MIN_SHARE", min_share)
    assert calculate_shares([]) == []
    assert shares_valid([]) is False


@pytest.mark.parametrize("shares, valid", [
    ([100], True), ([50, 50], True), ([34, 33, 33], True),
    ([], False), ([50, 49], False), ([101], False), ([0, 100], False),
])
def test_shares_valid(shares, valid):
    assert shares_valid(shares) is valid


@pytest.mark.parametrize("min_share", [0, 1])
def test_deterministic_remainders(monkeypatch, min_share):
    monkeypatch.setattr(sc, "MIN_SHARE", min_share)
    spec = [(1, 1, ""), (2, 1, ""), (3, 1, "")]
    runs = [[s.share for s in calculate_shares(_offers(spec))] for _ in range(20)]
    assert all(r == runs[0] for r in runs)
    assert runs[0][0] == 34  # лишняя единица — самому первому


@pytest.mark.parametrize("min_share", [0, 1])
def test_property_sum_or_error(monkeypatch, min_share):
    monkeypatch.setattr(sc, "MIN_SHARE", min_share)
    rng = random.Random(42 + min_share)
    for _ in range(100):
        n = rng.randint(1, 8)
        spec = [
            (i, rng.randint(0, 100), "F" if rng.random() < 0.25 else "")
            for i in range(1, n + 1)
        ]
        try:
            result = calculate_shares(_offers(spec))
        except AppError:
            continue
        assert sum(s.share for s in result) == 100
        assert all(min_share <= s.share <= 100 for s in result)
        assert shares_valid([s.share for s in result], min_share=min_share)