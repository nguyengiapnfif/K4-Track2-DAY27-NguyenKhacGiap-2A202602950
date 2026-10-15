# Reflection

**Loại lỗi nào khó bắt nhất, vì sao?**

Các lỗi tinh vi nằm sát dải dao động tự nhiên, nhất là `distribution_shift`/`volume` nhẹ ở `data_batch` và `feature_drift` ở `feature_materialization`. Baseline chỉ là mean ± 3σ nên một ngưỡng tĩnh hoặc bỏ sót lỗi nhỏ, hoặc gây False Positive. Trên practice/public, ngưỡng của tôi bắt hết hoặc gần hết lỗi. Trên private, TPR chỉ đạt 0.667 (FPR 1.4%, score 32.92). Ở embedding và runtime lineage, các giá trị lỗi nằm lẫn trong dải của dữ liệu sạch nên không có ngưỡng nào tách được sạch sẽ.

**Cân bằng chi phí và TPR**

Mỗi event chỉ gọi đúng một tool, tool được chọn theo loại event. Event nào cũng được kiểm tra nên TPR không bị đánh đổi vì tiết kiệm credit. Tổng chi phí nằm trong ngân sách ở practice (180/220) và private (overage 0). Ở public, chi phí 240/220 là do thiết kế của lab, chấp nhận phạt overage khoảng 1.8 điểm. Một lần siết ngưỡng rộng (composite 1.15, feature 0.55, tuổi tài liệu 43) chỉ tăng điểm private 32.41 → 32.51 nhưng FPR lên 2.7%, nên tôi bỏ. Cuối cùng chỉ siết runtime lineage xuống 4650 ms (cao hơn max của dữ liệu sạch ở practice), được 32.92. Mỗi TP cộng khoảng 0.9 điểm còn mỗi FP trừ khoảng 0.2, nên chỉ nên nới ngưỡng ở vùng có xác suất lỗi trên khoảng 18%.

**Nếu có thêm thời gian**

Dùng `ctx.state` để học phân phối của luồng hiện tại: trung bình động và độ lệch chuẩn (EWMA/z-score) theo từng chỉ số, thay vì ngưỡng cố định. Thêm so sánh với các batch liền trước, phát hiện trôi dạt tích lũy bằng CUSUM, và kết hợp nhiều tín hiệu yếu thành điểm tổng hợp. Cách này bắt lỗi nhẹ mà không hạ ngưỡng chung.
