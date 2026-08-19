import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import os
import re
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials

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

# JSON Schema definition to enforce perfectly structured JSON from Gemini
INVOICE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "INVOICE NO": {"type": "STRING"},
            "PAGE": {"type": "STRING"},
            "SOLD TO": {"type": "STRING"},
            "CUST #": {"type": "STRING"},
            "INV DATE": {"type": "STRING"},
            "ORD DATE": {"type": "STRING"},
            "PO #": {"type": "STRING"},
            "QTY": {"type": "STRING"},
            "UOM": {"type": "STRING"},
            "CODE": {"type": "STRING"},
            "DESCRIPTION": {"type": "STRING"},
            "BCODE": {"type": "STRING"},
            "AREA": {"type": "STRING"},
            "U. PRICE": {"type": "STRING"},
            "PRICE": {"type": "STRING"},
            "AMOUNT": {"type": "STRING"}
        },
        "required": [
            "INVOICE NO", "PAGE", "SOLD TO", "CUST #", "INV DATE", "ORD DATE", 
            "PO #", "QTY", "UOM", "CODE", "DESCRIPTION", "BCODE", "AREA", 
            "U. PRICE", "PRICE", "AMOUNT"
        ]
    }
}

def safe_generate_content(model_name, contents, prompt):
    # Configure generation parameters to force structured JSON output
    generation_config = genai.GenerationConfig(
        response_mime_type="application/json",
        response_schema=INVOICE_SCHEMA
    )
    model = genai.GenerativeModel(model_name, generation_config=generation_config)
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
    - "QTY": Quantity
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
    3. Return ONLY a valid JSON array of objects matching the schema.
    """
    
    contents = []
    
    # Reset file position pointer to 0
    uploaded_file.seek(0)
    
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
    except Exception:
        response = safe_generate_content("gemini-2.5-flash-lite", contents, prompt)

    raw_text = response.text.strip()

    # Clean out markdown code blocks if present
    json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
    if json_match:
        json_text = json_match.group(0)
    else:
        json_text = raw_text

    return json.loads(json_text)

# Initialize session state
if 'df' not in st.session_state:
    st.session_state.df = None

uploaded_file = st.file_uploader("Upload Suy Sing Invoice (PDF, PNG, JPG, JPEG)", type=['pdf', 'png', 'jpg', 'jpeg'])

if uploaded_file:
    if uploaded_file.type == "application/pdf":
        st.info("📄 PDF file uploaded. Ready to scan!")
    else:
        try:
            uploaded_file.seek(0)
            image = Image.open(uploaded_file)
            st.image(image, caption="Ready to scan", use_container_width=True)
        except Exception:
            st.warning("⚠️ Image uploaded. Click 'Run AI Scan' to process.")
    
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
                st.error(f"Error parsing JSON: {str(e)}")

# Show editor + buttons if data exists
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
                    
                    # Clean NaN/None values
                    df_clean = st.session_state.df.fillna("")
                    rows = df_clean.values.tolist()
                    
                    # Check Column A length to determine next row
                    col_a_values = sheet.col_values(1)
                    
                    if len(col_a_values) == 0:
                        # If empty sheet, include column headers
                        data_to_send = [df_clean.columns.tolist()] + rows
                        next_row = 1
                    else:
                        # Append directly after last populated row in Column A
                        data_to_send = rows
                        next_row = len(col_a_values) + 1
                    
                    # Update starting strictly from Column A
                    range_to_update = f"A{next_row}"
                    sheet.update(range_to_update, data_to_send, value_input_option='USER_ENTERED')
                    
                    st.success(f"✅ {len(rows)} rows synced starting at Column A (Row {next_row})!")
                    st.balloons()
                    
            except Exception as e:
                st.error(f"Sync failed: {str(e)}")
                st.code(f"Error details: {repr(e)}")
                st.info("Check: 1. Naka-share ba sheet sa service account? 2. Tama ba secrets?")
else:
    st.info("👆 Upload a Suy Sing Invoice photo or PDF file to start")
    st.warning("⚠️ REVIEW and EDIT kung may MALI")
