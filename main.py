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
    .context-display {
        font-family: 'Times New Roman', serif; font-size: 22px !important; line-height: 1.8;
        background-color: #ffffff; padding: 20px; border-radius: 10px; color: #333;
    }
    .stTextArea textarea { border: 2px solid #1565c0 !important; font-size: 16px !important; border-radius: 10px; }
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

# --- 4. HÀM XỬ LÝ LƯU TRỮ ---
def save_draft(u_account, ex_id, answers):
    db.collection('drafts').document(f"{u_account}_{ex_id}").set({'answers': {str(k): v for k, v in answers.items()}, 'updated_at': firestore.SERVER_TIMESTAMP})

def get_draft(u_account, ex_id):
    try:
        doc = db.collection('drafts').document(f"{u_account}_{ex_id}").get()
        return {int(k): v for k, v in doc.to_dict().get('answers', {}).items()} if doc.exists else {}
    except: return {}

def save_note(u_acc, ex_id, g_id, text):
    if not ex_id: return
    note_id = f"{u_acc}_{ex_id}_{str(g_id)}"
    db.collection('notes').document(note_id).set({'content': text, 'updated_at': firestore.SERVER_TIMESTAMP})

def get_notes(u_acc, ex_id):
    notes = {}
    try:
        prefix = f"{u_acc}_{ex_id}_"
        # SỬA LỖI TẠI ĐÂY: Dùng firestore.FieldPath.document_id()
        docs = db.collection('notes').where(firestore.FieldPath.document_id(), '>=', prefix).where(firestore.FieldPath.document_id(), '<=', prefix + '\uf8ff').stream()
        for doc in docs:
            gid_key = doc.id.replace(prefix, "")
            notes[str(gid_key)] = doc.to_dict().get('content', "")
    except Exception as e:
        print(f"DEBUG NẠP NOTE: {e}")
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
        st.session_state.current_df, st.session_state.current_ex_info, st.session_state.current_ex_id = df, ex, ex_id
        acc = st.session_state.user['account']
        st.session_state.user_answers = get_draft(acc, ex_id)
        
        # Nạp ghi chú từ Database
        fetched = get_notes(acc, ex_id)
        st.session_state.user_notes = fetched
        
        # DÒNG TEST (Xóa sau khi thấy nó hiện):
        if "1" not in st.session_state.user_notes:
             st.session_state.user_notes["1"] = "NẾU THẤY DÒNG NÀY LÀ APP ĐÃ KẾT NỐI ĐÚNG!"
        
        st.session_state.view_mode = 'quiz'
    except Exception as e: st.error(f"Lỗi nạp bài: {e}")

def start_review_direct_callback(ex, ex_id, history):
    try:
        df = pd.read_excel(get_drive_url(ex['excel_link']))
        df.columns = [str(c).strip().lower() for c in df.columns]
        st.session_state.current_df, st.session_state.current_ex_info, st.session_state.current_ex_id = df, ex, ex_id
        latest = max(history, key=lambda x: x['submitted_at'])
        st.session_state.user_answers = {int(k): v for k, v in latest.get('user_answers', {}).items()}
        st.session_state.user_notes = get_notes(st.session_state.user['account'], ex_id)
        st.session_state.view_mode = 'review'
    except: st.error("Lỗi nạp Review.")

# --- 6. TRANG CHÍNH ---
def student_page():
    st.sidebar.button("Đăng xuất", on_click=logout)
    u_acc = st.session_state.user['account']
    st.title(f"👋 Xin chào, {st.session_state.user.get('full_name', 'Học viên')}!")

    if st.session_state.view_mode == 'list':
        exs = db.collection('exercises').where('assigned_to', 'array_contains', u_acc).stream()
        for doc in exs:
            ex, ex_id = doc.to_dict(), doc.id
            with st.container(border=True):
                c1, c2 = st.columns([4, 1.5])
                c1.subheader(ex['title'])
                c2.button("Làm bài ➔", key=f"btn_{ex_id}", on_click=start_lesson_callback, args=(ex, ex_id), use_container_width=True)

    elif st.session_state.view_mode == 'quiz':
        if st.button("⬅ Thoát"): st.session_state.view_mode = 'list'; st.rerun()
        df = st.session_state.current_df
        df['ctx_tmp'] = df['context'].fillna('').astype(str).str.strip()
        df['group'] = (df['ctx_tmp'] != df['ctx_tmp'].shift()).cumsum()
        
        for g_id, group_df in df.groupby('group'):
            gid_str = str(g_id)
            saved_val = st.session_state.user_notes.get(gid_str, "")
            
            # Ô GHI CHÚ
            note_input = st.text_area(
                "📝 Ghi chú / Chiến thuật (Tự động lưu):", 
                value="ABCA", 
                key=f"note_input_{st.session_state.current_ex_id}_{gid_str}", 
                height=150
            )
            
            if note_input != saved_val:
                st.session_state.user_notes[gid_str] = note_input
                save_note(u_acc, st.session_state.current_ex_id, g_id, note_input)
                st.toast("Đã lưu ghi chú!", icon="💾")
            
            # Hiển thị Context & Questions
            l, r = st.columns([1, 1])
            with l:
                st.markdown(f'<div class="context-display">{clean_nan(group_df.iloc[0]["context"])}</div>', unsafe_allow_html=True)
            with r:
                for i, row in group_df.iterrows():
                    st.write(f"**Câu {i+1}:** {row.get('question', '')}")
                    st.radio(f"q{i}", ["A", "B", "C", "D"], key=f"radio_{i}", label_visibility="collapsed")
            st.divider()

def login_page():
    # Giữ nguyên code đăng nhập của Thầy
    pass

# --- ĐIỀU HƯỚNG ---
if st.session_state.user is None: 
    # (Đoạn này Thầy tự sửa theo hệ thống đăng nhập của Thầy nhé)
    login_page()
else: 
    student_page()
