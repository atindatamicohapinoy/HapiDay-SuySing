import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import os
from PIL import Image
import io
import gspread
from google.oauth2.service_account import Credentials
import pypdf

st.set_page_config(page_title="Suy Sing Invoice Scanner - Gemini AI", layout="wide")
st.title("🧾 Suy Sing Sales Invoice Scanner - Gemini AI")

# Setup Gemini API
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"] if "GEMINI_API_KEY" in st.secrets else os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# Google Sheets setup
SHEET_ID = "1LOnYf1REHRVimyNWU6se2LkiYjoTMLMKAjQx1oDjcYc"

def get_gsheet_client():
    """Connect to Google Sheets using service account"""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    client = gspread.authorize(creds)
    return client

def safe_generate_content(model_name, contents, prompt):
    model = genai.GenerativeModel(model_name)
    response = model.generate_content([prompt] + contents)
    return response

def extract_table_gemini(uploaded_file):
    prompt = """
    Extract all information from this Suy Sing Sales Invoice receipt into a JSON list.
    
    For EVERY line item/row in the item table, include the Invoice Header details as metadata fields in each row object.
    
    Extract the following fields for EVERY row:
    - "INVOICE NO": Sales Invoice No. (e.g., 104002114944)
    - "PAGE": Page number info (e.g., 1 of 1)
    - "SOLD TO": Customer Name (e.g., MARK JOAQUIN RUIZ)
    - "CUST #": Customer ID (e.g., MARKR43)
    - "INV DATE": Invoice Date (e.g., 07/06/2026)
    - "ORD DATE": Order Date (e.g., 07/06/2026)
    - "PO #": PO Number (e.g., 3205950)
    - "QTY": Quantity (integer or float)
    - "UOM": Unit of Measure (e.g., PCK, CTN)
    - "CODE": Product item code (e.g., CLO69Y)
    - "DESCRIPTION": Full item description
    - "BCODE": Barcode number (e.g., 043901)
    - "AREA": Storage/location code (e.g., 2YD010)
    - "U. PRICE": Unit price
    - "PRICE": Line price
    - "AMOUNT": Total amount for the line item
    
    Rules:
    1. Repeat the Header fields ("INVOICE NO", "PAGE", "SOLD TO", "CUST #", "INV DATE", "ORD DATE", "PO #") across EVERY row object so each line item has its invoice metadata.
    2. Parse every row under the line items table section.
    3. Keep numerical values as strings or standard numbers.
    4. Return ONLY a valid JSON array of objects. Do not include markdown formatting outside ```json.
    
    Example output structure:
    [
      {
        "INVOICE NO": "104002114944",
        "PAGE": "1 of 1",
        "SOLD TO": "MARK JOAQUIN RUIZ",
        "CUST #": "MARKR43",
        "INV DATE": "07/06/2026",
        "ORD DATE": "07/06/2026",
        "PO #": "3205950",
        "QTY": "1",
        "UOM": "PCK",
        "CODE": "CLO69Y",
        "DESCRIPTION": "4390 CLOUD 9 CRUNCHIES 10/20G",
        "BCODE": "043901",
        "AREA": "2YD010",
        "U. PRICE": "8.14",
        "PRICE": "81.40",
        "AMOUNT": "81.40"
      }
    ]
    """
    
    contents = []
    
    # Check file type
    if uploaded_file.type == "application/pdf":
        pdf_bytes = uploaded_file.read()
        contents.append({
            "mime_type": "application/pdf",
            "data": pdf_bytes
        })
    else:
        # Image file (PNG, JPG, JPEG)
        image = Image.open(uploaded_file)
        contents.append(image)

    try:
        response = safe_generate_content("gemini-2.5-flash", contents, prompt)
    except:
        response = safe_generate_content("gemini-2.5-flash-lite", contents, prompt)

    json_text = response.text.strip()
    if json_text.startswith("```json"):
        json_text = json_text.replace("```json", "").replace("```", "").strip()
    elif json_text.startswith("```"):
        json_text = json_text.replace("```", "").strip()
    
    return json.loads(json_text)

# Initialize session state
if 'df' not in st.session_state:
    st.session_state.df = None

uploaded_file = st.file_uploader("Upload Suy Sing Invoice (PDF, PNG, JPG, JPEG)", type=['pdf', 'png', 'jpg', 'jpeg'])

if uploaded_file:
    if uploaded_file.type == "application/pdf":
        st.info("📄 PDF file uploaded. Ready to scan!")
    else:
        image = Image.open(uploaded_file)
        st.image(image, caption="Ready to scan", use_column_width=True)
    
    if st.button("🔍 Run AI Scan", type="primary"):
        with st.spinner('Gemini AI is reading invoice headers & item data... ~3-5 seconds'):
            try:
                table_data = extract_table_gemini(uploaded_file)
                
                if table_data:
                    st.success(f"✅ Extracted {len(table_data)} rows with Header Details!")
                    st.session_state.df = pd.DataFrame(table_data)
                else:
                    st.warning("Walang na-detect na data. Try mo mas malinaw na file.")
                    
            except Exception as e:
                st.error(f"Error: {str(e)}")

# Show editor + buttons kung may data na
if st.session_state.df is not None:
    st.subheader("📋 Verify Data - Edit mo kung may mali")
    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        key="editor"
    )
    # Update session state with edits
    st.session_state.df = edited_df
    
    col1, col2 = st.columns(2)
    
    with col1:
        csv = st.session_state.df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Download CSV",
            csv,
            "suysing_invoice_data.csv",
            "text/csv",
            use_container_width=True
        )
    
    with col2:
        if st.button("🚀 Sync All to Google Sheets", use_container_width=True):
            try:
                with st.spinner('Syncing to Google Sheets...'):
                    client = get_gsheet_client()
                    sheet = client.open_by_key(SHEET_ID).sheet1
                    
                    rows = st.session_state.df.values.tolist()
                    
                    # Add headers kung empty pa yung sheet
                    if len(sheet.get_all_values()) == 0:
                        sheet.append_row(st.session_state.df.columns.tolist())
                    
                    sheet.append_rows(rows, value_input_option='USER_ENTERED')
                    st.success(f"✅ {len(rows)} rows synced sa Google Sheets!")
                    st.balloons()
                    
            except Exception as e:
                st.error(f"Sync failed: {str(e)}")
                st.code(f"Error details: {repr(e)}")
                st.info("Check: 1. Naka-share ba sheet sa service account? 2. Tama ba secrets?")
else:
    st.info("👆 Upload a Suy Sing Invoice photo or PDF file to start")
    st.warning("⚠️ REVIEW and EDIT kung may MALI")
