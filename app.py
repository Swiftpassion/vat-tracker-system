import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

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
    """Initializes and caches the Supabase client."""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# --- 2. Helper Functions ---
def convert_df_to_excel(df: pd.DataFrame) -> bytes:
    """Converts a pandas DataFrame to an Excel byte stream.
    
    Args:
        df (pd.DataFrame): The dataframe to convert.
        
    Returns:
        bytes: The Excel file as a byte stream.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Report')
    return output.getvalue()

# --- 3. Main Application UI ---
st.title("📊 ระบบจัดการ VAT คงเหลือ (KIT & S16)")

menu = st.sidebar.radio(
    "เลือกเมนูการทำงาน:",
    [
        "📥 1. อัปโหลดไฟล์ซื้อเข้า (เพิ่ม VAT)", 
        "📤 2. อัปโหลดไฟล์ขายออก (ตัด VAT)", 
        "📈 3. ดูรายงาน / ดาวน์โหลด",
        "✏️ 4. แก้ไขข้อมูลตามวันที่ (Custom UI)"
    ]
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
            
            # 1. & 3. เปลี่ยนค่า Default เป็น " " (Blank)
            edit_df['วิธีชำระเงิน'] = " "
            edit_df['ธนาคารหรือบริษัท'] = " "
            edit_df.rename(columns={'vat_company_enum': 'บริษัท_VAT'}, inplace=True)
            
            st.markdown("### กรุณาตรวจสอบและกรอกข้อมูลการชำระเงิน")
            
            # 2. ย้ายปุ่มมาด้านบน (ก่อนตาราง)
            action_col1, action_col2 = st.columns([1, 4])
            with action_col1:
                is_save_clicked = st.button("💾 บันทึกลงฐานข้อมูล", type="primary", use_container_width=True)
                
            edited_df = st.data_editor(
                edit_df,
                column_config={
                    "วิธีชำระเงิน": st.column_config.SelectboxColumn(
                        "วิธีชำระเงิน", 
                        options=[" ", "เงินสด", "โอนเงิน", "ผ่อนธนาคาร", "เครดิตบริษัท"], 
                        required=True
                    )
                },
                use_container_width=True, hide_index=True
            )
            
            # จัดการ Logic หลังจากปุ่มถูกคลิก
            if is_save_clicked:
                added_count = 0
                for _, row in edited_df.iterrows():
                    imei_val = str(row['Serial No'])
                    
                    try:
                        existing = supabase.table('vat_inventory').select('imei').eq('imei', imei_val).execute()
                        
                        if not existing.data:
                            try:
                                date_obj = datetime.strptime(str(row['วันที่']), "%d/%m/%Y").date()
                            except ValueError:
                                date_obj = datetime.now().date()
                            
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
                    except Exception as e:
                        logger.error(f"Failed to process IMEI {imei_val}: {str(e)}")
                        
                st.success(f"บันทึกข้อมูล VAT ใหม่สำเร็จ {added_count} รายการ!")
        else:
            st.error("ไม่สามารถอ่านไฟล์ได้ หรือ ไม่พบข้อมูล Serial No ในไฟล์นี้")

# --- Menu 2: Upload Sales File ---
elif menu == "📤 2. อัปโหลดไฟล์ขายออก (ตัด VAT)":
    # (คงโค้ดเดิมของคุณไว้)
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

                    try:
                        update_response = supabase.table('vat_inventory').update({
                            "status": "USED",
                            "used_date": used_date,
                            "customer_name": customer
                        }).eq('imei', imei).eq('status', 'AVAILABLE').execute()
                        
                        if update_response.data:
                            updated_count += len(update_response.data)
                    except Exception as e:
                         logger.error(f"Failed to update stock for IMEI {imei}: {str(e)}")
                
                st.info(f"ระบบทำการค้นหาและตัดสต๊อก VAT สำเร็จจำนวน {updated_count} รายการ")

# --- Menu 3: Dashboard & Reports ---
elif menu == "📈 3. ดูรายงาน / ดาวน์โหลด":
    # (คงโค้ดเดิมของคุณไว้)
    st.header("รายงานสถานะ VAT")
    
    response = supabase.table('vat_inventory').select('*').execute()
    all_data = response.data
    
    if not all_data:
        st.warning("ยังไม่มีข้อมูลในระบบฐานข้อมูล")
    else:
        df_report = pd.DataFrame(all_data)
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
        
        display_cols = ["วันที่รับ", "รุ่น", "IMEI", "บริษัท VAT", "สถานะ", "ราคาทุน", "วันที่ขาย", "ลูกค้า"]
        df_report = df_report[display_cols]
        
        tab1, tab2, tab3 = st.tabs(["🟢 VAT คงเหลือ (AVAILABLE)", "🔴 VAT ที่ใช้แล้ว (USED)", "📋 ข้อมูลทั้งหมด"])
        
        with tab1:
            df_avail = df_report[df_report['สถานะ'] == 'AVAILABLE']
            st.dataframe(df_avail, use_container_width=True, hide_index=True)
            st.download_button("ดาวน์โหลด VAT คงเหลือ", data=convert_df_to_excel(df_avail), file_name="vat_available.xlsx")
            
        with tab2:
            df_used = df_report[df_report['สถานะ'] == 'USED']
            st.dataframe(df_used, use_container_width=True, hide_index=True)
            st.download_button("ดาวน์โหลด VAT ที่ใช้แล้ว", data=convert_df_to_excel(df_used), file_name="vat_used.xlsx")
            
        with tab3:
            st.dataframe(df_report, use_container_width=True, hide_index=True)
            st.download_button("ดาวน์โหลดข้อมูลทั้งหมด", data=convert_df_to_excel(df_report), file_name="vat_all.xlsx")

# --- Menu 4: Edit by Date (Custom HTML UI) ---
elif menu == "✏️ 4. แก้ไขข้อมูลตามวันที่ (Custom UI)":
    st.header("✏️ ค้นหาและแก้ไขข้อมูล (Custom Card UI)")
    
    # Filter Controls
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        target_date = st.date_input("เลือกวันที่รับเข้า (Receive Date)")
    with filter_col2:
        status_filter = st.selectbox("เลือกสถานะ", ["ALL", "AVAILABLE", "USED"])
        
    # Fetch Data
    query = supabase.table('vat_inventory').select('*').eq('receive_date', target_date.isoformat())
    if status_filter != "ALL":
        query = query.eq('status', status_filter)
        
    try:
        response = query.execute()
        records: List[Dict[str, Any]] = response.data
    except Exception as e:
        logger.error(f"Failed to fetch records: {str(e)}")
        records = []

    if not records:
        st.info("ไม่พบข้อมูลสำหรับวันที่ระบุ")
    else:
        st.markdown(f"**พบข้อมูลทั้งหมด {len(records)} รายการ**")
        
        # 4.1 Inject Custom CSS สำหรับสร้าง HTML Card สไตล์ Modern 
        st.markdown("""
        <style>
        .custom-card {
            background-color: #f8f9fa;
            border-left: 5px solid #0068c9;
            padding: 16px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            margin-bottom: 12px;
            font-family: sans-serif;
        }
        .card-header { color: #1f2937; font-size: 16px; font-weight: 600; margin-bottom: 8px; }
        .card-body { color: #4b5563; font-size: 14px; margin: 4px 0; }
        .highlight { font-weight: bold; color: #059669; }
        </style>
        """, unsafe_allow_html=True)
        
        # ใช้ Form เพื่อป้องกันหน้าจอรีเฟรชทุกครั้งที่พิมพ์ Input (Performance Optimization)
        with st.form("bulk_edit_form"):
            updated_payload = []
            
            for idx, record in enumerate(records):
                # แสดง Card ข้อมูลด้วย HTML เพียวๆ ไม่ใช้ Table
                html_card = f"""
                <div class="custom-card">
                    <div class="card-header">📱 IMEI: {record.get('imei', '-')} | {record.get('model', '-')}</div>
                    <div class="card-body">🏢 บริษัท: <span class="highlight">{record.get('vat_company', '-')}</span> | 🏭 ผู้จัดจำหน่าย: {record.get('supplier_name', '-')}</div>
                    <div class="card-body">💰 ราคาทุน: ฿{record.get('cost', 0):,.2f} | 📦 สถานะ: {record.get('status', '-')}</div>
                </div>
                """
                st.markdown(html_card, unsafe_allow_html=True)
                
                # Input Controls สำหรับแก้ไข
                inp_col1, inp_col2 = st.columns(2)
                
                with inp_col1:
                    pm_options = [" ", "เงินสด", "โอนเงิน", "ผ่อนธนาคาร", "เครดิตบริษัท"]
                    current_pm = record.get('inbound_payment_method')
                    default_idx = pm_options.index(current_pm) if current_pm in pm_options else 0
                    
                    new_pm = st.selectbox(
                        f"วิธีชำระเงิน (ID: {record['id']})", 
                        options=pm_options, 
                        index=default_idx, 
                        key=f"pm_{record['id']}"
                    )
                
                with inp_col2:
                    current_bank = record.get('inbound_bank_or_company')
                    new_bank = st.text_input(
                        f"ธนาคาร/บริษัท (ID: {record['id']})", 
                        value=current_bank if current_bank else " ", 
                        key=f"bank_{record['id']}"
                    )
                
                updated_payload.append({
                    "id": record['id'],
                    "inbound_payment_method": new_pm,
                    "inbound_bank_or_company": new_bank
                })
                
                st.markdown("<hr style='margin: 10px 0 20px 0; border-top: 1px solid #e5e7eb;'/>", unsafe_allow_html=True)
            
            # Submit Button ภายใน Form
            submit_update = st.form_submit_button("💾 อัปเดตข้อมูลทั้งหมด", type="primary")
            
            if submit_update:
                with st.spinner("กำลังบันทึกข้อมูลลงฐานข้อมูล..."):
                    success_count = 0
                    for item in updated_payload:
                        try:
                            supabase.table('vat_inventory').update({
                                "inbound_payment_method": item["inbound_payment_method"],
                                "inbound_bank_or_company": item["inbound_bank_or_company"]
                            }).eq('id', item["id"]).execute()
                            success_count += 1
                        except Exception as e:
                            logger.error(f"Failed to update ID {item['id']}: {str(e)}")
                            
                    st.success(f"✅ อัปเดตข้อมูลสำเร็จ {success_count} รายการ!")
                    st.rerun()  # รีโหลดหน้าจอเพื่อให้แสดงข้อมูลล่าสุด
