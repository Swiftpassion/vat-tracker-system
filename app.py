import io
import logging
from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st
from supabase import create_client, Client

from data_processor import process_purchase_file, process_sales_file

# --- 1. System Setup & Configuration ---
st.set_page_config(page_title="VAT Tracker (KIT & S16)", page_icon="📊", layout="wide")
logger = logging.getLogger(__name__)

# Initialize Supabase API Client
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# --- 2. Helper Functions ---
def convert_df_to_excel(df: pd.DataFrame) -> bytes:
    """Converts a pandas DataFrame to an Excel byte stream."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Report')
    return output.getvalue()

# --- 3. Main Application UI ---
st.title("📊 ระบบจัดการ VAT คงเหลือ (KIT & S16)")

menu = st.sidebar.radio(
    "เลือกเมนูการทำงาน:",
    ["📥 1. อัปโหลดไฟล์ซื้อเข้า (เพิ่ม VAT)", 
     "📤 2. อัปโหลดไฟล์ขายออก (ตัด VAT)", 
     "📈 3. ดูรายงาน / ดาวน์โหลด"]
)

# --- Menu 1: Upload Purchase File ---
if menu == "📥 1. อัปโหลดไฟล์ซื้อเข้า (เพิ่ม VAT)":
    st.header("อัปโหลดไฟล์ซื้อเข้า เพื่อบันทึก VAT")
    purchase_file = st.file_uploader("ลากไฟล์ Excel/CSV ซื้อเข้า มาวางที่นี่", type=['csv', 'xls', 'xlsx'])
    
    if purchase_file is not None:
        with st.spinner('กำลังประมวลผลไฟล์...'):
            file_bytes = purchase_file.read()
            df_cleaned = process_purchase_file(file_bytes)
            
        if df_cleaned is not None:
            st.success(f"อ่านข้อมูลสำเร็จ! พบรายการที่มี Serial No จำนวน {len(df_cleaned)} รายการ")
            
            display_cols = ['วันที่', 'Serial No', 'ชื่อสินค้า', 'ชื่อผู้จำหน่าย', 'vat_company_enum', 'ราคาซื้อ']
            edit_df = df_cleaned[display_cols].copy()
            edit_df['วิธีชำระเงิน'] = "เงินสด"
            edit_df['ธนาคารหรือบริษัท'] = "-"
            edit_df.rename(columns={'vat_company_enum': 'บริษัท_VAT'}, inplace=True)
            
            st.markdown("### กรุณาตรวจสอบและกรอกข้อมูลการชำระเงิน")
            edited_df = st.data_editor(
                edit_df,
                column_config={
                    "วิธีชำระเงิน": st.column_config.SelectboxColumn(
                        "วิธีชำระเงิน", options=["เงินสด", "โอนเงิน", "ผ่อนธนาคาร", "เครดิตบริษัท"], required=True
                    )
                },
                use_container_width=True, hide_index=True
            )
            
            if st.button("💾 บันทึกลงฐานข้อมูล", type="primary"):
                added_count = 0
                for _, row in edited_df.iterrows():
                    imei_val = str(row['Serial No'])
                    # Check duplicate via API
                    existing = supabase.table('vat_inventory').select('imei').eq('imei', imei_val).execute()
                    
                    if not existing.data:
                        try:
                            date_obj = datetime.strptime(str(row['วันที่']), "%d/%m/%Y").date()
                        except ValueError:
                            date_obj = datetime.now().date()
                        
                        # Handle Enum conversion if necessary
                        vat_comp = row['บริษัท_VAT'].value if hasattr(row['บริษัท_VAT'], 'value') else str(row['บริษัท_VAT']).replace("VatCompany.", "")

                        insert_data = {
                            "receive_date": date_obj.isoformat(),
                            "model": str(row['ชื่อสินค้า']),
                            "imei": imei_val,
                            "supplier_name": str(row['ชื่อผู้จำหน่าย']),
                            "vat_company": vat_comp,
                            "cost": float(row['ราคาซื้อ']),
                            "inbound_payment_method": str(row['วิธีชำระเงิน']),
                            "inbound_bank_or_company": str(row['ธนาคารหรือบริษัท']),
                            "status": "AVAILABLE"
                        }
                        supabase.table('vat_inventory').insert(insert_data).execute()
                        added_count += 1
                
                st.success(f"บันทึกข้อมูล VAT ใหม่สำเร็จ {added_count} รายการ!")
        else:
            st.error("ไม่สามารถอ่านไฟล์ได้ หรือ ไม่พบข้อมูล Serial No ในไฟล์นี้")

# --- Menu 2: Upload Sales File ---
elif menu == "📤 2. อัปโหลดไฟล์ขายออก (ตัด VAT)":
    st.header("อัปโหลดไฟล์ขายออก เพื่อตัดสต๊อก VAT")
    sales_file = st.file_uploader("ลากไฟล์ Excel/CSV ขายออก มาวางที่นี่", type=['csv', 'xls', 'xlsx'])
    
    if sales_file is not None:
        with st.spinner('กำลังประมวลผลไฟล์...'):
            file_bytes = sales_file.read()
            df_sales = process_sales_file(file_bytes)
            
        if df_sales is not None:
            st.success(f"อ่านข้อมูลสำเร็จ! พบรายการขาย {len(df_sales)} รายการ")
            st.dataframe(df_sales[['วันที่', 'Serial No', 'ชื่อลูกค้า']].head(), use_container_width=True)
            
            if st.button("✂️ ยืนยันการตัดสต๊อก VAT", type="primary"):
                updated_count = 0
                for _, row in df_sales.iterrows():
                    imei = str(row['Serial No'])
                    customer = str(row['ชื่อลูกค้า'])
                    try:
                        used_date = datetime.strptime(str(row['วันที่']), "%d/%m/%Y").date().isoformat()
                    except ValueError:
                        used_date = datetime.now().date().isoformat()

                    # Update via API where status is AVAILABLE
                    update_response = supabase.table('vat_inventory').update({
                        "status": "USED",
                        "used_date": used_date,
                        "customer_name": customer
                    }).eq('imei', imei).eq('status', 'AVAILABLE').execute()
                    
                    if update_response.data:
                        updated_count += len(update_response.data)
                
                st.info(f"ระบบทำการค้นหาและตัดสต๊อก VAT สำเร็จจำนวน {updated_count} รายการ")

# --- Menu 3: Dashboard & Reports ---
elif menu == "📈 3. ดูรายงาน / ดาวน์โหลด":
    st.header("รายงานสถานะ VAT")
    
    # Query all data via API
    response = supabase.table('vat_inventory').select('*').execute()
    all_data = response.data
    
    if not all_data:
        st.warning("ยังไม่มีข้อมูลในระบบฐานข้อมูล")
    else:
        df_report = pd.DataFrame(all_data)
        # Rename columns to Thai for display
        df_report.rename(columns={
            "receive_date": "วันที่รับ",
            "model": "รุ่น",
            "imei": "IMEI",
            "vat_company": "บริษัท VAT",
            "status": "สถานะ",
            "cost": "ราคาทุน",
            "used_date": "วันที่ขาย",
            "customer_name": "ลูกค้า"
        }, inplace=True)
        
        # Select only needed columns
        display_cols = ["วันที่รับ", "รุ่น", "IMEI", "บริษัท VAT", "สถานะ", "ราคาทุน", "วันที่ขาย", "ลูกค้า"]
        df_report = df_report[display_cols]
        
        tab1, tab2, tab3 = st.tabs(["🟢 VAT คงเหลือ (AVAILABLE)", "🔴 VAT ที่ใช้แล้ว (USED)", "📋 ข้อมูลทั้งหมด"])
        
        with tab1:
            df_avail = df_report[df_report['สถานะ'] == 'AVAILABLE']
            st.dataframe(df_avail, use_container_width=True, hide_index=True)
            st.download_button("ดาวน์โหลด VAT คงเหลือ (Excel)", data=convert_df_to_excel(df_avail), file_name="vat_available.xlsx")
            
        with tab2:
            df_used = df_report[df_report['สถานะ'] == 'USED']
            st.dataframe(df_used, use_container_width=True, hide_index=True)
            st.download_button("ดาวน์โหลด VAT ที่ใช้แล้ว (Excel)", data=convert_df_to_excel(df_used), file_name="vat_used.xlsx")
            
        with tab3:
            st.dataframe(df_report, use_container_width=True, hide_index=True)
            st.download_button("ดาวน์โหลดข้อมูลทั้งหมด (Excel)", data=convert_df_to_excel(df_report), file_name="vat_all.xlsx")
