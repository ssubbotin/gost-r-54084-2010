#!/usr/bin/env python3
"""
Parse GOST R 54084-2010 PDF text pages into a Python data module.

Data structure: 108 tables (9 parameters × 12 longitude groups)
Pages 9-116 of the PDF contain the data tables (one table per page).
"""

import re
import os

PAGES_DIR = "pages"

# Height levels used in all tables (meters above ground)
HEIGHTS = [10, 100, 300, 600, 1000, 1500, 2000, 2500, 3000]

# OCR sometimes garbles heights - map known garbled values to correct ones
HEIGHT_FIXES = {
    1200: 1000,  # OCR sometimes reads "1000" as "1200"
    5000: 3000,  # OCR sometimes reads "3000" as "5000"
}

SEASONS = ["winter", "spring", "summer", "autumn", "annual"]

# Parameters: index -> (name, unit_mean, unit_std, description)
PARAMETERS = {
    0: ("temperature", "K", "K", "Temperature T and std σT"),
    1: ("pressure", "hPa", "%", "Pressure P and std σP"),
    2: ("density", "kg/m3", "kg/m3", "Density ρ and std σρ"),
    3: ("scalar_wind_speed", "m/s", "m/s", "Scalar wind speed Vs and std σv"),
    4: ("zonal_wind_speed", "m/s", "m/s", "Zonal wind speed Vx and std σvx"),
    5: ("meridional_wind_speed", "m/s", "m/s", "Meridional wind speed Vy and std σvy"),
    6: ("resultant_wind", "m/s", "deg", "Resultant wind VR (m/s) and direction θR (°)"),
    7: ("specific_humidity", "g/kg", "g/kg", "Specific humidity q and std σq"),
    8: ("relative_humidity_dewpoint", "%", "degC", "Relative humidity Q% and dew point Dp"),
}

# Location grids for each longitude table index (0-11)
# Each entry: list of (latitude_N, longitude_E) tuples
# Negative longitude = West
LOCATION_GRIDS = {
    0: [(55, 20), (45, 30), (50, 30), (55, 30), (60, 30), (65, 30), (70, 30)],
    1: [(45, 40), (50, 40), (55, 40), (60, 40), (65, 40), (70, 40)],
    2: [(40, 50), (45, 50), (50, 50), (55, 50), (60, 50), (65, 50), (70, 50)],
    3: [(40, 60), (45, 60), (50, 60), (55, 60), (60, 60), (65, 60), (70, 60)],
    4: [(40, 70), (45, 70), (50, 70), (55, 70), (60, 70), (65, 70), (70, 70)],
    5: [(45, 80), (50, 80), (55, 80), (60, 80), (65, 80), (70, 80), (75, 80)],
    6: [(50, 90), (55, 90), (60, 90), (65, 90), (70, 90), (75, 90)],
    7: [(50, 105), (55, 105), (60, 105), (65, 105), (70, 105), (75, 105)],
    8: [(50, 120), (55, 120), (60, 120), (65, 120), (70, 120)],
    9: [(45, 135), (50, 135), (55, 135), (60, 135), (65, 135), (70, 135)],
    10: [(50, 155), (55, 155), (60, 155), (65, 155), (70, 155)],
    11: [(60, 175), (65, 175), (70, 175), (65, -170)],
}

# All valid heights including OCR garbled versions
ALL_VALID_HEIGHTS = set(HEIGHTS) | set(HEIGHT_FIXES.keys())


def strip_line_prefix(line):
    """Remove the line number prefix from Read tool output."""
    return re.sub(r'^\s*\d+→', '', line)


def is_data_line(line):
    """
    Check if a line is a data row (starts with a height, followed by numbers).

    Data lines are almost entirely numeric. Text lines have many non-numeric chars.
    We use the ratio of numeric characters to total characters as a heuristic.
    """
    stripped = line.strip()
    if not stripped:
        return False

    # Count characters that are part of numbers (digits, dots, minus, spaces)
    numeric_chars = sum(1 for c in stripped if c in '0123456789.-+ ')
    total_chars = len(stripped)

    # Data lines should be >85% numeric characters
    if total_chars == 0 or numeric_chars / total_chars < 0.85:
        return False

    # Must start with a number that could be a height
    match = re.match(r'^(\d+)', stripped)
    if not match:
        return False

    first_num = int(match.group(1))
    return first_num in ALL_VALID_HEIGHTS


def fix_height(h):
    """Map OCR-garbled heights to correct values."""
    return HEIGHT_FIXES.get(h, h)


def try_merge_split_decimals(values, expected_count):
    """
    Fix OCR errors where a decimal point was lost, e.g. "261.7" -> "261 7".

    When we have more values than expected, try merging adjacent values
    where the second could be a fractional part (single digit 0-9).
    """
    if len(values) <= expected_count:
        return values

    excess = len(values) - expected_count
    result = []
    i = 0
    merges_done = 0

    while i < len(values):
        if (merges_done < excess and
                i + 1 < len(values) and
                values[i] == int(values[i]) and
                abs(values[i]) >= 1 and
                values[i + 1] == int(values[i + 1]) and
                0 <= values[i + 1] <= 9):
            # Merge: "261" + "7" -> "261.7"
            sign = 1 if values[i] >= 0 else -1
            merged = values[i] + sign * values[i + 1] / 10.0
            result.append(merged)
            i += 2
            merges_done += 1
        else:
            result.append(values[i])
            i += 1

    return result


def extract_data_values(line):
    """
    Extract height and data values from a data line.

    Returns (height, [values]) or None if parsing fails.
    """
    stripped = line.strip()

    # Fix comma used as decimal separator: "4,8" -> "4.8"
    stripped = re.sub(r'(\d),(\d)', r'\1.\2', stripped)

    # Extract all numbers (including negative values)
    numbers = re.findall(r'-?\d+\.?\d*', stripped)

    if len(numbers) < 3:  # Need at least height + one pair
        return None

    try:
        height = int(float(numbers[0]))
        height = fix_height(height)
        values = [float(n) for n in numbers[1:]]
        return (height, values)
    except (ValueError, IndexError):
        return None


def parse_data_page(page_num, expected_cols):
    """
    Parse a single data page and extract seasonal data.

    Returns: dict {season_name: list of 9 rows, each row = list of floats}
             or None on failure
    """
    filepath = os.path.join(PAGES_DIR, f"page_{page_num:03d}.txt")
    if not os.path.exists(filepath):
        print(f"  WARNING: {filepath} not found")
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        raw_lines = f.readlines()

    # Extract data rows
    data_rows = []
    for raw_line in raw_lines:
        line = strip_line_prefix(raw_line.strip())
        if not is_data_line(line):
            continue

        result = extract_data_values(line)
        if result is None:
            continue

        height, values = result
        if height in set(HEIGHTS):
            data_rows.append((height, values))

    # We expect 5 seasons × 9 heights = 45 data rows
    expected_total = 45
    if len(data_rows) != expected_total:
        print(f"  INFO: page {page_num}: found {len(data_rows)} data rows "
              f"(expected {expected_total})")

    # Group into seasons by finding height=10 markers (start of each season)
    # Each season starts with h=10 and goes through the height sequence
    seasons_data = {}
    expected_values_per_row = expected_cols * 2

    # Find season boundaries (lines where height == 10)
    season_starts = [i for i, (h, _) in enumerate(data_rows) if h == 10]

    if len(season_starts) != 5:
        # Fallback: try splitting into groups of 9
        if len(data_rows) >= 45:
            season_starts = [i * 9 for i in range(5)]
        else:
            print(f"  WARNING: page {page_num}: found {len(season_starts)} "
                  f"season starts (expected 5), {len(data_rows)} total rows")
            # Try best effort with what we have
            if not season_starts:
                return None

    for season_idx, start_row in enumerate(season_starts):
        if season_idx >= 5:
            break

        season_name = SEASONS[season_idx]
        end_row = (season_starts[season_idx + 1]
                   if season_idx + 1 < len(season_starts)
                   else min(start_row + 9, len(data_rows)))

        season_rows = []
        for row_idx in range(start_row, min(end_row, start_row + 9)):
            height, values = data_rows[row_idx]

            # Validate/fix value count
            if len(values) > expected_values_per_row:
                # Try to fix OCR split decimals (e.g. "261 7" -> "261.7")
                values = try_merge_split_decimals(values, expected_values_per_row)

            if len(values) < expected_values_per_row:
                # Pad with None
                values = values + [None] * (expected_values_per_row - len(values))
            elif len(values) > expected_values_per_row:
                values = values[:expected_values_per_row]

            season_rows.append(values)

        # Pad missing rows with None values
        while len(season_rows) < 9:
            season_rows.append([None] * expected_values_per_row)

        seasons_data[season_name] = season_rows

    return seasons_data


def build_data_module():
    """Parse all data pages and build the complete data structure."""
    all_data = {}
    warnings_count = 0

    for page_num in range(9, 117):
        table_index = page_num - 9
        param_index = table_index // 12
        lon_index = table_index % 12

        param_name = PARAMETERS[param_index][0]
        locations = LOCATION_GRIDS[lon_index]
        num_cols = len(locations)
        table_num = table_index + 1

        print(f"Page {page_num:3d}: Table {table_num:3d} - {param_name:<30s} "
              f"lon_idx={lon_index:2d}, {num_cols} locations")

        seasons_data = parse_data_page(page_num, num_cols)

        if seasons_data is None:
            print(f"  ERROR: Failed to parse page {page_num}")
            warnings_count += 1
            continue

        if param_name not in all_data:
            all_data[param_name] = {}

        for season_name, season_rows in seasons_data.items():
            for loc_idx, (lat, lon) in enumerate(locations):
                loc_key = (lat, lon)
                if loc_key not in all_data[param_name]:
                    all_data[param_name][loc_key] = {}

                height_data = []
                for row_values in season_rows:
                    val1_idx = loc_idx * 2
                    val2_idx = loc_idx * 2 + 1
                    val1 = row_values[val1_idx] if val1_idx < len(row_values) and row_values[val1_idx] is not None else None
                    val2 = row_values[val2_idx] if val2_idx < len(row_values) and row_values[val2_idx] is not None else None
                    height_data.append((val1, val2))

                all_data[param_name][loc_key][season_name] = height_data

    return all_data, warnings_count


def format_value(v):
    """Format a value for Python output."""
    if v is None:
        return "None"
    if isinstance(v, float) and v == int(v) and abs(v) < 1e6:
        return str(int(v))
    return repr(v)


def format_tuple(t):
    """Format a (val1, val2) tuple."""
    return f"({format_value(t[0])}, {format_value(t[1])})"


def write_python_module(all_data, output_path):
    """Write the parsed data as a Python module."""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('"""\n')
        f.write("GOST R 54084-2010: Models of the atmosphere in the boundary layer\n")
        f.write("at altitudes from 0 to 3000 m for aerospace practice. Parameters.\n\n")
        f.write("ГОСТ Р 54084-2010: Модели атмосферы в пограничном слое на высотах\n")
        f.write("от 0 до 3000 м для аэрокосмической практики. Параметры.\n\n")
        f.write("This module contains digitized data from the standard tables.\n\n")
        f.write("Data organization:\n")
        f.write("    Each parameter is a dict: {(lat_N, lon_E): {season: [(val, std), ...]}}\n")
        f.write("    - lat_N: latitude in degrees North (40-75)\n")
        f.write("    - lon_E: longitude in degrees East (20-175), negative = West\n")
        f.write('    - season: "winter", "spring", "summer", "autumn", or "annual"\n')
        f.write("    - Each season contains 9 tuples, one per height level\n\n")
        f.write("Height levels (meters above ground):\n")
        f.write("    HEIGHTS = [10, 100, 300, 600, 1000, 1500, 2000, 2500, 3000]\n\n")
        f.write("Seasons:\n")
        f.write("    winter  = December, January, February\n")
        f.write("    spring  = March, April, May\n")
        f.write("    summer  = June, July, August\n")
        f.write("    autumn  = September, October, November\n")
        f.write("    annual  = yearly mean\n\n")
        f.write("Parameters and their value tuples:\n")
        f.write("    temperature:                (T [K],    σT [K])\n")
        f.write("    pressure:                   (P [hPa],  σP [%])\n")
        f.write("    density:                    (ρ [kg/m³], σρ [kg/m³])\n")
        f.write("    scalar_wind_speed:          (Vs [m/s],  σv [m/s])\n")
        f.write("    zonal_wind_speed:           (Vx [m/s],  σvx [m/s])\n")
        f.write("    meridional_wind_speed:      (Vy [m/s],  σvy [m/s])\n")
        f.write("    resultant_wind:             (VR [m/s],  θR [°])\n")
        f.write("    specific_humidity:          (q [g/kg],  σq [g/kg])\n")
        f.write("    relative_humidity_dewpoint: (RH [%],    Dp [°C])\n\n")
        f.write("Usage example:\n")
        f.write("    from gost_54084 import temperature, HEIGHTS\n\n")
        f.write("    # Get winter temperature profile at 55°N, 30°E\n")
        f.write('    profile = temperature[(55, 30)]["winter"]\n')
        f.write("    for h, (t, sigma_t) in zip(HEIGHTS, profile):\n")
        f.write('        print(f"  {h:5d} m: T = {t:.1f} K, σT = {sigma_t:.1f} K")\n')
        f.write('"""\n\n')

        f.write("HEIGHTS = [10, 100, 300, 600, 1000, 1500, 2000, 2500, 3000]\n\n")
        f.write('SEASONS = ["winter", "spring", "summer", "autumn", "annual"]\n\n')

        # Write location grid for reference
        f.write("# Available locations per longitude group\n")
        f.write("LOCATION_GRIDS = {\n")
        lon_labels = [
            "20E+30E", "40E", "50E", "60E", "70E", "80E",
            "90E", "105E", "120E", "135E", "155E", "175E+170W"
        ]
        for idx, label in enumerate(lon_labels):
            locs = LOCATION_GRIDS[idx]
            loc_strs = [f"({lat}, {lon})" for lat, lon in locs]
            f.write(f'    "{label}": [{", ".join(loc_strs)}],\n')
        f.write("}\n\n")

        # Write each parameter
        for param_idx in range(9):
            param_name = PARAMETERS[param_idx][0]
            param_desc = PARAMETERS[param_idx][3]
            unit_mean = PARAMETERS[param_idx][1]
            unit_std = PARAMETERS[param_idx][2]

            if param_name not in all_data:
                f.write(f"# {param_desc} - NO DATA PARSED\n")
                f.write(f"{param_name} = {{}}\n\n")
                continue

            f.write(f"# {param_desc}\n")
            f.write(f"# Values: ({unit_mean}, {unit_std}) per height level\n")
            f.write(f"{param_name} = {{\n")

            param_data = all_data[param_name]
            sorted_locs = sorted(param_data.keys())

            for loc_key in sorted_locs:
                lat, lon = loc_key
                f.write(f"    ({lat}, {lon}): {{\n")

                loc_data = param_data[loc_key]
                for season in SEASONS:
                    if season not in loc_data:
                        continue
                    height_data = loc_data[season]
                    tuples_str = ", ".join(format_tuple(t) for t in height_data)
                    f.write(f'        "{season}": [{tuples_str}],\n')

                f.write("    },\n")

            f.write("}\n\n")

    print(f"\nOutput written to: {output_path}")


def validate_data(all_data):
    """Print validation summary."""
    print("\n" + "=" * 70)
    print("Validation Summary")
    print("=" * 70)

    total_points = 0
    total_none = 0

    for param_name, param_data in all_data.items():
        locs = len(param_data)
        points = 0
        nones = 0
        for loc_key, loc_data in param_data.items():
            for season, height_data in loc_data.items():
                for v1, v2 in height_data:
                    points += 1
                    if v1 is None or v2 is None:
                        nones += 1
        total_points += points
        total_none += nones
        pct_ok = (points - nones) / max(points, 1) * 100
        print(f"  {param_name:<35s}: {locs:3d} locs, "
              f"{points:6d} points, {nones:4d} None ({pct_ok:.1f}% OK)")

    print(f"\n  TOTAL: {total_points} data points, "
          f"{total_none} None ({(total_points - total_none) / max(total_points, 1) * 100:.1f}% OK)")


def main():
    print("=" * 70)
    print("Parsing GOST R 54084-2010 data tables")
    print("=" * 70)

    all_data, warnings = build_data_module()
    validate_data(all_data)

    output_path = "src/gost_54084/data.py"
    write_python_module(all_data, output_path)

    # Quick sanity check: print a sample profile
    print("\n" + "=" * 70)
    print("Sample: Temperature at 55°N, 30°E (winter)")
    print("=" * 70)
    if "temperature" in all_data and (55, 30) in all_data["temperature"]:
        profile = all_data["temperature"][(55, 30)].get("winter", [])
        for h, (t, sigma_t) in zip(HEIGHTS, profile):
            t_str = f"{t:.1f}" if t is not None else "N/A"
            s_str = f"{sigma_t:.1f}" if sigma_t is not None else "N/A"
            print(f"  {h:5d} m: T = {t_str} K, σT = {s_str} K")


if __name__ == "__main__":
    main()
