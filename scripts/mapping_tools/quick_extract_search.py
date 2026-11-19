from pathlib import Path
import io
import re
import time
import urllib3
import requests
import pandas as pd

MAPDIR = Path(__file__).resolve().parent.parent.parent / "inputs" / "mapping"
INPUT_FILE = str(MAPDIR / "Equation_mapping.xlsx")
OUTPUT_FILE = str(MAPDIR / "Equation_mapping_populated.xlsx")
URL = "https://www.neopoint.com.au/data/query"
API_KEY = "AKAY21"
VERIFY_SSL = False

# Search settings. Each inner list is an AND group; groups are OR'd together.
# Example below returns descriptions containing BOTH 81 and 82,
# OR descriptions containing ALL of "Upper Tumut", "Murray", and "051".
SEARCH_GROUPS = [
    # ["81", "82"],
    # ["Upper Tumut", "Murray", "051"],
]
SEARCH_COLUMNS = ["GENCONID", "DESCRIPTION"]
SEARCH_OUTPUT_FILE = str(MAPDIR / "GENCONDATA_search_results.xlsx")
INTERACTIVE_SEARCH = True

if not VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def clean_constraint_id(value):
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", "", str(value).strip().upper())


def remove_leading_zeros(match):
    number = match.group(0)
    try:
        return str(int(number))
    except ValueError:
        return number


def clean_description(value):
    if pd.isna(value):
        return ""
    value = str(value)
    for old, new in [("–", "-"), ("—", "-"), ("−", "-"), ("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"')]:
        value = value.replace(old, new)
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*=\s*", "=", value)
    value = re.sub(r"\s*,\s*", ",", value)
    value = re.sub(r"\s*;\s*", ";", value)
    value = re.sub(r"\s*:\s*", ":", value)
    value = re.sub(r"\(\s+", "(", value)
    value = re.sub(r"\s+\)", ")", value)
    value = re.sub(r"(?<!\d)\d+(?!\d)", remove_leading_zeros, value)
    return re.sub(r"\s+", " ", value).strip()


def normalise_search_text(value):
    """Loose normalisation for searching, including 051 == 51."""
    return clean_description(value)


def qt_post_request(query_string: str, retries: int = 3) -> pd.DataFrame:
    payload = {"query": query_string, "key": API_KEY, "format": "csv"}
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(URL, params=payload, timeout=120, verify=VERIFY_SSL)
            response.raise_for_status()
            if not response.text.strip():
                raise ValueError("NEOpoint returned an empty response.")
            return pd.read_csv(io.StringIO(response.text))
        except (requests.exceptions.RequestException, pd.errors.ParserError, ValueError) as exc:
            print(f"Query attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                time.sleep(5)
    raise RuntimeError(f"Query failed after {retries} attempts.")


def get_gencondata() -> pd.DataFrame:
    query = """
    SELECT EFFECTIVEDATE, VERSIONNO, GENCONID, CONSTRAINTTYPE,
           DESCRIPTION, STATUS, LASTCHANGED
    FROM mms.gencondata
    ORDER BY GENCONID, EFFECTIVEDATE DESC, VERSIONNO DESC;
    """
    print("Querying GENCONDATA...")
    constraints = qt_post_request(query)
    print(f"Retrieved {len(constraints):,} GENCONDATA rows.")
    constraints.columns = [str(c).strip().upper() for c in constraints.columns]

    required = {"EFFECTIVEDATE", "VERSIONNO", "GENCONID", "DESCRIPTION"}
    missing = required - set(constraints.columns)
    if missing:
        raise ValueError("GENCONDATA query is missing columns: " + ", ".join(sorted(missing)))

    constraints["EFFECTIVEDATE"] = pd.to_datetime(constraints["EFFECTIVEDATE"], errors="coerce")
    constraints["VERSIONNO"] = pd.to_numeric(constraints["VERSIONNO"], errors="coerce")
    constraints = (constraints
        .sort_values(["GENCONID", "EFFECTIVEDATE", "VERSIONNO"], ascending=[True, False, False], na_position="last")
        .drop_duplicates(subset=["GENCONID"], keep="first")
        .reset_index(drop=True))

    constraints["_CLEAN_GENCONID"] = constraints["GENCONID"].apply(clean_constraint_id)
    constraints["_CLEAN_DESCRIPTION"] = constraints["DESCRIPTION"].apply(clean_description)
    constraints["_SEARCH_GENCONID"] = constraints["GENCONID"].apply(normalise_search_text)
    constraints["_SEARCH_DESCRIPTION"] = constraints["DESCRIPTION"].apply(normalise_search_text)
    print(f"Retained {len(constraints):,} unique current GENCONIDs.")
    return constraints


def search_gencondata(constraints, groups, columns=None):
    """
    Search current GENCONDATA.

    Syntax:
      [["81", "82"]]                       -> 81 AND 82
      [["81", "82"], ["Upper Tumut", "051"]]
                                             -> (81 AND 82) OR (Upper Tumut AND 051)

    Searches are case-insensitive and numeric tokens are normalised, so 051 matches 51.
    A term may occur in any selected search column.
    """
    if columns is None:
        columns = SEARCH_COLUMNS
    groups = [[str(t).strip() for t in group if str(t).strip()] for group in groups]
    groups = [g for g in groups if g]
    if not groups:
        return constraints.iloc[0:0].copy()

    search_fields = []
    if "GENCONID" in columns:
        search_fields.append("_SEARCH_GENCONID")
    if "DESCRIPTION" in columns:
        search_fields.append("_SEARCH_DESCRIPTION")
    if not search_fields:
        raise ValueError("SEARCH_COLUMNS must contain GENCONID and/or DESCRIPTION.")

    final_mask = pd.Series(False, index=constraints.index)
    for group in groups:
        group_mask = pd.Series(True, index=constraints.index)
        for term in group:
            needle = normalise_search_text(term)
            term_mask = pd.Series(False, index=constraints.index)
            for field in search_fields:
                term_mask |= constraints[field].str.contains(needle, regex=False, na=False)
            group_mask &= term_mask
        final_mask |= group_mask

    output_cols = ["GENCONID", "DESCRIPTION", "CONSTRAINTTYPE", "EFFECTIVEDATE", "VERSIONNO", "LASTCHANGED"]
    output_cols = [c for c in output_cols if c in constraints.columns]
    return constraints.loc[final_mask, output_cols].sort_values("GENCONID").reset_index(drop=True)


def parse_interactive_query(text):
    """
    Console syntax:
      81 82
        => 81 AND 82
      81 82 | "Upper Tumut" Murray 051
        => (81 AND 82) OR (Upper Tumut AND Murray AND 051)
    Quotes preserve multi-word terms.
    """
    import shlex
    groups = []
    for raw_group in text.split("|"):
        raw_group = raw_group.strip()
        if raw_group:
            groups.append(shlex.split(raw_group))
    return groups


def run_search_mode(constraints):
    # Always run configured searches first, if supplied.
    if SEARCH_GROUPS:
        results = search_gencondata(constraints, SEARCH_GROUPS)
        results.to_excel(SEARCH_OUTPUT_FILE, index=False, engine="openpyxl")
        print(f"\nConfigured search returned {len(results):,} rows.")
        print(results[["GENCONID", "DESCRIPTION"]].to_string(index=False))
        print(f"Saved search results: {SEARCH_OUTPUT_FILE}")

    if not INTERACTIVE_SEARCH:
        return

    print("\nGENCONDATA SEARCH")
    print("Use spaces for AND, | for OR, and quotes for phrases.")
    print('Example: 81 82 | "Upper Tumut" Murray 051')
    print("Press Enter with no search terms to continue to the mapping process.\n")

    while True:
        raw = input("Search GENCONDATA> ").strip()
        if not raw:
            break
        groups = parse_interactive_query(raw)
        results = search_gencondata(constraints, groups)
        print(f"\nFound {len(results):,} matching constraints.\n")
        if results.empty:
            print("No matches.\n")
            continue
        print(results[["GENCONID", "DESCRIPTION"]].to_string(index=False))
        results.to_excel(SEARCH_OUTPUT_FILE, index=False, engine="openpyxl")
        print(f"\nSaved these results to {SEARCH_OUTPUT_FILE}\n")


def make_constraint_id_lookup(constraints):
    grouped = (constraints.loc[constraints["_CLEAN_GENCONID"] != "", ["_CLEAN_GENCONID", "GENCONID"]]
               .groupby("_CLEAN_GENCONID")["GENCONID"]
               .agg(lambda v: sorted({str(x).strip() for x in v if pd.notna(x)})))
    return grouped.to_dict()


def make_description_lookup(constraints):
    grouped = (constraints.loc[constraints["_CLEAN_DESCRIPTION"] != "", ["_CLEAN_DESCRIPTION", "GENCONID"]]
               .groupby("_CLEAN_DESCRIPTION")["GENCONID"]
               .agg(lambda v: sorted({str(x).strip() for x in v if pd.notna(x)})))
    return grouped.to_dict()


def resolve_single_match(matching_ids):
    return matching_ids[0] if matching_ids is not None and len(matching_ids) == 1 else None


def match_constraint(row, constraint_id_lookup, description_lookup):
    eso_constraint_id = clean_constraint_id(row.get("ESOO constraint ID"))
    cleaned_description = clean_description(row.get("Description"))
    if eso_constraint_id:
        id_matches = constraint_id_lookup.get(eso_constraint_id)
        matched_id = resolve_single_match(id_matches)
        if matched_id is not None:
            return pd.Series([matched_id, "Constraint ID"])
        if id_matches is not None and len(id_matches) > 1:
            return pd.Series(["AMBIGUOUS: " + " | ".join(id_matches), "Ambiguous constraint ID"])
    if cleaned_description:
        description_matches = description_lookup.get(cleaned_description)
        matched_id = resolve_single_match(description_matches)
        if matched_id is not None:
            return pd.Series([matched_id, "Cleaned description"])
        if description_matches is not None and len(description_matches) > 1:
            return pd.Series(["AMBIGUOUS: " + " | ".join(description_matches), "Ambiguous cleaned description"])
    return pd.Series(["NO MATCH", "No match"])


def main():
    constraints = get_gencondata()
    run_search_mode(constraints)

    # Preserve original mapping workflow. If the workbook is not present, search mode still works.
    try:
        mapping = pd.read_excel(INPUT_FILE, engine="openpyxl")
    except FileNotFoundError:
        print(f"\n{INPUT_FILE} not found. Search mode completed; skipping mapping.")
        return

    mapping.columns = [" ".join(str(c).split()) for c in mapping.columns]
    required = {"ESOO constraint ID", "Description", "AEMO constraint ID"}
    missing = required - set(mapping.columns)
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(sorted(missing)))

    constraint_id_lookup = make_constraint_id_lookup(constraints)
    description_lookup = make_description_lookup(constraints)
    matched_values = mapping.apply(match_constraint, axis=1, args=(constraint_id_lookup, description_lookup))
    matched_values.columns = ["_MATCHED_AEMO_ID", "_MATCH_METHOD"]
    mapping = pd.concat([mapping, matched_values], axis=1)

    existing = mapping["AEMO constraint ID"].notna() & (mapping["AEMO constraint ID"].astype(str).str.strip() != "")
    mapping.loc[~existing, "AEMO constraint ID"] = mapping.loc[~existing, "_MATCHED_AEMO_ID"]
    mapping["Match method"] = mapping["_MATCH_METHOD"]
    mapping.loc[existing, "Match method"] = "Existing value preserved"
    mapping = mapping.drop(columns=["_MATCHED_AEMO_ID", "_MATCH_METHOD"])

    print("\n" + "=" * 70)
    print("MATCH RESULTS")
    print("=" * 70)
    for method, count in mapping["Match method"].value_counts(dropna=False).items():
        print(f"{method}: {count:,}")

    mapping.to_excel(OUTPUT_FILE, index=False, engine="openpyxl")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
