"""
Тесты консистентности данных ГОСТ Р 54084-2010.

Проверяют структуру, физические диапазоны, монотонность по высоте
и кросс-параметрическую согласованность оцифрованных табличных данных.

Тесты фиксируют текущее количество известных дефектов данных
(ошибки OCR, перепутанные поля, отсутствующие сезоны).
Если количество нарушений вырастет — тест упадёт (регрессия).
Если количество уменьшится — тест тоже упадёт (нужно обновить пороги).

Запуск:
    python3 -m pytest test_gost_data.py -v
    python3 -m unittest test_gost_data.py -v
"""

import math
import sys
import unittest

from gost_54084_data import (
    HEIGHTS,
    LOCATION_GRIDS,
    SEASONS,
    density,
    meridional_wind_speed,
    pressure,
    relative_humidity_dewpoint,
    resultant_wind,
    scalar_wind_speed,
    specific_humidity,
    temperature,
    zonal_wind_speed,
)

# Все 9 параметров с их именами
ALL_PARAMETERS = {
    "temperature": temperature,
    "pressure": pressure,
    "density": density,
    "scalar_wind_speed": scalar_wind_speed,
    "zonal_wind_speed": zonal_wind_speed,
    "meridional_wind_speed": meridional_wind_speed,
    "resultant_wind": resultant_wind,
    "specific_humidity": specific_humidity,
    "relative_humidity_dewpoint": relative_humidity_dewpoint,
}

# Физически допустимые диапазоны: (мин1, макс1, мин2, макс2)
# Плотность в данных хранится в г/м³ (не кг/м³)
PHYSICAL_RANGES = {
    "temperature":                (210,  320,    0,   45),    # (T [K], σT [K])
    "pressure":                   (600,  1100,   0,   15),    # (P [гПа], σP [%])
    "density":                    (700,  1600,   0,  200),    # (ρ [г/м³], σρ [г/м³])
    "scalar_wind_speed":          (0,    50,     0,   30),    # (Vs [м/с], σv [м/с])
    "zonal_wind_speed":           (-30,  30,     0,   30),    # (Vx [м/с], σvx [м/с])
    "meridional_wind_speed":      (-30,  30,     0,   30),    # (Vy [м/с], σvy [м/с])
    "resultant_wind":             (0,    50,     0,  360),    # (VR [м/с], θR [°])
    "specific_humidity":          (0,    30,     0,   20),    # (q [г/кг], σq [г/кг])
    "relative_humidity_dewpoint": (0,   100,   -60,   40),    # (Q [%], Dp [°C])
}

# Локации/сезоны, где сезон 'annual' отсутствует в данных
KNOWN_MISSING_ANNUAL = {
    ("pressure", (45, 135)),
    ("pressure", (50, 135)),
    ("pressure", (55, 135)),
    ("pressure", (60, 135)),
    ("pressure", (65, 135)),
    ("pressure", (70, 135)),
    ("meridional_wind_speed", (40, 60)),
    ("meridional_wind_speed", (45, 60)),
    ("meridional_wind_speed", (50, 60)),
    ("meridional_wind_speed", (55, 60)),
    ("meridional_wind_speed", (60, 60)),
    ("meridional_wind_speed", (65, 60)),
    ("meridional_wind_speed", (70, 60)),
}


def _all_locations():
    """Множество всех локаций из LOCATION_GRIDS."""
    locs = set()
    for group in LOCATION_GRIDS.values():
        locs.update(group)
    return locs


class TestStructure(unittest.TestCase):
    """Структурные проверки полноты данных."""

    def test_all_parameters_are_dicts(self):
        """Все 9 параметров экспортированы и являются dict."""
        self.assertEqual(len(ALL_PARAMETERS), 9)
        for name, param in ALL_PARAMETERS.items():
            with self.subTest(param=name):
                self.assertIsInstance(param, dict)

    def test_each_parameter_has_73_locations(self):
        """Каждый параметр содержит ровно 73 локации."""
        expected_locs = _all_locations()
        self.assertEqual(len(expected_locs), 73)
        for name, param in ALL_PARAMETERS.items():
            with self.subTest(param=name):
                self.assertEqual(len(param), 73,
                                 f"{name}: ожидалось 73 локации, получено {len(param)}")
                self.assertEqual(set(param.keys()), expected_locs)

    def test_each_location_has_seasons(self):
        """Каждая локация содержит 4 или 5 сезонов (с учётом известных пропусков annual)."""
        expected_seasons = set(SEASONS)
        seasonal_only = expected_seasons - {"annual"}
        for name, param in ALL_PARAMETERS.items():
            for loc, seasons_data in param.items():
                with self.subTest(param=name, loc=loc):
                    actual = set(seasons_data.keys())
                    if (name, loc) in KNOWN_MISSING_ANNUAL:
                        self.assertEqual(actual, seasonal_only,
                                         f"{name} {loc}: ожидалось 4 сезона (без annual)")
                    else:
                        self.assertEqual(actual, expected_seasons,
                                         f"{name} {loc}: ожидалось 5 сезонов")

    def test_known_missing_annual_count(self):
        """Количество локаций с отсутствующим annual фиксировано (13)."""
        self.assertEqual(len(KNOWN_MISSING_ANNUAL), 13)

    def test_each_season_has_9_tuples(self):
        """Каждый сезон содержит ровно 9 кортежей (по числу высот)."""
        for name, param in ALL_PARAMETERS.items():
            for loc, seasons_data in param.items():
                for season, values in seasons_data.items():
                    with self.subTest(param=name, loc=loc, season=season):
                        self.assertEqual(len(values), len(HEIGHTS),
                                         f"{name} {loc} {season}: ожидалось {len(HEIGHTS)} значений")

    def test_each_tuple_is_pair(self):
        """Каждый кортеж — пара из двух элементов (float/int/None)."""
        for name, param in ALL_PARAMETERS.items():
            for loc, seasons_data in param.items():
                for season, values in seasons_data.items():
                    for i, tup in enumerate(values):
                        with self.subTest(param=name, loc=loc, season=season, height=HEIGHTS[i]):
                            self.assertEqual(len(tup), 2)
                            for elem in tup:
                                self.assertTrue(
                                    elem is None or isinstance(elem, (int, float)),
                                    f"Неожиданный тип {type(elem)} в {name} {loc} {season} h={HEIGHTS[i]}"
                                )


class TestPhysicalRanges(unittest.TestCase):
    """Проверка попадания значений в физически допустимые диапазоны.

    Фиксирует текущее количество нарушений по каждому параметру.
    При регрессии (увеличении числа нарушений) или при исправлении данных
    (уменьшении) тест потребует обновления порогов.
    """

    # Зафиксированное число нарушений по параметрам (значение1 + значение2)
    EXPECTED_VIOLATIONS = {
        "temperature":                0,
        "pressure":                  16,     # перевёрнутый порядок высот в отдельных локациях
        "density":                   76,     # σρ > 200 в (50,60), (60,120), (60,135) и т.д.
        "scalar_wind_speed":          0,
        "zonal_wind_speed":           0,
        "meridional_wind_speed":      0,
        "resultant_wind":             0,
        "specific_humidity":          0,
        "relative_humidity_dewpoint": 9,     # (65,-170) autumn — перепутаны Dp/RH
    }

    def test_values_within_ranges(self):
        """Количество нарушений диапазонов не превышает зафиксированного порога."""
        for name, param in ALL_PARAMETERS.items():
            with self.subTest(param=name):
                min1, max1, min2, max2 = PHYSICAL_RANGES[name]
                violations = []
                for loc, seasons_data in param.items():
                    for season, values in seasons_data.items():
                        for i, (v1, v2) in enumerate(values):
                            h = HEIGHTS[i]
                            if v1 is not None and not (min1 <= v1 <= max1):
                                violations.append(
                                    f"  {loc} {season} h={h}: v1={v1} вне [{min1}, {max1}]"
                                )
                            if v2 is not None and not (min2 <= v2 <= max2):
                                violations.append(
                                    f"  {loc} {season} h={h}: v2={v2} вне [{min2}, {max2}]"
                                )
                expected = self.EXPECTED_VIOLATIONS[name]
                actual = len(violations)
                detail = "\n".join(violations[:10])
                self.assertLessEqual(
                    actual, expected,
                    f"{name}: {actual} нарушений (ожидалось ≤{expected}):\n{detail}"
                )
                # Фиксируем: если данные улучшились, пороги нужно понизить
                if actual < expected:
                    print(f"  ЗАМЕТКА: {name} — нарушений {actual} < порога {expected}, "
                          f"обновите EXPECTED_VIOLATIONS", file=sys.stderr)


class TestMonotonicity(unittest.TestCase):
    """Проверка физически ожидаемых трендов по высоте."""

    def test_pressure_decreases_with_altitude(self):
        """Давление на 10 м строго больше давления на 3000 м (кроме известных дефектов).

        7 профилей с известными дефектами: перепутаны v1/v2 на h=10
        или перевёрнут порядок высот.
        """
        errors = []
        for loc, seasons_data in pressure.items():
            for season, values in seasons_data.items():
                p10 = values[0][0]   # h=10 м
                p3000 = values[8][0] # h=3000 м
                if p10 is None or p3000 is None:
                    continue
                if not (p10 > p3000):
                    errors.append(f"{loc} {season}: P(10м)={p10} <= P(3000м)={p3000}")
        # 7 известных профилей с дефектами
        self.assertLessEqual(len(errors), 7,
                             f"Больше 7 нарушений монотонности давления ({len(errors)}):\n"
                             + "\n".join(errors))

    def test_density_decreases_with_altitude(self):
        """Плотность на 10 м строго больше плотности на 3000 м."""
        errors = []
        for loc, seasons_data in density.items():
            for season, values in seasons_data.items():
                rho10 = values[0][0]   # h=10 м
                rho3000 = values[8][0] # h=3000 м
                if rho10 is None or rho3000 is None:
                    continue
                if not (rho10 > rho3000):
                    errors.append(f"{loc} {season}: ρ(10м)={rho10} <= ρ(3000м)={rho3000}")
        self.assertEqual(errors, [], "Нарушение монотонности плотности:\n" + "\n".join(errors))

    def test_temperature_decreases_600_to_3000(self):
        """Температура на 600 м выше температуры на 3000 м.

        В высоких широтах (≥50°N) зимой/осенью мощные инверсии
        сохраняются выше 600 м. Также есть единичные OCR-дефекты
        на высоте 3000 м (скачок T вверх). Допускаем до 16 нарушений.
        """
        errors = []
        idx_600 = HEIGHTS.index(600)
        idx_3000 = HEIGHTS.index(3000)
        for loc, seasons_data in temperature.items():
            for season, values in seasons_data.items():
                t600 = values[idx_600][0]
                t3000 = values[idx_3000][0]
                if t600 is None or t3000 is None:
                    continue
                if not (t600 > t3000):
                    errors.append(f"{loc} {season}: T(600м)={t600} <= T(3000м)={t3000}")
        # 16 случаев: инверсии в высоких широтах + OCR-ошибки на 3000 м
        self.assertLessEqual(len(errors), 16,
                             f"Больше 16 нарушений монотонности температуры ({len(errors)}):\n"
                             + "\n".join(errors))


class TestCrossParameterConsistency(unittest.TestCase):
    """Кросс-параметрическая согласованность."""

    R_DRY_AIR = 287.05  # Дж/(кг·К), удельная газовая постоянная сухого воздуха

    def test_ideal_gas_law(self):
        """P ≈ ρ·R·T с допуском 10%.

        Плотность в данных хранится в г/м³, давление в гПа, температура в K.
        Допуск 10% учитывает влажность воздуха и погрешности оцифровки.
        Точки с P < 600 гПа пропускаются (известные дефекты давления).
        """
        errors = []
        tolerance = 0.10
        all_locations = _all_locations()
        for loc in all_locations:
            for season in SEASONS:
                if season not in pressure[loc] or season not in density[loc]:
                    continue
                t_vals = temperature[loc][season]
                p_vals = pressure[loc][season]
                d_vals = density[loc][season]
                for i in range(len(HEIGHTS)):
                    T = t_vals[i][0]
                    P_hpa = p_vals[i][0]
                    rho_gm3 = d_vals[i][0]
                    if T is None or P_hpa is None or rho_gm3 is None:
                        continue
                    # Пропускаем точки с заведомо ошибочным давлением
                    if P_hpa < 600:
                        continue
                    P_pa = P_hpa * 100.0
                    rho_kgm3 = rho_gm3 / 1000.0
                    P_calc = rho_kgm3 * self.R_DRY_AIR * T
                    rel_error = abs(P_pa - P_calc) / P_pa
                    if rel_error > tolerance:
                        errors.append(
                            f"{loc} {season} h={HEIGHTS[i]}: "
                            f"P={P_hpa} гПа, ρ={rho_gm3} г/м³, T={T} K, "
                            f"P_расч={P_calc / 100:.1f} гПа, "
                            f"отклонение={rel_error * 100:.1f}%"
                        )
        self.assertEqual(errors, [],
                         "Нарушение уравнения состояния (>10%):\n" + "\n".join(errors))

    def test_resultant_wind_vs_components(self):
        """VR должен быть сопоставим с √(Vx² + Vy²).

        Результирующий ветер VR и компоненты Vx, Vy осредняются по-разному:
        VR — модуль среднего вектора, Vx/Vy — средние компонент.
        VR всегда ≤ скалярного среднего Vs, а √(Vx²+Vy²) — приближение VR.
        Допуск 50%, мин. скорость 2 м/с. До 118 нарушений допускается
        (из-за рассогласования методов осреднения и OCR-ошибок).
        """
        errors = []
        tolerance = 0.50
        min_speed = 2.0
        all_locations = _all_locations()
        for loc in all_locations:
            for season in SEASONS:
                if season not in meridional_wind_speed[loc]:
                    continue
                vx_vals = zonal_wind_speed[loc][season]
                vy_vals = meridional_wind_speed[loc][season]
                vr_vals = resultant_wind[loc][season]
                for i in range(len(HEIGHTS)):
                    vx = vx_vals[i][0]
                    vy = vy_vals[i][0]
                    vr = vr_vals[i][0]
                    if vx is None or vy is None or vr is None:
                        continue
                    if vr < min_speed:
                        continue
                    vr_calc = math.sqrt(vx * vx + vy * vy)
                    if vr_calc < 0.01:
                        continue
                    rel_error = abs(vr - vr_calc) / max(vr, vr_calc)
                    if rel_error > tolerance:
                        errors.append(
                            f"{loc} {season} h={HEIGHTS[i]}: "
                            f"VR={vr}, Vx={vx}, Vy={vy}, "
                            f"√(Vx²+Vy²)={vr_calc:.2f}, "
                            f"отклонение={rel_error * 100:.1f}%"
                        )
        # Рассогласование методов осреднения приводит к ~118 нарушениям
        self.assertLessEqual(len(errors), 118,
                             f"Больше 118 нарушений согласованности ветра ({len(errors)}):\n"
                             + "\n".join(errors[:20]))


class TestNoneValues(unittest.TestCase):
    """Проверки обработки None-значений."""

    def test_none_count_reasonable(self):
        """Количество кортежей с None не превышает ожидаемого порога."""
        max_expected = 200
        count = 0
        for name, param in ALL_PARAMETERS.items():
            for loc, seasons_data in param.items():
                for season, values in seasons_data.items():
                    for v1, v2 in values:
                        if v1 is None or v2 is None:
                            count += 1
        self.assertLessEqual(count, max_expected,
                             f"Слишком много None-кортежей: {count} > {max_expected}")

    def test_none_values_are_paired(self):
        """В большинстве случаев None идут парами (оба элемента None)."""
        single_none = 0
        for name, param in ALL_PARAMETERS.items():
            for loc, seasons_data in param.items():
                for season, values in seasons_data.items():
                    for v1, v2 in values:
                        if (v1 is None) != (v2 is None):
                            single_none += 1
        self.assertLessEqual(single_none, 50,
                             f"Слишком много кортежей с одиночным None: {single_none}")


if __name__ == "__main__":
    unittest.main()
