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
    except Exception as e: st.error(f"Lỗi nạp Review: {e}")

# --- 6. ĐIỀU HƯỚNG ---
def login_page():
    st.markdown('<h1 style="text-align: center;">🔑 Đăng nhập Hệ thống</h1>', unsafe_allow_html=True)
    with st.container(border=True):
        account = st.text_input("📧 Tài khoản của bạn:")
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
    with t3:
        all_users = {u.id: u.to_dict().get('full_name', u.id) for u in db.collection('users').stream()}
        chosen = st.multiselect("Chọn nhóm học sinh:", list(all_users.keys()))
        if chosen:
            student_ex_lists = []
            for acc in chosen:
                exs = db.collection('exercises').where('assigned_to', 'array_contains', acc).stream()
                student_ex_lists.append({doc.to_dict()['title'] for doc in exs})
            common = list(set.intersection(*student_ex_lists)) if student_ex_lists else []
            if common:
                sel_title = st.selectbox("Chọn bài tập:", ["-- Chọn bài tập --"] + common)
                if sel_title != "-- Chọn bài tập --":
                    ex_doc = db.collection('exercises').where('title', '==', sel_title).limit(1).get()[0]
                    df_ex = pd.read_excel(get_drive_url(ex_doc.to_dict()['excel_link']))
                    df_ex.columns = [str(c).strip().lower() for c in df_ex.columns]
                    all_s = db.collection('submissions').where('exercise_title', '==', sel_title).stream()
                    data_map = {acc: [] for acc in chosen}
                    for s in all_s:
                        d = s.to_dict()
                        if d['student_email'] in chosen:
                            try:
                                n, t = map(int, d.get('score_raw', '0/0').split('/'))
                                d['calculated_score'] = n * 5
                            except: d['calculated_score'] = 0
                            data_map[d['student_email']].append(d)
                    summary, wrong_stats = [], {i: set() for i in range(len(df_ex))}
                    for acc in chosen:
                        subs = data_map[acc]
                        if subs:
                            scores = [s['calculated_score'] for s in subs]
                            summary.append({'Học sinh': all_users.get(acc, acc), 'Thấp nhất': min(scores), 'Cao nhất': max(scores)})
                            latest = max(subs, key=lambda x: x['submitted_at'])
                            ans_dict = latest.get('user_answers', {})
                            for i, row in df_ex.iterrows():
                                ck = str(row.get('correct_ans', '')).strip().upper()
                                mapping = {clean_nan(row.get('opt_a')):'A', clean_nan(row.get('opt_b')):'B', clean_nan(row.get('opt_c')):'C', clean_nan(row.get('opt_d')):'D'}
                                if mapping.get(ans_dict.get(str(i))) != ck: wrong_stats[i].add(all_users.get(acc, acc))
                    if summary:
                        df_s, max_p = pd.DataFrame(summary), len(df_ex) * 5
                        st.markdown(f"#### 📊 Thống kê điểm (Max: {max_p})")
                        c_l, c_h = st.columns(2)
                        chart_low = alt.Chart(df_s).mark_bar(color='#90caf9').encode(x=alt.X('Học sinh:N', title=None), y=alt.Y('Thấp nhất:Q', scale=alt.Scale(domain=[0, max_p]), title="Điểm")).properties(title="📉 Lần thấp nhất")
                        chart_high = alt.Chart(df_s).mark_bar(color='#1565c0').encode(x=alt.X('Học sinh:N', title=None), y=alt.Y('Cao nhất:Q', scale=alt.Scale(domain=[0, max_p]), title="Điểm")).properties(title="🏆 Lần cao nhất")
                        c_l.altair_chart(chart_low, use_container_width=True); c_h.altair_chart(chart_high, use_container_width=True)
                        st.markdown("#### 🎯 Phân tích chi tiết câu sai")
                        cl, cr = st.columns([1, 1.5])
                        q_errs = sorted([(i, len(ems)) for i, ems in wrong_stats.items() if ems], key=lambda x: x[1], reverse=True)
                        if q_errs:
                            with cl:
                                sq = st.radio("Câu:", [f"Câu {i+1} ({c} bạn sai)" for i, c in q_errs], label_visibility="collapsed")
                                idx = int(sq.split(" ")[1]) - 1
                            with cr:
                                r = df_ex.iloc[idx]
                                with st.container(border=True):
                                    if 'audio' in df_ex.columns and clean_nan(r.get('audio')) != " ": display_drive_audio(r.get('audio'))
                                    ctx = clean_nan(r.get('context'))
                                    for p in ctx.split(";;"):
                                        if p.strip().startswith("http"): display_drive_image(p.strip())
                                        else: st.markdown(f"*{p.strip()}*")
                                    st.markdown(f"**Câu {idx+1}: {clean_nan(r.get('question'))}**")
                                    ck = str(r.get('correct_ans')).strip().upper()
                                    st.success(f"✅ Đáp án đúng: {ck}. {clean_nan(r.get(f'opt_{ck.lower()}'))}")
                                    st.error(f"❌ Các bạn đang sai: {', '.join(wrong_stats[idx])}")

def student_page():
    st.sidebar.button("Đăng xuất", on_click=logout)
    u_acc = st.session_state.user['account']
    st.title(f"👋 Xin chào, {st.session_state.user.get('full_name', 'Học viên')}!")
    st.divider()

    if st.session_state.view_mode == 'list':
        all_subs = [s.to_dict() for s in db.collection('submissions').where('student_email', '==', u_acc).stream()]
        exs_stream = db.collection('exercises').where('assigned_to', 'array_contains', u_acc).stream()
        ex_list = []
        for doc in exs_stream:
            ex_data, ex_id = doc.to_dict(), doc.id
            history = [s for s in all_subs if s.get('exercise_title') == ex_data['title']]
            ex_list.append({'data': ex_data, 'id': ex_id, 'history': history, 'is_done': len(history) > 0, 'has_draft': db.collection('drafts').document(f"{u_acc}_{ex_id}").get().exists, 'created_at': ex_data.get('created_at', datetime.min)})

        sort_opt = st.selectbox("Sắp xếp:", ["Mới nhất", "Ưu tiên chưa làm"], label_visibility="collapsed")
        if sort_opt == "Mới nhất": ex_list.sort(key=lambda x: x['created_at'], reverse=True)
        else: ex_list.sort(key=lambda x: (x['is_done'], -x['created_at'].timestamp() if hasattr(x['created_at'], 'timestamp') else 0))

        for item in ex_list:
            ex, ex_id, history = item['data'], item['id'], item['history']
            with st.container(border=True):
                c1, c2 = st.columns([4, 1.5])
                with c1:
                    st.subheader(f"{ex['type']} - {ex['title']}")
                    date_str = item['created_at'].strftime("%d/%m/%Y") if hasattr(item['created_at'], 'strftime') else "N/A"
                    if item['has_draft'] and not item['is_done']: st.warning(f"📅 Giao: `{date_str}` | 🟠 *Đang làm dở - Tự động lưu bài*")
                    elif history:
                        scs = [int(s.get('score_raw','0/0').split('/')[0]) for s in history]
                        st.markdown(f"📅 Giao: `{date_str}` | 🔢 Lần làm: `{len(history)}` | 📉 Thấp nhất: `{min(scs)*5}đ` | 🏆 Cao nhất: `{max(scs)*5}đ` / {int(history[0].get('score_raw','').split('/')[-1])*5}đ")
                    else: st.markdown(f"📅 Giao: `{date_str}` | 🆕 **Chưa làm**")
                with c2:
                    st.button("Làm bài ➔", key=f"btn_{ex_id}", on_click=start_lesson_callback, args=(ex, ex_id), use_container_width=True)
                    if history and ex.get('review_permissions', {}).get(u_acc, False):
                        st.button("Xem lại 🧐", key=f"rev_{ex_id}", on_click=start_review_direct_callback, args=(ex, ex_id, history), use_container_width=True)

    elif st.session_state.view_mode == 'quiz':
        st.subheader(f"✍️ {st.session_state.current_ex_info['title']}")
        if st.button("⬅ Thoát"): st.session_state.view_mode = 'list'; st.rerun()
        df = st.session_state.current_df
        df['ctx_tmp'] = df['context'].fillna('').astype(str).str.strip()
        df['aud_tmp'] = df['audio'].fillna('').astype(str).str.strip() if 'audio' in df.columns else ""
        df['group'] = ((df['ctx_tmp'] != df['ctx_tmp'].shift()) | (df['aud_tmp'] != df['aud_tmp'].shift())).cumsum()
        
        for g_id, group_df in df.groupby('group'):
            first = group_df.iloc[0]
            if str(first.get('aud_tmp')).strip() != "": display_drive_audio(first.get('aud_tmp'))
            
            gid_str = str(g_id)
            # DÙNG KEY ĐỂ STREAMLIT TỰ NẠP TỪ SESSION STATE
            note_input = st.text_area("📝 Ghi chú / Chiến thuật (Tự động lưu khi nhấn ra ngoài):", key=f"note_quiz_{st.session_state.current_ex_id}_{gid_str}", height=150, max_chars=500)
            
            # Chỉ lưu khi nội dung thay đổi thực sự
            if note_input != st.session_state.user_notes.get(gid_str, ""):
                st.session_state.user_notes[gid_str] = note_input
                save_note(u_acc, st.session_state.current_ex_id, g_id, note_input)
                st.toast("Đã lưu ghi chú!", icon="💾")
            
            ctx, l, r_col = clean_nan(first.get('context')), *st.columns([1, 1])
            with l:
                with st.container(height=900):
                    for p in ctx.split(";;"):
                        if p.strip().startswith("http"): display_drive_image(p.strip())
                        else: st.markdown(f'<div class="context-display">{p.strip()}</div>', unsafe_allow_html=True)
            with r_col:
                with st.container(height=900):
                    for i, r in group_df.iterrows():
                        st.write(f"**Câu {i+1}: {clean_nan(r.get('question'))}**")
                        opts = [clean_nan(r.get(f'opt_{let}')) for let in ['a','b','c','d'] if clean_nan(r.get(f'opt_{let}')) != " " and clean_nan(r.get(f'opt_{let}')).upper() != "NONE"]
                        cur_v = st.session_state.user_answers.get(i)
                        sel = st.radio(f"q{i}", opts, key=f"r_{st.session_state.current_ex_id}_{i}", index=opts.index(cur_v) if cur_v in opts else None, label_visibility="collapsed")
                        if sel != cur_v:
                            st.session_state.user_answers[i] = sel
                            save_draft(u_acc, st.session_state.current_ex_id, st.session_state.user_answers)
                        st.write("---")
            st.divider()
        if st.button("Nộp bài 🏁", use_container_width=True, type="primary"):
            correct = sum(1 for i, r in df.iterrows() if {clean_nan(r.get('opt_a')):'A', clean_nan(r.get('opt_b')):'B', clean_nan(r.get('opt_c')):'C', clean_nan(r.get('opt_d')):'D'}.get(st.session_state.user_answers.get(i)) == str(r.get('correct_ans','')).strip().upper())
            st.session_state.res = f"{correct}/{len(df)}"
            db.collection('submissions').add({'student_email':u_acc, 'exercise_title':st.session_state.current_ex_info['title'], 'score_raw':st.session_state.res, 'user_answers': {str(k): v for k, v in st.session_state.user_answers.items()}, 'submitted_at':datetime.now()})
            delete_draft(u_acc, st.session_state.current_ex_id)
            st.session_state.view_mode = 'res'; st.rerun()

    elif st.session_state.view_mode == 'res':
        n, t = map(int, st.session_state.res.split('/'))
        st.balloons(); st.title(f"🎉 Kết quả: {n*5} / {t*5} điểm")
        if st.button("XEM LẠI ĐÁP ÁN (REVIEW)"): st.session_state.view_mode = 'review'; st.rerun()
        if st.button("QUAY LẠI TRANG CHỦ"): st.session_state.view_mode = 'list'; st.rerun()

    elif st.session_state.view_mode == 'review':
        st.title("🧐 Review đáp án chi tiết")
        if st.button("⬅ Quay lại danh sách"): st.session_state.view_mode = 'list'; st.rerun()
        df = st.session_state.current_df
        df['ctx_tmp'] = df['context'].fillna('').astype(str).str.strip()
        df['aud_tmp'] = df['audio'].fillna('').astype(str).str.strip() if 'audio' in df.columns else ""
        df['group'] = ((df['ctx_tmp'] != df['ctx_tmp'].shift()) | (df['aud_tmp'] != df['aud_tmp'].shift())).cumsum()
        
        for g_id, group_df in df.groupby('group'):
            first = group_df.iloc[0]
            if str(first.get('aud_tmp')).strip() != "": display_drive_audio(first.get('aud_tmp'))
            
            gid_str = str(g_id)
            note_rev = st.text_area("📝 Ghi chú của bạn:", key=f"note_rev_{st.session_state.current_ex_id}_{gid_str}", height=150, max_chars=500)
            if note_rev != st.session_state.user_notes.get(gid_str, ""):
                st.session_state.user_notes[gid_str] = note_rev
                save_note(u_acc, st.session_state.current_ex_id, g_id, note_rev)
                st.toast("Đã cập nhật ghi chú!", icon="💾")
            
            ctx, l_rev, r_rev = clean_nan(first.get('context')), *st.columns([1, 1])
            with l_rev:
                with st.container(height=900):
                    for p in ctx.split(";;"):
                        if p.strip().startswith("http"): display_drive_image(p.strip())
                        else: st.markdown(f'<div class="context-display">{p.strip()}</div>', unsafe_allow_html=True)
            with r_rev:
                with st.container(height=900):
                    for i, r in group_df.iterrows():
                        st.write(f"**Câu {i+1}: {clean_nan(r.get('question'))}**")
                        u_ans, ck_let = st.session_state.user_answers.get(i), str(r.get('correct_ans')).strip().upper()
                        opts = {'A': clean_nan(r.get('opt_a')), 'B': clean_nan(r.get('opt_b')), 'C': clean_nan(r.get('opt_c')), 'D': clean_nan(r.get('opt_d'))}
                        for let, txt in opts.items():
                            if txt == " " or (let == 'D' and txt.upper() == "NONE"): continue
                            is_cor, is_mi = (let == ck_let), (txt == u_ans)
                            if is_cor and is_mi: st.markdown(f'<div class="correct-box">✅ <b>{let}. {txt}</b> (Bạn chọn đúng)</div>', unsafe_allow_html=True)
                            elif is_cor and not u_ans: st.markdown(f'<div class="warning-box">⚠️ <b>{let}. {txt}</b> (Đáp án đúng - Bạn bỏ trống)</div>', unsafe_allow_html=True)
                            elif is_cor: st.markdown(f'<div class="correct-box">🟢 <b>{let}. {txt}</b> (Đáp án đúng)</div>', unsafe_allow_html=True)
                            elif is_mi: st.markdown(f'<div class="wrong-box">❌ <b>{let}. {txt}</b> (Bạn chọn sai)</div>', unsafe_allow_html=True)
                            else: st.markdown(f'<div class="normal-box">{let}. {txt}</div>', unsafe_allow_html=True)
                        if 'transcript' in df.columns and clean_nan(r.get('transcript')) != " ":
                            st.markdown(f'<div class="transcript-box">📝 <b>Transcript:</b><br>{clean_nan(r.get("transcript"))}</div>', unsafe_allow_html=True)
                        st.write("---")
            st.divider()
        st.button("XONG", on_click=lambda: st.session_state.update({"view_mode":"list"}), use_container_width=True)

# --- 7. ĐIỀU HƯỚNG ---
if st.session_state.user is None: login_page()
else: teacher_page() if st.session_state.user.get('role') == 'teacher' else student_page()
