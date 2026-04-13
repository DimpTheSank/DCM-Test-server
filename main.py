import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd
import re
import requests
from datetime import datetime
import altair as alt

# --- 1. CẤU HÌNH GIAO DIỆN & CSS ---
st.set_page_config(page_title="NCKH LMS - Dank's Class", layout="wide")

st.markdown("""
    <style>
    /* UI Dashboard: Sidebar bám sát & Header cố định */
    [data-testid="stSidebarNav"] { background-color: #f8f9fa; }
    .stTextArea textarea { border: 2px solid #1565c0 !important; font-size: 16px !important; border-radius: 10px; }
    
    /* Giao diện hiển thị Context (Đề bài) */
    .context-display {
        font-family: 'Times New Roman', serif;
        font-size: 21px !important; line-height: 1.7;
        white-space: pre-wrap !important; background-color: #ffffff;
        padding: 20px; border-radius: 10px; border: 1px solid #eee;
        margin-bottom: 15px; color: #333;
    }
    
    /* Các Box thông báo trong Review */
    .correct-box { border: 2px solid #28a745; background-color: #e8f5e9; padding: 10px; border-radius: 10px; margin-bottom: 5px; }
    .wrong-box { border: 2px solid #dc3545; background-color: #ffebee; padding: 10px; border-radius: 10px; margin-bottom: 5px; }
    .warning-box { border: 2px solid #ffc107; background-color: #fffde7; padding: 10px; border-radius: 10px; margin-bottom: 5px; }
    .transcript-box { background-color: #f0f7ff; border-left: 5px solid #1565c0; padding: 15px; margin-top: 10px; border-radius: 5px; font-style: italic; }

    audio { width: 100%; margin-bottom: 20px; }
    img { -webkit-user-select: none; pointer-events: none; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }
    </style>
    """, unsafe_allow_html=True)

# --- 2. HÀM HỖ TRỢ DỮ LIỆU ---
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
    try:
        # Streamlit Cloud: Dùng secrets
        fb_dict = dict(st.secrets["firebase"])
        if "private_key" in fb_dict: fb_dict["private_key"] = fb_dict["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(fb_dict)
    except:
        # Local: Dùng file json
        cred = credentials.Certificate('data/serviceAccountKey.json')
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- 4. HÀM XỬ LÝ LƯU TRỮ (DRAFTS & NOTES) ---
def save_draft(u_account, ex_id, answers):
    db.collection('drafts').document(f"{u_account}_{ex_id}").set({
        'answers': {str(k): v for k, v in answers.items()},
        'updated_at': firestore.SERVER_TIMESTAMP
    })

def get_draft(u_account, ex_id):
    try:
        doc = db.collection('drafts').document(f"{u_account}_{ex_id}").get()
        return {int(k): v for k, v in doc.to_dict().get('answers', {}).items()} if doc.exists else {}
    except: return {}

def delete_draft(u_account, ex_id):
    db.collection('drafts').document(f"{u_account}_{ex_id}").delete()

def save_note(u_acc, ex_id, g_id, text):
    if not ex_id or ex_id == "temp": return
    note_id = f"{u_acc}_{ex_id}_{str(g_id)}"
    db.collection('notes').document(note_id).set({'content': text, 'updated_at': firestore.SERVER_TIMESTAMP})

def get_notes(u_acc, ex_id):
    notes = {}
    if not ex_id or ex_id == "temp": return notes
    try:
        prefix = f"{u_acc}_{ex_id}_"
        # CHIÊU CUỐI: Dùng order_by và range filter trên ID để né lỗi 400
        query = db.collection('notes').order_by("__name__") \
                  .start_at([prefix]) \
                  .end_at([prefix + '\uf8ff'])
        
        docs = query.stream()
        for doc in docs:
            gid_key = doc.id.replace(prefix, "")
            notes[gid_key] = doc.to_dict().get('content', "")
    except Exception as e:
        print(f"Lỗi nạp Note: {e}")
    return notes

# --- 5. QUẢN LÝ SESSION & CALLBACKS ---
for key in ['user', 'view_mode', 'current_df', 'user_answers', 'user_notes', 'current_ex_id']:
    if key not in st.session_state: st.session_state[key] = None if key != 'user_answers' and key != 'user_notes' else {}

def logout():
    for key in list(st.session_state.keys()): del st.session_state[key]
    st.rerun()

def start_lesson_callback(ex, ex_id):
    try:
        df = pd.read_excel(get_drive_url(ex['excel_link']))
        df.columns = [str(c).strip().lower() for c in df.columns]
        st.session_state.current_df, st.session_state.current_ex_info, st.session_state.current_ex_id = df, ex, ex_id
        st.session_state.view_mode = 'quiz'
        acc = st.session_state.user['account']
        st.session_state.user_answers = get_draft(acc, ex_id)
        st.session_state.user_notes = get_notes(acc, ex_id)
    except Exception as e: st.error(f"Lỗi: {e}")

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

# --- 6. GIAO DIỆN HỌC SINH ---
def student_page():
    st.sidebar.button("Đăng xuất", on_click=logout)
    u_acc = st.session_state.user['account']
    st.title(f"👋 {st.session_state.user.get('full_name', 'Học viên')}")

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
        df['aud_tmp'] = df['audio'].fillna('').astype(str).str.strip() if 'audio' in df.columns else ""
        df['group'] = ((df['ctx_tmp'] != df['ctx_tmp'].shift()) | (df['aud_tmp'] != df['aud_tmp'].shift())).cumsum()
        
        for g_id, group_df in df.groupby('group'):
            gid_str = str(g_id)
            if str(group_df.iloc[0].get('aud_tmp')) != "": display_drive_audio(group_df.iloc[0]['aud_tmp'])
            
            # NẠP VÀ HIỂN THỊ NOTE
            saved_note = st.session_state.user_notes.get(gid_str, "")
            note_input = st.text_area("📝 Ghi chú / Chiến thuật:", value=saved_note, key=f"n_q_{st.session_state.current_ex_id}_{gid_str}", height=130)
            
            if note_input != saved_note:
                st.session_state.user_notes[gid_str] = note_input
                save_note(u_acc, st.session_state.current_ex_id, g_id, note_input)
                st.toast("Đã lưu ghi chú!", icon="💾")
            
            l, r = st.columns([1, 1])
            with l:
                with st.container(height=800):
                    ctx = clean_nan(group_df.iloc[0]['context'])
                    for p in ctx.split(";;"):
                        if p.strip().startswith("http"): display_drive_image(p.strip())
                        else: st.markdown(f'<div class="context-display">{p.strip()}</div>', unsafe_allow_html=True)
            with r:
                with st.container(height=800):
                    for i, r in group_df.iterrows():
                        st.write(f"**Câu {i+1}:** {r['question']}")
                        cur_v = st.session_state.user_answers.get(i)
                        opts = [clean_nan(r.get(f'opt_{l}')) for l in ['a','b','c','d'] if clean_nan(r.get(f'opt_{l}')) != " "]
                        sel = st.radio(f"q{i}", opts, key=f"r_{i}", index=opts.index(cur_v) if cur_v in opts else None, label_visibility="collapsed")
                        if sel != cur_v:
                            st.session_state.user_answers[i] = sel
                            save_draft(u_acc, st.session_state.current_ex_id, st.session_state.user_answers)
            st.divider()
        if st.button("Nộp bài 🏁", use_container_width=True, type="primary"):
            # (Thầy dán logic tính điểm & nộp bài cũ của Thầy vào đây)
            st.success("Đã nộp bài thành công!")
            delete_draft(u_acc, st.session_state.current_ex_id)
            st.session_state.view_mode = 'list'; st.rerun()

    elif st.session_state.view_mode == 'review':
        st.title("🧐 Xem lại bài tập")
        if st.button("⬅ Quay lại"): st.session_state.view_mode = 'list'; st.rerun()
        # (Tương tự Quiz nhưng hiển thị đáp án đúng/sai như các bản trước)
        st.info("Tính năng Review đang hiển thị dữ liệu đã lưu.")

# --- 7. ĐIỀU HƯỚNG ---
def login_page():
    st.title("🔑 Đăng nhập")
    acc = st.text_input("Tài khoản:")
    pwd = st.text_input("Mật khẩu:", type="password")
    if st.button("Vào hệ thống"):
        user_ref = db.collection('users').document(acc).get()
        if user_ref.exists and str(user_ref.to_dict().get('password')) == pwd:
            st.session_state.user = {**user_ref.to_dict(), 'account': acc}
            st.rerun()

if st.session_state.user is None: login_page()
else: student_page() # Hoặc teacher_page() tùy Role
