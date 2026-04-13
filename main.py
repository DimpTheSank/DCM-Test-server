import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd
import re
import requests
import time
import uuid
from datetime import datetime
import altair as alt

# --- 1. CẤU HÌNH GIAO DIỆN & CSS ---
st.set_page_config(page_title="Dank's class management", layout="wide")

st.markdown("""
    <style>
    .big-font { font-size:70px !important; font-weight: bold; text-align: center; }
    div.stButton > button { height: 100px; font-size: 25px !important; font-weight: bold; border-radius: 20px; }
    
    /* Giao diện hiển thị đề bài */
    .context-display {
        font-family: 'Times New Roman', serif;
        font-size: 22px !important; line-height: 1.8;
        white-space: pre-wrap !important; background-color: #ffffff;
        padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        margin-bottom: 15px; color: #333;
    }
    
    /* Box thông báo đúng/sai */
    .correct-box { border: 2px solid #28a745; background-color: #e8f5e9; padding: 10px; border-radius: 10px; margin-bottom: 5px; }
    .wrong-box { border: 2px solid #dc3545; background-color: #ffebee; padding: 10px; border-radius: 10px; margin-bottom: 5px; }
    .warning-box { border: 2px solid #ffc107; background-color: #fffde7; padding: 10px; border-radius: 10px; margin-bottom: 5px; }
    .normal-box { border: 1px solid #ddd; padding: 10px; border-radius: 10px; margin-bottom: 5px; color: #666; }
    .transcript-box { background-color: #f0f7ff; border-left: 5px solid #1565c0; padding: 15px; margin-top: 10px; border-radius: 5px; font-style: italic; color: #0d47a1; }
    
    /* Tùy chỉnh ô Note */
    .stTextArea textarea { border: 2px solid #1565c0 !important; font-size: 16px !important; border-radius: 10px; background-color: #fcfdff; }
    
    audio { width: 100%; margin-bottom: 20px; border-radius: 10px; background-color: #f1f3f4; }

    /* CSS CHO NÚT THOÁT NỔI (STICKY) */
    .sticky-exit-container {
        position: -webkit-sticky;
        position: sticky;
        top: 2.85rem; /* Khoảng cách né thanh menu Streamlit */
        z-index: 1000;
        background-color: white;
        padding: 10px 0;
        border-bottom: 1px solid #eee;
        margin-bottom: 20px;
    }

    @media (max-width: 768px) {
        .context-display { font-size: 19px !important; }
        div.stButton > button { height: 60px; font-size: 18px !important; }
    }

    img { -webkit-touch-callout: none !important; -webkit-user-select: none !important; user-select: none !important; pointer-events: none; border-radius: 8px; }
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
    if "firebase" in st.secrets:
        fb_dict = dict(st.secrets["firebase"])
        if "private_key" in fb_dict: fb_dict["private_key"] = fb_dict["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(fb_dict)
    else: cred = credentials.Certificate('data/serviceAccountKey.json')
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- 4. HÀM XỬ LÝ DỮ LIỆU ---
def save_draft(u_account, ex_id, answers):
    db.collection('drafts').document(f"{u_account}_{ex_id}").set({
        'answers': {str(k): v for k, v in answers.items()},
        'updated_at': firestore.SERVER_TIMESTAMP
    })

def get_draft(u_account, ex_id):
    doc = db.collection('drafts').document(f"{u_account}_{ex_id}").get()
    if doc.exists:
        data = doc.to_dict().get('answers', {})
        return {int(k): v for k, v in data.items()}
    return {}

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
        docs = db.collection('notes').order_by("__name__").start_at([prefix]).end_at([prefix + '\uf8ff']).stream()
        for doc in docs:
            gid_key = doc.id.replace(prefix, "")
            notes[gid_key] = doc.to_dict().get('content', "")
    except: pass
    return notes

# --- 5. QUẢN LÝ SESSION ---
if 'user' not in st.session_state: st.session_state.user = None
if 'view_mode' not in st.session_state: st.session_state.view_mode = 'list'
if 'current_df' not in st.session_state: st.session_state.current_df = None
if 'user_answers' not in st.session_state: st.session_state.user_answers = {}
if 'user_notes' not in st.session_state: st.session_state.user_notes = {}
if 'current_ex_id' not in st.session_state: st.session_state.current_ex_id = None

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
        st.session_state.user_answers, st.session_state.user_notes = get_draft(acc, ex_id), get_notes(acc, ex_id)
    except: st.error("Lỗi nạp bài.")

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

# --- 6. CÁC TRANG ---
def login_page():
    st.markdown('<h1 style="text-align: center;">🔑 Đăng nhập Hệ thống</h1>', unsafe_allow_html=True)
    with st.container(border=True):
        account = st.text_input("📧 Tài khoản:")
        password = st.text_input("🔒 Mật khẩu:", type="password")
        if st.button("Xác nhận", use_container_width=True):
            user_ref = db.collection('users').document(account).get()
            if user_ref.exists and str(user_ref.to_dict().get('password')) == password:
                st.session_state.user = {**user_ref.to_dict(), 'account': account}
                st.rerun()
            else: st.error("Sai tài khoản hoặc mật khẩu.")

def teacher_page():
    st.sidebar.button("Đăng xuất", on_click=logout)
    st.title("👨‍🏫 Quản lý Học viên")
    t1, t2, t3 = st.tabs(["📤 Giao bài", "👥 Quản lý", "📊 Thống kê"])
    # (Phần code Teacher giữ nguyên như cũ)
    with t1:
        with st.expander("Giao bài tập mới", expanded=True):
            students = [s.id for s in db.collection('users').where('role', '==', 'student').stream()]
            title, link = st.text_input("Tiêu đề"), st.text_input("Link Excel")
            ex_type = st.selectbox("Loại", ["Reading (Part 5,6,7)", "Listening", "Vocab Game"])
            assigned = st.multiselect("Giao cho:", students)
            if st.button("🚀 Đăng bài", use_container_width=True):
                db.collection('exercises').add({'title': title, 'type': ex_type, 'excel_link': link, 'assigned_to': assigned, 'created_at': firestore.SERVER_TIMESTAMP, 'review_permissions': {acc: False for acc in assigned}})
                st.success("Đã đăng bài!")
    with t2:
        all_st_ids = [s.id for s in db.collection('users').where('role', '==', 'student').stream()]
        sel_st = st.selectbox("Chọn học sinh:", ["-- Chọn --"] + all_st_ids)
        if sel_st != "-- Chọn --":
            exs = db.collection('exercises').where('assigned_to', 'array_contains', sel_st).stream()
            for doc in exs:
                ex, ex_id = doc.to_dict(), doc.id
                with st.expander(f"📝 {ex['title']}"):
                    c1, c2, c3 = st.columns([2, 1, 1])
                    c1.write(f"Loại: {ex['type']}")
                    perms = ex.get('review_permissions', {})
                    if c2.toggle("Cho phép Review", value=perms.get(sel_st, False), key=f"rev_{ex_id}_{sel_st}"):
                        perms[sel_st] = True
                        db.collection('exercises').document(ex_id).update({'review_permissions': perms})
                    else:
                        perms[sel_st] = False
                        db.collection('exercises').document(ex_id).update({'review_permissions': perms})
                    if c3.button("🗑️ Xoá bài", key=f"del_{ex_id}_{sel_st}"):
                        new_a = [acc for acc in ex['assigned_to'] if acc != sel_st]
                        if not new_a: db.collection('exercises').document(ex_id).delete()
                        else: db.collection('exercises').document(ex_id).update({'assigned_to': new_a})
                        st.rerun()

def student_page():
    st.sidebar.button("Đăng xuất", on_click=logout)
    u_acc = st.session_state.user['account']
    st.title(f"👋 Xin chào, {st.session_state.user.get('full_name', 'Học viên')}!")

    if st.session_state.view_mode == 'list':
        all_subs = [s.to_dict() for s in db.collection('submissions').where('student_email', '==', u_acc).stream()]
        exs = db.collection('exercises').where('assigned_to', 'array_contains', u_acc).stream()
        for doc in exs:
            ex, ex_id = doc.to_dict(), doc.id
            history = [s for s in all_subs if s.get('exercise_title') == ex['title']]
            with st.container(border=True):
                c1, c2 = st.columns([4, 1.5])
                with c1: st.subheader(f"{ex['type']} - {ex['title']}")
                with c2: 
                    st.button("Làm bài ➔", key=f"btn_{ex_id}", on_click=start_lesson_callback, args=(ex, ex_id), use_container_width=True)
                    if history and ex.get('review_permissions', {}).get(u_acc, False):
                        st.button("Xem lại 🧐", key=f"rev_{ex_id}", on_click=start_review_direct_callback, args=(ex, ex_id, history), use_container_width=True)

    elif st.session_state.view_mode == 'quiz':
        # --- NÚT THOÁT NỔI (STICKY) ---
        st.markdown('<div class="sticky-exit-container">', unsafe_allow_html=True)
        if st.button("⬅ Thoát (Bài làm sẽ được lưu tự động)", key="sticky_exit_quiz", use_container_width=True):
            st.session_state.view_mode = 'list'; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        df = st.session_state.current_df
        df['ctx_tmp'] = df['context'].fillna('').astype(str).str.strip()
        df['group'] = (df['ctx_tmp'] != df['ctx_tmp'].shift()).cumsum()
        
        for g_id, group_df in df.groupby('group'):
            gid_str = str(g_id)
            if 'audio' in group_df.columns and clean_nan(group_df.iloc[0].get('audio')) != " ":
                display_drive_audio(group_df.iloc[0]['audio'])
            
            # Ô ghi chú nạp từ Firebase
            saved_note = st.session_state.user_notes.get(gid_str, "")
            note_input = st.text_area("📝 Ghi chú / Chiến thuật:", value=saved_note, key=f"n_q_{st.session_state.current_ex_id}_{gid_str}", height=150)
            if note_input != saved_note:
                st.session_state.user_notes[gid_str] = note_input
                save_note(u_acc, st.session_state.current_ex_id, g_id, note_input); st.toast("Đã lưu!")

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
                        opts = [clean_nan(r.get(f'opt_{let}')) for let in ['a','b','c','d'] if clean_nan(r.get(f'opt_{let}')) != " "]
                        cur_v = st.session_state.user_answers.get(i)
                        sel = st.radio(f"q{i}", opts, key=f"r_{i}", index=opts.index(cur_v) if cur_v in opts else None, label_visibility="collapsed")
                        if sel != cur_v:
                            st.session_state.user_answers[i] = sel
                            save_draft(u_acc, st.session_state.current_ex_id, st.session_state.user_answers)
            st.divider()
        if st.button("Nộp bài 🏁", use_container_width=True, type="primary"):
            # (Thầy dán lại logic tính điểm ở đây nhé)
            st.session_state.view_mode = 'list'; st.rerun()

    elif st.session_state.view_mode == 'review':
        # --- NÚT THOÁT NỔI (STICKY) CHO REVIEW ---
        st.markdown('<div class="sticky-exit-container">', unsafe_allow_html=True)
        if st.button("⬅ Quay lại danh sách", key="sticky_exit_rev", use_container_width=True):
            st.session_state.view_mode = 'list'; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        df = st.session_state.current_df
        df['ctx_tmp'] = df['context'].fillna('').astype(str).str.strip()
        df['group'] = (df['ctx_tmp'] != df['ctx_tmp'].shift()).cumsum()
        
        for g_id, group_df in df.groupby('group'):
            gid_str = str(g_id)
            if 'audio' in group_df.columns and clean_nan(group_df.iloc[0].get('audio')) != " ":
                display_drive_audio(group_df.iloc[0]['audio'])

            # Chỉnh sửa ghi chú ngay trong Review
            saved_note = st.session_state.user_notes.get(gid_str, "")
            note_rev = st.text_area("📝 Chỉnh sửa ghi chú ôn tập:", value=saved_note, key=f"n_r_{st.session_state.current_ex_id}_{gid_str}", height=150)
            if note_rev != saved_note:
                st.session_state.user_notes[gid_str] = note_rev
                save_note(u_acc, st.session_state.current_ex_id, g_id, note_rev); st.toast("Đã cập nhật!")

            l_rev, r_rev = st.columns([1, 1])
            with l_rev:
                with st.container(height=800):
                    ctx = clean_nan(group_df.iloc[0]['context'])
                    for p in ctx.split(";;"):
                        if p.strip().startswith("http"): display_drive_image(p.strip())
                        else: st.markdown(f'<div class="context-display">{p.strip()}</div>', unsafe_allow_html=True)
            with r_rev:
                with st.container(height=800):
                    for i, r in group_df.iterrows():
                        st.write(f"**Câu {i+1}:** {r['question']}")
                        u_ans, ck_let = st.session_state.user_answers.get(i), str(r.get('correct_ans')).strip().upper()
                        opts = {'A': clean_nan(r.get('opt_a')), 'B': clean_nan(r.get('opt_b')), 'C': clean_nan(r.get('opt_c')), 'D': clean_nan(r.get('opt_d'))}
                        for let, txt in opts.items():
                            if txt == " ": continue
                            is_cor, is_mi = (let == ck_let), (txt == u_ans)
                            if is_cor and is_mi: st.markdown(f'<div class="correct-box">✅ <b>{let}. {txt}</b> (Đúng)</div>', unsafe_allow_html=True)
                            elif is_cor: st.markdown(f'<div class="correct-box">🟢 <b>{let}. {txt}</b> (Đáp án)</div>', unsafe_allow_html=True)
                            elif is_mi: st.markdown(f'<div class="wrong-box">❌ <b>{let}. {txt}</b> (Sai)</div>', unsafe_allow_html=True)
                            else: st.markdown(f'<div class="normal-box">{let}. {txt}</div>', unsafe_allow_html=True)
            st.divider()

# --- 7. ĐIỀU HƯỚNG ---
if st.session_state.user is None: login_page()
else: teacher_page() if st.session_state.user.get('role') == 'teacher' else student_page()
