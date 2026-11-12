# Qwen2.5 Coder notes

The production RAG backend uses Ollama with the local model `qwen2.5-coder:32b`.
Embeddings stay on BGE via FastEmbed and are independent of the chat model.
When answering questions, the assistant must rely on retrieved document context.
If context is missing, it should say it cannot answer from the available documents.
