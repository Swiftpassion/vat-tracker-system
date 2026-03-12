import io
import logging
import re
from typing import Any, Dict, Optional

import pandas as pd

from models import VatCompany

# Initialize logging
logger = logging.getLogger(__name__)


def extract_vat_company(supplier_name: Any) -> VatCompany:
    """Extracts VAT company from supplier name using Regex."""
    if pd.isna(supplier_name) or not isinstance(supplier_name, str):
        return VatCompany.NONE

    # Remove all spaces and convert to uppercase
    text = supplier_name.upper().replace(" ", "")

    if re.search(r'/VATS16', text):
        return VatCompany.S16
    elif re.search(r'/VATKIT', text):
        return VatCompany.KIT
    elif re.search(r'/N', text):
        return VatCompany.NONE

    return VatCompany.NONE


def clean_serial_no(serial_series: pd.Series) -> pd.Series:
    """Removes trailing '.0' and cleans the Serial Number column."""
    return (
        serial_series.astype(str)
        .str.replace(r'\.0$', '', regex=True)
        .str.strip()
        .replace('nan', '')
    )


def load_pos_file(file_content: bytes) -> Optional[pd.DataFrame]:
    """
    ฟังก์ชันสุดแกร่ง: ค้นหาแถวที่มีคำว่า 'Serial No' อัตโนมัติ 
    รองรับภาษาไทยทุกรูปแบบ (UTF-8, TIS-620, CP874)
    และดึงวันที่จากแถวก่อนหน้า (ถ้ามี) เพิ่มเป็นคอลัมน์ 'วันที่'
    """
    encodings = ['utf-8', 'tis-620', 'cp874']
    
    # ------------------- กรณีไฟล์ CSV/Text -------------------
    for enc in encodings:
        try:
            text_data = file_content.decode(enc)
            lines = text_data.splitlines()
            
            header_idx = -1
            date_value = None
            for i, line in enumerate(lines):
                if 'Serial No' in line:
                    header_idx = i
                    # หาวันที่จากบรรทัดก่อนหน้า
                    if i > 0 and 'วันที่' in lines[i-1]:
                        parts = lines[i-1].replace(',', '\t').split('\t')
                        for part in parts:
                            part = part.strip()
                            # รูปแบบวันที่ DD/MM/YYYY
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

    # ------------------- กรณีไฟล์ Excel -------------------
    try:
        excel_file = pd.ExcelFile(io.BytesIO(file_content))
        # อ่านชีตแรกโดยไม่กำหนด header เพื่อหาบรรทัดที่มี 'Serial No'
        df_temp = pd.read_excel(excel_file, header=None, sheet_name=0)
        header_idx = -1
        date_value = None
        for i, row in df_temp.iterrows():
            if 'Serial No' in [str(val).strip() for val in row.values]:
                header_idx = i
                # ตรวจสอบแถวก่อนหน้าว่ามีวันที่หรือไม่
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
    df = load_pos_file(file_content)
    
    if df is None:
        logger.error("Failed to read purchase file.")
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
        # ลบเครื่องหมายคอมม่าในราคา (ถ้ามี) แล้วแปลงเป็นตัวเลข
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
    df = load_pos_file(file_content)
    
    if df is None:
        logger.error("Failed to read sales file.")
        return None

    if 'Serial No' in df.columns:
        df['Serial No'] = clean_serial_no(df['Serial No'])
        df = df[df['Serial No'] != '']

    return df


