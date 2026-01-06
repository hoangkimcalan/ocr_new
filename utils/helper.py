import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Iterable, Optional, Tuple, Union

from utils.config import Config

CFG = Config()


# =========================
# LOGGING (log chung)
# =========================
def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Console logger, format rõ ràng để thay print().
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("ocr")


# =========================
# XML helpers
# =========================
def parse_bounds(bounds_str: Optional[str]) -> Tuple[int, int, int, int]:
    """
    Parse bounds dạng: "[l,t][r,b]" -> (l,t,r,b)
    """
    if not bounds_str:
        return (0, 0, 0, 0)
    nums = re.findall(r"\d+", bounds_str)
    if len(nums) == 4:
        l, t, r, b = map(int, nums)
        return (l, t, r, b)
    return (0, 0, 0, 0)


def get_all_text_from_node_recursive(node: ET.Element) -> str:
    """
    Gom toàn bộ text + content-desc của node và con.
    Dedup cơ bản để giảm rác.
    """
    texts: list[str] = []

    def add_if_ok(s: str) -> None:
        s = (s or "").strip()
        if not s:
            return
        if s not in texts:
            texts.append(s)

    add_if_ok(node.attrib.get("text", ""))
    desc = node.attrib.get("content-desc", "")
    if desc and desc != node.attrib.get("text", ""):
        add_if_ok(desc)

    for child in node.iter():
        add_if_ok(child.attrib.get("text", ""))
        cdesc = child.attrib.get("content-desc", "")
        if cdesc and cdesc != child.attrib.get("text", ""):
            add_if_ok(cdesc)

    return " ".join(texts).strip()


def find_recycler_view(root: ET.Element) -> Optional[ET.Element]:
    for elem in root.iter():
        if CFG.recycler_class_contains in elem.attrib.get("class", ""):
            return elem
    return None


def is_bounds_inside_image(l: int, t: int, r: int, b: int, img) -> bool:
    h, w = img.shape[:2]
    return l >= 0 and t >= 0 and r <= w and b <= h and r > l and b > t


# =========================
# UIAutomator helpers (uuid flow)
# =========================
def safe_click_xpath(
    d,
    xpath: str,
    log: logging.Logger,
    *,
    timeout_s: float = 10.0,
    post_sleep_s: float = 0.0,
) -> bool:
    try:
        if d.xpath(xpath).wait(timeout=timeout_s):
            d.xpath(xpath).click()
            if post_sleep_s:
                time.sleep(post_sleep_s)
            return True
        log.warning("XPath không xuất hiện trong %.1fs: %s", timeout_s, xpath)
        return False
    except Exception as e:
        log.exception("Click xpath fail: %s | %s", xpath, e)
        return False


def find_popup_elem(d):
    for marker in CFG.popup_text_markers:
        elem = d(textContains=marker)
        if elem.exists:
            return elem
    return None


def crop_popup_screenshot(d, bounds: dict, log: logging.Logger):
    try:
        screenshot = d.screenshot(format="opencv")
    except Exception as e:
        log.exception("Không chụp được screenshot (opencv): %s", e)
        return None

    h, w = screenshot.shape[:2]
    left = max(0, min(int(bounds["left"]), w - 1))
    top = max(0, min(int(bounds["top"]), h - 1))
    right = max(0, min(int(bounds["right"]), w))
    bottom = max(0, min(int(bounds["bottom"]), h))

    if right <= left or bottom <= top:
        log.warning("Bounds crop không hợp lệ: %s", bounds)
        return None

    return screenshot[top:bottom, left:right]


# Regex extract user id from OCR popup
_FB_FROM_DOMAIN_RE = re.compile(
    r"facebook[\s\.]*com[\s\/]+(.*?)(?=\sSao|\s*$)", re.IGNORECASE
)
_FB_ID_PARAM_RE = re.compile(r"\bid[\s=]+(\d+)\b", re.IGNORECASE)


def extract_facebook_id_from_ocr_text(text: str) -> Optional[str]:
    normalized = " ".join((text or "").split())

    m = _FB_FROM_DOMAIN_RE.search(normalized)
    if m:
        raw = m.group(1)
        final_id = raw.replace(" ", "").strip().rstrip(".")
        if final_id:
            return final_id

    m2 = _FB_ID_PARAM_RE.search(normalized)
    if m2:
        return m2.group(1)

    return None


def navigate_to_profile_popup(d, log: logging.Logger) -> bool:
    """
    Luồng: mở chi tiết thread -> tab Trang cá nhân -> mở popup link
    """
    # step 1
    try:
        if d(description=CFG.thread_detail_desc).exists:
            log.info(
                "Mở chi tiết chuỗi bài (description=%s)...", CFG.thread_detail_desc
            )
            d(description=CFG.thread_detail_desc).click()
        else:
            log.info("Mở chi tiết chuỗi bài (resourceId=%s)...", CFG.thread_title_resid)
            d(resourceId=CFG.thread_title_resid).click()
    except Exception as e:
        log.exception("Lỗi bước 1: %s", e)
        return False

    time.sleep(CFG.sleep_after_open_detail_s)

    # step 2
    log.info("Mở Trang cá nhân...")
    if not safe_click_xpath(
        d,
        CFG.profile_tab_xpath,
        log,
        timeout_s=10.0,
        post_sleep_s=CFG.sleep_after_open_profile_s,
    ):
        log.error("Lỗi bước 2: không click được Trang cá nhân.")
        return False

    # step 3
    log.info("Mở popup liên kết...")
    if not safe_click_xpath(
        d,
        CFG.open_popup_xpath,
        log,
        timeout_s=10.0,
        post_sleep_s=CFG.sleep_after_open_popup_s,
    ):
        log.error("Lỗi bước 3: không mở được popup.")
        return False

    return True


def get_facebook_id_via_ocr(d, reader, log: logging.Logger) -> Optional[str]:
    """
    OCR trong popup để lấy username/uid.
    """
    log.info("BẮT ĐẦU QUÉT ID TỪ POPUP (OCR)")
    start = time.time()

    elem = find_popup_elem(d)
    if not elem:
        log.error("Không tìm thấy popup (marker text).")
        return None

    try:
        bounds = elem.info["bounds"]
    except Exception as e:
        log.exception("Không lấy được bounds của popup: %s", e)
        return None

    crop_img = crop_popup_screenshot(d, bounds, log)
    if crop_img is None:
        return None

    try:
        lines = reader.readtext(crop_img, detail=0)
    except Exception as e:
        log.exception("OCR lỗi khi đọc popup: %s", e)
        return None

    full_text = " ".join(lines).strip()
    log.debug("Popup OCR raw: %s", full_text)

    user_id = extract_facebook_id_from_ocr_text(full_text)
    log.info("OCR elapsed: %.2fs", time.time() - start)

    if user_id:
        log.info("ID DATABASE CHUẨN: %s", user_id)
        return user_id

    log.warning("Không tìm thấy ID (regex không khớp).")
    return None


def jump_to_chat_by_id(d, user_id: str, log: logging.Logger) -> bool:
    """
    Chỉ thực hiện Deep Link để mở khung chat với user_id.
    Trả về True nếu thấy ô nhập tin nhắn xuất hiện.
    """
    log.info("Đang nhảy tới khung chat của: %s", user_id)

    url = f"https://m.me/{user_id}"
    # com.facebook.orca là package của Messenger, giúp tránh mở nhầm bằng Chrome
    cmd = f'am start -a android.intent.action.VIEW -d "{url}" com.facebook.orca'

    try:
        d.shell(cmd)
    except Exception as e:
        log.exception("Lỗi shell deeplink: %s", e)
        return False

    log.info("Đang chờ Messenger load giao diện chat...")

    # Chờ ô nhập tin nhắn xuất hiện
    if d.xpath(CFG.chat_input_xpath).wait(timeout=CFG.wait_ui_timeout_s):
        log.info("Đã vào khung chat thành công.")
        time.sleep(1.0) # Chờ UI ổn định thêm chút
        return True
    else:
        log.error("Chờ %.0fs vẫn không thấy ô 'Nhắn tin'.", CFG.wait_ui_timeout_s)
        return False


def send_messages(
    d,
    log: logging.Logger,
    messages: Optional[Iterable[str]] = None,
    message: Optional[str] = None,
    delay_between_sends_s: float = 0.5
) -> bool:
    """
    Hàm chỉ thực hiện nhập và gửi tin nhắn (yêu cầu đang ở trong khung chat).
    """
    # 1. Chuẩn bị danh sách tin nhắn
    to_send: list[str] = []
    if messages is not None:
        to_send = [str(m) for m in messages if m is not None and str(m).strip() != ""]
    elif message is not None and str(message).strip() != "":
        to_send = [str(message)]

    if not to_send:
        log.warning("Không có nội dung tin nhắn nào để gửi.")
        return False

    try:
        # Focus vào ô nhập một lần đầu
        if d.xpath(CFG.chat_input_xpath).exists:
            d.xpath(CFG.chat_input_xpath).click()
            time.sleep(0.5)
        else:
            log.error("Không tìm thấy ô nhập tin nhắn để gửi.")
            return False

        # 2. Vòng lặp gửi từng tin
        for i, msg in enumerate(to_send, start=1):
            log.info("[Send %d/%d] Nhập: %r", i, len(to_send), msg)

            # Nhập text
            d.send_keys(msg)
            time.sleep(0.5) # Chờ nút gửi hiện ra/active

            log.info("[Send %d/%d] Bấm Gửi...", i, len(to_send))

            # Tìm nút gửi (Ưu tiên Description -> ResourceId -> Enter Key)
            if d(description="Gửi").exists:
                d(description="Gửi").click()
            elif d(description="Send").exists:
                d(description="Send").click()
            elif d(resourceId="com.facebook.orca:id/send_btn").exists:
                d(resourceId="com.facebook.orca:id/send_btn").click()
            else:
                log.warning("Không thấy nút Gửi -> Bấm phím Enter.")
                d.press("enter")

            time.sleep(delay_between_sends_s)

            # Click lại vào ô input để chắc chắn focus cho tin tiếp theo (phòng hờ)
            if i < len(to_send):
                d.xpath(CFG.chat_input_xpath).click()
                time.sleep(0.2)

        log.info("HOÀN TẤT GỬI %d TIN NHẮN.", len(to_send))
        return True

    except Exception as e:
        log.exception("Lỗi khi nhập/gửi tin nhắn: %s", e)
        return False
def _iter_descendants(node: ET.Element):
    # node.iter() bao gồm cả node hiện tại; mình muốn descendants cũng ok.
    for n in node.iter():
        yield n


def pick_message_bubble_bounds(
    item: ET.Element,
    *,
    screen_width: Optional[int] = None,
    max_width_ratio: float = 0.95,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Pick bounds của bubble/message node trong item.

    - Lọc node full-width (thường là container row) bằng max_width_ratio.
    - Ưu tiên node có diện tích lớn nhất trong nhóm còn lại.
    """
    best: Optional[Tuple[int, int, int, int]] = None
    best_area = 0

    for n in _iter_descendants(item):
        txt = (n.attrib.get("text") or "").strip()
        dsc = (n.attrib.get("content-desc") or "").strip()
        if not txt and not dsc:
            continue

        l, t0, r, b = parse_bounds(n.attrib.get("bounds"))
        w, h = (r - l), (b - t0)
        if w <= 0 or h <= 0:
            continue

        if h < 24 or w < 24:
            continue

        if screen_width and screen_width > 0:
            if (w / float(screen_width)) >= max_width_ratio:
                # loại container full row
                continue

        area = w * h
        if area > best_area:
            best_area = area
            best = (l, t0, r, b)

    return best


def classify_message_side_by_bounds(
    left: int,
    right: int,
    screen_width: int,
    *,
    near_edge_ratio: float = 0.08,
    my_edge_ratio: float = 0.92,
    my_side_threshold_ratio: float = 0.55,  # fallback bằng center
) -> str:
    """
    Phân loại tin nhắn theo vị trí bubble (robust hơn):
    - Nếu bubble chạm/gần mép phải => "me"
    - Nếu bubble chạm/gần mép trái => "other"
    - Nếu không rõ => dùng center fallback
    """
    if screen_width <= 0:
        return "unknown"

    l_ratio = left / float(screen_width)
    r_ratio = right / float(screen_width)

    # Ưu tiên check theo mép (ổn định hơn center khi bubble/container lệch)
    if r_ratio >= my_edge_ratio:
        return "me"
    if l_ratio <= near_edge_ratio:
        return "other"

    center_x = (left + right) / 2.0
    ratio = center_x / float(screen_width)
    return "me" if ratio >= my_side_threshold_ratio else "other"


def classify_message_side_from_item(item: ET.Element, screen_width: int) -> str:
    b = pick_message_bubble_bounds(item, screen_width=screen_width)
    if not b:
        return "unknown"
    left, _, right, _ = b
    return classify_message_side_by_bounds(left, right, screen_width)
