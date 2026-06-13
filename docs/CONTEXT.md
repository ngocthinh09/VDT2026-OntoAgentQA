# KNOWLEDGE BASE: VIETTEL DIGITAL TALENT (VDT) 2026 - MINIPROJECT
# TOPIC: ONTOLOGY-BASED QUESTION ANSWERING OVER CORPORATE STRUCTURED DATA

## 1. PROJECT OVERVIEW & GOAL
- **Bản chất bài toán:** Xây dựng hệ thống hỏi đáp tri thức dựa trên bản thể học (Ontology-based Question Answering).
- **Mục tiêu:** Nhận câu hỏi ngôn ngữ tự nhiên, dịch thành câu lệnh truy vấn SPARQL (Text-to-SPARQL) để lấy dữ liệu từ cơ sở tri thức có cấu trúc.
- **Yêu cầu sinh tồn (Baseline):** Hệ thống đề xuất BẮT BUỘC phải có độ chính xác cao hơn phương pháp chỉ dùng LLM thông thường (LLM-only).

---

## 2. KNOWLEDGE BASE INFRASTRUCTURE & CONSTRAINTS
Agent cần tuân thủ các quy tắc dữ liệu sau khi sinh mã và thực thi SPARQL:
- **SPARQL Endpoint:** Phải được thiết kế dạng tham số cấu hình linh hoạt (ví dụ truyền qua biến môi trường `SPARQL_ENDPOINT`), hỗ trợ thay đổi giữa public server và local server.
- **Output Format:** Bắt buộc cấu hình đầu ra của thư viện truy vấn dạng `application/json` (để bóc tách mảng `results.bindings` trong mã nguồn).
- **Namespaces (Tiền tố đồ thị):**
  * `dbr:` (Resource): Dùng định danh các Thực thể/Cá thể (Ví dụ: `dbr:Lionel_Messi`).
  * `dbo:` (Ontology): Dùng định danh Lớp (Classes) và Thuộc tính chuẩn (Clean Properties). Dữ liệu này đã được ép luật RDFS (có Domain/Range). LUÔN ƯU TIÊN SỬ DỤNG `dbo:`.
  * `dbp:` (Property): Thuộc tính thô cào từ Wikipedia infobox. Dữ liệu rất nhiễu, KHÔNG CÓ ràng buộc logic. Hạn chế tối đa sử dụng.

---

## 3. IMPLEMENTATION METHODS (PIPELINE ARCHITECTURES)
Dự án được cấu trúc theo 4 hướng tiếp cận Text-to-SPARQL. Agent sẽ tập trung lập trình hệ thống theo hướng **[1.4]**.

- **[1.1] LLM-only (Baseline):** Đưa câu hỏi cho LLM trả lời dựa trên tham số (Parametric Memory). Nhanh nhưng dễ bị ảo giác (Hallucination).
- **[1.2] LLM-based Agent SPARQL Gen + Self-correction:** LLM tự mò mẫm sinh SPARQL. Nếu Endpoint trả về lỗi cú pháp hoặc kết quả rỗng `bindings: []`, Agent tự đọc log để sửa lỗi. Tỷ lệ ảo giác thuộc tính rất cao.
- **[1.3] Ontology-based SPARQL Gen + Self-correction:** Đưa toàn bộ schema/ontology vào Prompt làm Guardrails. Dễ gây tràn token hoặc loãng thông tin.
- **[1.4] Retrieval-Augmented SPARQL Gen + Self-correction (CORE APPROACH):**
  * Bước 1 (Retrieval): Tìm các Class/Property liên quan bằng Vector Database (Milvus).
  * Bước 2 (Augmentation): Chỉ đưa Ontology Fragment (phân đoạn nhỏ) đó vào Prompt làm phao cứu sinh.
  * Bước 3 (Generation & Correction): Agent sinh SPARQL, thực thi, tự sửa lỗi dựa trên ngữ cảnh cô đọng.

---

## 4. ADVANCED OPTIMIZATIONS (GUARDRAILS)
Hệ thống cần nhúng thêm các kỹ thuật nâng cao sau để triệt tiêu lỗi logic trước khi gọi Endpoint:
- **Local Schema Constraint Validator:** Thay vì gửi ngay câu lệnh SPARQL lên Endpoint, sử dụng thư viện xử lý dữ liệu ở local để kiểm tra câu lệnh do LLM sinh ra. Nếu vi phạm `rdfs:domain` hoặc `rdfs:range`, tự động chặn và nạp log lỗi vào Prompt để ép LLM sửa lại.
- **Speculative SPARQL Sketching:** Tách quá trình sinh lệnh thành 2 pha. Pha 1: LLM sinh "khung xương" SPARQL, dùng placeholder cho IRI. Pha 2: Dùng thuật toán quét Vector DB và điền IRI chuẩn xác 100% vào placeholder để triệt tiêu lỗi sai chính tả IRI.

---

## 5. TOOLING & CODING REQUIREMENTS
- **SPARQL Execution:** Sử dụng thư viện `SPARQLWrapper`. Cấu hình bắt buộc: `sparql.setReturnFormat(JSON)`.
- **Data Processing:** Ưu tiên sử dụng `polars` (hiệu năng cao) để xử lý log, parse JSON và làm Constraint Validator.
- **LLM API Proxy:** Hệ thống kết nối qua OpenRouter.
  * SDK: Sử dụng `openai` package chuẩn.
  * Cấu hình: `base_url="https://openrouter.ai/api/v1"`.
  * System Metrics: Bắt buộc bóc tách HTTP Response Headers từ OpenRouter để đo lường True Model Latency (TPS) thay vì dùng Wall-Clock Time thông thường.