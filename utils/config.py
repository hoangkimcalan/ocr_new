from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    ocr_langs: tuple[str, ...] = ("vi", "en")
    min_item_height_px: int = 40

    # Regex nhận diện thời gian
    timestamp_regex: str = (
        r"(?i)^((TH\s\d|CN|T\d|HÔM\sNAY|HÔM\sQUA|\d{1,2}\sTHG\s\d{1,2})\s+LÚC\s+)?\d{1,2}:\d{2}$"
    )
    # Regex dùng để XÓA thời gian ra khỏi kết quả OCR
    clean_time_regex: str = (
        r"(?i)((TH\s\d|CN|T\d|HÔM\sNAY|HÔM\sQUA|\d{1,2}\sTHG\s\d{1,2})\s+LÚC\s+)?\d{1,2}:\d{2}"
    )

    # Detect chat list container
    recycler_class_contains: str = "RecyclerView"
    
    # =========================
    # UUID-from-profile flow
    # =========================
    thread_detail_desc: str = "Chi tiết chuỗi bài"
    thread_title_resid: str = "com.facebook.orca:id/thread_title_name"

    profile_tab_xpath: str = "//android.widget.HorizontalScrollView/android.view.ViewGroup[1]/android.view.ViewGroup[3]"
    open_popup_xpath: str = (
        '//*[@resource-id="android:id/content"]/android.widget.FrameLayout[1]/android.widget.LinearLayout[1]/'
        "android.widget.FrameLayout[1]/android.widget.LinearLayout[1]/android.widget.LinearLayout[1]/android.view.View[1]"
    )
    popup_text_markers: tuple[str, ...] = ("Liên kết riêng của", "facebook.com")

    # Sleeps / timeouts
    sleep_after_open_detail_s: float = 4.0
    sleep_after_open_profile_s: float = 4.0
    sleep_after_open_popup_s: float = 3.0
    sleep_after_click_copy_s: float = 1.0
    wait_ui_timeout_s: float = 15.0

    # Chat deeplink / UI
    chat_input_xpath: str = '//*[@text="Nhắn tin"]'