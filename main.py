# --- SỬA LẠI PHẦN IMPORT (QUAN TRỌNG) ---
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import FieldPath # Thêm dòng này để sửa lỗi FieldPath
import pandas as pd
# ... (các import khác giữ nguyên)

# --- CẬP NHẬT HÀM GET_NOTES (Sửa lỗi mất Note) ---
def get_notes(u_acc, ex_id):
    notes = {}
    try:
        prefix = f"{u_acc}_{ex_id}_"
        # Sử dụng FieldPath.document_id() từ thư viện vừa import
        docs = db.collection('notes').where(FieldPath.document_id(), '>=', prefix).where(FieldPath.document_id(), '<=', prefix + '\uf8ff').stream()
        
        for doc in docs:
            # Tách ID để lấy số nhóm (group_id) ở cuối
            # Ví dụ: "dang@gmail.com_ex123_1" -> lấy số 1
            parts = doc.id.split('_')
            if parts:
                gid_str = parts[-1]
                if gid_str.isdigit():
                    notes[int(gid_str)] = doc.to_dict().get('content', "")
    except Exception as e:
        # Không dùng st.error ở đây để tránh hiện thông báo lỗi đỏ làm học sinh hoảng
        print(f"Lỗi nạp ghi chú: {e}") 
    return notes

# --- CẬP NHẬT HÀM SAVE_NOTE (Đảm bảo ID chuẩn) ---
def save_note(u_acc, ex_id, g_id, text):
    if not ex_id: return
    note_id = f"{u_acc}_{ex_id}_{g_id}"
    db.collection('notes').document(note_id).set({
        'content': text, 
        'updated_at': firestore.SERVER_TIMESTAMP
    })

# --- ĐIỀU CHỈNH CALLBACKS ĐỂ LIÊN KẾT DỮ LIỆU ---
def start_lesson_callback(ex, ex_id):
    try:
        df = pd.read_excel(get_drive_url(ex['excel_link']))
        df.columns = [str(c).strip().lower() for c in df.columns]
        st.session_state.current_df = df
        st.session_state.current_ex_info = ex
        st.session_state.current_ex_id = ex_id # Luôn giữ ID bài tập
        st.session_state.view_mode = 'quiz'
        
        acc = st.session_state.user['account']
        st.session_state.user_answers = get_draft(acc, ex_id)
        # Nạp Note ngay khi mở bài
        st.session_state.user_notes = get_notes(acc, ex_id)
    except Exception as e:
        st.error(f"Lỗi: {e}")

def start_review_direct_callback(ex, ex_id, history):
    try:
        df = pd.read_excel(get_drive_url(ex['excel_link']))
        df.columns = [str(c).strip().lower() for c in df.columns]
        st.session_state.current_df = df
        st.session_state.current_ex_id = ex_id
        
        latest_sub = max(history, key=lambda x: x['submitted_at'])
        st.session_state.user_answers = {int(k): v for k, v in latest_sub.get('user_answers', {}).items()}
        # Nạp lại Note để học sinh xem lại
        st.session_state.user_notes = get_notes(st.session_state.user['account'], ex_id)
        st.session_state.view_mode = 'review'
    except Exception as e:
        st.error(f"Lỗi Review: {e}")

# --- PHẦN HIỂN THỊ TRONG QUIZ/REVIEW (Auto-save & Toast) ---
# Thầy tìm đoạn st.text_area và cập nhật:
curr_note = st.session_state.user_notes.get(g_id, "")
note_input = st.text_area(
    "📝 Ghi chú / Chiến thuật (Tự động lưu khi nhấn ra ngoài):", 
    value=curr_note, 
    key=f"note_{g_id}", 
    height=150, 
    max_chars=500
)

# Logic lưu tự động không cần Ctrl+Enter
if note_input != curr_note:
    st.session_state.user_notes[g_id] = note_input
    save_note(u_acc, st.session_state.current_ex_id, g_id, note_input)
    st.toast("Đã lưu ghi chú!", icon="💾")
