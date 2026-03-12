import io
import logging
import re
from typing import Any, Dict, List, Optional

import pandas as pd

from models import VatCompany

# Initialize logging context
logger = logging.getLogger(__name__)


def extract_vat_company(supplier_name: Any) -> VatCompany:
    """Extracts VAT company from supplier name using Regex.
    
    Args:
        supplier_name (Any): The name of the supplier.
        
    Returns:
        VatCompany: The matched VAT company enum (KIT, S16, or NONE).
    """
    if pd.isna(supplier_name) or not isinstance(supplier_name, str):
        return VatCompany.NONE

    # Remove all spaces and convert to uppercase for robust matching
    text = supplier_name.upper().replace(" ", "")

    # Match /KIT, /S16 directly
    if re.search(r'/S16', text):
        return VatCompany.S16
    elif re.search(r'/KIT', text):
        return VatCompany.KIT
    elif re.search(r'/N', text):
        return VatCompany.NONE

    return VatCompany.NONE


def clean_serial_no(serial_series: pd.Series) -> pd.Series:
    """Removes trailing '.0' and cleans the Serial Number column.
    
    Args:
        serial_series (pd.Series): The pandas Series containing raw serial numbers.
        
    Returns:
        pd.Series: The cleaned serial number series.
    """
    return (
        serial_series.astype(str)
        .str.replace(r'\.0$', '', regex=True)
        .str.strip()
        .replace('nan', '')
    )


def load_pos_file(file_content: bytes) -> Optional[pd.DataFrame]:
    """Finds the 'Serial No' row automatically across encodings and extracts data.
    
    Also attempts to extract the date from the preceding row if available.
    Supports CSV, Text, and Excel file formats.
    
    Args:
        file_content (bytes): The raw bytes of the uploaded file.
        
    Returns:
        Optional[pd.DataFrame]: The extracted DataFrame with a 'วันที่' column, or None if failed.
    """
    encodings = ['utf-8', 'tis-620', 'cp874']
    
    # ------------------- CSV/Text Case -------------------
    for enc in encodings:
        try:
            text_data = file_content.decode(enc)
            lines = text_data.splitlines()
            
            header_idx = -1
            date_value = None
            for i, line in enumerate(lines):
                # We need to ensure we are matching the actual column, not the report title.
                cells = [cell.strip() for cell in line.replace('\t', ',').split(',')]
                if 'Serial No' in cells:
                    header_idx = i
                    # Find date from the previous line
                    if i > 0 and 'วันที่' in lines[i-1]:
                        parts = lines[i-1].replace(',', '\t').split('\t')
                        for part in parts:
                            part = part.strip()
                            # Format DD/MM/YYYY
                            if part and '/' in part and len(part.split('/')) == 3:
                                date_value = part
                                break
                    break
            
            if header_idx != -1:
                sep = '\t' if '\t' in lines[header_idx] else ','
                df = pd.read_csv(io.StringIO(text_data), header=header_idx, sep=sep)
                if date_value:
                    df['วันที่'] = date_value
                return df
        except Exception:
            continue

    # ------------------- Excel Case -------------------
    try:
        excel_file = pd.ExcelFile(io.BytesIO(file_content))
        df_temp = pd.read_excel(excel_file, header=None, sheet_name=0)
        
        header_idx = -1
        date_value = None
        for i, row in df_temp.iterrows():
            if 'Serial No' in [str(val).strip() for val in row.values]:
                header_idx = i
                # Check previous row for date
                if i > 0:
                    prev_row = df_temp.iloc[i-1]
                    for val in prev_row.values:
                        val_str = str(val).strip()
                        if '/' in val_str and len(val_str.split('/')) == 3:
                            date_value = val_str
                            break
                break
        
        if header_idx != -1:
            df = pd.read_excel(excel_file, header=header_idx, sheet_name=0)
            if date_value:
                df['วันที่'] = date_value
            return df
    except Exception as e:
        logger.exception("Error reading Excel file: %s", e)
    
    return None


def process_purchase_file(file_content: bytes) -> Optional[pd.DataFrame]:
    """Processes the purchase inbound file and extracts the required fields.
    
    Merges continuation rows if the document number is empty.
    
    Args:
        file_content (bytes): Raw bytes of the uploaded file.
        
    Returns:
        Optional[pd.DataFrame]: Cleaned DataFrame ready for DB insertion, or None.
    """
    df = load_pos_file(file_content)
    
    if df is None:
        logger.error("Failed to read purchase file.")
        return None

    cleaned_rows: List[Dict[str, Any]] = []
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
        # Remove commas and convert to numeric
        df_cleaned['ราคาซื้อ'] = df_cleaned['ราคาซื้อ'].astype(str).str.replace(',', '')
        df_cleaned['ราคาซื้อ'] = pd.to_numeric(df_cleaned['ราคาซื้อ'], errors='coerce').fillna(0.0)

    # Apply Regex to find VAT Company
    if 'ชื่อผู้จำหน่าย' in df_cleaned.columns:
        df_cleaned['vat_company_enum'] = df_cleaned['ชื่อผู้จำหน่าย'].apply(extract_vat_company)

    # Filter out rows without a valid Serial Number
    if 'Serial No' in df_cleaned.columns:
        df_cleaned = df_cleaned[df_cleaned['Serial No'] != '']

    return df_cleaned


def process_sales_file(file_content: bytes) -> Optional[pd.DataFrame]:
    """Processes the sales outbound file, extracting Serial No, Customer, and Sales Price.
    
    Args:
        file_content (bytes): Raw bytes of the uploaded file.
        
    Returns:
        Optional[pd.DataFrame]: Cleaned DataFrame ready for status update, or None.
    """
    df = load_pos_file(file_content)
    
    if df is None:
        logger.error("Failed to read sales file.")
        return None

    # Clean Serial Numbers
    if 'Serial No' in df.columns:
        df['Serial No'] = clean_serial_no(df['Serial No'])
        df = df[df['Serial No'] != '']

    # Identify the sales price column dynamically
    price_col = None
    for col in df.columns:
        # Searching for typical POS column names indicating money received/sales amount
        if any(keyword in str(col) for keyword in ['ราคาขาย', 'จำนวนเงิน', 'ยอดเงิน', 'มูลค่า']):
            price_col = col
            break
            
    if price_col:
        # Remove commas and convert to float
        df['ยอดขายที่สกัดได้'] = df[price_col].astype(str).str.replace(',', '')
        df['ยอดขายที่สกัดได้'] = pd.to_numeric(df['ยอดขายที่สกัดได้'], errors='coerce').fillna(0.0)
    else:
        df['ยอดขายที่สกัดได้'] = 0.0

    return df
