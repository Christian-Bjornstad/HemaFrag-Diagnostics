from __future__ import annotations


# Curated from repeated visual/manual review. These tokens identify runs that
# should not be used as motor-training targets even if residuals are poor.
KNOWN_OPERATOR_OR_BAD_DATA = {
    "25OUM07000",
    "25OUM11795",
    "25OUM11890",
    "25OUM12332",
    "25OUM12848",
    "25OUM13218",
    "25OUM13702",
    "25OUM13731",
    "25OUM15784",
}


def has_known_operator_or_bad_data_token(file_name: object) -> bool:
    lower = str(file_name or "").lower()
    return any(token.lower() in lower for token in KNOWN_OPERATOR_OR_BAD_DATA)
