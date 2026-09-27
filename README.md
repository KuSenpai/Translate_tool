# Novel Translator

Công cụ web chạy local để xử lý và đăng chương truyện dịch Hàn → Việt:

```
Word (.docx) → tìm chương → tách bản Hàn + bản Việt → sửa (có AI gợi ý + glossary)
→ Preview → Save DOCX → Publish lên Wattpad
```

## Cài đặt (Windows)

```bash
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

> Nếu `pip` trong venv báo lỗi SSL (`CERTIFICATE_VERIFY_FAILED`), cài bằng pip của Python hệ thống:
> `py -3.11 -m pip --python "<đường dẫn tuyệt đối>\.venv\Scripts\python.exe" install -r requirements.txt`

Playwright dùng Edge/Chrome có sẵn trên máy (`WATTPAD_BROWSER_CHANNEL=msedge`). Muốn dùng Chromium riêng:
`.venv\Scripts\python -m playwright install chromium` rồi đặt `WATTPAD_BROWSER_CHANNEL=`.

## Chạy

```bash
.venv\Scripts\python -m app.main
```

Mở http://127.0.0.1:8765 (hoặc chạy `run.bat`).

## Cách dùng

1. **Mở file Word**: kéo thả `.docx`, hoặc nhập đường dẫn (mở bằng đường dẫn luôn đọc bản mới nhất của file; file gốc không bao giờ bị ghi).
2. **Chọn chương**: nhập số chương hoặc bấm vào danh sách. Màu: xanh = đủ Hàn + Việt, vàng = có cảnh báo, đỏ = cần kiểm tra.
   Chương có độ tin cậy thấp (thiếu heading, trùng số chương, ranh giới suy luận) bị khóa cho tới khi bạn xác nhận đã kiểm tra.
3. **Sửa bản Việt** bên phải, đối chiếu bản Hàn bên trái. `Ctrl+S` lưu draft, `Ctrl+Z/Ctrl+Y` undo/redo, `Reset` lấy lại bản gốc trong Word.
4. **AI**: bôi đen một đoạn → `✨ Suggest correction` → xem Original / Suggestion / Reason → `Apply` (hoặc bỏ qua). AI không bao giờ tự sửa bản dịch.
5. **Glossary**: `김수현 → Kim Soo-hyun`, `형 → anh`… (có thể thêm các cách viết cần tránh). Được gửi cho AI và dùng để kiểm tra ở tab *Lỗi*.
6. **Preview** → `Đánh dấu đã review` → `Save DOCX` (lưu vào `output/<tên-truyện>/Chapter_N.docx`).
7. **Wattpad**: `Đăng nhập Wattpad…` mở một cửa sổ trình duyệt để bạn **tự đăng nhập** (tool không đọc/lưu mật khẩu; phiên được giữ trong `data/wattpad_profile`).
   `Tải danh sách truyện` → chọn truyện → tick *I confirm this is the final version* → `Publish` (hoặc chỉ lưu nháp trên Wattpad).
   Thành công → tự lưu DOCX và chuyển trạng thái `PUBLISHED`. Thất bại → giữ `READY_TO_PUBLISH`, hiện lỗi; bấm lại để retry
   (phần đã tạo trên Wattpad được dùng lại, không tạo trùng).

Trạng thái chương: `LOADED → EDITING → REVIEWED → READY_TO_PUBLISH → PUBLISHED`. Sửa sau khi review sẽ quay về `EDITING`.

## Nhận diện chương

Heading phải là **cả một đoạn ngắn** khớp một trong các mẫu: `제 12 화`, `제12화`, `12화`, `제 12 장`, `Chương 12`, `CHƯƠNG 12: Tiêu đề`,
`Tập 12. Tiêu đề`, `Chapter 12`, `Ch. 12`, `EP.12 12. Tiêu đề`, `1920. Tiêu đề`… Số xuất hiện trong câu văn ("năm 12 tuổi",
"chương 12 của đời anh") không bị coi là heading. Dạng `1920. Tiêu đề` và dòng chỉ có số (`2151`) chỉ được nhận khi số chương
khớp thứ tự với các heading xung quanh; dòng bị loại được ghi trong cảnh báo. Rác dính trước heading (`Ads by Pubfuture`,
`Interrupted`) được bỏ qua (xem `NOISE_PREFIX`).

File lớn (hàng chục nghìn đoạn) mất khoảng 20 giây ở lần đọc đầu; kết quả được cache trong `data/projects/<id>/parsed.pkl`
nên các lần mở sau gần như tức thì (cache tự làm mới khi file Word thay đổi).
Ngôn ngữ của mỗi phần được xác định theo nội dung (tỉ lệ chữ Hangul), không chỉ theo heading.
Thêm mẫu mới trong `HEADING_PATTERNS` ở `app/document/chapter_parser.py`.

## Cấu trúc

```
app/
  document/    docx_reader, chapter_parser, docx_writer, models   (không phụ thuộc UI/Wattpad)
  editor/      chapter_editor (workflow), chapter_state, glossary, validation
  ai/          llm_service (Anthropic | OpenAI | local | mock), correction_service
  publishing/  wattpad_publisher (Playwright), wattpad_worker (subprocess), jobs, publish_service,
               wattpad_selectors.json
  storage/     project_state (JSON trong data/projects/)
  static/      UI (HTML/CSS/JS thuần)
tests/         pytest + fake_wattpad (site giả lập để test publisher) + make_sample (tạo book.docx mẫu)
```

## Đăng lên Wattpad bằng extension (mặc định)

Tool không điều khiển được Edge bạn đang dùng hằng ngày (Edge chặn tự động hoá profile chính), nên việc
đăng được làm bởi một extension nhỏ chạy ngay trong Edge đó — dùng luôn đăng nhập Wattpad (Google/Facebook)
và VPN của bạn.

**Cài một lần:**
1. Mở `edge://extensions`, bật **Developer mode** (góc trái dưới).
2. Bấm **Load unpacked** → chọn thư mục `extension` trong thư mục tool (`D:\Tool dịch\Translate_tool\extension`).
3. Mở tool ở `http://127.0.0.1:8765` **trong chính Edge đó**.

**Dùng:**
- Preview → **Mở Wattpad (Edge của bạn)** / **↻ Lấy danh sách từ My Works**: mở My Works trong tab mới; extension gửi
  danh sách truyện về tool.
- Chọn truyện, tick xác nhận, **Publish** → tool mở tab Wattpad; extension mở truyện → New Part → điền tiêu đề + nội dung
  → lưu → đếm ngược 5 giây (bấm **Huỷ** trên khung thông báo nếu muốn dừng) → Publish → báo kết quả về tool.
- Nút extension trên thanh công cụ: xem trạng thái kết nối, đổi địa chỉ tool, **Gửi chẩn đoán trang** (lưu cấu trúc
  trang Wattpad vào `data/logs/wattpad/` để sửa khi Wattpad đổi giao diện).
- Nhãn nút / selector nằm ở mục `"ext"` trong `app/publishing/wattpad_selectors.json`; extension đọc trực tiếp từ tool nên
  sửa file này không cần cài lại extension.

Extension chỉ nói chuyện với tool trên máy (`127.0.0.1`), không đọc mật khẩu hay cookie. API của nó (`/api/ext/*`) chỉ
nhận request có header riêng của extension, các trang web khác không gọi được.

Muốn dùng lại cách cũ (cửa sổ Edge tự động riêng): đặt `WATTPAD_MODE=playwright` trong `.env`.

## Test

```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m tests.make_sample      # tạo samples/book.docx
.venv\Scripts\python -m tests.demo_server      # app + Wattpad giả lập ở http://127.0.0.1:8766
```

Log: `data/logs/app.log` (không ghi mật khẩu, API key, cookie). Ảnh chụp khi Wattpad lỗi: `data/logs/wattpad/`.
