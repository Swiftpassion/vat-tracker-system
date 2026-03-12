import io
import logging
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
import streamlit as st
from supabase import create_client, Client

from data_processor import process_purchase_file, process_sales_file

# --- 1. System Setup & Configuration ---
st.set_page_config(page_title="VAT Tracker (KIT & S16)", page_icon="📊", layout="wide")
logger = logging.getLogger(__name__)

# --- Apply TH Sarabun Font ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] {
    font-family: 'Sarabun', sans-serif !important;
    font-size: 16px;
}
.custom-card {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-left: 5px solid #0068c9;
    padding: 16px;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    margin-bottom: 12px;
}
.card-header { color: #1f2937; font-size: 18px; font-weight: 600; margin-bottom: 8px; }
.card-body { color: #4b5563; font-size: 15px; margin: 4px 0; }
.highlight { font-weight: 600; color: #059669; }
.highlight-blue { font-weight: 600; color: #2563eb; }
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def init_supabase() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_supabase()

def parse_thai_date(date_str: str) -> str:
    """Converts DD/MM/YYYY string (Thai BE or AD) to YYYY-MM-DD for Database."""
    try:
        parts = str(date_str).strip().split('/')
        if len(parts) == 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            if year > 2500:
                year -= 543
            return f"{year:04d}-{month:02d}-{day:02d}"
    except Exception:
        pass
    return datetime.now().date().isoformat()

# --- 3. Main Application UI ---
st.title("📊 ระบบจัดการ VAT คงเหลือ (KIT & S16)")

menu = st.sidebar.radio(
    "เลือกเมนูการทำงาน:",
    ["📥 1. อัปโหลดไฟล์ซื้อเข้า (เพิ่ม VAT)", 
     "📤 2. อัปโหลดไฟล์ขายออก (ตัด VAT)", 
     "📈 3. ดูรายงาน / ดาวน์โหลด",
     "✏️ 4. ค้นหาและแก้ไขข้อมูล"]
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
if menu == "📤 2. อัปโหลดไฟล์ขายออก (ตัด VAT)":
    st.header("อัปโหลดไฟล์ขายออก เพื่อตัดสต๊อก VAT")
    sales_file = st.file_uploader("ลากไฟล์ Excel/CSV ขายออก", type=['csv', 'xls', 'xlsx'])
    
    if sales_file is not None:
        with st.spinner('กำลังประมวลผลไฟล์...'):
            df_sales = process_sales_file(sales_file.read())
            
        if df_sales is not None:
            st.success(f"พบรายการขาย {len(df_sales)} รายการ")
            
            if st.button("✂️ ยืนยันการตัดสต๊อก VAT", type="primary"):
                updated_count = 0
                for _, row in df_sales.iterrows():
                    imei = str(row['Serial No'])
                    customer = str(row.get('ชื่อลูกค้า', '-'))
                    sales_price = float(row.get('ยอดขายที่สกัดได้', 0.0))
                    used_date = parse_thai_date(row.get('วันที่', ''))

                    try:
                        resp = supabase.table('vat_inventory').update({
                            "status": "USED",
                            "used_date": used_date,
                            "customer_name": customer,
                            "sales_price": sales_price
                        }).eq('imei', imei).eq('status', 'AVAILABLE').execute()
                        if resp.data:
                            updated_count += len(resp.data)
                    except Exception as e:
                         logger.error(f"Error updating IMEI {imei}: {e}")
                
                st.info(f"ตัดสต๊อก VAT สำเร็จ {updated_count} รายการ")
                
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

# --- Menu 4: Search and Edit (New UI) ---
elif menu == "✏️ 4. ค้นหาและแก้ไขข้อมูล":
    st.header("🔍 ค้นหาและแก้ไขข้อมูล")
    
    col_search, col_date, col_status = st.columns(3)
    with col_search:
        search_type = st.radio("ค้นหา", ["การซื้อเข้า", "การขายออก"], horizontal=True)
    with col_date:
        target_date = st.date_input("เลือกวันที่")
    with col_status:
        status_map = {"ทั้งหมด": "ALL", "ยังไม่ขาย": "AVAILABLE", "ขายแล้ว": "USED"}
        status_filter = st.selectbox("เลือกสถานะ", list(status_map.keys()))

    # Build DB Query
    date_field = 'receive_date' if search_type == "การซื้อเข้า" else 'used_date'
    query = supabase.table('vat_inventory').select('*').eq(date_field, target_date.isoformat())
    
    if status_map[status_filter] != "ALL":
        query = query.eq('status', status_map[status_filter])
        
    response = query.execute()
    records: List[Dict[str, Any]] = response.data

    if not records:
        st.warning(f"ไม่พบข้อมูล {search_type} ในวันที่ {target_date.strftime('%d/%m/%Y')}")
    else:
        st.markdown(f"**พบข้อมูลทั้งหมด {len(records)} รายการ**")
        
        with st.form("edit_form"):
            payload = []
            
            for rec in records:
                if search_type == "การซื้อเข้า":
                    # HTML Card แบบ การซื้อเข้า
                    st.markdown(f"""
                    <div class="custom-card">
                        <div class="card-header">🏷️ IMEI: {rec.get('imei')} | {rec.get('model')}</div>
                        <div class="card-body">📅 วันที่: {rec.get('receive_date')} | 🏭 ผู้จำหน่าย: {rec.get('supplier_name')} | 🏢 <span class="highlight-blue">{rec.get('vat_company')}</span></div>
                        <div class="card-body">💰 ราคาทุน: <span class="highlight">฿{rec.get('cost', 0):,.2f}</span></div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        opts = [" ", "เงินสด", "โอนเงิน", "ผ่อนธนาคาร", "เครดิตบริษัท"]
                        curr_pm = rec.get('inbound_payment_method', " ")
                        new_pm = st.selectbox(f"วิธีการชำระเงิน (ID: {rec['id']})", opts, index=opts.index(curr_pm) if curr_pm in opts else 0, key=f"p_pm_{rec['id']}")
                    with c2:
                        curr_bank = rec.get('inbound_bank_or_company', "")
                        new_bank = st.text_input(f"ธนาคารหรือบริษัท (ID: {rec['id']})", value=curr_bank, key=f"p_b_{rec['id']}")
                        
                    payload.append({"id": rec['id'], "type": "in", "inbound_payment_method": new_pm, "inbound_bank_or_company": new_bank})

                else:
                    # HTML Card แบบ การขายออก
                    st.markdown(f"""
                    <div class="custom-card" style="border-left-color: #059669;">
                        <div class="card-header">🏷️ IMEI: {rec.get('imei')} | {rec.get('model')}</div>
                        <div class="card-body">📅 วันที่: {rec.get('used_date')} | 👤 ลูกค้า: {rec.get('customer_name')} | 🏢 <span class="highlight-blue">{rec.get('vat_company')}</span></div>
                        <div class="card-body">💸 ราคาขาย: <span class="highlight">฿{rec.get('sales_price', 0):,.2f}</span></div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        opts = [" ", "เงินสด", "โอนเงิน", "ผ่อนธนาคาร", "เครดิตบริษัท"]
                        curr_pm = rec.get('outbound_payment_method', " ")
                        new_pm = st.selectbox(f"วิธีการชำระเงิน (ID: {rec['id']})", opts, index=opts.index(curr_pm) if curr_pm in opts else 0, key=f"s_pm_{rec['id']}")
                    with c2:
                        comp_opts = [" ", "บริษัท KIT", "บริษัท S16"]
                        curr_comp = rec.get('outbound_receiving_company', " ")
                        new_comp = st.selectbox(f"บริษัทที่รับเงิน (ID: {rec['id']})", comp_opts, index=comp_opts.index(curr_comp) if curr_comp in comp_opts else 0, key=f"s_c_{rec['id']}")
                        
                    payload.append({"id": rec['id'], "type": "out", "outbound_payment_method": new_pm, "outbound_receiving_company": new_comp})
                
                st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

            if st.form_submit_button("💾 บันทึกการแก้ไข", type="primary"):
                with st.spinner("กำลังอัปเดต..."):
                    for item in payload:
                        if item["type"] == "in":
                            supabase.table('vat_inventory').update({
                                "inbound_payment_method": item["inbound_payment_method"],
                                "inbound_bank_or_company": item["inbound_bank_or_company"]
                            }).eq('id', item["id"]).execute()
                        else:
                            supabase.table('vat_inventory').update({
                                "outbound_payment_method": item["outbound_payment_method"],
                                "outbound_receiving_company": item["outbound_receiving_company"]
                            }).eq('id', item["id"]).execute()
                    st.success("✅ อัปเดตข้อมูลเรียบร้อยแล้ว!")
                    st.rerun()
