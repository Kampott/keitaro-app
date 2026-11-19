"""Автоматический пересчёт shares офферов потока (ТЗ §4.7, Приложение C).

Чистая функция: только целые числа, без БД / FastAPI / HTTP / float / Decimal.
Рабочее значение MIN_SHARE = 1: WRITE-проверка §2.3 п.8 не проводилась.
Тесты прогоняют ВСЕ векторы Приложения C и для MIN_SHARE = 0.
"""
from dataclasses import dataclass
from typing import Sequence

from app.core.errors import AppError

MIN_SHARE = 1
TOTAL = 100


@dataclass(frozen=True)
class OfferInput:
    """Один активный локальный оффер в стабильном порядке (created_at, id).

    is_new   — только что добавлен/восстановлен: вес берём по остальным;
    is_pivot — share только что введён вручную: считается закреплённым (D1).
    """
    id: int
    share: int
    is_fixed: bool = False
    is_new: bool = False
    is_pivot: bool = False


@dataclass(frozen=True)
class Share:
    id: int
    share: int


def _err(code: str, message: str, **details) -> AppError:
    return AppError(code, message, status=422, details=details or None)


def calculate_shares(
    offers: Sequence[OfferInput], *, min_share: int | None = None
) -> list[Share]:
    """Итоговые shares в том же порядке, что и вход.

    Пустой список — допустимое локальное состояние (шаг 1 §4.7).
    Ошибки: INVALID_SHARES, FIXED_SUM_EXCEEDS_100, FIXED_SUM_MUST_BE_100,
    INFEASIBLE_SHARES — все с HTTP 422; вызывающий не меняет свои данные.
    """
    minimum = MIN_SHARE if min_share is None else min_share

    if not offers:
        return []

    seen = set()
    for o in offers:
        if o.id in seen:
            raise _err("INVALID_SHARES", "Оффер дублируется в потоке", offer_id=o.id)
        seen.add(o.id)
        if not isinstance(o.share, int) or o.share < 0 or o.share > TOTAL:
            raise _err(
                "INVALID_SHARES", "Share должен быть целым от 0 до 100",
                offer_id=o.id, share=o.share,
            )
        if (o.is_fixed or o.is_pivot) and not (minimum <= o.share <= TOTAL):
            raise _err(
                "INVALID_SHARES", "Закреплённый share вне диапазона",
                offer_id=o.id, share=o.share, min_share=minimum,
            )

    fixed = [o for o in offers if o.is_fixed or o.is_pivot]
    free = [o for o in offers if not (o.is_fixed or o.is_pivot)]
    f_sum = sum(o.share for o in fixed)

    if f_sum > TOTAL:
        raise _err("FIXED_SUM_EXCEEDS_100", "Сумма закреплённых shares больше 100", fixed_sum=f_sum)

    if not free:
        if f_sum != TOTAL:
            raise _err("FIXED_SUM_MUST_BE_100", "Все офферы закреплены, но их сумма не 100", fixed_sum=f_sum)
        return [Share(o.id, o.share) for o in offers]

    n = len(free)
    r = TOTAL - f_sum
    if r < minimum * n:
        raise _err(
            "INFEASIBLE_SHARES", "Не хватает долей, чтобы дать каждому офферу минимум",
            free=n, remainder=r, min_share=minimum,
        )

    # шаг 6: новый оффер получает целое среднее весов остальных незакреплённых
    weights: list[int] = []
    for i, o in enumerate(free):
        if o.is_new:
            others = [x.share for j, x in enumerate(free) if j != i and not x.is_new]
            weights.append(max(1, sum(others) // len(others)) if others else 1)
        else:
            weights.append(o.share)

    w_sum = sum(weights)
    if w_sum == 0:
        weights = [1] * n
        w_sum = n

    # шаги 7–8: largest remainder; при равенстве — первый в стабильном порядке
    r_m = r - minimum * n
    base: list[int] = []
    rem: list[int] = []
    for weight in weights:
        product = r_m * weight
        base.append(product // w_sum)
        rem.append(product % w_sum)

    missing = r_m - sum(base)
    for i in sorted(range(n), key=lambda k: (-rem[k], k))[:missing]:
        base[i] += 1

    # шаг 9
    free_shares = {o.id: minimum + b for o, b in zip(free, base)}
    result = [
        Share(o.id, free_shares[o.id])
        if not (o.is_fixed or o.is_pivot)
        else Share(o.id, o.share)
        for o in offers
    ]
    assert sum(s.share for s in result) == TOTAL
    return result


def shares_valid(shares: Sequence[int], *, min_share: int | None = None) -> bool:
    """Статус shares_valid из §4.8 п.5 (пустой список → false)."""
    minimum = MIN_SHARE if min_share is None else min_share
    return bool(shares) and sum(shares) == TOTAL and all(minimum <= s <= TOTAL for s in shares)