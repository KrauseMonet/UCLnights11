"""Normalise the nationality an article gives -- a FIFA code, an ISO-style code
or a country name -- to one display name.

An unrecognised value maps to None, never to a guess: a blank nationality on a
card is honest, a wrong one is not.
"""

from __future__ import annotations

_CODES = {
    "ALB": "Albania", "ALG": "Algeria", "ANG": "Angola", "ARG": "Argentina", "ARM": "Armenia",
    "AUS": "Australia", "AUT": "Austria", "BEL": "Belgium", "BFA": "Burkina Faso",
    "BIH": "Bosnia and Herzegovina", "BLR": "Belarus", "BOL": "Bolivia", "BRA": "Brazil",
    "BUL": "Bulgaria", "BUR": "Burkina Faso", "CAN": "Canada", "CGO": "Congo", "CHA": "Chad",
    "CHI": "Chile", "CHL": "Chile", "CHN": "China", "CIV": "Ivory Coast", "CMR": "Cameroon",
    "COD": "DR Congo", "COL": "Colombia", "CPV": "Cape Verde", "CRC": "Costa Rica",
    "CRO": "Croatia", "CTA": "Central African Republic", "CUB": "Cuba", "CUW": "Curaçao",
    "CYP": "Cyprus", "CZE": "Czech Republic", "DEN": "Denmark", "DOM": "Dominican Republic",
    "DRC": "DR Congo", "ECU": "Ecuador", "EGY": "Egypt", "ENG": "England", "ESP": "Spain",
    "EST": "Estonia", "FIN": "Finland", "FRA": "France", "FRY": "FR Yugoslavia",
    "GAB": "Gabon", "GAM": "Gambia", "GBS": "Guinea-Bissau", "GEO": "Georgia", "GER": "Germany",
    "GHA": "Ghana", "GRE": "Greece", "GUI": "Guinea", "HAI": "Haiti", "HON": "Honduras",
    "HRV": "Croatia", "HUN": "Hungary", "IDN": "Indonesia", "IRE": "Republic of Ireland",
    "IRL": "Republic of Ireland", "IRN": "Iran", "ISL": "Iceland", "ISR": "Israel",
    "ITA": "Italy", "JAM": "Jamaica", "JAP": "Japan", "JPN": "Japan", "KEN": "Kenya",
    "KOR": "South Korea", "KOS": "Kosovo", "KVX": "Kosovo", "LAT": "Latvia", "LBR": "Liberia",
    "LIT": "Lithuania", "LTU": "Lithuania", "LUX": "Luxembourg", "LVA": "Latvia",
    "MAR": "Morocco", "MEX": "Mexico", "MKD": "North Macedonia", "MLI": "Mali",
    "MNE": "Montenegro", "MOZ": "Mozambique", "NED": "Netherlands", "NGA": "Nigeria",
    "NGR": "Nigeria", "NIR": "Northern Ireland", "NOR": "Norway", "NZL": "New Zealand",
    "PAR": "Paraguay", "PER": "Peru", "POL": "Poland", "POR": "Portugal", "PRC": "China",
    "PRT": "Portugal", "PRY": "Paraguay", "ROM": "Romania", "ROU": "Romania",
    "RSA": "South Africa", "RUS": "Russia", "SCG": "Serbia and Montenegro", "SCO": "Scotland",
    "SEN": "Senegal", "SER": "Serbia", "SLE": "Sierra Leone", "SLO": "Slovenia",
    "SPA": "Spain", "SRB": "Serbia", "SUI": "Switzerland", "SVK": "Slovakia",
    "SVN": "Slovenia", "SWE": "Sweden", "SWI": "Switzerland", "THA": "Thailand",
    "TOG": "Togo", "TRI": "Trinidad and Tobago", "TUN": "Tunisia", "TUR": "Turkey",
    "UKR": "Ukraine", "URU": "Uruguay", "USA": "United States", "VEN": "Venezuela",
    "WAL": "Wales", "ZAM": "Zambia",
}
_NAMES = {name.lower(): name for name in set(_CODES.values())}
_NAMES.update({
    "the netherlands": "Netherlands", "ireland": "Republic of Ireland",
    "zaire": "DR Congo", "serbia and montenegro": "Serbia and Montenegro",
    "fr yugoslavia": "FR Yugoslavia",
})


def nation(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    return _CODES.get(raw.upper()) or _NAMES.get(raw.lower())
