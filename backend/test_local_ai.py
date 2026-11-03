
from ollama import chat

response = chat(
    model="llama3.2",
    messages=[
        {
            "role": "user",
            "content": "You are an ERP assistant. Explain what low stock means."
        }
    ]
)

print("\nAI RESPONSE:")
print(response.message.content)
