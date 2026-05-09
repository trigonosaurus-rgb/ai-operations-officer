import streamlit as st
import requests

# 1. Page configuration and layout
st.set_page_config(page_title="Logistics AI Agent", page_icon="📦", layout="centered")

st.title("📦 Logistics AI Assistant")
st.markdown("I can help you with scheduling, shipping costs, and packaging rules from the Baker Logistics contract.")

# --- Sidebar for settings and memory management ---
with st.sidebar:
    st.header("Settings")
    if st.button("🗑️ Clear Chat History"):
        # Clear visual memory in Streamlit
        st.session_state.messages = []
        # Send signal to backend to forget context
        try:
            requests.post("http://127.0.0.1:8000/clear_memory")
            st.success("Memory cleared!")
        except Exception:
            st.error("Failed to reach the backend.")
        st.rerun()
# ------------------------------------------------

# 2. Initialize chat memory in session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# 3. Render all previous messages on page update
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. User input field
if prompt := st.chat_input("Ask a question (e.g., 'What is the cost for a 5000 lb truck?'):"):
    
    # Display the user's question in the chat immediately
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 5. Send request to the FastAPI backend
    with st.chat_message("assistant"):
        with st.spinner("Agent is searching databases and documents..."):
            try:
                response = requests.post(
                    "http://127.0.0.1:8000/ask_agent",
                    json={"query": prompt}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("answer", "Error: No answer received.")
                    sources = data.get("sources", [])
                    
                    # Display the main answer
                    st.markdown(answer)
                    
                    # Display sources if available
                    if sources:
                        st.markdown("---") # Thin separator line
                        st.caption("Sources used for this answer:")
                        for s in sources:
                            st.caption(s)
                            
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                else:
                    st.error(f"Server Error {response.status_code}: {response.text}")
            
            except Exception as e:
                st.error("Connection failed. Is the FastAPI server running?")
                st.error(str(e))