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

# --- Apply TH Sarabun Font ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] {
    font-family: 'Sarabun', sans-serif !important;
    font-size: 16px;
}
.stAlert { font-family: 'Sarabun', sans-serif !important; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def init_supabase() -> Client:
    """Initializes and caches the Supabase client."""
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
    [
        "📥 1. อัปโหลดไฟล์ซื้อเข้า", 
        "📤 2. อัปโหลดไฟล์ขายออก", 
        "📈 3. ดูรายงาน / ดาวน์โหลด",
        "✏️ 4. ค้นหาและแก้ไขข้อมูล"
    ]
)

# ==========================================
# Menu 1: Upload Purchase File
# ==========================================
if menu == "📥 1. อัปโหลดไฟล์ซื้อเข้า":
    st.header("อัปโหลดไฟล์ซื้อเข้า")
    purchase_file = st.file_uploader("ลากไฟล์ Excel/CSV ซื้อเข้า มาวางที่นี่", type=['csv', 'xls', 'xlsx'])
    
    if purchase_file is not None:
        with st.spinner('กำลังประมวลผลไฟล์...'):
            df_cleaned = process_purchase_file(purchase_file.read())
            
        if df_cleaned is not None:
            # 3. แจ้งเตือนเมื่ออ่านไฟล์สำเร็จ
            st.info(f"✅ อ่านไฟล์สำเร็จ! พบรายการสินค้า {len(df_cleaned)} รายการ กรุณาตรวจสอบและบันทึกข้อมูล")
            
            display_cols = ['วันที่', 'Serial No', 'ชื่อสินค้า', 'ชื่อผู้จำหน่าย', 'vat_company_enum', 'ราคาซื้อ']
            edit_df = df_cleaned[display_cols].copy()
            edit_df['วิธีชำระเงิน'] = " "
            edit_df['ธนาคารหรือบริษัท'] = " "
            edit_df.rename(columns={'vat_company_enum': 'บริษัท_VAT'}, inplace=True)
            
            action_col1, action_col2 = st.columns([1, 4])
            with action_col1:
                is_save_clicked = st.button("💾 บันทึกลงฐานข้อมูล", type="primary", use_container_width=True)
                
            edited_df = st.data_editor(
                edit_df,
                column_config={
                    "วิธีชำระเงิน": st.column_config.SelectboxColumn(
                        "วิธีชำระเงิน", 
                        options=[" ", "เงินสด", "โอนเงิน", "ผ่อนธนาคาร", "เครดิตบริษัท"], 
                    )
                },
                use_container_width=True, hide_index=True
            )
            
            if is_save_clicked:
                with st.spinner('กำลังบันทึกลงฐานข้อมูล...'):
                    added_count = 0
                    for _, row in edited_df.iterrows():
                        imei_val = str(row['Serial No'])
                        try:
                            existing = supabase.table('vat_inventory').select('imei').eq('imei', imei_val).execute()
                            if not existing.data:
                                date_obj = parse_thai_date(row['วันที่'])
                                vat_comp = row['บริษัท_VAT'].value if hasattr(row['บริษัท_VAT'], 'value') else str(row['บริษัท_VAT']).replace("VatCompany.", "")
                                insert_data = {
                                    "receive_date": date_obj,
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
                            
                    # 3. แจ้งเตือนเมื่อบันทึกฐานข้อมูลสำเร็จ
                    st.success(f"🎉 บันทึกข้อมูล VAT ใหม่ลงฐานข้อมูลสำเร็จจำนวน {added_count} รายการ!")

# ==========================================
# Menu 2: Upload Sales File
# ==========================================
elif menu == "📤 2. อัปโหลดไฟล์ขายออก":
    st.header("อัปโหลดไฟล์ขายออก")
    sales_file = st.file_uploader("ลากไฟล์ Excel/CSV ขายออก มาวางที่นี่", type=['csv', 'xls', 'xlsx'])
    
    if sales_file is not None:
        with st.spinner('กำลังประมวลผลไฟล์...'):
            df_sales = process_sales_file(sales_file.read())
            
        if df_sales is not None:
            # 2. ทำ Preview ตารางข้อมูลก่อนอัปโหลด
            st.write("### 📋 พรีวิวข้อมูลที่จะทำการตัดสต๊อก")
            st.dataframe(df_sales, use_container_width=True)
            
            st.info(f"✅ ระบบพร้อมตัดสต๊อกจำนวน {len(df_sales)} รายการ กรุณากดปุ่มยืนยันด้านล่าง")
            
            if st.button("✂️ ยืนยันการตัดสต๊อก VAT ลงฐานข้อมูล", type="primary"):
                with st.spinner("กำลังทำการอัปเดตฐานข้อมูล..."):
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
                    
                    # 3. แจ้งเตือนเมื่ออัปโหลดและตัดสต๊อกเสร็จสิ้น
                    st.success(f"🎉 ดำเนินการตัดสต๊อก VAT ลงฐานข้อมูลสำเร็จ {updated_count} รายการ!")

# ==========================================
# Menu 3: Dashboard & Reports (Custom UI)
# ==========================================
elif menu == "📈 3. ดูรายงาน / ดาวน์โหลด":
    st.header("📈 รายงานสถานะ VAT")
    
    # 1. Filters
    f_col1, f_col2, f_col3 = st.columns([1.5, 1.5, 2])
    with f_col1:
        stat_map = {"ทั้งหมด": "ALL", "คงเหลือ": "AVAILABLE", "ขายแล้ว": "USED"}
        stat_filter = st.selectbox("สถานะสินค้า", list(stat_map.keys()))
    with f_col2:
        vat_map = {"ทั้งหมด": "ALL", "บริษัท KIT Vat": "KIT", "บริษัท S16 Vat": "S16"}
        vat_filter = st.selectbox("บริษัท_Vat", list(vat_map.keys()))
    with f_col3:
        model_search = st.text_input("รุ่นสินค้า (พิมพ์บางส่วน)")

    # 2. Build Database Query
    query = supabase.table('vat_inventory').select('*')
    if stat_map[stat_filter] != "ALL":
        query = query.eq('status', stat_map[stat_filter])
    if vat_map[vat_filter] != "ALL":
        query = query.eq('vat_company', vat_map[vat_filter])
    if model_search:
        query = query.ilike('model', f'%{model_search}%')
        
    response = query.order('id', desc=True).execute()
    records: List[Dict[str, Any]] = response.data

    if not records:
        st.warning("ไม่พบข้อมูลที่ตรงกับเงื่อนไขการค้นหา")
    else:
        # เตรียม Dataframe สำหรับดาวน์โหลด (รวมข้อมูลทั้งหมดทุกหน้า)
        df_dl = pd.DataFrame(records)
        df_dl = df_dl[['receive_date', 'model', 'imei', 'vat_company', 'supplier_name', 'cost', 
                       'inbound_payment_method', 'inbound_bank_or_company', 
                       'used_date', 'customer_name', 'sales_price', 
                       'outbound_payment_method', 'outbound_receiving_company']]
        df_dl.columns = ["วันที่ซื้อ", "รุ่น", "IMEI", "บริษัท VAT", "ผู้จัดจำหน่าย", "ราคาทุน", 
                         "วิธีการชำระเงิน(เข้า)", "ธนาคาร/บริษัท(เข้า)", 
                         "วันที่ขาย", "ลูกค้า", "ราคาขาย", 
                         "วิธีการชำระเงิน(ออก)", "ธนาคาร/บริษัท(ออก)"]

        # --- CSS บังคับฟอนต์และตกแต่งปุ่มดาวน์โหลด ---
        st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
        html, body, [class*="css"], [class*="st-"], *, div, span, p, table, th, td, button, input, select {
            font-family: 'Sarabun', sans-serif !important;
        }
        .btn-custom-download {
            display: flex; align-items: center; justify-content: center;
            background-color: transparent; color: #f3f4f6 !important;
            text-decoration: none; border-radius: 0.5rem;
            border: 1px solid rgba(250, 250, 250, 0.2);
            font-weight: 400; font-size: 16px; height: 42px; width: 100%;
            transition: border-color 0.2s, color 0.2s;
            margin-top: 2px;
        }
        .btn-custom-download:hover { border-color: #ff4b4b; color: #ff4b4b !important; }
        .tiny-text { font-size: 14px; word-break: break-word; text-align: center; }
        .neon-price { color: #39ff14; font-weight: bold; font-size: 14px; text-align: center; }
        div[data-baseweb="select"] { font-size: 14px !important; }
        input[class*="st-"] { font-size: 14px !important; }
        hr { border-top: 1px solid #374151 !important; margin: 8px 0 !important; }
        </style>
        """, unsafe_allow_html=True)

        import base64
        def get_excel_download_html(df: pd.DataFrame, filename: str) -> str:
            val = convert_df_to_excel(df)
            b64 = base64.b64encode(val).decode()
            return f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{filename}" class="btn-custom-download" target="_blank">📥 ดาวน์โหลด Excel</a>'

        # --- ระบบ Pagination แบ่งหน้า ---
        items_per_page = 100
        total_items = len(records)
        total_pages = (total_items - 1) // items_per_page + 1

        # สร้าง Container เพื่อกำหนดลำดับการจัดวาง UI บนหน้าจอ
        main_table_area = st.container()
        bottom_pagination_area = st.container()

        # 1. ประมวลผลและแสดงผลตัวเลือกหน้า ไว้ด้านล่างสุด (bottom_pagination_area)
        with bottom_pagination_area:
            st.markdown("<br>", unsafe_allow_html=True)
            _, page_col, _ = st.columns([2, 1.5, 2])
            with page_col:
                current_page = st.number_input(f"หน้า (จากทั้งหมด {total_pages} หน้า)", min_value=1, max_value=total_pages, value=1)

        # ตัดข้อมูลเฉพาะหน้าปัจจุบัน
        start_idx = (current_page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_records = records[start_idx:end_idx]

        # 2. แสดงผลตารางและปุ่ม ไว้ด้านบนสุด (main_table_area)
        with main_table_area:
            with st.form("report_edit_form"):
                # แถวปุ่มควบคุมด้านบน
                action_col1, action_col2, _ = st.columns([1.5, 1.5, 5])
                with action_col1:
                    submitted = st.form_submit_button("💾 บันทึกการแก้ไข", type="primary", use_container_width=True)
                with action_col2:
                    st.markdown(get_excel_download_html(df_dl, "vat_report_all.xlsx"), unsafe_allow_html=True)

                st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)

                def fmt(val: Any) -> str:
                    if pd.isna(val) or val is None: return " "
                    s = str(val).strip()
                    if s in ["", "-", "None", "nan"]: return " "
                    return s

                col_ratios = [1.2, 1.5, 1.5, 0.8, 1.5, 1, 1.5, 1.5, 1.2, 1.5, 1, 1.5, 1.5]
                
                # --- หัวตาราง ---
                st.markdown('<div style="background-color:#1f2937; padding:8px; border-radius:6px 6px 0 0;">', unsafe_allow_html=True)
                hcols = st.columns(col_ratios)
                headers = ["วันที่ซื้อ", "รุ่น", "IMEI", "บริษัท VAT", "ผู้จำหน่าย", "ราคาทุน", 
                           "วิธีชำระ(เข้า)", "ธนาคาร(เข้า)", "วันที่ขาย", "ลูกค้า", "ราคาขาย", 
                           "วิธีชำระ(ออก)", "บริษัท(ออก)"]
                for col, th in zip(hcols, headers):
                    col.markdown(f"<div style='text-align: center; font-size: 13px; color:#f3f4f6;'><b>{th}</b></div>", unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

                payload = []
                
                # --- ข้อมูลตาราง (วนลูปเฉพาะหน้าปัจจุบัน) ---
                with st.container(height=600, border=True):
                    for rec in page_records:
                        cols = st.columns(col_ratios)
                        
                        # ข้อมูล ขาเข้า
                        cols[0].markdown(f"<div class='tiny-text'>{fmt(rec.get('receive_date'))}</div>", unsafe_allow_html=True)
                        cols[1].markdown(f"<div class='tiny-text'>{fmt(rec.get('model'))}</div>", unsafe_allow_html=True)
                        cols[2].markdown(f"<div class='tiny-text'>{fmt(rec.get('imei'))}</div>", unsafe_allow_html=True)
                        cols[3].markdown(f"<div class='tiny-text'>{fmt(rec.get('vat_company'))}</div>", unsafe_allow_html=True)
                        cols[4].markdown(f"<div class='tiny-text'>{fmt(rec.get('supplier_name'))}</div>", unsafe_allow_html=True)
                        
                        cost = rec.get('cost')
                        cost_html = f"<div class='neon-price'>฿{cost:,.2f}</div>" if cost else "<div class='tiny-text'> </div>"
                        cols[5].markdown(cost_html, unsafe_allow_html=True)
                        
                        pm_opts = [" ", "เงินสด", "โอนเงิน", "ผ่อนธนาคาร", "เครดิตบริษัท"]
                        in_pm = fmt(rec.get('inbound_payment_method'))
                        new_in_pm = cols[6].selectbox("in_pm", pm_opts, index=pm_opts.index(in_pm) if in_pm in pm_opts else 0, key=f"r_in_pm_{rec['id']}", label_visibility="collapsed")
                        
                        in_bank = fmt(rec.get('inbound_bank_or_company'))
                        new_in_bank = cols[7].text_input("in_bnk", value=in_bank, key=f"r_in_bnk_{rec['id']}", label_visibility="collapsed")

                        # ข้อมูล ขาออก
                        is_avail = rec.get('status') == 'AVAILABLE'
                        u_date = " " if is_avail else fmt(rec.get('used_date'))
                        u_cust = " " if is_avail else fmt(rec.get('customer_name'))
                        sp = 0 if is_avail else rec.get('sales_price', 0)
                        out_pm = " " if is_avail else fmt(rec.get('outbound_payment_method'))
                        out_comp = " " if is_avail else fmt(rec.get('outbound_receiving_company'))

                        cols[8].markdown(f"<div class='tiny-text'>{u_date}</div>", unsafe_allow_html=True)
                        cols[9].markdown(f"<div class='tiny-text'>{u_cust}</div>", unsafe_allow_html=True)
                        
                        sp_html = f"<div class='neon-price'>฿{sp:,.2f}</div>" if sp and sp > 0 else "<div class='tiny-text'> </div>"
                        cols[10].markdown(sp_html, unsafe_allow_html=True)

                        new_out_pm = cols[11].selectbox("out_pm", pm_opts, index=pm_opts.index(out_pm) if out_pm in pm_opts else 0, key=f"r_out_pm_{rec['id']}", label_visibility="collapsed")
                        
                        comp_opts = [" ", "บริษัท KIT", "บริษัท S16"]
                        new_out_comp = cols[12].selectbox("out_comp", comp_opts, index=comp_opts.index(out_comp) if out_comp in comp_opts else 0, key=f"r_out_comp_{rec['id']}", label_visibility="collapsed")

                        payload.append({
                            "id": rec['id'], "in_pm": new_in_pm, "in_bank": new_in_bank,
                            "out_pm": new_out_pm, "out_comp": new_out_comp
                        })
                        st.markdown("<hr/>", unsafe_allow_html=True)

                if submitted:
                    with st.spinner("กำลังอัปเดตข้อมูล..."):
                        for item in payload:
                            supabase.table('vat_inventory').update({
                                "inbound_payment_method": item["in_pm"], "inbound_bank_or_company": item["in_bank"],
                                "outbound_payment_method": item["out_pm"], "outbound_receiving_company": item["out_comp"]
                            }).eq('id', item["id"]).execute()
                    st.success("✅ อัปเดตข้อมูลสำเร็จ!")
                    st.rerun()
                
# ==========================================
# Menu 4: Search and Edit (Custom Table UI)
# ==========================================
elif menu == "✏️ 4. ค้นหาและแก้ไขข้อมูล":
    st.header("🔍 ค้นหาและแก้ไขข้อมูล")
    
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"], [class*="st-"], *, div, span, p, table, th, td, button, input, select {
        font-family: 'Sarabun', sans-serif !important;
    }
    .table-header { background-color: #1f2937; padding: 12px 8px; border-radius: 6px 6px 0 0; color: #f3f4f6; }
    .neon-price { color: #39ff14; font-weight: bold; font-size: 16px; text-align: center; }
    hr { border-top: 1px solid #374151 !important; margin: 5px 0 !important; }
    div[data-testid="column"] { display: flex; flex-direction: column; justify-content: center; }
    </style>
    """, unsafe_allow_html=True)

    col_search, col_date, col_status, col_vat, col_model = st.columns([1.5, 1.5, 1.5, 1.5, 2])
    with col_search:
        search_type = st.radio("ค้นหา", ["การซื้อเข้า", "การขายออก"], horizontal=True)
    with col_date:
        target_date = st.date_input("เลือกวันที่")
    with col_status:
        status_map = {"ทั้งหมด": "ALL", "ยังไม่ขาย": "AVAILABLE", "ขายแล้ว": "USED"}
        status_filter = st.selectbox("เลือกสถานะ", list(status_map.keys()))
    with col_vat:
        vat_map = {"ทั้งหมด": "ALL", "บริษัท KIT Vat": "KIT", "บริษัท S16 Vat": "S16"}
        vat_filter = st.selectbox("บริษัท_Vat", list(vat_map.keys()))
    with col_model:
        model_search = st.text_input("รุ่นสินค้า (พิมพ์บางส่วน)", value="")

    # 3. แก้ปัญหาค้นหาวันที่ โดยการส่ง Query ค้นหาทั้ง พ.ศ. และ ค.ศ. พร้อมกัน
    try:
        search_date_be = target_date.replace(year=target_date.year + 543).isoformat()
    except ValueError:
        search_date_be = target_date.isoformat()
    search_date_ad = target_date.isoformat()

    date_field = 'receive_date' if search_type == "การซื้อเข้า" else 'used_date'
    
    # ใช้ .in_ เพื่อครอบคลุมทั้ง 2 Format
    query = supabase.table('vat_inventory').select('*').in_(date_field, [search_date_ad, search_date_be])
    
    if status_map[status_filter] != "ALL":
        query = query.eq('status', status_map[status_filter])
    if vat_map[vat_filter] != "ALL":
        query = query.eq('vat_company', vat_map[vat_filter])
    if model_search:
        query = query.ilike('model', f'%{model_search}%')
        
    response = query.execute()
    records: List[Dict[str, Any]] = response.data

    def fmt(val: Any) -> str:
        if pd.isna(val) or val is None: return " "
        s = str(val).strip()
        return " " if s in ["", "-", "None", "nan"] else s

    if not records:
        st.warning(f"ไม่พบข้อมูล {search_type} ในวันที่ระบุ")
    else:
        st.success(f"พบข้อมูลทั้งหมด {len(records)} รายการ")
        
        with st.form("custom_table_form"):
            save_col, _ = st.columns([1, 4])
            with save_col:
                submitted = st.form_submit_button("💾 บันทึกการแก้ไข", type="primary", use_container_width=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            payload = []
            pm_opts = [" ", "เงินสด", "โอนเงิน", "ผ่อนธนาคาร", "เครดิตบริษัท"]
            
            if search_type == "การซื้อเข้า":
                st.markdown('<div class="table-header">', unsafe_allow_html=True)
                hcols = st.columns([1.5, 2.5, 2, 2, 1, 1.5, 2, 2])
                headers = ["วันที่", "สินค้า", "Serial No", "ชื่อผู้จำหน่าย", "บริษัท_VAT", "ราคาทุน", "วิธีการชำระเงิน", "ธนาคาร/บริษัท"]
                for col, th in zip(hcols, headers):
                    col.markdown(f"<div style='text-align: center;'><b>{th}</b></div>", unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

                with st.container(height=500, border=True):
                    for rec in records:
                        cols = st.columns([1.5, 2.5, 2, 2, 1, 1.5, 2, 2])
                        cols[0].markdown(f"<div style='text-align: center;'>{fmt(rec.get('receive_date'))}</div>", unsafe_allow_html=True)
                        cols[1].write(fmt(rec.get('model')))
                        cols[2].write(fmt(rec.get('imei')))
                        cols[3].write(fmt(rec.get('supplier_name')))
                        cols[4].markdown(f"<div style='text-align: center;'>{fmt(rec.get('vat_company'))}</div>", unsafe_allow_html=True)
                        
                        cost = rec.get('cost')
                        cost_html = f"<div class='neon-price'>฿{cost:,.2f}</div>" if cost else "<div style='text-align: center;'> </div>"
                        cols[5].markdown(cost_html, unsafe_allow_html=True)

                        curr_pm = fmt(rec.get('inbound_payment_method'))
                        new_pm = cols[6].selectbox("pm", pm_opts, index=pm_opts.index(curr_pm) if curr_pm in pm_opts else 0, key=f"in_pm_{rec['id']}", label_visibility="collapsed")

                        curr_bank = fmt(rec.get('inbound_bank_or_company'))
                        new_bank = cols[7].text_input("bank", value=curr_bank, key=f"in_bnk_{rec['id']}", label_visibility="collapsed")

                        payload.append({"id": rec['id'], "type": "in", "pm": new_pm, "bank": new_bank})
                        st.markdown("<hr/>", unsafe_allow_html=True)

            else:
                st.markdown('<div class="table-header">', unsafe_allow_html=True)
                hcols = st.columns([1.5, 2.5, 2, 2, 1, 1.5, 2, 2])
                headers = ["วันที่", "สินค้า", "Serial No", "ชื่อลูกค้า", "บริษัท_VAT", "ราคาขาย", "วิธีการชำระเงิน", "บริษัทที่รับเงิน"]
                for col, th in zip(hcols, headers):
                    col.markdown(f"<div style='text-align: center;'><b>{th}</b></div>", unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

                with st.container(height=500, border=True):
                    for rec in records:
                        cols = st.columns([1.5, 2.5, 2, 2, 1, 1.5, 2, 2])
                        
                        is_avail = rec.get('status') == 'AVAILABLE'
                        u_date = " " if is_avail else fmt(rec.get('used_date'))
                        u_cust = " " if is_avail else fmt(rec.get('customer_name'))
                        sp = 0 if is_avail else rec.get('sales_price', 0)
                        
                        cols[0].markdown(f"<div style='text-align: center;'>{u_date}</div>", unsafe_allow_html=True)
                        cols[1].write(fmt(rec.get('model')))
                        cols[2].write(fmt(rec.get('imei')))
                        cols[3].write(u_cust)
                        cols[4].markdown(f"<div style='text-align: center;'>{fmt(rec.get('vat_company'))}</div>", unsafe_allow_html=True)
                        
                        sp_html = f"<div class='neon-price'>฿{sp:,.2f}</div>" if sp and sp > 0 else "<div style='text-align: center;'> </div>"
                        cols[5].markdown(sp_html, unsafe_allow_html=True)

                        curr_pm = " " if is_avail else fmt(rec.get('outbound_payment_method'))
                        new_pm = cols[6].selectbox("pm", pm_opts, index=pm_opts.index(curr_pm) if curr_pm in pm_opts else 0, key=f"out_pm_{rec['id']}", label_visibility="collapsed")

                        comp_opts = [" ", "บริษัท KIT", "บริษัท S16"]
                        curr_comp = " " if is_avail else fmt(rec.get('outbound_receiving_company'))
                        new_comp = cols[7].selectbox("comp", comp_opts, index=comp_opts.index(curr_comp) if curr_comp in comp_opts else 0, key=f"out_comp_{rec['id']}", label_visibility="collapsed")

                        payload.append({"id": rec['id'], "type": "out", "pm": new_pm, "comp": new_comp})
                        st.markdown("<hr/>", unsafe_allow_html=True)

            if submitted:
                with st.spinner("กำลังอัปเดตฐานข้อมูล..."):
                    for item in payload:
                        if item["type"] == "in":
                            supabase.table('vat_inventory').update({
                                "inbound_payment_method": item["pm"],
                                "inbound_bank_or_company": item["bank"]
                            }).eq('id', item["id"]).execute()
                        else:
                            supabase.table('vat_inventory').update({
                                "outbound_payment_method": item["pm"],
                                "outbound_receiving_company": item["comp"]
                            }).eq('id', item["id"]).execute()
                            
                st.success("✅ อัปเดตข้อมูลสำเร็จ!")
                st.rerun()




