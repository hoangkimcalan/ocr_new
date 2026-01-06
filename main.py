import re
import time
import xml.etree.ElementTree as ET

import easyocr
import uiautomator2 as u2

from crawl_message.crawl_msg import crawl_history_with_scroll
from utils.config import Config
from utils.helper import (find_recycler_view, get_all_text_from_node_recursive,
                          get_facebook_id_via_ocr, is_bounds_inside_image,
                          jump_to_chat_by_id, navigate_to_profile_popup,
                          parse_bounds, send_messages, setup_logging)

log = setup_logging()
CFG = Config()

# Pre-compile regex (nhanh + gọn)
TIMESTAMP_RE = re.compile(CFG.timestamp_regex)
CLEAN_TIME_RE = re.compile(CFG.clean_time_regex)

log.info("Kết nối thiết bị qua uiautomator2...")
d = u2.connect()

# =========================
# INIT
# =========================
log.info("Đang tải model OCR (đợi tí)...")
reader = easyocr.Reader(list(CFG.ocr_langs))

# =========================
# ENTRYPOINT
# =========================
def main() -> None:
    # --- BƯỚC 1: Lấy UUID trước (từ profile popup)
    if not navigate_to_profile_popup(d, log):
        log.error("Không thể điều hướng tới popup để lấy UUID. Dừng luồng.")
        return

    user_id = get_facebook_id_via_ocr(d, reader, log)
    if not user_id:
        log.error("Không lấy được UUID. Dừng luồng.")
        return

        # Đợi chat load
    time.sleep(5)

    # --- BƯỚC 2: NHẢY VÀO KHUNG CHAT (BẮT BUỘC TRƯỚC KHI CRAWL) ---
    # Phải vào chat thì mới thấy tin nhắn để crawl
    if not jump_to_chat_by_id(d, user_id, log):
        log.error("Không thể nhảy vào khung chat. Dừng luồng.")
        return

    # Chờ load lịch sử chat cũ
    time.sleep(3)

    # --- BƯỚC 3: Đọc tin nhắn (Crawl 2-3 màn hình)
    # scroll_times=2 nghĩa là lấy màn hình hiện tại + scroll lên 2 lần nữa (Tổng 3 màn hình)
    history_data = crawl_history_with_scroll(scroll_times=2)
    # In kết quả ra console để kiểm tra
    print("\n" + "="*40)
    print(f"HỘI THOẠI VỚI: {user_id}")
    print("="*40)
    for msg in history_data:
        role = "Khách" if msg['sender'] == "THEM" else "Page "
        print(f"[{role}]: {msg['content']}")
    print("="*40 + "\n")

    # --- BƯỚC 4: GỬI TIN NHẮN (LOGIC TRẢ LỜI) ---
    # Ví dụ: Nếu khách hỏi giá, gửi báo giá. Ở đây demo gửi list tin.

    log.info("Bắt đầu gửi tin nhắn phản hồi...")
    send_success = send_messages(
        d,
        log,
        messages=["hello", "xin chao", "da crawl xong history", "bye bye"],
        delay_between_sends_s=0.5
    )

    if not send_success:
        log.error("Gửi tin nhắn thất bại.")

    # Đợi xíu trước khi kết thúc
    time.sleep(2)

if __name__ == "__main__":
    main()
