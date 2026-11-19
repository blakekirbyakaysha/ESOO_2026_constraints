"""Compare matched 2027 ESOO constraint outputs with recent MMS actuals.

MMS observations are averaged into 30-minute, interval-ending values. ESOO hourly
interval-ending outputs are repeated over their two 30-minute intervals. The
script writes matched time series, comparison metrics, and profile charts.

Usage:
    python scripts/compare_to_MMS.py
"""
import argparse
import math
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import mean, median, stdev

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
COMPARE_DIR = ROOT / "inputs" / "compare_to_MMS"
DEFAULT_ACTUALS = COMPARE_DIR / "Constraint_Data.csv"
DEFAULT_ESOO = COMPARE_DIR / "ESOO_2027_network_constraints.csv"
DEFAULT_MAPPING = COMPARE_DIR / "Equation_mapping_populated_BK_manual.xlsx"
DEFAULT_OUTPUT = ROOT / "outputs" / "mms_comparison"
RHS_SENTINEL = 1e20


def require_columns(df: pl.DataFrame, columns: set[str], path: Path) -> None:
    missing = columns - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing required column(s): {', '.join(sorted(missing))}")


def parse_datetime_column(df: pl.DataFrame, column: str, path: Path) -> pl.DataFrame:
    parsed = df.with_columns(pl.col(column).str.to_datetime(strict=False).alias("datetime"))
    bad = parsed.filter(pl.col("datetime").is_null()).height
    if bad:
        raise ValueError(f"{path} has {bad:,} invalid or blank {column} timestamp(s)")
    return parsed


def numeric_column(column: str) -> pl.Expr:
    raw = pl.col(column).str.strip_chars()
    return raw.str.replace_all(",", "").cast(pl.Float64, strict=False)


def read_actuals(path: Path) -> tuple[pl.DataFrame, date, date]:
    df = pl.read_csv(path, infer_schema_length=0)
    require_columns(
        df,
        {"SETTLEMENTDATE", "LHS", "RHS", "Binding", "constraint"},
        path,
    )
    df = parse_datetime_column(df, "SETTLEMENTDATE", path).with_columns(
        pl.col("constraint").str.strip_chars(),
        numeric_column("LHS").alias("lhs"),
        numeric_column("RHS").alias("rhs"),
        pl.col("Binding").str.to_lowercase().is_in(["true", "1", "yes"]).alias("binding"),
    ).with_columns(
        pl.when(pl.col("rhs").abs() >= RHS_SENTINEL)
        .then(None)
        .otherwise(pl.col("rhs"))
        .alias("rhs")
    )
    bad_ids = df.filter(pl.col("constraint").is_null() | (pl.col("constraint") == "")).height
    if bad_ids:
        raise ValueError(f"{path} has {bad_ids:,} row(s) with a blank constraint name")

    max_date = df["datetime"].max().date()
    # Include the most recent 12 calendar months, inclusive of the last date.
    try:
        prior_year = max_date.replace(year=max_date.year - 1)
    except ValueError:
        prior_year = max_date.replace(year=max_date.year - 1, day=28)
    start_date = prior_year + timedelta(days=1)
    start = datetime.combine(start_date, time.min)
    end = df["datetime"].max()
    df = df.filter((pl.col("datetime") >= start) & (pl.col("datetime") <= end))

    # Settlement timestamps mark interval ends. Keep exact half-hour boundaries
    # and round all other 5-minute records up to the next half-hour boundary.
    df = df.with_columns(
        pl.col("datetime").dt.truncate("30m").alias("_half_hour_floor")
    ).with_columns(
        pl.when(pl.col("datetime") == pl.col("_half_hour_floor"))
        .then(pl.col("_half_hour_floor"))
        .otherwise(pl.col("_half_hour_floor") + pl.duration(minutes=30))
        .alias("datetime")
    )
    grouped = (
        df.group_by("constraint", "datetime")
        .agg(
            pl.col("lhs").mean(),
            pl.col("rhs").mean(),
            pl.col("binding").max(),
        )
        .sort("constraint", "datetime")
    )
    return grouped, start_date, end.date()


def read_esoo(path: Path) -> pl.DataFrame:
    df = pl.read_csv(path, infer_schema_length=0)
    require_columns(df, {"Child Name", "Category", "Datetime", "Activity", "RHS"}, path)
    df = parse_datetime_column(df, "Datetime", path).filter(
        pl.col("Category") == "NetworkConstraints"
    ).with_columns(
        pl.col("Child Name").str.strip_chars().alias("constraint"),
        numeric_column("Activity").alias("lhs"),
        numeric_column("RHS").alias("rhs"),
    )
    for column in ("lhs", "rhs"):
        invalid = df.filter(pl.col(column).is_null()).height
        if invalid:
            raise ValueError(f"{path} has {invalid:,} invalid or blank {column} value(s)")
    df = df.with_columns(
        pl.when(pl.col("rhs").abs() >= RHS_SENTINEL)
        .then(None)
        .otherwise(pl.col("rhs"))
        .alias("rhs")
    )

    # The supplied ESOO data is hourly. An interval ending at 01:00 covers the
    # half-hour intervals ending at 00:30 and 01:00.
    times = sorted(df["datetime"].unique().to_list())
    if len(times) < 2:
        raise ValueError(f"{path} needs at least two unique ESOO timestamps")
    median_minutes = median((b - a).total_seconds() / 60 for a, b in zip(times, times[1:]))
    if math.isclose(median_minutes, 60.0, abs_tol=1.0):
        prior_half_hours = df.with_columns(
            (pl.col("datetime") - pl.duration(minutes=30)).alias("datetime")
        )
        df = pl.concat([prior_half_hours, df], how="vertical")
    elif not math.isclose(median_minutes, 30.0, abs_tol=1.0):
        raise ValueError(
            f"{path} has an unsupported median time step of {median_minutes:g} minutes; "
            "expected hourly or 30-minute ESOO data"
        )
    return df.select("constraint", "datetime", "lhs", "rhs").sort("constraint", "datetime")


def read_mapping(path: Path) -> list[dict[str, str]]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        headers = next(rows, None)
        if headers is None:
            raise ValueError(f"{path} has no header row")
        indexes = {str(value).strip(): i for i, value in enumerate(headers) if value is not None}
        needed = {"ESOO constraint ID", "Match method", "Output"}
        missing = needed - set(indexes)
        if missing:
            raise ValueError(f"{path} is missing mapping column(s): {', '.join(sorted(missing))}")
        mappings = []
        for row in rows:
            esoo_name = row[indexes["ESOO constraint ID"]]
            output_name = row[indexes["Output"]]
            if output_name is None and "AEMO constraint ID" in indexes:  # formula cache lost (file saved by openpyxl)
                auto, manual = row[indexes["AEMO constraint ID"]], row[indexes.get("Manual match", 0)]
                output_name = auto if auto and auto != "NO MATCH" else (manual if manual and manual != "None" else None)
            if esoo_name is None or output_name is None:
                continue
            esoo_name, output_name = str(esoo_name).strip(), str(output_name).strip()
            if not esoo_name or not output_name or output_name.casefold() in {"none", "no match"}:
                continue
            mappings.append(
                {
                    "esoo_constraint": esoo_name,
                    "mms_constraint": output_name,
                    "match_method": str(row[indexes["Match method"]] or ""),
                }
            )
        return mappings
    finally:
        workbook.close()


def profile_key(ts: datetime) -> tuple[date, int, int, int]:
    # Treat midnight interval-ending observations as the final interval of the
    # previous day so month and financial-quarter profiles remain correctly grouped.
    day = ts.date() - timedelta(days=1) if ts.hour == 0 and ts.minute == 0 else ts.date()
    slot = (ts.hour * 2 - (1 if ts.minute == 0 else 0)) % 48
    month = day.month
    quarter = ((month - 7) % 12) // 3 + 1
    return day, month, quarter, slot


def summary_stats(actual: list[float], esoo: list[float]) -> tuple[float | None, ...]:
    if not actual:
        return None, None, None, None
    differences = [m - a for a, m in zip(actual, esoo)]
    bias = mean(differences)
    mae = mean(abs(value) for value in differences)
    rmse = math.sqrt(mean(value * value for value in differences))
    if len(actual) > 1:
        mean_a, mean_m = mean(actual), mean(esoo)
        denom = math.sqrt(
            sum((a - mean_a) ** 2 for a in actual)
            * sum((m - mean_m) ** 2 for m in esoo)
        )
        corr = (
            sum((a - mean_a) * (m - mean_m) for a, m in zip(actual, esoo)) / denom
            if denom
            else None
        )
    else:
        corr = None
    return bias, mae, rmse, corr


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "constraint"


def clear_prior_outputs(mappings: list[dict[str, str]], output: Path) -> None:
    generated_suffixes = (
        "_30min.csv",
        "_timeseries.png",
        "_lhs_profiles.png",
        "_rhs_profiles.png",
    )
    for name in {mapping["esoo_constraint"] for mapping in mappings}:
        for suffix in generated_suffixes:
            old_file = output / f"{safe_name(name)}{suffix}"
            if old_file.exists():
                old_file.unlink()


def pin_zero_if_nonnegative(ax: plt.Axes, *series: list[float]) -> None:
    values = [value for points in series for value in points if math.isfinite(value)]
    if values and min(values) >= 0:
        ax.set_ylim(bottom=0)


def make_timeseries_chart(
    frame: pl.DataFrame,
    esoo_constraint: str,
    mms_constraint: str,
    path: Path,
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
    actual_period = frame.filter(pl.col("actual_lhs").is_not_null())
    esoo_period = frame.filter(pl.col("esoo_lhs").is_not_null())
    actual_start, actual_end = actual_period["datetime"].min(), actual_period["datetime"].max()
    esoo_start, esoo_end = esoo_period["datetime"].min(), esoo_period["datetime"].max()
    overlap_start, overlap_end = max(actual_start, esoo_start), min(actual_end, esoo_end)
    for ax, actual_col, esoo_col, label in (
        (axes[0], "actual_lhs", "esoo_lhs", "LHS / activity"),
        (axes[1], "actual_rhs", "esoo_rhs", "RHS"),
    ):
        actual = frame.filter(pl.col(actual_col).is_not_null())
        esoo = frame.filter(pl.col(esoo_col).is_not_null())
        actual_values = actual[actual_col].to_list()
        esoo_values = esoo[esoo_col].to_list()
        ax.plot(actual["datetime"].to_list(), actual_values, linewidth=0.7, label="MMS actuals")
        ax.plot(esoo["datetime"].to_list(), esoo_values, linewidth=0.8, alpha=0.85, label="ESOO 2027")
        ax.set_ylabel(label)
        ax.grid(True, alpha=0.25)
        pin_zero_if_nonnegative(ax, actual_values, esoo_values)
        if overlap_start <= overlap_end:
            ax.axvspan(overlap_start, overlap_end, color="grey", alpha=0.12, label="Date overlap")
        ax.legend(loc="best")
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    axes[-1].set_xlabel("Interval-ending date/time")
    fig.suptitle(f"{esoo_constraint}  |  MMS constraint: {mms_constraint}")
    fig.text(
        0.5,
        0.01,
        f"30-minute values; MMS {actual_start:%d %b %Y} to {actual_end:%d %b %Y}; "
        f"ESOO {esoo_start:%d %b %Y} to {esoo_end:%d %b %Y}. Shading marks overlap.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.96))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def profile_series(frame: pl.DataFrame, variable: str) -> dict[str, dict[str, tuple[list[float], list[float]]]]:
    gathered: dict[str, dict[tuple[str, int], list[float]]] = {}
    for ts, value, source in frame.select("datetime", variable, "source").iter_rows():
        if value is None:
            continue
        day, month, quarter, slot = profile_key(ts)
        gathered.setdefault(source, {}).setdefault(("Annual", slot), []).append(float(value))
        gathered[source].setdefault((f"Q{quarter}", slot), []).append(float(value))
        gathered[source].setdefault((date(day.year, month, 1).strftime("%b"), slot), []).append(float(value))

    results: dict[str, dict[str, tuple[list[float], list[float]]]] = {}
    for source, groups in gathered.items():
        results[source] = {}
        for period in ("Annual", "Q1", "Q2", "Q3", "Q4", *[date(2000, m, 1).strftime("%b") for m in range(1, 13)]):
            means = [float("nan")] * 48
            deviations = [float("nan")] * 48
            for (group, slot), points in groups.items():
                if group == period:
                    means[slot] = mean(points)
                    deviations[slot] = stdev(points) if len(points) > 1 else 0.0
            if any(not math.isnan(value) for value in means):
                results[source][period] = (means, deviations)
    return results


def make_profile_chart(
    actual: pl.DataFrame,
    esoo: pl.DataFrame,
    variable: str,
    esoo_constraint: str,
    path: Path,
) -> None:
    fig, axes = plt.subplots(3, 6, figsize=(19, 12), sharex=True)
    periods = [
        ("Annual", "Annual"),
        ("Q1", "FY Q1 (Jul-Sep)"),
        ("Q2", "FY Q2 (Oct-Dec)"),
        ("Q3", "FY Q3 (Jan-Mar)"),
        ("Q4", "FY Q4 (Apr-Jun)"),
        *[(date(2000, month, 1).strftime("%b"), date(2000, month, 1).strftime("%B")) for month in range(1, 13)],
    ]
    series = {
        "MMS actuals": profile_series(actual.with_columns(pl.lit("MMS actuals").alias("source")), variable).get("MMS actuals", {}),
        "ESOO 2027": profile_series(esoo.with_columns(pl.lit("ESOO 2027").alias("source")), variable).get("ESOO 2027", {}),
    }
    x = list(range(48))
    for ax, (period, title) in zip(axes.flat, periods):
        plotted_values = []
        for label, profiles in series.items():
            if period not in profiles:
                continue
            values, deviations = profiles[period]
            ax.plot(x, values, linewidth=1, label=label)
            lower = [v - d for v, d in zip(values, deviations)]
            upper = [v + d for v, d in zip(values, deviations)]
            ax.fill_between(x, lower, upper, alpha=0.15)
            plotted_values.extend((values, lower, upper))
        pin_zero_if_nonnegative(ax, *plotted_values)
        ax.set_title(title, fontsize=9)
        ax.grid(True, alpha=0.2)
        ax.set_xticks([0, 12, 24, 36, 47], ["00:30", "06:30", "12:30", "18:30", "00:00"], fontsize=7)
        ax.tick_params(axis="y", labelsize=7)
    for ax in axes.flat[len(periods):]:
        ax.set_visible(False)
    axes.flat[0].legend(fontsize=8)
    fig.suptitle(f"{esoo_constraint} — {variable.upper()} average daily profiles (mean ± 1 SD)")
    fig.text(
        0.5,
        0.01,
        "MMS uses the latest 12 months available; ESOO quarters are financial-year quarters. "
        "Monthly panels compare like-named calendar months.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.96))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def build_comparison(
    mappings: list[dict[str, str]],
    actual: pl.DataFrame,
    esoo: pl.DataFrame,
    output: Path,
    actual_start: date,
    actual_end: date,
) -> None:
    clear_prior_outputs(mappings, output)
    actual_names, esoo_names = set(actual["constraint"].unique()), set(esoo["constraint"].unique())
    mapping_rows = []
    summaries = []
    for mapping in mappings:
        mms_name, esoo_name = mapping["mms_constraint"], mapping["esoo_constraint"]
        has_actual, has_esoo = mms_name in actual_names, esoo_name in esoo_names
        status = (
            "matched"
            if has_actual and has_esoo
            else "missing_actual"
            if not has_actual
            else "missing_esoo"
        )
        mapping_rows.append({**mapping, "status": status})
        if status != "matched":
            continue

        actual_one = actual.filter(pl.col("constraint") == mms_name).select(
            "datetime", pl.col("lhs").alias("actual_lhs"), pl.col("rhs").alias("actual_rhs"),
            pl.col("binding").alias("actual_binding"),
        )
        esoo_one = esoo.filter(pl.col("constraint") == esoo_name).select(
            "datetime", pl.col("lhs").alias("esoo_lhs"), pl.col("rhs").alias("esoo_rhs"),
        )
        combined = actual_one.join(esoo_one, on="datetime", how="full", coalesce=True).sort("datetime")
        valid_lhs = combined.filter(pl.col("actual_lhs").is_not_null() & pl.col("esoo_lhs").is_not_null())
        valid_rhs = combined.filter(pl.col("actual_rhs").is_not_null() & pl.col("esoo_rhs").is_not_null())
        lhs_stats = summary_stats(valid_lhs["actual_lhs"].to_list(), valid_lhs["esoo_lhs"].to_list())
        rhs_stats = summary_stats(valid_rhs["actual_rhs"].to_list(), valid_rhs["esoo_rhs"].to_list())
        valid_headroom = combined.filter(
            pl.all_horizontal(
                pl.col("actual_lhs").is_not_null(),
                pl.col("esoo_lhs").is_not_null(),
                pl.col("actual_rhs").is_not_null(),
                pl.col("esoo_rhs").is_not_null(),
            )
        ).with_columns(
            (pl.col("actual_rhs") - pl.col("actual_lhs")).alias("actual_headroom"),
            (pl.col("esoo_rhs") - pl.col("esoo_lhs")).alias("esoo_headroom"),
        )
        headroom_stats = summary_stats(
            valid_headroom["actual_headroom"].to_list(),
            valid_headroom["esoo_headroom"].to_list(),
        )
        summary = {
            **mapping,
            "status": status,
            "actual_window_start": actual_start.isoformat(),
            "actual_window_end": actual_end.isoformat(),
            "actual_30min_intervals": actual_one.height,
            "esoo_30min_intervals": esoo_one.height,
            "overlap_30min_intervals": valid_headroom.height,
            "lhs_overlap_30min_intervals": valid_lhs.height,
            "rhs_overlap_30min_intervals": valid_rhs.height,
            "lhs_mms_mean_on_overlap": mean(valid_lhs["actual_lhs"].to_list()) if valid_lhs.height else None,
            "lhs_esoo_mean_on_overlap": mean(valid_lhs["esoo_lhs"].to_list()) if valid_lhs.height else None,
            "rhs_mms_mean_on_overlap": mean(valid_rhs["actual_rhs"].to_list()) if valid_rhs.height else None,
            "rhs_esoo_mean_on_overlap": mean(valid_rhs["esoo_rhs"].to_list()) if valid_rhs.height else None,
            "headroom_mms_mean_on_overlap": mean(valid_headroom["actual_headroom"].to_list()) if valid_headroom.height else None,
            "headroom_esoo_mean_on_overlap": mean(valid_headroom["esoo_headroom"].to_list()) if valid_headroom.height else None,
            "actual_binding_pct": (
                100 * sum(actual_one["actual_binding"].to_list()) / actual_one.height
                if actual_one.height
                else None
            ),
        }
        for prefix, stats in (("lhs", lhs_stats), ("rhs", rhs_stats)):
            for suffix, value in zip(("bias_esoo_minus_mms", "mae", "rmse", "correlation"), stats):
                summary[f"{prefix}_{suffix}"] = value
        for suffix, value in zip(
            ("bias_esoo_minus_mms", "mae", "rmse", "correlation"),
            headroom_stats,
        ):
            summary[f"headroom_{suffix}"] = value
        summaries.append(summary)

        series = combined.with_columns(
            pl.lit(esoo_name).alias("esoo_constraint"),
            pl.lit(mms_name).alias("mms_constraint"),
        ).select(
            "datetime", "esoo_constraint", "mms_constraint",
            "actual_lhs", "esoo_lhs", "actual_rhs", "esoo_rhs", "actual_binding",
        )
        series.write_csv(output / f"{safe_name(esoo_name)}_30min.csv")

        actual_series = actual_one.select(
            "datetime", pl.col("actual_lhs").alias("lhs"), pl.col("actual_rhs").alias("rhs")
        )
        esoo_series = esoo_one.select(
            "datetime", pl.col("esoo_lhs").alias("lhs"), pl.col("esoo_rhs").alias("rhs")
        )
        actual_series = actual_series.with_columns(pl.lit("MMS actuals").alias("source"))
        esoo_series = esoo_series.with_columns(pl.lit("ESOO 2027").alias("source"))
        make_timeseries_chart(
            series,
            esoo_name,
            mms_name,
            output / f"{safe_name(esoo_name)}_timeseries.png",
        )
        for variable in ("lhs", "rhs"):
            make_profile_chart(
                actual_series,
                esoo_series,
                variable,
                esoo_name,
                output / f"{safe_name(esoo_name)}_{variable}_profiles.png",
            )

    pl.DataFrame(mapping_rows).write_csv(output / "matched_constraints.csv")
    if not summaries:
        raise ValueError("No mapped constraints were present in both data sources; see matched_constraints.csv")
    pl.DataFrame(summaries).write_csv(output / "comparison_summary.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actuals", type=Path, default=DEFAULT_ACTUALS)
    parser.add_argument("--esoo", type=Path, default=DEFAULT_ESOO)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    for path in (args.actuals, args.esoo, args.mapping):
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")
    args.output.mkdir(parents=True, exist_ok=True)
    actual, actual_start, actual_end = read_actuals(args.actuals)
    esoo = read_esoo(args.esoo)
    mappings = read_mapping(args.mapping)
    if not mappings:
        raise ValueError(f"No usable ESOO-to-MMS mappings found in {args.mapping}")
    build_comparison(mappings, actual, esoo, args.output, actual_start, actual_end)

    statuses: dict[str, int] = {}
    for row in pl.read_csv(args.output / "matched_constraints.csv").iter_rows(named=True):
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    print(f"MMS actual window: {actual_start} to {actual_end}")
    print(f"ESOO data: {esoo['datetime'].min()} to {esoo['datetime'].max()}")
    print(f"Constraint mappings: {statuses}")
    print(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
