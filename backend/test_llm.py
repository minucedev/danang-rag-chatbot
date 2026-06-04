import asyncio
from app.llm.gemini import GeminiClient
from app.rag.pipeline import _ITINERARY_RULES

async def test():
    client = GeminiClient()
    system_prompt = "Bạn là chuyên gia lập lịch trình du lịch Đà Nẵng.\n" + _ITINERARY_RULES
    
    context = """
[1] Central Market - The Vietnam Hostel
   - Loại: nhà hàng
   - Quận/Huyện: Hải Châu
   - Đánh giá: 8.5/10
   - Giá: 5,000,000 - 20,000,000 VND
   - Địa chỉ: 24-26 Hùng Vương, Hải Châu
[2] Suối Hoa
   - Loại: địa điểm tham quan
   - Quận/Huyện: Hòa Vang
   - Đánh giá: 8.0/10
   - Địa chỉ: Thôn Phú Túc, Xã Hòa Phú
    """
    
    user_prompt = f"""
Dựa vào dữ liệu sau:
{context}

Hãy lên lịch trình 1 ngày đi Suối Hoa và ăn ở Central Market.
    """
    
    print("Testing with Gemini...")
    try:
        response = await client.generate(
            system_content=system_prompt,
            user_content=user_prompt
        )
        print("Response:\n", response)
    except Exception as e:
        print("Gemini failed:", e)

asyncio.run(test())
