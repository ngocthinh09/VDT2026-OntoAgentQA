> "Vì các kết quả của SPINACH [1] và hướng tiếp cận ReAct trông khá hứa hẹn đối với chúng tôi, chúng tôi đã quyết định khái quát hóa mã nguồn hiện có cho các đồ thị RDF được cung cấp trong thử thách Text2SPARQL. Hệ thống được xây dựng xung quanh một cấu hình ReAct [17, 18] được triển khai bằng LangGraph, một thiết lập cổng lưu trữ (endpoint) SPARQL được hiện thực hóa bằng RPT & Qlever [26], một công cụ tìm kiếm lai (hybrid search) được thực hiện với cơ sở dữ liệu vector Qdrant, một công cụ tìm kiếm văn bản với Lucene, và một cổng API dành cho thử thách Text2SPARQL."

### Strategy 1: Tìm kiếm vector lai (Hybrid Vector Search) cho Schema

* 
**Đối tượng xử lý:** Dành riêng cho việc giải quyết các **Khái niệm, Lớp (Class)** và **Thuộc tính (Property/Predicate)** của lược đồ đồ thị (ví dụ: các từ khóa mơ hồ như *"dân số"*, *"chiều dài"*, *"ai đóng"*...).


* 
**Cách hoạt động:** Nhóm tác giả gom nhãn (`rdfs:label`) và mô tả (`rdfs:comment`) của schema thành một văn bản, sau đó index vào **Qdrant Vector Database** dưới 2 dạng biểu diễn:


1. 
*Dense Vector (Vector dày):* Dùng mô hình *BGE Large English* để bắt trọn vẹn ngữ nghĩa, giúp hiểu các từ đồng nghĩa.

2. 
*Sparse Vector (Vector thưa):* Dùng thuật toán *BM25* để bắt chính xác từ khóa kỹ thuật.

* 
**Kết quả:** Khi Agent cần tra thuộc tính, hệ thống thực hiện truy vấn lai và gộp kết quả bằng thuật toán **RRF (Reciprocal Rank Fusion)** để trả về IRI thuộc tính chuẩn xác nhất (ví dụ: biến từ *"population"* thành `dbo:populationTotal`).

---

### Strategy 2: Tìm kiếm toàn văn (Full-Text Search) cho Thực thể có tên

* 
**Đối tượng xử lý:** Dành riêng cho việc giải quyết các **Tên riêng, Thực thể cụ thể (Named Entities / Instances)** xuất hiện trong câu hỏi (ví dụ: *"Berlin"*, *"Google"*, *"Messi"*...).


* 
**Cách hoạt động:** Đối với thực thể, thách thức không nằm ở sự mơ hồ ngữ nghĩa mà nằm ở **quy mô số lượng nút khổng lồ** (hàng triệu đến hàng tỷ thực thể). Vì vậy, họ hoàn toàn né Vector DB để tránh ngốn tài nguyên. Thay vào đó, họ index toàn bộ tên của các cá thể sống vào một kho chỉ mục **Lucene** truyền thống.


* 
**Kết quả:** Khi Agent trích xuất được một danh từ riêng, nó sẽ gọi trực tiếp sang tool tìm kiếm toàn văn của Lucene để khớp chuỗi văn bản, trả về IRI thực thể một cách cực kỳ nhanh, nhẹ và chính xác (ví dụ: khớp từ *"Berlin"* thành `dbr:Berlin`).


### 3.1. ReAct với các Tiện ích Khám phá Đồ thị Tri thức (KG Exploration Utilities)

Hướng tiếp cận ReAct (suy luận và hành động) [17] được xây dựng xung quanh một đồ thị của các hành động mà LLM có thể định hướng qua. ReAct đề xuất một khuôn mẫu bao gồm các nhóm suy nghĩ (thoughts), hành động (actions) và quan sát (observations) để tạo nên lời nhắc (prompt). Ý tưởng ở đây là không để LLM cố gắng giải quyết một nhiệm vụ cho trước trong một lần thử duy nhất, mà thay vào đó cho phép nó chia nhỏ nhiệm vụ thành các nhiệm vụ phụ nhỏ hơn nếu thấy phù hợp và cung cấp cho nó các công cụ để tương tác với nhiệm vụ cũng như lịch sử của tất cả các hành động trước đó và các quan sát kết quả. Các hành động có sẵn và cách chúng tương tác với bộ điều khiển (hay còn gọi là đồ thị hành động) được hiển thị trong Hình 1.

Trong bước khởi tạo, ngôn ngữ của câu truy vấn được phát hiện để chuyển đổi giữa DBpedia tiếng Anh hoặc tiếng Tây Ban Nha. Tại hành động của "bộ điều khiển" (controller), LLM có thể chọn dừng lại và báo cáo câu trả lời cuối cùng hoặc kích hoạt một trong sáu tiện ích khám phá đồ thị tri thức:

* 
**search (tìm kiếm):** tìm kiếm các thực thể liên quan. Hành động `search_entity` cung cấp một tra cứu cho dữ liệu thực thể (instance data), `search_property` tìm kiếm các thuộc tính và `search_class` tìm kiếm các lớp. Hành động `search_entity` được triển khai dưới dạng tìm kiếm toàn văn (full-text search) trong khi các hành động `search_property` và `search_class` được triển khai bằng Tìm kiếm vector lai (hybrid vector Search).


* 
**inspect (kiểm tra):** lấy thêm thông tin chi tiết về các thực thể trong đồ thị tri thức. Hoặc với một đoạn trích trên một mục nhập cho trước bằng `get_knowledgegraph_entry` hoặc một vài ví dụ sử dụng với `get_property_examples`. Hành động `get_knowledgegraph_entry` được triển khai bằng một câu lệnh truy vấn SPARQL tìm kiếm các cạnh đi ra (outgoing edges). Hành động `get_property_examples` được triển khai bằng một câu lệnh truy vấn SPARQL cho 5 ví dụ sử dụng của thuộc tính cho trước.


* 
**execute (thực thi):** sử dụng `execute_sparql` để kiểm tra một câu lệnh truy vấn SPARQL trên KG. Hành động này thực thi câu lệnh truy vấn SPARQL cho trước trên KG và trả về kết quả.



Các hành động này cũng được mô tả trong lời nhắc của bộ điều khiển (controller prompt) mà chúng tôi kế thừa từ SPINACH [27] như có thể thấy trong Danh sách 1. Bước 'bộ điều khiển' tuân theo sau mỗi bước tìm kiếm/kiểm tra/thực thi để lựa chọn hành động tiếp theo. Quá trình này có thể được lặp lại lên đến 15 lần lặp, điều này có thể thay đổi được trong mã nguồn.

* 
**`get_knowledgegraph_entry(entity URI)`**: Lấy ra tất cả các cạnh đi ra (các thực thể được liên kết, các thuộc tính) của một thực thể đồ thị tri thức được chỉ định bằng cách sử dụng URI đầy đủ của nó. Ví dụ: '[http://dbpedia.org/resource/Sufism](http://dbpedia.org/resource/Sufism)'.


* 
**`search_entity_by_label(string)`**: Tìm kiếm trong đồ thị tri thức {dataset} các thực thể riêng lẻ trong thế giới thực như các công ty, con người, địa điểm hoặc sự vật (ví dụ: “Apple”, “Sufism”, “Barack Obama”).


* 
**`search_property_by_label(string)`**: Tìm kiếm trong đồ thị tri thức {dataset} các *thuộc tính* (còn được gọi là vị từ hoặc mối quan hệ) như “price”, “hasLocation”, hoặc “producedBy”. Hãy sử dụng công cụ này khi bạn đang cố gắng tìm thuộc tính phù hợp để hoàn thiện một bộ ba (triple).


* 
**`search_class_by_label(string)`**: Tìm kiếm các *lớp* (loại/danh mục) trong đồ thị tri thức như “Company”, “Service”, “Book”, hoặc “Organization”.


* 
**`get_property_examples(property URI)`**: Lấy ra một vài ví dụ sử dụng của thuộc tính được chỉ định, được cung cấp dưới dạng một URI đầy đủ.


* 
**`execute_sparql(SPARQL)`**: Thực thi một truy vấn SPARQL trên đồ thị tri thức {dataset}. Hãy sử dụng công cụ này khi bạn tự tin vào cấu trúc truy vấn của mình và sẵn sàng kiểm tra một giả thuyết.


* 
**`stop()`**: Đánh dấu truy vấn SPARQL gần đây nhất là câu trả lời cuối cùng của bạn và kết thúc quá trình.

Các hành động tìm kiếm/kiểm tra/thực thi đều nhận một đối số duy nhất. Đây có thể là một chuỗi ký tự để tìm kiếm, hoặc một thực thể để tra cứu, hoặc một truy vấn SPARQL để thực thi trên cổng lưu trữ (endpoint) SPARQL. Trong mã nguồn Python, các hành động này được dịch thành các lượt gọi hàm với các tham số bổ sung như tên của KG cần sử dụng hoặc ngôn ngữ được phát hiện trong bước khởi tạo.

Mô hình LLM được sử dụng cần phải có sự hỗ trợ công cụ (tool hỗ trợ) để tương tác với LangGraph và các công cụ. Sau một vài đánh giá nội bộ đối với các LLM khác nhau bao gồm Llama, DeepSeek và các biến thể GPT khác nhau, chúng tôi quyết định chọn GPT 4.1 mini làm LLM có tỷ lệ chi phí - kết quả tốt nhất cho trường hợp của mình.

### 3.2. Hướng tiếp cận Chiến lược Kép cho Định vị Ngữ nghĩa (Semantic Grounding)

Một thách thức quan trọng đối với bất kỳ hệ thống chuyển đổi ngôn ngữ tự nhiên sang SPARQL nào là định vị ngữ nghĩa (semantic grounding): quá trình ánh xạ một cách chính xác các cụm từ ngôn ngữ tự nhiên mơ hồ hoặc đa dạng từ câu hỏi của người dùng sang các IRI chuẩn xác, chính tắc của các lớp (classes) và thuộc tính (properties) trong lược đồ (schema) của đồ thị tri thức. Quá trình này bao gồm hai nhiệm vụ phụ riêng biệt: phân giải các thuật ngữ mang tính khái niệm (ví dụ: “population” [dân số], “who made this” [ai đã tạo ra cái này]) thành các thành phần lược đồ (các cá thể thuộc kiểu `owl:Class`, `owl:ObjectProperty`, `owl:DatatypeProperty`), và phân giải các danh từ riêng (ví dụ: “Berlin”, “Google”) thành các cá thể thực thể cụ thể. Tác nhân (agent) của chúng tôi áp dụng một hướng tiếp cận chiến lược kép được thiết kế riêng biệt, nhận thức được rằng hai nhiệm vụ này có các yêu cầu khác nhau về độ chính xác và sắc thái ngữ nghĩa.

#### Chiến lược 1: Tìm kiếm Vector Lai cho các Thực thể Lược đồ (Schema Entities)

Để định vị các thuật ngữ mang tính khái niệm dựa trên lược đồ của đồ thị tri thức (KG schema) – nơi có độ mơ hồ ngữ nghĩa cao – chúng tôi sử dụng phương pháp tìm kiếm lai tinh vi, được hỗ trợ nguyên bản bởi kho lưu trữ vector Qdrant. Hướng tiếp cận này kết hợp tìm kiếm dày (dense search) và tìm kiếm từ vựng (lexical search) để mang lại sự hiểu biết sâu sắc về ý định của người dùng.

1. 
**Lập chỉ mục Lược đồ (Schema Indexing):** Trước tiên, chúng tôi tạo một chỉ mục có thể tìm kiếm trong Qdrant cho tất cả các thực thể lược đồ (các cá thể thuộc kiểu `owl:Class`, `owl:ObjectProperty`, `owl:DatatypeProperty`). Đối với mỗi thực thể, chúng tôi nối thuộc tính `rdfs:label` và `rdfs:comment` của nó lại thành một tài liệu văn bản duy nhất. Tài liệu này sau đó được mã hóa thành hai dạng biểu diễn vector riêng biệt:


* 
**Vector Dày (Dense Vector):** Một mô hình transformer (BGE Large English) tạo ra một embedding dày nhằm nắm bắt ý nghĩa ngữ nghĩa của thực thể. Điều này cho phép khớp dựa trên sự tương đồng về mặt khái niệm.


* 
**Vector Thưa (Sparse Vector):** Một mô hình dựa trên BM25 tạo ra một vector thưa, cao chiều, có ưu thế vượt trội trong việc khớp tập trung vào từ khóa, đảm bảo độ chính xác về mặt từ vựng cho các thuật ngữ kỹ thuật hoặc đặc thù tên miền.

Cả hai vector đều được lưu trữ trong một bộ sưu tập (collection) Qdrant, được lập chỉ mục bởi IRI của thực thể. Ngoài ra, chúng tôi cũng lưu trữ miền nguồn (domain) và miền đích (range) của các thuộc tính (bằng nếu có sẵn) trong các trường siêu dữ liệu (metadata) của bộ sưu tập.

2. 
**Luồng công việc Agent (Agentic Workflow) cho Định vị Lược đồ:** Khi tác nhân cần phân giải một thuật ngữ như “population”, nó sẽ tạo ra một vector dày và thực hiện một câu truy vấn lai bằng phương pháp Shuffled Rank Fusion / Reciprocal Rank Fusion (RRF). Điều này giúp xác định một cách mạnh mẽ thành phần lược đồ chính xác (ví dụ: `dbo:populationTotal`) bằng cách cân bằng giữa mức độ liên quan ngữ nghĩa và độ chính xác của từ khóa.

#### Chiến lược 2: Tìm kiếm Toàn văn cho Phân giải Thực thể có Tên (Named Entity Resolution)

Đối với việc định vị các thực thể có tên, thách thức ít nằm ở sự mơ hồ về mặt khái niệm mà nằm nhiều hơn ở việc khớp các chuỗi ký tự một cách hiệu quả với một tập hợp các cá thể khổng lồ. Đối với nhiệm vụ này, một phương pháp tìm kiếm toàn văn thực tế và có hiệu năng cao sẽ phù hợp hơn.

1. 
**Lập chỉ mục Cá thể (Instance Indexing):** Chúng tôi sử dụng một chỉ mục Lucene tiêu chuẩn, một thư viện tìm kiếm toàn văn mạnh mẽ và đã trưởng thành. Tất cả các cá thể thực thể từ đồ thị tri thức đều được lập chỉ mục. Tài liệu được lập chỉ mục cho mỗi thực thể bao gồm tên của nó (`rdfs:label`) và mô tả (`rdfs:comment`) (nếu có sẵn).


2. 
**Luồng công việc Agent cho Phân giải Thực thể có Tên:** Khi LLM của tác nhân được gọi trong nút bộ điều khiển (controller node) trích xuất ra một danh từ riêng như “Berlin”, nó không sử dụng kho lưu trữ vector. Thay vào đó, nó truy vấn chỉ mục Lucene. Điều này cung cấp một phương pháp nhanh chóng, có khả năng mở rộng và chính xác về mặt từ vựng để phân giải “Berlin” thành IRI chính tắc của nó, `dbr:Berlin`.

Bằng cách sử dụng chiến lược kép này, tác nhân của chúng tôi sử dụng đúng công cụ cho đúng việc một cách hiệu quả. Nó tận dụng chiều sâu ngữ nghĩa của tìm kiếm vector lai cho nhiệm vụ phân tách sắc thái của ánh xạ lược đồ, trong khi dựa vào tốc độ và độ chính xác từ vựng của Lucene cho nhiệm vụ có khối lượng lớn của phân giải thực thể có tên. Sự phân chia này được thể hiện khi phân tích câu “What is the population of Berlin?” (Dân số của Berlin là bao nhiêu?): tác nhân sử dụng tìm kiếm lai để định vị “population” thành `dbo:populationTotal` và sử dụng Lucene để định vị “Berlin” thành `dbr:Berlin`, qua đó thu được cả hai thành phần cần thiết để xây dựng câu truy vấn cuối cùng.