"""Fixed ISO 3166-1 alpha-2 country list for competitor study targeting.

A closed vocabulary, not free text: "USA" vs "United States" vs "US" would
otherwise reach the discovery prompt inconsistently and weaken it. Codes are
the storage/API form; names are only for prompt text and UI labels.
"""

from __future__ import annotations

COUNTRIES: dict[str, str] = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AD": "Andorra",
    "AO": "Angola", "AG": "Antigua and Barbuda", "AR": "Argentina", "AM": "Armenia",
    "AU": "Australia", "AT": "Austria", "AZ": "Azerbaijan", "BS": "Bahamas",
    "BH": "Bahrain", "BD": "Bangladesh", "BB": "Barbados", "BY": "Belarus",
    "BE": "Belgium", "BZ": "Belize", "BJ": "Benin", "BT": "Bhutan",
    "BO": "Bolivia", "BA": "Bosnia and Herzegovina", "BW": "Botswana", "BR": "Brazil",
    "BN": "Brunei", "BG": "Bulgaria", "BF": "Burkina Faso", "BI": "Burundi",
    "KH": "Cambodia", "CM": "Cameroon", "CA": "Canada", "CV": "Cape Verde",
    "CF": "Central African Republic", "TD": "Chad", "CL": "Chile", "CN": "China",
    "CO": "Colombia", "KM": "Comoros", "CG": "Congo", "CD": "Congo (DRC)",
    "CR": "Costa Rica", "HR": "Croatia", "CU": "Cuba", "CY": "Cyprus",
    "CZ": "Czech Republic", "DK": "Denmark", "DJ": "Djibouti", "DM": "Dominica",
    "DO": "Dominican Republic", "EC": "Ecuador", "EG": "Egypt", "SV": "El Salvador",
    "GQ": "Equatorial Guinea", "ER": "Eritrea", "EE": "Estonia", "SZ": "Eswatini",
    "ET": "Ethiopia", "FJ": "Fiji", "FI": "Finland", "FR": "France",
    "GA": "Gabon", "GM": "Gambia", "GE": "Georgia", "DE": "Germany",
    "GH": "Ghana", "GR": "Greece", "GD": "Grenada", "GT": "Guatemala",
    "GN": "Guinea", "GW": "Guinea-Bissau", "GY": "Guyana", "HT": "Haiti",
    "HN": "Honduras", "HK": "Hong Kong", "HU": "Hungary", "IS": "Iceland",
    "IN": "India", "ID": "Indonesia", "IR": "Iran", "IQ": "Iraq",
    "IE": "Ireland", "IL": "Israel", "IT": "Italy", "JM": "Jamaica",
    "JP": "Japan", "JO": "Jordan", "KZ": "Kazakhstan", "KE": "Kenya",
    "KI": "Kiribati", "KW": "Kuwait", "KG": "Kyrgyzstan", "LA": "Laos",
    "LV": "Latvia", "LB": "Lebanon", "LS": "Lesotho", "LR": "Liberia",
    "LY": "Libya", "LI": "Liechtenstein", "LT": "Lithuania", "LU": "Luxembourg",
    "MO": "Macao", "MG": "Madagascar", "MW": "Malawi", "MY": "Malaysia",
    "MV": "Maldives", "ML": "Mali", "MT": "Malta", "MH": "Marshall Islands",
    "MR": "Mauritania", "MU": "Mauritius", "MX": "Mexico", "FM": "Micronesia",
    "MD": "Moldova", "MC": "Monaco", "MN": "Mongolia", "ME": "Montenegro",
    "MA": "Morocco", "MZ": "Mozambique", "MM": "Myanmar", "NA": "Namibia",
    "NR": "Nauru", "NP": "Nepal", "NL": "Netherlands", "NZ": "New Zealand",
    "NI": "Nicaragua", "NE": "Niger", "NG": "Nigeria", "MK": "North Macedonia",
    "NO": "Norway", "OM": "Oman", "PK": "Pakistan", "PW": "Palau",
    "PS": "Palestine", "PA": "Panama", "PG": "Papua New Guinea", "PY": "Paraguay",
    "PE": "Peru", "PH": "Philippines", "PL": "Poland", "PT": "Portugal",
    "QA": "Qatar", "RO": "Romania", "RU": "Russia", "RW": "Rwanda",
    "KN": "Saint Kitts and Nevis", "LC": "Saint Lucia", "VC": "Saint Vincent and the Grenadines",
    "WS": "Samoa", "SM": "San Marino", "ST": "Sao Tome and Principe", "SA": "Saudi Arabia",
    "SN": "Senegal", "RS": "Serbia", "SC": "Seychelles", "SL": "Sierra Leone",
    "SG": "Singapore", "SK": "Slovakia", "SI": "Slovenia", "SB": "Solomon Islands",
    "SO": "Somalia", "ZA": "South Africa", "KR": "South Korea", "SS": "South Sudan",
    "ES": "Spain", "LK": "Sri Lanka", "SD": "Sudan", "SR": "Suriname",
    "SE": "Sweden", "CH": "Switzerland", "SY": "Syria", "TW": "Taiwan",
    "TJ": "Tajikistan", "TZ": "Tanzania", "TH": "Thailand", "TL": "Timor-Leste",
    "TG": "Togo", "TO": "Tonga", "TT": "Trinidad and Tobago", "TN": "Tunisia",
    "TR": "Turkey", "TM": "Turkmenistan", "TV": "Tuvalu", "UG": "Uganda",
    "UA": "Ukraine", "AE": "United Arab Emirates", "GB": "United Kingdom",
    "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan", "VU": "Vanuatu",
    "VA": "Vatican City", "VE": "Venezuela", "VN": "Vietnam", "YE": "Yemen",
    "ZM": "Zambia", "ZW": "Zimbabwe",
}


# Common abbreviations/demonyms/informal names that don't match a COUNTRIES
# name or code exactly, mapped to the code they mean. Not exhaustive - just
# the forms an LLM (or a human writer) actually uses in running text, so
# normalize_region/region_detection stop fragmenting "US"/"USA"/"American"
# into three different stored values. Keys are lowercase.
COUNTRY_ALIASES: dict[str, str] = {
    "us": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US", "america": "US", "american": "US", "americans": "US",
    "uk": "GB", "u.k.": "GB", "britain": "GB", "british": "GB", "great britain": "GB",
    "england": "GB", "english": "GB", "scotland": "GB", "scottish": "GB", "wales": "GB", "welsh": "GB",
    "uae": "AE", "emirati": "AE", "emiratis": "AE", "emirates": "AE",
    "ksa": "SA", "saudi": "SA", "saudis": "SA", "saudi arabian": "SA",
    "germany": "DE", "german": "DE", "germans": "DE",
    "france": "FR", "french": "FR",
    "japan": "JP", "japanese": "JP",
    "china": "CN", "chinese": "CN", "prc": "CN",
    "south korea": "KR", "south korean": "KR", "korean": "KR", "koreans": "KR",
    "russia": "RU", "russian": "RU", "russians": "RU",
    "india": "IN", "indian": "IN", "indians": "IN",
    "brazil": "BR", "brazilian": "BR",
    "canada": "CA", "canadian": "CA", "canadians": "CA",
    "australia": "AU", "australian": "AU", "aussie": "AU", "aussies": "AU",
    "spain": "ES", "spanish": "ES",
    "italy": "IT", "italian": "IT",
    "mexico": "MX", "mexican": "MX",
    "egypt": "EG", "egyptian": "EG",
    "turkey": "TR", "turkish": "TR",
    "netherlands": "NL", "dutch": "NL", "holland": "NL",
}


def resolve_country_alias(text: str) -> str | None:
    """Look up an abbreviation/demonym against COUNTRY_ALIASES. Returns the
    matching country code, or None when `text` isn't a known alias."""
    return COUNTRY_ALIASES.get(str(text or "").strip().lower())


def validate_countries(values) -> list[str]:
    """Clean a list of country codes down to known, deduped, upper-case ISO codes."""
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for item in values:
        code = str(item or "").strip().upper()
        if code in COUNTRIES and code not in out:
            out.append(code)
    return out


def country_label(code: str | None) -> str:
    code = str(code or "").strip().upper()
    return COUNTRIES.get(code, code)
