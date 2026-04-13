import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd
import re
import requests
from datetime import datetime
import altair as alt

# --- 1. CẤU HÌNH GIAO DIỆN & CSS ---
st.set_page_config(page_title="Dank's class management", layout="wide")
st.markdown("""
    <style>
    .big-font { font-size:70px !important; font-weight: bold; text-align: center; }
    div.stButton > button { height: 100px; font-size: 25px !important; font-weight: bold; border-radius: 20px; }
    .context-display {
        font-family: 'Times New Roman', serif;
        font-size: 22px !important; line-height: 1.8;
        white-space: pre-wrap !important; background-color: #ffffff;
        padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        margin-bottom: 15px; color: #333;
    }
    .correct-box { border: 2px solid #28a745; background-color: #e8f5e9; padding: 10px; border-radius: 10px; margin-bottom: 5px; }
    .wrong-box { border: 2px solid #dc3545; background-color: #ffebee; padding: 10px; border-radius: 10px; margin-bottom: 5px; }
    .warning-box { border: 2px solid #ffc107; background-color: #fffde7; padding: 10px; border-radius: 10px; margin-bottom: 5px; }
    .normal-box { border: 1px solid #ddd; padding: 10px; border-radius: 10px; margin-bottom: 5px; color: #666; }
    .transcript-box { background-color: #f0f7ff; border-left: 5px solid #1565c0; padding: 15px; margin-top: 10px; border-radius: 5px; font-style: italic; color: #0d47a1; }
    .stTextArea textarea { border: 2px solid #1565c0 !important; font-size: 16px !important; border-radius: 10px; background-color: #fcfdff; }
    audio { width: 100%; margin-bottom: 20px; }
    img { -webkit-user-select: none; pointer-events: none; border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. HÀM HỖ TRỢ ---
def get_drive_url(url):
    if not url or not isinstance(url, str): return ""
    match = re.search(r'(?:d/|id=)([a-zA-Z0-9_-]{25,})', url)
    return f'https://drive.google.com/uc?export=download&id={match.group(1)}' if match else url.strip()

@st.cache_data(show_spinner=False)
def get_drive_content(url):
    try:
        response = requests.get(get_drive_url(url), timeout=15)
        return response.content if response.status_code == 200 else None
    except: return None

def display_drive_image(url):
    content = get_drive_content(url)
    if content: st.image(content, use_container_width=True)

def display_drive_audio(url):
    content = get_drive_content(url)
    if content: st.audio(content)

def clean_nan(val):
    return str(val).strip() if pd.notna(val) and str(val).lower() != "nan" else " "

# --- 3. KHỞI TẠO FIREBASE ---
if not firebase_admin._apps:
    fb_dict = dict(st.secrets["firebase"])
    if "private_key" in fb_dict: fb_dict["private_key"] = fb_dict["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(fb_dict)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- 4. HÀM XỬ LÝ DRAFT & NOTES ---
def save_draft(u_account, ex_id, answers):
    db.collection('drafts').document(f"{u_account}_{ex_id}").set({
        'answers': {str(k): v for k, v in answers.items()},
        'updated_at': firestore.SERVER_TIMESTAMP
    })

def get_draft(u_account, ex_id):
    doc = db.collection('drafts').document(f"{u_account}_{ex_id}").get()
    return {int(k): v for k, v in doc.to_dict().get('answers', {}).items()} if doc.exists else {}

def delete_draft(u_account, ex_id):
    db.collection('drafts').document(f"{u_account}_{ex_id}").delete()

def save_note(u_acc, ex_id, g_id, text):
    if not ex_id: return
    note_id = f"{u_acc}_{ex_id}_{str(g_id)}"
    db.collection('notes').document(note_id).set({'content': text, 'updated_at': firestore.SERVER_TIMESTAMP})

def get_notes(u_acc, ex_id):
    notes = {}
    try:
        prefix = f"{u_acc}_{ex_id}_"
        docs = db.collection('notes').where(firestore.FieldPath.document_id(), '>=', prefix).where(firestore.FieldPath.document_id(), '<=', prefix + '\uf8ff').stream()
        for doc in docs:
            # Bóc tách g_id chính xác bằng cách lấy phần sau prefix
            gid_key = doc.id[len(prefix):]
            notes[str(gid_key)] = doc.to_dict().get('content', "")
    except Exception as e:
        print(f"DEBUG: {e}")
    return notes

# --- 5. CALLBACKS ---
if 'user' not in st.session_state: st.session_state.user = None
if 'view_mode' not in st.session_state: st.session_state.view_mode = 'list'
if 'current_df' not in st.session_state: st.session_state.current_df = None
if 'user_answers' not in st.session_state: st.session_state.user_answers = {}
if 'user_notes' not in st.session_state: st.session_state.user_notes = {}

def logout():
    for key in list(st.session_state.keys()): del st.session_state[key]
    st.rerun()

def start_lesson_callback(ex, ex_id):
    try:
        df = pd.read_excel(get_drive_url(ex['excel_link']))
        df.columns = [str(c).strip().lower() for c in df.columns]
        st.session_state.current_df = df
        st.session_state.current_ex_info = ex
        st.session_state.current_ex_id = ex_id
        st.session_state.view_mode = 'quiz'
        
        acc = st.session_state.user['account']
        st.session_state.user_answers = get_draft(acc, ex_id)
        
        # Nạp Note và ĐẨY THẲNG VÀO SESSION STATE CỦA WIDGET
        fetched_notes = get_notes(acc, ex_id)
        st.session_state.user_notes = fetched_notes
        for gid, content in fetched_notes.items():
            st.session_state[f"note_quiz_{ex_id}_{gid}"] = content
            
    except Exception as e: st.error(f"Lỗi nạp bài: {e}")

def start_review_direct_callback(ex, ex_id, history):
    try:
        df = pd.read_excel(get_drive_url(ex['excel_link']))
        df.columns = [str(c).strip().lower() for c in df.columns]
        st.session_state.current_df, st.session_state.current_ex_info, st.session_state.current_ex_id = df, ex, ex_id
        latest_sub = max(history, key=lambda x: x['submitted_at'])
        st.session_state.user_answers = {int(k): v for k, v in latest_sub.get('user_answers', {}).items()}
        
        # Nạp và đẩy Note cho trang Review
        acc = st.session_state.user['account']
        fetched_notes = get_notes(acc, ex_id)
        st.session_state.user_notes = fetched_notes
        for gid, content in fetched_notes.items():
            st.session_state[f"note_rev_{ex_id}_{gid}"] = content
            
        st.session_state.view_mode = 'review'
    except Exception as e: st.error(f"Lỗi
