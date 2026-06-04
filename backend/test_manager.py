import asyncio
import os
import sys

# Setup mock for config
sys.path.append(os.path.dirname(__file__))

from app.rag.manager import ConversationManager

class MockLLM:
    def create_chat_completion(self, messages, **kwargs):
        prompt = messages[0]['content']
        print(f"--- Prompt Sent to LLM ---\n{prompt}\n--------------------------")
        # Return mock JSON
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"is_followup": true, "is_topic_shift": false, "standalone_query": "Khách sạn Novotel Đà Nẵng giá bao nhiêu?"}'
                    }
                }
            ]
        }

async def test_resolve():
    llm = MockLLM()
    manager = ConversationManager(llm)
    
    history = [
        {"role": "user", "content": "Khách sạn Novotel Đà Nẵng có tốt không?"},
        {"role": "assistant", "content": "Khách sạn Novotel Đà Nẵng rất tốt, đạt chuẩn 5 sao."}
    ]
    query = "Giá bao nhiêu?"
    
    result = await asyncio.to_thread(manager.resolve_context, query, history)
    print("Resolved Context:", result)

if __name__ == "__main__":
    asyncio.run(test_resolve())
