
from agent import ask_erp

print("\n========== ERP AI AGENT ==========\n")

question = input("Ask your ERP: ")

answer, history = ask_erp(question)

print("\nAI ANSWER:")
print(answer)
