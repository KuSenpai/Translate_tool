# Novel Translator

🇻🇳 Tiếng Việt · [🇬🇧 English](README.en.md)

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

| Nút trên màn hình chính | Việc làm                                                                                                                                    |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Mở file Word → editor      | Sửa bản Việt, AI gợi ý, glossary, Preview, Save DOCX, đăng Wattpad                                                                     |
| 🤖 Dịch AI                  | Dịch cả truyện Hàn → Việt bằng Claude API, Claude Code (gói Pro/Max), Gemini (Antigravity), Grok (API xAI / Grok CLI) hoặc OmniRoute |
| 📚 Thuật ngữ               | Kho thuật ngữ + ghi chú truyện, quét chương cũ bằng AI, kiểm tra nhất quán                                                        |
| 🧹 Xử lý data thô         | Làm sạch bản dịch dán từ ChatGPT; tách raw tiếng Hàn chưa dịch                                                                     |

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
   chỉnh **Hướng dẫn dịch** (văn phong, xưng hô) → **Bắt đầu dịch**. Có ước tính chi phí trước khi chạy
   và chi phí thật trong lúc chạy.
4. Kết quả `output/translations/<tên>_vi_<id>.docx` (+ `.txt` nếu đầu vào là .txt): mỗi chương tiếng Hàn, ngay dưới là bản
   dịch — đúng định dạng editor đọc được (**Mở trong editor** để soát và sửa, rồi đăng Wattpad như bình thường).

- Chạy nền, lưu sau từng chương: tạm dừng / tiếp tục / dịch lại chương lỗi; tắt tool rồi mở lại vẫn tiếp tục được.
- Chương đã có bản Việt (file song ngữ dịch dở) được bỏ qua.
- Tên nhân vật/thuật ngữ mới được AI ghi lại và dùng cho các chương sau để nhất quán.
- Nếu AI từ chối hoặc bộ lọc an toàn chặn một chương, chương đó được đánh dấu lỗi `AI_REFUSED` và giữ nguyên bản Hàn trong
  file kết quả — dịch lại chương đó bằng model khác.

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
đọc/ghi file của bạn. Hết hạn mức → job tạm dừng như Claude Code. Gemini có bộ lọc an toàn riêng: vài đoạn có thể bị chặn
(`AI_REFUSED`) — dịch lại các chương đó bằng model khác.

### Dịch bằng Grok (xAI)

Chọn model **Grok (xAI) · mạnh nhất** hoặc **Grok (xAI) · rẻ** (ở 🤖 Dịch AI và 📚 Thuật ngữ). Hợp để làm model dự phòng
dịch lại các chương bị `AI_REFUSED`. Tính tiền theo token trên tài khoản xAI.

1. Lấy API key ở console.x.ai, nạp credit.
2. Thêm vào `.env`: `XAI_API_KEY=xai-...` rồi khởi động lại tool.
3. Chọn model Grok trong tool → tool gọi `GET /v1/models` kiểm tra key và báo nếu slug model không có.
   Mặc định `grok-4.7` (mạnh) / `grok-4.3` (rẻ); đổi bằng `XAI_MODEL` / `XAI_MODEL_FAST`.

Tool dùng chung prompt dịch với Claude (`SYSTEM_PROMPT` + *Hướng dẫn văn phong*), gọi qua API tương thích OpenAI
(`https://api.x.ai/v1`, đổi bằng `XAI_BASE_URL`). Sai số đoạn hoặc sót chữ Hàn thì tự dịch lại chương một lần. Hết credit → job tạm dừng,
nạp thêm rồi bấm **Tiếp tục**.

### Dịch bằng Grok CLI (đăng nhập grok.com, không cần API key)

Chọn model **Grok CLI** (ở 🤖 Dịch AI và 📚 Thuật ngữ): tool gọi lệnh `grok` ở chế độ headless bằng tài khoản grok.com bạn đã đăng nhập.

1. Cài (PowerShell, không phải cmd): `irm https://x.ai/cli/install.ps1 | iex`
2. Chạy `grok` một lần để đăng nhập (trình duyệt mở ra). Tool tự tìm `grok.exe` trong PATH hoặc `~/.grok/bin`
   (đổi bằng `GROK_CLI_PATH`). Model mặc định của tài khoản; ép model bằng `GROK_CLI_MODEL` (xem `grok models`).
3. Chọn **Grok CLI** trong tool → tool chạy `grok models` để kiểm tra đăng nhập.

**Nhiều tài khoản grok.com:** mỗi tài khoản là một thư mục `GROK_HOME` riêng (có `auth.json` riêng). Đăng nhập tài khoản thứ hai (PowerShell):

```powershell
New-Item -ItemType Directory -Force D:\Tool\Translate_tool\data\grok_accounts\acc2
$env:GROK_HOME = "D:\Tool\Translate_tool\data\grok_accounts\acc2"
& "$env:USERPROFILE\.grok\bin\grok.exe" login      # đăng nhập bằng tài khoản thứ hai, rồi đóng cửa sổ
```

Rồi liệt kê trong `.env`: `GROK_CLI_HOMES=default;D:/Tool/Translate_tool/data/grok_accounts/acc2` (`default` = tài khoản `grok` đang đăng nhập sẵn). Tool xoay vòng các lệnh gọi
giữa các tài khoản (các phần chia song song của một chương chạy trên các tài khoản khác nhau, nên không còn dính giới hạn 2 yêu cầu/giây của riêng một tài khoản) và
tự chuyển sang tài khoản khác ngay khi một tài khoản bị giới hạn tốc độ / hết lượt (nghỉ 45 giây / 30 phút). Chỉ muốn đổi hẳn sang tài khoản khác: `grok logout` rồi `grok login`.

`grok` chạy trong một thư mục trống ngoài dự án, tắt hết công cụ (`--tools ""`) và tìm web, nên agent không đọc/ghi file của bạn.
Mỗi lần gọi có ~14k token chi phí cố định của agent (phần lớn được cache). Hết hạn mức → job tạm dừng, bấm **Tiếp tục** khi được làm mới.

## Dịch lại chương bằng AI (trình sửa chương)

Trong trình sửa một chương, bấm **🔁 Dịch lại chương** (hoặc mở mục *Dịch lại cả chương bằng AI* ở tab ✨ AI): chọn model (Claude, Claude Code,
Gemini, Grok…), mức suy luận, thêm yêu cầu riêng nếu muốn → tool dịch lại cả chương từ **bản Hàn**, kèm glossary, ghi chú truyện và
đoạn cuối chương trước. Kết quả chỉ hiện để xem; bấm **Áp dụng** mới thay bản đang sửa (có thể Undo, rồi Save Draft). Hợp để thử model khác
cho chương bị `AI_REFUSED`.

### Dịch qua OmniRoute (cổng AI cục bộ)

[OmniRoute](https://github.com/diegosouzapw/OmniRoute) là cổng AI chạy trên máy bạn (mặc định `http://localhost:20128`), gom nhiều nhà cung cấp / tài khoản / combo
sau một endpoint tương thích OpenAI. Chọn model **OmniRoute** ở 🤖 Dịch AI, 📚 Thuật ngữ và mục dịch lại chương. Điền trong `.env`:

```
OMNIROUTE_API_KEY=...      # tạo trong dashboard OmniRoute
OMNIROUTE_MODEL=...        # đúng tên model hoặc combo như OmniRoute liệt kê (dashboard hoặc GET /v1/models)
OMNIROUTE_BASE_URL=        # tuỳ chọn, mặc định http://localhost:20128/v1
```

Khi chọn model OmniRoute, tool hỏi `GET /v1/models` để kiểm tra key và tên model, và liệt kê các model có sẵn nếu `OMNIROUTE_MODEL` sai. Nếu model phía sau không
hỗ trợ JSON schema nghiêm ngặt, tool tự hạ xuống `json_object` rồi văn bản thường (đưa schema vào prompt và tự đọc kết quả). Chi phí / hạn mức do OmniRoute và các nhà cung cấp
bạn nối trong đó quyết định; tool không ước tính được tiền.

## Tự đặt tiêu đề theo arc (🏷)

Truyện chia thành nhiều arc dài xen kẽ nhau; tiêu đề chương có dạng **`Số chương. Tên arc (n)`** (ví dụ `2761. Atlantis của Thần (107)`),
với `n` là chương thứ mấy của arc đó. Trong trình sửa chương bấm **🏷 Tự đặt tiêu đề**:

- Arc được nhận từ **tiêu đề tiếng Hàn** của chương (`다크 문` → *Dark Moon*). Chương không có tiêu đề Hàn (file raw mới chỉ ghi `2760화`)
  thì **theo arc của chương trước** — đổi bằng danh sách chọn arc. Tiêu đề Hàn lạ → tạo **arc nhỏ mới** (có nút 🤖 Dịch tên); số `(n)` của arc nhỏ tự đếm.
- 6 arc lớn có sẵn (Atlantis của Thần, Quang Minh Thăng Thiên Đồ, Eternal Eden, Dark Moon, Cứu Tinh Học Viện, Kiếm sĩ Hoa Mai…) và được nhớ lâu dài
  cùng số thứ tự: **Quản lý arc…** cho sửa tên, tên Hàn, mẫu tiêu đề, và cột **Đã tới số** (sửa thành số thật trên Wattpad thì các chương sau đếm tiếp từ đó).
- **↻ Dựng từ file Word** quét các file của truyện để gán arc cho mọi chương đã có (arc nhỏ tự tạo, tên lấy từ tiêu đề Việt cũ).
- `n` được tính từ thứ tự chương (số chương đã gán cho arc ở phía dưới), nên bấm Áp dụng lại không đếm đôi và gán lệch thứ tự vẫn đúng.
  Dữ liệu ở `data/stories/<truyện>/arcs.json` (hoặc trong thư mục project nếu chưa thuộc truyện nào). Chương mới load sẽ lấy sẵn tiêu đề này nếu đã gán arc.

## Đối chiếu thuật ngữ với chương cũ trên Wattpad (📚 → mục 3b)

Chương cũ bạn đã đăng được coi là **đúng hơn** glossary hiện tại. Mục **3b** cào chúng về, so với kho thuật ngữ và đưa chỗ khác nhau vào mục 4
(nguồn “chương cũ Wattpad”, có cột *hiện tại*; nhận đề xuất thì dùng cách dịch cũ và giữ cách hiện tại trong danh sách “tránh”).

1. Tải lại extension (`edge://extensions` → Reload; phải là **v1.3.0**), bật VPN, mở một tab `wattpad.com` trong Edge.
2. Ở 📚 Thuật ngữ: tick các truyện Wattpad (lấy từ My Works), nhập **file Hàn gốc** (`.txt`/`.docx` chứa các chương đó, ví dụ
   `data/Data raw/into-the-creative-work/[610] 창작물 속으로.txt` — phải là bản tiếng Hàn, không phải `book.txt` tiếng Anh), khoảng chương, chọn model rồi bấm **Cào & đối chiếu**.
3. Extension đọc danh sách chương + nội dung qua endpoint của chính Wattpad (không sửa gì trên Wattpad), gửi về tool; tool ghép với bản Hàn theo số chương,
   bỏ dòng ghi chú đầu chương (`Note: …`, `-`), rồi cho AI so từng nhóm chương với glossary. **Dữ liệu cào không được lưu** (chỉ giữ trong RAM đến khi xong).
4. Tiêu đề đã đăng (`2201. Dark Moon (165)`) cũng cập nhật **số thứ tự arc** (🏷): mỗi chương được gán đúng arc và bộ đếm đặt theo chương mới nhất đã đăng.
   Arc có tên hơi khác (bỏ qua các từ nối “của/trong/vào”) được coi là cùng một arc; tên khác hẳn thì tạo arc nhỏ mới.

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

> Sau khi cập nhật tool (thư mục `extension` đổi), vào `edge://extensions` và bấm **Tải lại (⟳)** ở extension, rồi
> F5 các tab Wattpad đang mở. Nếu quên, tool tự cảnh báo “Extension đang chạy bản cũ” ở màn Preview và thẻ đăng nhiều
> chương (bản cũ không đăng đúng được: nó có thể kẹt ở “Đang mở trang soạn phần mới”).

**Dùng:**

- Preview → **Mở Wattpad (Edge của bạn)** / **↻ Lấy danh sách từ My Works**: mở My Works trong tab mới; extension gửi
  danh sách truyện về tool. Hoặc dán link của truyện (kể cả link soạn thảo `…/myworks/<truyện>/write/<phần>`) vào ô
  “Thêm truyện bằng link”.
- Chọn truyện, tick xác nhận, **Publish** → tool mở tab Wattpad và extension làm đúng như bạn làm tay:
  1. Ở trang truyện (`/myworks/<truyện>`) **mở chương mới nhất** trong danh sách (không bấm nút `+ New Part` ở trang
     này — nó chỉ thêm một bản nháp trống vào danh sách chứ không mở ra).
  2. Chương mới nhất **đã publish** → mở menu danh sách phần ở góc trái trên của editor → **New Part** → được chương trống.
     Chương mới nhất là **bản nháp trống** (vd “Untitled Part 78”) → dùng luôn chương đó. Chương mới nhất là bản nháp **đã
     có chữ** → dừng, báo lỗi `WATTPAD_LATEST_DRAFT_NOT_EMPTY` (không ghi đè việc của bạn).
  3. Điền tiêu đề + nội dung → lưu → đếm ngược 5 giây (bấm **Huỷ** trên khung thông báo nếu muốn dừng) → **Publish**.
  4. Popup xác nhận **của trình duyệt** (`confirm()`) được extension tự bấm OK — chỉ trong lúc nó vừa bấm Publish, các lúc
     khác popup của trang vẫn hiện bình thường (`extension/page_hook.js`). Popup trong trang (nếu có, kể cả hai bước) cũng
     được xử lý. Rồi báo kết quả về tool.
- Extension chỉ điền vào phần **do chính nó vừa tạo**, chương trống mới nhất, hoặc phần đã tạo ở lần thử trước của cùng
  chương — không bao giờ ghi đè một chương đã có. Nếu tab đang mở editor của một chương cũ, nó tự chuyển sang chương
  mới nhất trước.
- Bấm **Huỷ** trong tool (hoặc trên khung thông báo ở trang Wattpad) là extension dừng, kể cả khi đang đếm ngược trước
  khi bấm Publish. Nhiều tab Wattpad cùng mở thì chỉ một tab nhận việc, không bị tạo trùng chương.
- Nút extension trên thanh công cụ: xem trạng thái kết nối, đổi địa chỉ tool, **Gửi chẩn đoán trang** (lưu cấu trúc
  trang Wattpad vào `data/logs/wattpad/` để sửa khi Wattpad đổi giao diện).
- Popup trong trang được tìm theo cách nó che trang (không cần `role="dialog"`); chỉ các nhãn trong `confirm_texts` mới
  bị bấm. Nếu Wattpad đổi nhãn nút/popup, tool báo `WATTPAD_CONFIRM_NOT_FOUND` kèm **nội dung popup**; bấm **Gửi chẩn đoán
  trang** (khi popup đang mở) hoặc thêm nhãn vào `confirm_texts` / `confirm_selectors`.
- Nhãn nút / selector nằm ở mục `"ext"` trong `app/publishing/wattpad_selectors.json`; extension đọc trực tiếp từ tool nên
  sửa file này không cần cài lại extension.

### Đăng nhiều chương cùng lúc

Màn hình chọn chương (sau khi mở file Word) có thẻ **📤 Đăng nhiều chương lên Wattpad**:

1. Chọn **truyện** (danh sách lấy từ My Works, hoặc thêm bằng link ở màn Preview) và nhập các chương, ví dụ `12-20, 25`
   (nút **Chọn các chương chưa đăng** điền sẵn). Chọn *Publish* hoặc *Chỉ lưu nháp*.
2. Tick **Tôi xác nhận các chương này là bản cuối cùng** → **Đăng N chương** → xác nhận. Tool mở một tab Wattpad.
3. Tool đăng **lần lượt từng chương, theo thứ tự số chương**, mỗi chương cách nhau vài giây (`BATCH_DELAY` trong
   `app/publishing/publish_service.py`, mặc định 8 giây). Tiến độ từng chương hiện ngay dưới nút; **Huỷ đợt đăng** dừng
   ngay, chương đã đăng không bị gỡ.

Lưu ý:

- **Giữ tab Wattpad đó mở và hiển thị** (đừng thu nhỏ cửa sổ, đừng để tab chạy nền lâu) — extension chạy trong tab này;
  trình duyệt làm chậm tab ẩn và đóng băng hiệu ứng giao diện của Wattpad (menu, popup). Extension có cách dự phòng cho
  trường hợp này nhưng tab ở trên cùng vẫn là chắc chắn nhất.
- Chương chưa mở trong editor được tự đọc từ file Word; xác nhận cả đợt tính là đã review. Chương **đã đăng** được bỏ
  qua; chương parser không chắc ranh giới (độ tin cậy thấp, chưa mở xem) bị chặn — mở nó trong editor để kiểm tra trước.
- Tiêu đề trên Wattpad = tiêu đề chương trong editor.
- **Gặp lỗi ở chương nào là dừng ngay ở đó** (các chương sau không bị đụng tới) để không đăng lệch thứ tự. Sửa lỗi rồi bấm
  đăng lại cùng khoảng chương: chương lỗi cập nhật đúng phần đã tạo (không tạo trùng), các chương sau chạy tiếp.

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
