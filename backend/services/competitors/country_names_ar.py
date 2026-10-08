"""Arabic names for services/competitors/countries.py's COUNTRIES, so a
region the model wrote in Arabic ("لبنان", "إسرائيل") canonicalizes to the
same country as its English form instead of becoming a separate free-text
bucket. A static table rather than a runtime lookup (no ICU/Babel in the
backend, and nothing here may fetch from the network) - generated once from
CLDR's Arabic region names (Intl.DisplayNames('ar')), the same names the
dashboard shows for a country in the Arabic UI.

Kept out of COUNTRY_ALIASES on purpose: region_detection.py scans article
text for those surface forms, and widening that scan to Arabic is a separate
analysis change - this table only canonicalizes a value already given.
"""

from __future__ import annotations

import re
import unicodedata

ARABIC_COUNTRY_NAMES: dict[str, str] = {
    "AD": "أندورا", "AE": "الإمارات العربية المتحدة", "AF": "أفغانستان",
    "AG": "أنتيغوا وبربودا", "AL": "ألبانيا", "AM": "أرمينيا",
    "AO": "أنغولا", "AR": "الأرجنتين", "AT": "النمسا",
    "AU": "أستراليا", "AZ": "أذربيجان", "BA": "البوسنة والهرسك",
    "BB": "بربادوس", "BD": "بنغلاديش", "BE": "بلجيكا",
    "BF": "بوركينا فاسو", "BG": "بلغاريا", "BH": "البحرين",
    "BI": "بوروندي", "BJ": "بنين", "BN": "بروناي",
    "BO": "بوليفيا", "BR": "البرازيل", "BS": "جزر البهاما",
    "BT": "بوتان", "BW": "بوتسوانا", "BY": "بيلاروس",
    "BZ": "بليز", "CA": "كندا", "CD": "الكونغو - كينشاسا",
    "CF": "جمهورية أفريقيا الوسطى", "CG": "الكونغو - برازافيل", "CH": "سويسرا",
    "CL": "تشيلي", "CM": "الكاميرون", "CN": "الصين",
    "CO": "كولومبيا", "CR": "كوستاريكا", "CU": "كوبا",
    "CV": "الرأس الأخضر", "CY": "قبرص", "CZ": "التشيك",
    "DE": "ألمانيا", "DJ": "جيبوتي", "DK": "الدانمرك",
    "DM": "دومينيكا", "DO": "جمهورية الدومينيكان", "DZ": "الجزائر",
    "EC": "الإكوادور", "EE": "إستونيا", "EG": "مصر",
    "ER": "إريتريا", "ES": "إسبانيا", "ET": "إثيوبيا",
    "FI": "فنلندا", "FJ": "فيجي", "FM": "ميكرونيزيا",
    "FR": "فرنسا", "GA": "الغابون", "GB": "المملكة المتحدة",
    "GD": "غرينادا", "GE": "جورجيا", "GH": "غانا",
    "GM": "غامبيا", "GN": "غينيا", "GQ": "غينيا الاستوائية",
    "GR": "اليونان", "GT": "غواتيمالا", "GW": "غينيا بيساو",
    "GY": "غيانا", "HK": "هونغ كونغ الصينية (منطقة إدارية خاصة)", "HN": "هندوراس",
    "HR": "كرواتيا", "HT": "هايتي", "HU": "هنغاريا",
    "ID": "إندونيسيا", "IE": "أيرلندا", "IL": "إسرائيل",
    "IN": "الهند", "IQ": "العراق", "IR": "إيران",
    "IS": "آيسلندا", "IT": "إيطاليا", "JM": "جامايكا",
    "JO": "الأردن", "JP": "اليابان", "KE": "كينيا",
    "KG": "قيرغيزستان", "KH": "كمبوديا", "KI": "كيريباتي",
    "KM": "جزر القمر", "KN": "سانت كيتس ونيفيس", "KR": "كوريا الجنوبية",
    "KW": "الكويت", "KZ": "كازاخستان", "LA": "لاوس",
    "LB": "لبنان", "LC": "سانت لوسيا", "LI": "ليختنشتاين",
    "LK": "سريلانكا", "LR": "ليبيريا", "LS": "ليسوتو",
    "LT": "ليتوانيا", "LU": "لوكسمبورغ", "LV": "لاتفيا",
    "LY": "ليبيا", "MA": "المغرب", "MC": "موناكو",
    "MD": "مولدوفا", "ME": "الجبل الأسود", "MG": "مدغشقر",
    "MH": "جزر مارشال", "MK": "مقدونيا الشمالية", "ML": "مالي",
    "MM": "ميانمار (بورما)", "MN": "منغوليا", "MO": "منطقة ماكاو الإدارية الخاصة",
    "MR": "موريتانيا", "MT": "مالطا", "MU": "موريشيوس",
    "MV": "جزر المالديف", "MW": "ملاوي", "MX": "المكسيك",
    "MY": "ماليزيا", "MZ": "موزمبيق", "NA": "ناميبيا",
    "NE": "النيجر", "NG": "نيجيريا", "NI": "نيكاراغوا",
    "NL": "هولندا", "NO": "النرويج", "NP": "نيبال",
    "NR": "ناورو", "NZ": "نيوزيلندا", "OM": "عُمان",
    "PA": "بنما", "PE": "بيرو", "PG": "بابوا غينيا الجديدة",
    "PH": "الفلبين", "PK": "باكستان", "PL": "بولندا",
    "PS": "الأراضي الفلسطينية", "PT": "البرتغال", "PW": "بالاو",
    "PY": "باراغواي", "QA": "قطر", "RO": "رومانيا",
    "RS": "صربيا", "RU": "روسيا", "RW": "رواندا",
    "SA": "المملكة العربية السعودية", "SB": "جزر سليمان", "SC": "سيشل",
    "SD": "السودان", "SE": "السويد", "SG": "سنغافورة",
    "SI": "سلوفينيا", "SK": "سلوفاكيا", "SL": "سيراليون",
    "SM": "سان مارينو", "SN": "السنغال", "SO": "الصومال",
    "SR": "سورينام", "SS": "جنوب السودان", "ST": "ساو تومي وبرينسيبي",
    "SV": "السلفادور", "SY": "سوريا", "SZ": "إسواتيني",
    "TD": "تشاد", "TG": "توغو", "TH": "تايلاند",
    "TJ": "طاجيكستان", "TL": "تيمور - ليشتي", "TM": "تركمانستان",
    "TN": "تونس", "TO": "تونغا", "TR": "تركيا",
    "TT": "ترينيداد وتوباغو", "TV": "توفالو", "TW": "تايوان",
    "TZ": "تنزانيا", "UA": "أوكرانيا", "UG": "أوغندا",
    "US": "الولايات المتحدة", "UY": "أورغواي", "UZ": "أوزبكستان",
    "VA": "الفاتيكان", "VC": "سانت فنسنت وجزر غرينادين", "VE": "فنزويلا",
    "VN": "فيتنام", "VU": "فانواتو", "WS": "ساموا",
    "YE": "اليمن", "ZA": "جنوب أفريقيا", "ZM": "زامبيا",
    "ZW": "زيمبابوي",
}

# Everyday short forms that differ from the CLDR names above.
ARABIC_COUNTRY_ALIASES: dict[str, str] = {
    "فلسطين": "PS", "السعودية": "SA", "الإمارات": "AE", "الامارات": "AE",
    "أمريكا": "US", "امريكا": "US", "الولايات المتحدة الأمريكية": "US",
    "بريطانيا": "GB", "إنجلترا": "GB", "انجلترا": "GB", "إنكلترا": "GB",
    "اسكتلندا": "GB", "ويلز": "GB",
    "هونغ كونغ": "HK", "ماكاو": "MO", "ميانمار": "MM", "بورما": "MM",
    "الكونغو الديمقراطية": "CD", "جمهورية الكونغو الديمقراطية": "CD",
    "التشيك": "CZ", "جمهورية التشيك": "CZ", "كوريا الجنوبية": "KR",
}

_DIACRITICS = re.compile("[\u064B-\u065F\u0670\u0640]")


def normalize_arabic(text: str) -> str:
    """Spelling-insensitive form for matching: no diacritics/tatweel, one alef
    form, taa marbuta as haa, alef maqsura as yaa, single spaces."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = _DIACRITICS.sub("", text)
    text = re.sub("[أإآٱ]", "ا", text).replace("ة", "ه").replace("ى", "ي")
    return " ".join(text.split())


_CODES_BY_ARABIC = {
    normalize_arabic(name): code
    for name, code in [*((n, c) for c, n in ARABIC_COUNTRY_NAMES.items()), *ARABIC_COUNTRY_ALIASES.items()]
}


def resolve_arabic_country(text: str) -> str | None:
    """The country code an Arabic country name means, or None."""
    return _CODES_BY_ARABIC.get(normalize_arabic(text))
