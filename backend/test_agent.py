
# from agent import ask_erp

# print("\n========== ERP AI AGENT ==========\n")

# question = input("Ask your ERP: ")

# answer, history = ask_erp(question)

# print("\nAI ANSWER:")
# print(answer)
from agent import ask_erp

print("\n========== ERP AI AGENT ==========")
print("Type 'hakuna matata' at any time to exit.\n")

# Start with an empty conversation history
history = None

while True:
    # 1. Get the user's question
    question = input("Ask your ERP: ").strip()
    
    # 2. Check for the exit command (ignores upper/lowercase spaces)
    if question.lower() == "hakuna matata":
        print("\nExiting ERP Agent. Goodbye!")
        break
        
    # 3. Skip empty inputs if the user just hits Enter
    if not question:
        continue
        
    # 4. Get the answer from the AI, passing the ongoing history
    answer, history = ask_erp(question, history)
    
    # 5. Print the AI's response
    print("\nAI ANSWER:")
    print(answer)
    print("-" * 40 + "\n")
