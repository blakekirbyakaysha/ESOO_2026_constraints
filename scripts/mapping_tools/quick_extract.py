from pathlib import Path
import io
import re
import time
import urllib3
import requests
import pandas as pd


# =============================================================================
# SETTINGS
# =============================================================================

MAPDIR = Path(__file__).resolve().parent.parent.parent / "inputs" / "mapping"
INPUT_FILE = str(MAPDIR / "Equation_mapping.xlsx")
OUTPUT_FILE = str(MAPDIR / "Equation_mapping_populated.xlsx")

URL = "https://www.neopoint.com.au/data/query"
API_KEY = "AKAY21"

# Temporary workaround for the SSL certificate issue.
VERIFY_SSL = False

if not VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# =============================================================================
# CLEANING FUNCTIONS
# =============================================================================

def clean_constraint_id(value):
    """
    Clean a constraint ID for matching.

    This:
      - converts to text;
      - strips leading/trailing whitespace;
      - removes internal whitespace;
      - converts to uppercase.
    """

    if pd.isna(value):
        return ""

    value = str(value).strip().upper()

    # Remove whitespace that may have been introduced into an ID.
    value = re.sub(r"\s+", "", value)

    return value


def remove_leading_zeros(match):
    """
    Convert numeric tokens such as:
        051  -> 51
        001  -> 1
        000  -> 0

    Numbers without leading zeros are unchanged.
    """

    number = match.group(0)

    try:
        return str(int(number))
    except ValueError:
        return number


def clean_description(value):
    """
    Clean a constraint description for secondary matching.

    Examples treated as equivalent:

        line 051
        line 51

    Cleaning includes:
      - lowercase conversion;
      - removal of leading/trailing whitespace;
      - removal of leading zeros from numeric tokens;
      - normalisation of whitespace;
      - normalisation of spacing around punctuation;
      - normalisation of spacing around '='.
    """

    if pd.isna(value):
        return ""

    value = str(value)

    # Normalise common Unicode punctuation.
    value = value.replace("–", "-")
    value = value.replace("—", "-")
    value = value.replace("−", "-")
    value = value.replace("’", "'")
    value = value.replace("‘", "'")
    value = value.replace("“", '"')
    value = value.replace("”", '"')

    value = value.lower().strip()

    # Treat all whitespace, including tabs and line breaks, consistently.
    value = re.sub(r"\s+", " ", value)

    # Normalise spacing around equals signs.
    # For example:
    #   out = nil
    #   out= nil
    #   out =nil
    # become:
    #   out=nil
    value = re.sub(r"\s*=\s*", "=", value)

    # Normalise spacing around selected punctuation.
    value = re.sub(r"\s*,\s*", ",", value)
    value = re.sub(r"\s*;\s*", ";", value)
    value = re.sub(r"\s*:\s*", ":", value)

    # Normalise spaces immediately inside brackets.
    value = re.sub(r"\(\s+", "(", value)
    value = re.sub(r"\s+\)", ")", value)

    # Remove leading zeros from standalone numeric tokens.
    #
    # The digit boundaries ensure that:
    #   051 becomes 51
    #   330 remains 330
    #   text051text is not modified
    value = re.sub(
        r"(?<!\d)\d+(?!\d)",
        remove_leading_zeros,
        value,
    )

    # Final whitespace normalisation.
    value = re.sub(r"\s+", " ", value).strip()

    return value


# =============================================================================
# QUERY NEOPOINT
# =============================================================================

def qt_post_request(query_string: str, retries: int = 3) -> pd.DataFrame:
    """
    Send a query to the IES/NEOpoint API and return a pandas DataFrame.
    """

    payload = {
        "query": query_string,
        "key": API_KEY,
        "format": "csv",
    }

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(
                URL,
                params=payload,
                timeout=120,
                verify=VERIFY_SSL,
            )

            response.raise_for_status()

            if not response.text.strip():
                raise ValueError("NEOpoint returned an empty response.")

            return pd.read_csv(
                io.StringIO(response.text)
            )

        except (
            requests.exceptions.RequestException,
            pd.errors.ParserError,
            ValueError,
        ) as exc:

            print(
                f"Query attempt {attempt}/{retries} failed: {exc}"
            )

            if attempt < retries:
                time.sleep(5)

    raise RuntimeError(
        f"Query failed after {retries} attempts."
    )


# =============================================================================
# GET GENCONDATA
# =============================================================================

def get_gencondata() -> pd.DataFrame:
    """
    Retrieve GENCONDATA and keep the latest version of every GENCONID.
    """

    query = """
    SELECT
        EFFECTIVEDATE,
        VERSIONNO,
        GENCONID,
        CONSTRAINTTYPE,
        DESCRIPTION,
        STATUS,
        LASTCHANGED
    FROM mms.gencondata
    ORDER BY
        GENCONID,
        EFFECTIVEDATE DESC,
        VERSIONNO DESC;
    """

    print("Querying GENCONDATA...")

    constraints = qt_post_request(query)

    print(
        f"Retrieved {len(constraints):,} GENCONDATA rows."
    )

    # Standardise returned column names.
    constraints.columns = [
        str(column).strip().upper()
        for column in constraints.columns
    ]

    required_columns = {
        "EFFECTIVEDATE",
        "VERSIONNO",
        "GENCONID",
        "DESCRIPTION",
    }

    missing_columns = required_columns - set(constraints.columns)

    if missing_columns:
        raise ValueError(
            "GENCONDATA query is missing columns: "
            + ", ".join(sorted(missing_columns))
        )

    constraints["EFFECTIVEDATE"] = pd.to_datetime(
        constraints["EFFECTIVEDATE"],
        errors="coerce",
    )

    constraints["VERSIONNO"] = pd.to_numeric(
        constraints["VERSIONNO"],
        errors="coerce",
    )

    # Keep the latest effective version of each individual GENCONID.
    constraints = (
        constraints
        .sort_values(
            by=[
                "GENCONID",
                "EFFECTIVEDATE",
                "VERSIONNO",
            ],
            ascending=[
                True,
                False,
                False,
            ],
            na_position="last",
        )
        .drop_duplicates(
            subset=["GENCONID"],
            keep="first",
        )
        .reset_index(drop=True)
    )

    # Create matching fields.
    constraints["_CLEAN_GENCONID"] = (
        constraints["GENCONID"]
        .apply(clean_constraint_id)
    )

    constraints["_CLEAN_DESCRIPTION"] = (
        constraints["DESCRIPTION"]
        .apply(clean_description)
    )

    print(
        f"Retained {len(constraints):,} unique current GENCONIDs."
    )

    return constraints


# =============================================================================
# LOOKUP FUNCTIONS
# =============================================================================

def make_constraint_id_lookup(constraints):
    """
    Create a cleaned GENCONID -> actual GENCONID lookup.
    """

    grouped = (
        constraints
        .loc[
            constraints["_CLEAN_GENCONID"] != "",
            ["_CLEAN_GENCONID", "GENCONID"],
        ]
        .groupby("_CLEAN_GENCONID")["GENCONID"]
        .agg(
            lambda values: sorted(
                {
                    str(value).strip()
                    for value in values
                    if pd.notna(value)
                }
            )
        )
    )

    return grouped.to_dict()


def make_description_lookup(constraints):
    """
    Create a cleaned DESCRIPTION -> GENCONID list lookup.
    """

    grouped = (
        constraints
        .loc[
            constraints["_CLEAN_DESCRIPTION"] != "",
            ["_CLEAN_DESCRIPTION", "GENCONID"],
        ]
        .groupby("_CLEAN_DESCRIPTION")["GENCONID"]
        .agg(
            lambda values: sorted(
                {
                    str(value).strip()
                    for value in values
                    if pd.notna(value)
                }
            )
        )
    )

    return grouped.to_dict()


def resolve_single_match(matching_ids):
    """
    Return a single ID only where the lookup is unambiguous.
    """

    if matching_ids is None:
        return None

    if len(matching_ids) == 1:
        return matching_ids[0]

    return None


# =============================================================================
# MATCH ONE ROW
# =============================================================================

def match_constraint(
    row,
    constraint_id_lookup,
    description_lookup,
):
    """
    Match one Equation_mapping row.

    Priority:
      1. ESOO constraint ID to GENCONID.
      2. Cleaned Description to cleaned DESCRIPTION.
      3. NO MATCH.

    Returns:
      AEMO constraint ID
      Match method
    """

    eso_constraint_id = clean_constraint_id(
        row.get("ESOO constraint ID")
    )

    cleaned_description = clean_description(
        row.get("Description")
    )

    # -------------------------------------------------------------------------
    # Priority 1: constraint ID
    # -------------------------------------------------------------------------

    if eso_constraint_id:
        id_matches = constraint_id_lookup.get(
            eso_constraint_id
        )

        matched_id = resolve_single_match(id_matches)

        if matched_id is not None:
            return pd.Series(
                [
                    matched_id,
                    "Constraint ID",
                ]
            )

        if id_matches is not None and len(id_matches) > 1:
            return pd.Series(
                [
                    "AMBIGUOUS: " + " | ".join(id_matches),
                    "Ambiguous constraint ID",
                ]
            )

    # -------------------------------------------------------------------------
    # Priority 2: cleaned description
    # -------------------------------------------------------------------------

    if cleaned_description:
        description_matches = description_lookup.get(
            cleaned_description
        )

        matched_id = resolve_single_match(
            description_matches
        )

        if matched_id is not None:
            return pd.Series(
                [
                    matched_id,
                    "Cleaned description",
                ]
            )

        if (
            description_matches is not None
            and len(description_matches) > 1
        ):
            return pd.Series(
                [
                    (
                        "AMBIGUOUS: "
                        + " | ".join(description_matches)
                    ),
                    "Ambiguous cleaned description",
                ]
            )

    return pd.Series(
        [
            "NO MATCH",
            "No match",
        ]
    )


# =============================================================================
# MAIN
# =============================================================================

def main():

    print(f"Reading {INPUT_FILE}...")

    mapping = pd.read_excel(
        INPUT_FILE,
        engine="openpyxl",
    )

    mapping.columns = [
        " ".join(str(column).split())
        for column in mapping.columns
    ]

    required_columns = {
        "ESOO constraint ID",
        "Description",
        "AEMO constraint ID",
    }

    missing_columns = required_columns - set(mapping.columns)

    if missing_columns:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(sorted(missing_columns))
        )

    print(f"Loaded {len(mapping):,} mapping rows.")

    constraints = get_gencondata()

    constraint_id_lookup = make_constraint_id_lookup(
        constraints
    )

    description_lookup = make_description_lookup(
        constraints
    )

    print("Matching constraints...")

    matched_values = mapping.apply(
        match_constraint,
        axis=1,
        args=(
            constraint_id_lookup,
            description_lookup,
        ),
    )

    matched_values.columns = [
        "_MATCHED_AEMO_ID",
        "_MATCH_METHOD",
    ]

    mapping = pd.concat(
        [
            mapping,
            matched_values,
        ],
        axis=1,
    )

    # Preserve an existing AEMO constraint ID if already populated.
    existing_value = (
        mapping["AEMO constraint ID"].notna()
        & (
            mapping["AEMO constraint ID"]
            .astype(str)
            .str.strip()
            != ""
        )
    )

    mapping.loc[
        ~existing_value,
        "AEMO constraint ID",
    ] = mapping.loc[
        ~existing_value,
        "_MATCHED_AEMO_ID",
    ]

    mapping["Match method"] = mapping["_MATCH_METHOD"]

    mapping.loc[
        existing_value,
        "Match method",
    ] = "Existing value preserved"

    mapping = mapping.drop(
        columns=[
            "_MATCHED_AEMO_ID",
            "_MATCH_METHOD",
        ]
    )

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------

    method_counts = (
        mapping["Match method"]
        .value_counts(dropna=False)
    )

    print()
    print("=" * 70)
    print("MATCH RESULTS")
    print("=" * 70)

    for match_method, count in method_counts.items():
        print(f"{match_method}: {count:,}")

    # -------------------------------------------------------------------------
    # Print unmatched rows
    # -------------------------------------------------------------------------

    unmatched = mapping.loc[
        mapping["Match method"] == "No match",
        [
            "ESOO constraint ID",
            "Description",
        ],
    ]

    if not unmatched.empty:
        print()
        print("UNMATCHED CONSTRAINTS")
        print("-" * 70)
        print(unmatched.to_string(index=False))

    # -------------------------------------------------------------------------
    # Print ambiguous rows
    # -------------------------------------------------------------------------

    ambiguous = mapping.loc[
        mapping["Match method"]
        .astype(str)
        .str.startswith("Ambiguous"),
        [
            "ESOO constraint ID",
            "Description",
            "AEMO constraint ID",
            "Match method",
        ],
    ]

    if not ambiguous.empty:
        print()
        print("AMBIGUOUS CONSTRAINTS")
        print("-" * 70)
        print(ambiguous.to_string(index=False))

    # -------------------------------------------------------------------------
    # Save
    # -------------------------------------------------------------------------

    mapping.to_excel(
        OUTPUT_FILE,
        index=False,
        engine="openpyxl",
    )

    print()
    print("=" * 70)
    print(f"Saved: {OUTPUT_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()