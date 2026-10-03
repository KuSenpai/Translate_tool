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

## Chạy (cả lần đầu và khi cập nhật tool)

```bash
git pull                                                    # nếu lấy bản mới từ git
.venv\Scripts\python -m pip install -r requirements.txt     # chỉ cần khi requirements.txt đổi
.venv\Scripts\python -m app.main
```

Mở http://127.0.0.1:8765 (hoặc double-click `run.bat`: tự mở trình duyệt và chạy server). Dừng bằng `Ctrl+C`.

**Cập nhật từ bản cũ:** giữ nguyên `.env` và thư mục `data/` (project, kho thuật ngữ, job dịch đang dở đều nằm ở đó).
So `.env.example` với `.env` của bạn và thêm các biến mới nếu cần (đều tuỳ chọn): `TRANSLATE_PROVIDER`,
`ANTIGRAVITY_MODEL_PRO`, `ANTIGRAVITY_MODEL_FLASH`, `ANTIGRAVITY_CLI_PATH`, `CLAUDE_CODE_PATH`.
Sau khi sửa `.env` phải khởi động lại tool. Muốn thử giao diện không tốn lượt/tiền: `TRANSLATE_PROVIDER=mock`.

## Tính năng chính

| Nút trên màn hình chính | Việc làm |
|---|---|
| Mở file Word → editor | Sửa bản Việt, AI gợi ý, glossary, Preview, Save DOCX, đăng Wattpad |
| 🤖 Dịch AI | Dịch cả truyện Hàn → Việt bằng Claude API, Claude Code (gói Pro/Max) hoặc Gemini (Antigravity) |
| 📚 Thuật ngữ | Kho thuật ngữ + ghi chú truyện, quét chương cũ bằng AI, kiểm tra nhất quán |
| 🧹 Xử lý data thô | Làm sạch bản dịch dán từ ChatGPT; tách raw tiếng Hàn chưa dịch |

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

## Dịch cả truyện bằng AI (🤖 Dịch AI)

1. Thêm `ANTHROPIC_API_KEY=sk-ant-...` vào `.env` (tạo key ở console.anthropic.com), khởi động lại tool.
2. Bấm **🤖 Dịch AI** → kéo thả file truyện tiếng Hàn `.txt` hoặc `.docx` (nhiều chương).
3. Chọn model (Opus 5.5 chất lượng cao nhất; Sonnet 5.5 rẻ ~2 lần; Haiku 4.5 rẻ nhất), khoảng chương, glossary,
   chỉnh **Hướng dẫn dịch** (văn phong, xưng hô, mức độ từ ngữ 18+) → **Bắt đầu dịch**. Có ước tính chi phí trước khi chạy
   và chi phí thật trong lúc chạy.
4. Kết quả `output/translations/<tên>_vi_<id>.docx` (+ `.txt` nếu đầu vào là .txt): mỗi chương tiếng Hàn, ngay dưới là bản
   dịch — đúng định dạng editor đọc được (**Mở trong editor** để soát và sửa, rồi đăng Wattpad như bình thường).

- Chạy nền, lưu sau từng chương: tạm dừng / tiếp tục / dịch lại chương lỗi; tắt tool rồi mở lại vẫn tiếp tục được.
- Chương đã có bản Việt (file song ngữ dịch dở) được bỏ qua.
- Tên nhân vật/thuật ngữ mới được AI ghi lại và dùng cho các chương sau để nhất quán.
- Prompt cho phép dịch đầy đủ nội dung 18+ và từ thô tục giữa các nhân vật trưởng thành. Claude vẫn có thể từ chối một số
  đoạn (ví dụ nội dung tình dục liên quan đến trẻ vị thành niên); chương đó được đánh dấu lỗi `AI_REFUSED` và giữ nguyên
  bản Hàn trong file kết quả.

### Dùng gói Claude (Pro/Max) thay cho API

Chọn model **Claude Code · Opus** hoặc **Claude Code · Sonnet** (ở 🤖 Dịch AI và 📚 Thuật ngữ): tool gọi lệnh `claude -p`
trên máy — trừ vào lượt dùng của gói Claude, **không tính tiền API**, không cần `ANTHROPIC_API_KEY`.
1. Cài Claude Code (nếu chưa có): `npm install -g @anthropic-ai/claude-code`
2. Đăng nhập một lần bằng tài khoản có gói: `claude auth login --claudeai`
3. Khi gói hết lượt, job tự **tạm dừng** (chương đang dịch quay lại hàng chờ) → bấm **Tiếp tục** khi gói được làm mới.

Tool xoá `ANTHROPIC_API_KEY` khỏi môi trường khi gọi `claude`, nên không bao giờ bị tính tiền API ở chế độ này.
Đường dẫn khác: đặt `CLAUDE_CODE_PATH` trong `.env`.

### Dịch bằng Gemini qua Antigravity

Chọn model **Antigravity · Gemini Pro** hoặc **Antigravity · Gemini Flash** (ở 🤖 Dịch AI và 📚 Thuật ngữ): tool gọi
Antigravity CLI (`agy`) ở chế độ headless — dùng hạn mức của tài khoản Google đăng nhập Antigravity, **không tính tiền API**.
1. Cài Antigravity CLI (PowerShell): `irm https://antigravity.google/cli/install.ps1 | iex`
2. Chạy `agy` một lần trong terminal để đăng nhập Google, thoát ra (Ctrl+D hai lần).
3. Chọn model Antigravity trong tool → tool chạy `agy models` để kiểm tra đăng nhập và tự chọn bản Gemini mới nhất
   (đổi bằng `ANTIGRAVITY_MODEL_PRO` / `ANTIGRAVITY_MODEL_FLASH` trong `.env`).

**Luật dịch cho Gemini** nằm ở `app/ai/gemini_rules.md` (vai trò, quy tắc bắt buộc theo thứ tự ưu tiên, xưng hô/kính ngữ Hàn,
không dùng công cụ, tự kiểm tra). Muốn sửa: chép file đó thành `data/gemini_rules.md` rồi sửa — tool ưu tiên bản trong `data/`.
`{style}` trong file được thay bằng *Hướng dẫn văn phong* của job. Nếu Gemini trả sai số đoạn hoặc còn sót chữ Hàn, tool
tự yêu cầu dịch lại chương đó một lần kèm lời nhắc lỗi.

`agy` chạy trong một thư mục trống ngoài dự án (có `GEMINI.md` cấm dùng công cụ) và không bật quyền tự duyệt, nên agent không
đọc/ghi file của bạn. Hết hạn mức → job tạm dừng như Claude Code. Gemini có bộ lọc an toàn riêng: vài cảnh 18+ có thể bị chặn
(`AI_REFUSED`) — dịch lại các chương đó bằng model Claude.

## Kho thuật ngữ (📚 Thuật ngữ) — giữ tên nhân vật, chiêu thức… thống nhất

Mỗi truyện (project = file Word song ngữ các chương cũ) có một kho thuật ngữ:
1. **Data của bạn**: nhập file .txt/.csv/.json/.docx hoặc dán. Dòng `김수현 = Kim Soo-hyun (ghi chú)` (hoặc `→`, Tab, `:`)
   thành thuật ngữ; các dòng mô tả khác thành **Ghi chú truyện** (nhân vật, quan hệ, xưng hô, bối cảnh).
2. **Quét chương cũ bằng AI**: Claude đọc các chương đã dịch (Hàn + Việt), lấy tên nhân vật, chiêu thức, địa danh, vật phẩm,
   danh hiệu… cùng *cách bạn đã dịch*, và báo các cách dịch khác nhau của cùng một từ → danh sách đề xuất để duyệt
   (sửa cách dịch, chọn loại, nhận/bỏ). Mặc định quét 30 chương gần nhất; có ước tính chi phí.
3. **Kiểm tra nhất quán** (miễn phí): mỗi thuật ngữ xuất hiện ở bao nhiêu chương, bao nhiêu % dùng đúng cách dịch, chương nào lệch.
   Từ trong ngoặc `[ ]「」『』` lặp lại nhiều chương nhưng chưa có trong kho được gợi ý để thêm.
4. Khi **🤖 Dịch AI** chọn “Dùng glossary của” truyện này: mỗi chương được gửi kèm các thuật ngữ có mặt trong chương đó
   + ghi chú truyện; thuật ngữ mới AI gặp khi dịch có thể đưa vào kho bằng nút **📚 Đưa … thuật ngữ mới vào kho**.
   Editor (tab Lỗi) và AI gợi ý sửa cũng dùng kho này; “Tránh dùng” = cách dịch cũ bị cảnh báo khi còn xuất hiện.

## Xử lý data thô (🧹)

Thẻ **🧹 Xử lý data thô** ở màn hình chính (nhập đường dẫn file, tuỳ chọn tên truyện để dùng chung kho thuật ngữ):

- **🧹 Làm sạch bản dịch thô (.docx)**: file song ngữ copy từ khung chat ChatGPT (chương Hàn → câu lệnh “dịch sang tiếng Việt”
  → lời dẫn của ChatGPT → bản Việt → lời kết, bộ đếm `2 / 2`, quảng cáo, chuỗi base64…) được dọn thành định dạng chuẩn
  `[tiêu đề Hàn] bản Hàn [tiêu đề Việt] bản Việt` cho từng chương. Kết quả lưu ở `data/library/<tên truyện>/`, tự mở thành
  project và gắn vào truyện. File gốc không bị ghi.
- **📄 Chuẩn bị raw tiếng Hàn (.txt)**: file raw xuất từ epub (có mục lục đầu file, tiêu đề chương lặp 2–3 lần) → mỗi chương một
  tiêu đề. Tool bỏ các chương **đã có bản Việt** trong truyện, chỉ giữ chương cần dịch (có thể giới hạn khoảng chương Từ/Đến)
  và đăng ký sẵn trong 🤖 Dịch AI — mở lên là chọn model rồi dịch.

Truyện (story) gom nhiều file/project dùng chung một kho thuật ngữ; chọn ở ô *Thuộc truyện* hoặc API `PUT /api/projects/{id}/story`.

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
  document/    docx_reader, chapter_parser, cleaner, docx_writer, models   (không phụ thuộc UI/Wattpad)
  editor/      chapter_editor (workflow), chapter_state, glossary, validation
  ai/          llm_service (Anthropic | OpenAI | local | mock), correction_service,
               novel_translator + translation_jobs (dịch cả truyện, job nền), termbase (kho thuật ngữ),
               claude_code (claude -p), antigravity (agy / Gemini) + gemini_rules.md
  tools/       data_import (làm sạch data thô, chuẩn bị raw)
  publishing/  wattpad_publisher (Playwright), wattpad_worker (subprocess), jobs, publish_service,
               wattpad_selectors.json
  storage/     project_state (JSON trong data/projects/)
  static/      UI (HTML/CSS/JS thuần): app.js, translate.js, termbase.js, data.js
tests/         pytest + fake_wattpad (site giả lập để test publisher) + make_sample (tạo book.docx mẫu)
```

## Đăng lên Wattpad bằng extension (mặc định)

Tool không điều khiển được Edge bạn đang dùng hằng ngày (Edge chặn tự động hoá profile chính), nên việc
đăng được làm bởi một extension nhỏ chạy ngay trong Edge đó — dùng luôn đăng nhập Wattpad (Google/Facebook)
và VPN của bạn.

**Cài một lần:**
1. Mở `edge://extensions`, bật **Developer mode** (góc trái dưới).
2. Bấm **Load unpacked** → chọn thư mục `extension` trong thư mục tool (`<thư mục tool>\extension`).
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
