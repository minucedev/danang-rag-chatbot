"""Bộ benchmark đánh giá RAG — port từ pbl7-metrics.ipynb (cell 4 & 5).

Hằng COL_* của notebook được thay bằng tên collection thật trong `app.config`
để metric so khớp đúng `collection` mà pipeline trả về.
"""
from __future__ import annotations

from app import config

COL_PLACES = config.COLLECTION_PLACES
COL_PLACE_REVIEWS = config.COLLECTION_PLACE_REVIEWS
COL_RESTAURANTS = config.COLLECTION_RESTAURANTS
COL_RESTAURANT_REVIEWS = config.COLLECTION_RESTAURANT_REVIEWS
COL_HOTELS = config.COLLECTION_ACCOMMODATION_HOTELS
COL_ROOMS = config.COLLECTION_ACCOMMODATION_ROOMS
COL_HOTEL_REVIEWS = config.COLLECTION_ACCOMMODATION_REVIEWS


# ── BENCHMARK chung (khách sạn / nhà hàng / địa điểm / giá / phức tạp) ────────
BENCHMARK = [
    # ── KHÁCH SẠN ──────────────────────────────────────────────────────────
    {
        "id": "H01",
        "category": "Khách sạn",
        "query": "Khách sạn nào ở Đà Nẵng có giá dưới 1 triệu đồng?",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["khách sạn", "giá", "đồng"],
        "gold_answer": "Một số khách sạn tại Đà Nẵng có giá dưới 1 triệu đồng mỗi đêm.",
    },
    {
        "id": "H02",
        "category": "Khách sạn",
        "query": "Gợi ý khách sạn ở quận Sơn Trà có đánh giá tốt trên 8.0",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["sơn trà", "khách sạn"],
        "gold_answer": "Có nhiều khách sạn tại Sơn Trà được đánh giá trên 8.0.",
    },
    {
        "id": "H03",
        "category": "Khách sạn",
        "query": "Khách sạn 5 sao nào ở Đà Nẵng được đánh giá cao?",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["5 sao", "resort"],
        "gold_answer": "Một số resort 5 sao tại Đà Nẵng nổi tiếng như InterContinental, Hyatt.",
    },
    {
        "id": "H04",
        "category": "Khách sạn",
        "query": "Resort nào phù hợp cho cặp đôi nghỉ dưỡng?",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["resort", "cặp đôi"],
        "gold_answer": "Có nhiều resort lãng mạn tại Đà Nẵng phù hợp cho cặp đôi.",
    },
    {
        "id": "H05",
        "category": "Khách sạn – Review",
        "query": "Review về khách sạn Le Sands Oceanfront Danang Hotel",
        "expected_intent": "review_search",
        "expected_collections": [COL_HOTEL_REVIEWS],
        "keywords": ["le sands", "review", "đánh giá"],
        "gold_answer": "Le Sands Oceanfront là khách sạn ven biển được nhiều khách đánh giá cao.",
    },
    {
        "id": "H06",
        "category": "Khách sạn – Phòng",
        "query": "Khách sạn nào có phòng gia đình sức chứa 4-5 người?",
        "expected_intent": "room_search",
        "expected_collections": [COL_ROOMS, COL_HOTELS],
        "keywords": ["phòng", "gia đình", "người"],
        "gold_answer": "Nhiều khách sạn có phòng family đủ chỗ cho 4-5 người.",
    },
    {
        "id": "H07",
        "category": "Khách sạn - View",
        "query": "Khách sạn nào gần biển Mỹ Khê và có view đẹp?",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["mỹ khê", "view", "biển"],
        "gold_answer": "Nhiều khách sạn ven biển Mỹ Khê có view đẹp hướng ra biển.",
    },
    {
        "id": "H08",
        "category": "Khách sạn - Gia đình",
        "query": "Khách sạn phù hợp cho gia đình 4 người ở Đà Nẵng",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["gia đình", "4 người"],
        "gold_answer": "Các khách sạn có phòng family hoặc suite phù hợp cho 4 người.",
    },
    {
        "id": "H09",
        "category": "Khách sạn - Hồ bơi",
        "query": "Khách sạn nào có hồ bơi vô cực đẹp?",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["hồ bơi", "vô cực"],
        "gold_answer": "Một số khách sạn tại Đà Nẵng có hồ bơi vô cực view biển đẹp.",
    },
    {
        "id": "H10",
        "category": "Khách sạn - Trung tâm",
        "query": "Khách sạn gần cầu Rồng và trung tâm thành phố",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["cầu rồng", "trung tâm"],
        "gold_answer": "Khu vực gần cầu Rồng có nhiều khách sạn tiện di chuyển.",
    },
    {
        "id": "H11",
        "category": "Khách sạn - Buffet",
        "query": "Khách sạn nào có buffet sáng ngon?",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["buffet sáng", "ăn sáng"],
        "gold_answer": "Nhiều khách sạn 4-5 sao có buffet sáng phong phú.",
    },
    {
        "id": "H12",
        "category": "Khách sạn - Check-in",
        "query": "Khách sạn nào có không gian check-in sống ảo đẹp?",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["check-in", "sống ảo"],
        "gold_answer": "Nhiều khách sạn có view đẹp và góc sống ảo cho khách.",
    },
    {
        "id": "H13",
        "category": "Khách sạn - Resort",
        "query": "Gợi ý resort yên tĩnh để nghỉ dưỡng cuối tuần",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["resort", "yên tĩnh", "nghỉ dưỡng"],
        "gold_answer": "Các resort tại khu vực Non Nước hoặc Sơn Trà thường yên tĩnh.",
    },

    # ── NHÀ HÀNG ───────────────────────────────────────────────────────────
    {
        "id": "R01",
        "category": "Nhà hàng",
        "query": "Gợi ý nhà hàng hải sản ngon ở Đà Nẵng",
        "expected_intent": "restaurant_search",
        "expected_collections": [COL_RESTAURANTS],
        "keywords": ["hải sản", "nhà hàng"],
        "gold_answer": "Đà Nẵng có nhiều nhà hàng hải sản nổi tiếng như Làng Cá, Bé Mặn.",
    },
    {
        "id": "R02",
        "category": "Nhà hàng",
        "query": "Quán mì Quảng nổi tiếng ở Đà Nẵng",
        "expected_intent": "restaurant_search",
        "expected_collections": [COL_RESTAURANTS],
        "keywords": ["mì quảng"],
        "gold_answer": "Mì Quảng là đặc sản nổi tiếng của Đà Nẵng.",
    },
    {
        "id": "R03",
        "category": "Nhà hàng",
        "query": "Nhà hàng nào ở Hải Châu có không gian đẹp và đồ ăn ngon?",
        "expected_intent": "restaurant_search",
        "expected_collections": [COL_RESTAURANTS],
        "keywords": ["hải châu", "nhà hàng"],
        "gold_answer": "Quận Hải Châu có nhiều nhà hàng có không gian đẹp.",
    },
    {
        "id": "R04",
        "category": "Nhà hàng",
        "query": "Quán ăn ngon bổ rẻ cho sinh viên ở Đà Nẵng",
        "expected_intent": "restaurant_search",
        "expected_collections": [COL_RESTAURANTS],
        "keywords": ["quán ăn", "giá"],
        "gold_answer": "Có nhiều quán ăn giá rẻ phù hợp cho sinh viên tại Đà Nẵng.",
    },
    {
        "id": "R05",
        "category": "Nhà hàng",
        "query": "Nhà hàng sang trọng thích hợp tiếp khách ở Đà Nẵng",
        "expected_intent": "restaurant_search",
        "expected_collections": [COL_RESTAURANTS],
        "keywords": ["nhà hàng", "sang trọng"],
        "gold_answer": "Đà Nẵng có nhiều nhà hàng sang trọng phù hợp tiếp khách.",
    },
    {
        "id": "R06",
        "category": "Nhà hàng - Bún chả cá",
        "query": "Ăn bún chả cá ngon ở đâu tại Đà Nẵng?",
        "expected_intent": "restaurant_search",
        "expected_collections": [COL_RESTAURANTS],
        "keywords": ["bún chả cá"],
        "gold_answer": "Bún chả cá là đặc sản Đà Nẵng, nhiều quán ngon trên đường Lê Duẩn.",
    },
    {
        "id": "R07",
        "category": "Nhà hàng - Đặc sản",
        "query": "Nhà hàng nào bán đặc sản Đà Nẵng ngon?",
        "expected_intent": "restaurant_search",
        "expected_collections": [COL_RESTAURANTS],
        "keywords": ["đặc sản"],
        "gold_answer": "Có nhiều nhà hàng chuyên đặc sản Đà Nẵng như mì Quảng, bánh tráng cuốn thịt heo.",
    },
    {
        "id": "R08",
        "category": "Nhà hàng - Buffet",
        "query": "Buffet nướng hải sản nào ngon và giá hợp lý?",
        "expected_intent": "restaurant_search",
        "expected_collections": [COL_RESTAURANTS],
        "keywords": ["buffet", "nướng", "hải sản"],
        "gold_answer": "Nhiều nhà hàng buffet hải sản tại Đà Nẵng giá từ 200k-400k/người.",
    },
    {
        "id": "R09",
        "category": "Nhà hàng - Gia đình",
        "query": "Nhà hàng phù hợp cho gia đình có trẻ em",
        "expected_intent": "restaurant_search",
        "expected_collections": [COL_RESTAURANTS],
        "keywords": ["gia đình", "trẻ em"],
        "gold_answer": "Các nhà hàng có không gian rộng, khu vui chơi cho trẻ em.",
    },
    {
        "id": "R10",
        "category": "Nhà hàng - Khuya",
        "query": "Quán ăn nào mở khuya ở Đà Nẵng?",
        "expected_intent": "restaurant_search",
        "expected_collections": [COL_RESTAURANTS],
        "keywords": ["mở khuya", "đêm"],
        "gold_answer": "Khu vực trung tâm Đà Nẵng có nhiều quán mở đến 23h-24h.",
    },

    # ── ĐỊA ĐIỂM ───────────────────────────────────────────────────────────
    {
        "id": "P01",
        "category": "Địa điểm",
        "query": "Địa điểm du lịch nổi tiếng nào ở bán đảo Sơn Trà?",
        "expected_intent": "place_search",
        "expected_collections": [COL_PLACES],
        "keywords": ["sơn trà"],
        "gold_answer": "Bán đảo Sơn Trà nổi tiếng với chùa Linh Ứng, bãi biển.",
    },
    {
        "id": "P02",
        "category": "Địa điểm",
        "query": "Bãi biển nào đẹp nhất ở Đà Nẵng?",
        "expected_intent": "place_search",
        "expected_collections": [COL_PLACES],
        "keywords": ["bãi biển"],
        "gold_answer": "Đà Nẵng có bãi biển Mỹ Khê được đánh giá đẹp nhất.",
    },
    {
        "id": "P03",
        "category": "Địa điểm",
        "query": "Buổi tối ở Đà Nẵng nên đi đâu chơi?",
        "expected_intent": "place_search",
        "expected_collections": [COL_PLACES],
        "keywords": ["đà nẵng", "tối"],
        "gold_answer": "Buổi tối tại Đà Nẵng có thể đi cầu Rồng, chợ Hàn.",
    },
    {
        "id": "P04",
        "category": "Địa điểm",
        "query": "Địa điểm tham quan miễn phí ở Đà Nẵng",
        "expected_intent": "place_search",
        "expected_collections": [COL_PLACES],
        "keywords": ["miễn phí", "tham quan"],
        "gold_answer": "Có nhiều điểm tham quan miễn phí tại Đà Nẵng.",
    },
    {
        "id": "P05",
        "category": "Địa điểm",
        "query": "Các địa điểm mang nét văn hóa và lịch sử ở Đà Nẵng",
        "expected_intent": "place_search",
        "expected_collections": [COL_PLACES],
        "keywords": ["văn hóa", "lịch sử"],
        "gold_answer": "Đà Nẵng có Bảo tàng Chăm, Ngũ Hành Sơn là điểm văn hoá.",
    },
    {
        "id": "P06",
        "category": "Địa điểm - Check-in",
        "query": "Địa điểm check-in đẹp ở Đà Nẵng",
        "expected_intent": "place_search",
        "expected_collections": [COL_PLACES],
        "keywords": ["check-in", "đẹp"],
        "gold_answer": "Cầu Rồng, cầu Tình Yêu, Bà Nà Hills là điểm check-in nổi tiếng.",
    },
    {
        "id": "P07",
        "category": "Địa điểm - Thiên nhiên",
        "query": "Địa điểm thiên nhiên đẹp và yên bình",
        "expected_intent": "place_search",
        "expected_collections": [COL_PLACES],
        "keywords": ["thiên nhiên", "yên bình"],
        "gold_answer": "Bán đảo Sơn Trà, Ngũ Hành Sơn, Hồ Hòa Trung.",
    },
    {
        "id": "P08",
        "category": "Địa điểm - Gia đình",
        "query": "Địa điểm vui chơi phù hợp cho gia đình có trẻ em",
        "expected_intent": "place_search",
        "expected_collections": [COL_PLACES],
        "keywords": ["vui chơi", "trẻ em"],
        "gold_answer": "Công viên Châu Á, Sun World Bà Nà Hills, công viên Biển Đông.",
    },
    {
        "id": "P09",
        "category": "Địa điểm - Cuối tuần",
        "query": "Cuối tuần nên đi đâu ở Đà Nẵng?",
        "expected_intent": "place_search",
        "expected_collections": [COL_PLACES],
        "keywords": ["cuối tuần"],
        "gold_answer": "Cuối tuần có thể đi chợ đêm Sơn Trà, cầu Rồng phun lửa.",
    },
    {
        "id": "P10",
        "category": "Địa điểm - Hoàng hôn",
        "query": "Địa điểm chụp ảnh đẹp lúc hoàng hôn",
        "expected_intent": "place_search",
        "expected_collections": [COL_PLACES],
        "keywords": ["hoàng hôn", "chụp ảnh"],
        "gold_answer": "Cầu Rồng, bán đảo Sơn Trà, bãi biển Mỹ Khê lúc hoàng hôn.",
    },

    # ── GIÁ ────────────────────────────────────────────────────────────────
    {
        "id": "PR01",
        "category": "Giá",
        "query": "Giá phòng khách sạn ở Đà Nẵng khoảng bao nhiêu?",
        "expected_intent": "price_search",
        "expected_collections": [COL_HOTELS],
        "keywords": ["giá", "phòng"],
        "gold_answer": "Giá phòng khách sạn tại Đà Nẵng dao động từ 500k đến vài triệu đồng.",
    },

    # ── PHỨC TẠP ───────────────────────────────────────────────────────────
    {
        "id": "C01",
        "category": "Phức tạp",
        "query": "Gợi ý khách sạn gần biển và có nhà hàng hải sản ngon xung quanh",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS, COL_RESTAURANTS],
        "keywords": ["khách sạn", "biển", "hải sản"],
        "gold_answer": "Khu vực Mỹ Khê có nhiều khách sạn ven biển gần nhà hàng hải sản.",
    },
    {
        "id": "C02",
        "category": "Phức tạp - Nhu cầu",
        "query": "Tôi thích nơi yên tĩnh, ít đông người, nên ở đâu?",
        "expected_intent": "hotel_search",
        "expected_collections": [COL_HOTELS, COL_PLACES],
        "keywords": ["yên tĩnh", "ít đông"],
        "gold_answer": "Khu vực Non Nước hoặc resort xa trung tâm phù hợp cho nhu cầu yên tĩnh.",
    },
]


# ── BENCHMARK lịch trình (itinerary) — có eval_criteria cho structure eval ────
BENCHMARK_ITINERARY = [
    {
        "id": "IT01",
        "category": "Lịch trình - 3N2Đ",
        "query": "Cho tôi kế hoạch du lịch Đà Nẵng 3 ngày 2 đêm",
        "expected_intent": "itinerary_search",
        "expected_collections": [COL_PLACES, COL_RESTAURANTS, COL_HOTELS],
        "keywords": ["ngày", "khách sạn", "địa điểm"],
        "gold_answer": (
            "Gợi ý lịch trình 3 ngày 2 đêm tại Đà Nẵng: Ngày 1 tham quan bãi biển Mỹ Khê và cầu Rồng, "
            "Ngày 2 khám phá Bà Nà Hills và Ngũ Hành Sơn, Ngày 3 thăm Sơn Trà và chùa Linh Ứng."
        ),
        "eval_criteria": {
            "has_daily_structure": True,
            "has_hotel": True,
            "has_food": True,
            "has_attractions": True,
            "min_days_mentioned": 3,
        },
    },
    {
        "id": "IT02",
        "category": "Lịch trình - 2N1Đ",
        "query": "Lịch trình du lịch Đà Nẵng 2 ngày 1 đêm cho cặp đôi",
        "expected_intent": "itinerary_search",
        "expected_collections": [COL_PLACES, COL_RESTAURANTS, COL_HOTELS],
        "keywords": ["cặp đôi", "ngày", "lãng mạn"],
        "gold_answer": (
            "Lịch trình 2 ngày 1 đêm cho cặp đôi: Ngày 1 dạo biển Mỹ Khê, xem cầu Rồng phun lửa buổi tối. "
            "Ngày 2 tham quan Bán đảo Sơn Trà, ăn hải sản."
        ),
        "eval_criteria": {
            "has_daily_structure": True,
            "has_hotel": True,
            "has_food": True,
            "has_attractions": True,
            "min_days_mentioned": 2,
        },
    },
    {
        "id": "IT03",
        "category": "Lịch trình - Gia đình",
        "query": "Lên kế hoạch du lịch Đà Nẵng 4 ngày 3 đêm cho gia đình có trẻ nhỏ",
        "expected_intent": "itinerary_search",
        "expected_collections": [COL_PLACES, COL_RESTAURANTS, COL_HOTELS],
        "keywords": ["gia đình", "trẻ em", "ngày", "vui chơi"],
        "gold_answer": (
            "Lịch trình 4 ngày cho gia đình: Ngày 1 nhận phòng và nghỉ ngơi tại biển. "
            "Ngày 2 Sun World Bà Nà Hills. Ngày 3 Công viên Châu Á, bãi biển. Ngày 4 mua sắm và về."
        ),
        "eval_criteria": {
            "has_daily_structure": True,
            "has_hotel": True,
            "has_food": True,
            "has_attractions": True,
            "min_days_mentioned": 4,
        },
    },
    {
        "id": "IT04",
        "category": "Lịch trình - Tiết kiệm",
        "query": "Kế hoạch du lịch Đà Nẵng 3 ngày tiết kiệm, ngân sách dưới 3 triệu đồng",
        "expected_intent": "itinerary_search",
        "expected_collections": [COL_PLACES, COL_RESTAURANTS, COL_HOTELS],
        "keywords": ["tiết kiệm", "ngân sách", "giá rẻ"],
        "gold_answer": (
            "Lịch trình tiết kiệm dưới 3 triệu: Chọn hostel hoặc nhà nghỉ bình dân, ăn mì Quảng, "
            "bún chả cá tại quán vỉa hè. Tham quan các điểm miễn phí như bãi biển, cầu Rồng."
        ),
        "eval_criteria": {
            "has_daily_structure": True,
            "has_hotel": True,
            "has_food": True,
            "has_attractions": True,
            "min_days_mentioned": 3,
        },
    },
    {
        "id": "IT05",
        "category": "Lịch trình - Cao cấp",
        "query": "Gợi ý lịch trình nghỉ dưỡng sang trọng 3 ngày 2 đêm tại Đà Nẵng",
        "expected_intent": "itinerary_search",
        "expected_collections": [COL_PLACES, COL_RESTAURANTS, COL_HOTELS],
        "keywords": ["resort", "sang trọng", "spa", "nghỉ dưỡng"],
        "gold_answer": (
            "Lịch trình sang trọng: Ngày 1 check-in resort 5 sao, thư giãn spa. "
            "Ngày 2 tour Sơn Trà, tối ăn nhà hàng fine dining. Ngày 3 buffet sáng và check-out."
        ),
        "eval_criteria": {
            "has_daily_structure": True,
            "has_hotel": True,
            "has_food": True,
            "has_attractions": True,
            "min_days_mentioned": 3,
        },
    },
    {
        "id": "IT06",
        "category": "Lịch trình - Nhóm bạn",
        "query": "Lịch trình đi Đà Nẵng 3 ngày 2 đêm cho nhóm 5 bạn trẻ thích vui chơi về đêm",
        "expected_intent": "itinerary_search",
        "expected_collections": [COL_PLACES, COL_RESTAURANTS, COL_HOTELS],
        "keywords": ["nhóm bạn", "đêm", "bar", "vui chơi"],
        "gold_answer": (
            "Lịch trình nhóm bạn: Ngày 1 biển Mỹ Khê, tối cầu Rồng. "
            "Ngày 2 Bà Nà Hills, tối chợ đêm Sơn Trà. Ngày 3 café sống ảo, mua đặc sản."
        ),
        "eval_criteria": {
            "has_daily_structure": True,
            "has_hotel": True,
            "has_food": True,
            "has_attractions": True,
            "min_days_mentioned": 3,
        },
    },
    {
        "id": "IT07",
        "category": "Lịch trình - Cuối tuần",
        "query": "Kế hoạch đi Đà Nẵng cuối tuần 2 ngày không cần đặt khách sạn trước",
        "expected_intent": "itinerary_search",
        "expected_collections": [COL_PLACES, COL_RESTAURANTS, COL_HOTELS],
        "keywords": ["cuối tuần", "2 ngày", "địa điểm"],
        "gold_answer": (
            "Cuối tuần tại Đà Nẵng: Ngày 1 biển Mỹ Khê buổi sáng, chiều Ngũ Hành Sơn, "
            "tối xem cầu Rồng phun lửa. Ngày 2 Bán đảo Sơn Trà, ăn hải sản."
        ),
        "eval_criteria": {
            "has_daily_structure": True,
            "has_hotel": False,
            "has_food": True,
            "has_attractions": True,
            "min_days_mentioned": 2,
        },
    },
    {
        "id": "IT08",
        "category": "Lịch trình - Trải nghiệm ẩm thực",
        "query": "Xây dựng lịch trình food tour 1 ngày khám phá ẩm thực Đà Nẵng",
        "expected_intent": "itinerary_search",
        "expected_collections": [COL_RESTAURANTS, COL_PLACES],
        "keywords": ["food tour", "ẩm thực", "quán", "đặc sản"],
        "gold_answer": (
            "Food tour 1 ngày: Sáng mì Quảng hoặc bún chả cá, trưa bánh tráng cuốn thịt heo, "
            "chiều bê thui Cầu Mống, tối hải sản tươi sống Mỹ Khê."
        ),
        "eval_criteria": {
            "has_daily_structure": True,
            "has_hotel": False,
            "has_food": True,
            "has_attractions": False,
            "min_days_mentioned": 1,
        },
    },
    {
        "id": "IT09",
        "category": "Lịch trình - Phượt xe máy",
        "query": "Lịch trình phượt xe máy Đà Nẵng 3 ngày, thích khám phá thiên nhiên",
        "expected_intent": "itinerary_search",
        "expected_collections": [COL_PLACES, COL_RESTAURANTS, COL_HOTELS],
        "keywords": ["thiên nhiên", "biển", "đèo", "ngày"],
        "gold_answer": (
            "Phượt 3 ngày: Ngày 1 đèo Hải Vân, biển Nam Ô. "
            "Ngày 2 Bán đảo Sơn Trà, Ngũ Hành Sơn. Ngày 3 Hội An."
        ),
        "eval_criteria": {
            "has_daily_structure": True,
            "has_hotel": True,
            "has_food": True,
            "has_attractions": True,
            "min_days_mentioned": 3,
        },
    },
    {
        "id": "IT10",
        "category": "Lịch trình - Hỏi gợi ý tổng hợp",
        "query": "Tôi sắp đến Đà Nẵng lần đầu, hãy giúp tôi lên kế hoạch 3 ngày hoàn chỉnh",
        "expected_intent": "itinerary_search",
        "expected_collections": [COL_PLACES, COL_RESTAURANTS, COL_HOTELS],
        "keywords": ["lần đầu", "ngày", "khách sạn", "ăn"],
        "gold_answer": (
            "Lần đầu đến Đà Nẵng: Ngày 1 biển Mỹ Khê và cầu Rồng, Ngày 2 Bà Nà Hills, "
            "Ngày 3 Ngũ Hành Sơn và làng nghề đá mỹ nghệ Non Nước."
        ),
        "eval_criteria": {
            "has_daily_structure": True,
            "has_hotel": True,
            "has_food": True,
            "has_attractions": True,
            "min_days_mentioned": 3,
        },
    },
]
