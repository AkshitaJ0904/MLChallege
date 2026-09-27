"""Unicode-preserving, non-destructive record views and extractors."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_SPACE = re.compile(r"\s+", flags=re.UNICODE)
_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_TOKEN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_NUMBER = re.compile(r"(?<!\w)\d{1,12}(?!\w)", flags=re.UNICODE)
_US_ZIP = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_INDIA_PIN = re.compile(r"\b[1-9]\d{5}\b")
_FR_POSTAL = re.compile(r"\b\d{5}\b")


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def whitespace_normalize(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def punctuation_normalize(text: str) -> str:
    """Separate punctuation; do not remove digits, scripts, or raw text."""
    return whitespace_normalize(_PUNCT.sub(" ", nfkc(text)).casefold())


def tokens(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(punctuation_normalize(text)))


def numeric_tokens(text: str) -> tuple[str, ...]:
    return tuple(_NUMBER.findall(nfkc(text)))


def postal_like(text: str, country: str) -> tuple[str, ...]:
    """Return conservative postal-like values, never claiming semantic certainty."""
    clean = nfkc(text)
    country_key = country.casefold().strip()
    pattern = _US_ZIP if country_key in {"us", "usa", "united states"} else (
        _INDIA_PIN if country_key in {"india", "in"} else _FR_POSTAL if country_key in {"france", "fr"} else None
    )
    return tuple(pattern.findall(clean)) if pattern else ()


def script_flags(text: str) -> dict[str, bool]:
    return {
        "has_non_ascii": any(ord(c) > 127 for c in text),
        "has_devanagari": any("DEVANAGARI" in unicodedata.name(c, "") for c in text),
    }


def country_bucket(country: str) -> str:
    """Reporting bucket only; original country remains the retrieval value."""
    key = country.casefold().strip()
    if key in {"india", "in"}:
        return "India"
    if key in {"us", "usa", "united states", "united states of america"}:
        return "US"
    if key in {"france", "fr"}:
        return "France"
    return "Other/unknown"


@dataclass(frozen=True)
class RecordViews:
    entity_id: str
    source: str
    business_name: str
    business_address: str
    country: str
    name_nfkc: str
    name_ws: str
    name_punct: str
    address_nfkc: str
    address_ws: str
    address_punct: str
    name_tokens: tuple[str, ...]
    address_tokens: tuple[str, ...]
    address_numbers: tuple[str, ...]
    postals: tuple[str, ...]
    name_length: int
    address_length: int
    name_token_count: int
    address_token_count: int
    name_has_non_ascii: bool
    address_has_non_ascii: bool


def make_views(entity_id: str, business_name: str, business_address: str, country: str) -> RecordViews:
    source = entity_id.split("-", 1)[0] if "-" in entity_id else "UNKNOWN"
    name_nfkc, address_nfkc = nfkc(business_name), nfkc(business_address)
    name_tokens, address_tokens = tokens(name_nfkc), tokens(address_nfkc)
    name_script, address_script = script_flags(name_nfkc), script_flags(address_nfkc)
    return RecordViews(
        entity_id=entity_id, source=source, business_name=business_name,
        business_address=business_address, country=country,
        name_nfkc=name_nfkc, name_ws=whitespace_normalize(name_nfkc),
        name_punct=punctuation_normalize(name_nfkc), address_nfkc=address_nfkc,
        address_ws=whitespace_normalize(address_nfkc), address_punct=punctuation_normalize(address_nfkc),
        name_tokens=name_tokens, address_tokens=address_tokens,
        address_numbers=numeric_tokens(address_nfkc), postals=postal_like(address_nfkc, country),
        name_length=len(business_name), address_length=len(business_address),
        name_token_count=len(name_tokens), address_token_count=len(address_tokens),
        name_has_non_ascii=name_script["has_non_ascii"], address_has_non_ascii=address_script["has_non_ascii"],
    )
