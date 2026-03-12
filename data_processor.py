import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from models import VatCompany

# Initialize logging
logger = logging.getLogger(__name__)


def extract_vat_company(supplier_name: Any) -> VatCompany:
    """Extracts VAT company from supplier name using Regex.

    Matches patterns like '/Vat S16', '/Vat Kit', or '/N' ignoring case and spaces.

    Args:
        supplier_name: The raw string of the supplier name.

    Returns:
        VatCompany: The matched enum value (S16, KIT, or NONE).
    """
    if pd.isna(supplier_name) or not isinstance(supplier_name, str):
        return VatCompany.NONE

    # Remove all spaces and convert to uppercase for easier regex matching
    text = supplier_name.upper().replace(" ", "")

    if re.search(r'/VATS16', text):
        return VatCompany.S16
    elif re.search(r'/VATKIT', text):
        return VatCompany.KIT
    elif re.search(r'/N', text):
        return VatCompany.NONE

    return VatCompany.NONE


def clean_serial_no(serial_series: pd.Series) -> pd.Series:
    """Removes trailing '.0' and cleans the Serial Number column.

    Args:
        serial_series: A pandas Series containing serial numbers.

    Returns:
        pd.Series: The cleaned serial numbers as strings.
    """
    return (
        serial_series.astype(str)
        .str.replace(r'\.0$', '', regex=True)
        .str.strip()
        .replace('nan', '')
    )


def process_purchase_file(file_content: bytes) -> Optional[pd.DataFrame]:
    """Reads and cleans the inbound purchase file.

    Handles the merging of multi-line product/supplier names and extracts VAT company.

    Args:
        file_content: Raw bytes of the uploaded file.

    Returns:
        pd.DataFrame: Cleaned data ready for preview/database insertion, or None if failed.
    """
    try:
        try:
            df = pd.read_csv(io.BytesIO(file_content), header=5, encoding='utf-8')
        except Exception:
            df = pd.read_excel(io.BytesIO(file_content), header=5)
    except Exception as e:
        logger.error("Failed to read purchase file: %s", e)
        return None

    cleaned_rows = []
    last_row: Optional[Dict[str, Any]] = None

    for _, row in df.iterrows():
        # Check if the document number is valid (indicates a primary row)
        doc_no = row.get('เลขที่เอกสาร')
        if pd.notna(doc_no) and str(doc_no).strip() != '':
            if last_row is not None:
                cleaned_rows.append(last_row)
            last_row = row.to_dict()
        else:
            # This is a continuation row, merge text fields
            if last_row is not None:
                prod_name = row.get('ชื่อสินค้า')
                if pd.notna(prod_name) and str(prod_name).strip() != '':
                    last_row['ชื่อสินค้า'] = str(last_row.get('ชื่อสินค้า', '')).strip() + ' ' + str(prod_name).strip()
                
                sup_name = row.get('ชื่อผู้จำหน่าย')
                if pd.notna(sup_name) and str(sup_name).strip() != '':
                    last_row['ชื่อผู้จำหน่าย'] = str(last_row.get('ชื่อผู้จำหน่าย', '')).strip() + ' ' + str(sup_name).strip()

    if last_row is not None:
        cleaned_rows.append(last_row)

    if not cleaned_rows:
        return None

    df_cleaned = pd.DataFrame(cleaned_rows)
    
    # Apply Data Cleaning
    if 'Serial No' in df_cleaned.columns:
        df_cleaned['Serial No'] = clean_serial_no(df_cleaned['Serial No'])
    
    if 'ราคาซื้อ' in df_cleaned.columns:
        df_cleaned['ราคาซื้อ'] = pd.to_numeric(df_cleaned['ราคาซื้อ'], errors='coerce').fillna(0.0)

    # Apply Regex to find VAT Company
    if 'ชื่อผู้จำหน่าย' in df_cleaned.columns:
        df_cleaned['vat_company_enum'] = df_cleaned['ชื่อผู้จำหน่าย'].apply(extract_vat_company)

    # Filter out rows without a valid Serial Number
    df_cleaned = df_cleaned[df_cleaned['Serial No'] != '']

    return df_cleaned


def process_sales_file(file_content: bytes) -> Optional[pd.DataFrame]:
    """Reads and cleans the outbound sales file to extract sold IMEI and customers.

    Args:
        file_content: Raw bytes of the uploaded sales file.

    Returns:
        pd.DataFrame: Cleaned sales data, or None if failed.
    """
    try:
        try:
            df = pd.read_csv(io.BytesIO(file_content), header=5, encoding='utf-8')
        except Exception:
            df = pd.read_excel(io.BytesIO(file_content), header=5)
    except Exception as e:
        logger.error("Failed to read sales file: %s", e)
        return None

    if 'Serial No' in df.columns:
        df['Serial No'] = clean_serial_no(df['Serial No'])
        df = df[df['Serial No'] != '']

    return df