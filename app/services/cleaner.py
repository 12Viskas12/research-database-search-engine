from __future__ import annotations

import argparse
import html
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

logger = logging.getLogger("cleaner")

SUPPORTED_INPUT = {".csv", ".xlsx", ".xls", ".xml"}
SUPPORTED_OUTPUT = {".csv", ".xlsx", ".xml", ".json", ".jsonl"}

NULL_LIKE = {
    "", "-", "--", "---", "—", "–", "n/a", "na", "n.a.", "nan", "none", "null",
    "nil", "undefined", "#n/a", "#null!", "#value!", "#ref!", "#div/0!",
    "нет данных", "н/д", "нд", "пусто", "не указано", "?", "...",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060\ufeff]")


@dataclass
class CleanerConfig:
    max_empty_ratio: float = 0.95
    drop_duplicates: bool = True
    strip_html: bool = True
    normalize_columns: bool = True
    lowercase_values: bool = False
    null_values: set[str] = field(default_factory=lambda: set(NULL_LIKE))
    csv_encodings: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1251", "latin-1")
    xml_xpath: str | None = None


def read_file(path: str | Path, config: CleanerConfig | None = None) -> pd.DataFrame:
    config = config or CleanerConfig()
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_INPUT:
        raise ValueError(f"Неподдерживаемый формат: {ext}. Допустимо: {sorted(SUPPORTED_INPUT)}")

    if ext == ".csv":
        return _read_csv(path, config)
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str, keep_default_na=False)
    return pd.read_xml(path, xpath=config.xml_xpath or "./*", dtype=str)


def _read_csv(path: Path, config: CleanerConfig) -> pd.DataFrame:
    last_err: Exception | None = None
    for enc in config.csv_encodings:
        try:
            return pd.read_csv(
                path, sep=None, engine="python", dtype=str,
                keep_default_na=False, encoding=enc, on_bad_lines="skip",
            )
        except (UnicodeDecodeError, pd.errors.ParserError) as e:
            last_err = e
    raise ValueError(f"Не удалось прочитать CSV {path}: {last_err}")


def clean_text(value, config: CleanerConfig | None = None):
    config = config or CleanerConfig()
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value)
    text = html.unescape(text)
    if config.strip_html:
        text = _TAG_RE.sub(" ", text)
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL_RE.sub("", text)
    text = _WS_RE.sub(" ", text).strip()
    if config.lowercase_values:
        text = text.lower()
    if text.lower() in config.null_values:
        return None
    return text


def normalize_column_name(name: object) -> str:
    name = clean_text(name, CleanerConfig(strip_html=True)) or "column"
    name = name.lower()
    name = re.sub(r"[^\w]+", "_", name, flags=re.UNICODE).strip("_")
    return name or "column"


def _unique_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for col in columns:
        if col in seen:
            seen[col] += 1
            result.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 0
            result.append(col)
    return result


def clean_dataframe(df: pd.DataFrame, config: CleanerConfig | None = None) -> pd.DataFrame:
    config = config or CleanerConfig()
    stats = {"rows_in": len(df), "cols_in": df.shape[1]}

    df = df.copy()

    if config.normalize_columns:
        df.columns = _unique_columns([normalize_column_name(c) for c in df.columns])

    df = df.astype(object).apply(lambda col: col.map(lambda v: clean_text(v, config)))

    df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)

    if len(df):
        empty_ratio = df.isna().mean()
        to_drop = empty_ratio[empty_ratio > config.max_empty_ratio].index
        if len(to_drop):
            logger.info("Удалены почти пустые столбцы: %s", list(to_drop))
            df = df.drop(columns=to_drop)

    if config.drop_duplicates:
        df = df.drop_duplicates()

    df = df.reset_index(drop=True)
    logger.info(
        "Очистка: строк %d -> %d, столбцов %d -> %d",
        stats["rows_in"], len(df), stats["cols_in"], df.shape[1],
    )
    return df


def write_file(df: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_OUTPUT:
        raise ValueError(f"Неподдерживаемый формат вывода: {ext}")
    path.parent.mkdir(parents=True, exist_ok=True)

    if ext == ".csv":
        df.to_csv(path, index=False, encoding="utf-8")
    elif ext == ".xlsx":
        df.to_excel(path, index=False)
    elif ext == ".xml":
        df.to_xml(path, index=False, root_name="records", row_name="record")
    elif ext == ".json":
        df.to_json(path, orient="records", force_ascii=False, indent=2)
    elif ext == ".jsonl":
        df.to_json(path, orient="records", force_ascii=False, lines=True)
    return path


def clean_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    config: CleanerConfig | None = None,
) -> pd.DataFrame:
    config = config or CleanerConfig()
    df = clean_dataframe(read_file(input_path, config), config)
    if output_path:
        write_file(df, output_path)
        logger.info("Сохранено: %s", output_path)
    return df


def main() -> None:
    p = argparse.ArgumentParser(description="Очистка .csv/.xlsx/.xml для поисковой системы")
    p.add_argument("input", help="входной файл (.csv, .xlsx, .xml)")
    p.add_argument("-o", "--output", help="выходной файл (.csv/.xlsx/.xml/.json/.jsonl); по умолчанию <имя>_clean.csv")
    p.add_argument("--max-empty-ratio", type=float, default=0.95,
                   help="удалять столбцы, где доля пустых значений больше (по умолчанию 0.95)")
    p.add_argument("--keep-duplicates", action="store_true", help="не удалять дубликаты")
    p.add_argument("--keep-html", action="store_true", help="не вырезать HTML-теги")
    p.add_argument("--keep-column-names", action="store_true", help="не нормализовать названия столбцов")
    p.add_argument("--lowercase", action="store_true", help="привести значения к нижнему регистру")
    p.add_argument("--xml-xpath", help="xpath записей для нестандартного XML")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s")

    config = CleanerConfig(
        max_empty_ratio=args.max_empty_ratio,
        drop_duplicates=not args.keep_duplicates,
        strip_html=not args.keep_html,
        normalize_columns=not args.keep_column_names,
        lowercase_values=args.lowercase,
        xml_xpath=args.xml_xpath,
    )
    src = Path(args.input)
    out = Path(args.output) if args.output else src.with_name(f"{src.stem}_clean.csv")
    df = clean_file(src, out, config)
    print(f"Готово: {out} ({len(df)} строк, {df.shape[1]} столбцов)")


if __name__ == "__main__":
    main()
