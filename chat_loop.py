import requests
import json

# Configuration
BASE_URL = "http://localhost:5678"
WEBHOOK_PATH = "/webhook/chat-local"

def send_message(phone, message):
    """Send message to webhook and return response"""
    url = f"{BASE_URL}{WEBHOOK_PATH}"
    payload = {
        "phone": phone,
        "message": message
    }
    
    print(f"   [DEBUG] Sending to: {url}")
    print(f"   [DEBUG] Payload: {json.dumps(payload)}")
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        
        response.raise_for_status()
        
        # Parse JSON
        data = response.json()
        return data
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Error: Cannot connect to {url}. Is n8n running?")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON response: {e}")
        print(f"   Raw response was: {response.text if 'response' in locals() else 'No response'}")
        return None
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
        return None

def main():
    print("="*60)
    print("JITO Event Bot - Interactive Chat")
    print("="*60)
    print()
    
    # Get phone number once at start
    phone = input("Enter your phone number (+91...): ").strip()
    if not phone:
        print("Phone number required!")
        return
    
    print(f"\n✅ Connected as: {phone}")
    print("Type 'exit' or 'quit' to stop")
    print("="*60)
    print()
    
    # Chat loop
    while True:
        # Get user message
        message = input("You: ").strip()
        
        # Check for exit
        if message.lower() in ['exit', 'quit', 'bye']:
            print("\n👋 Goodbye!")
            break
        
        # Skip empty messages
        if not message:
            continue
        
        # Send to webhook
        print("🤖 Bot is thinking...")
        result = send_message(phone, message)
        
        if result:
            print("✅ Got response")
            # FIX: Use 'reply_text' not 'reply'
            reply = result.get('reply_text', result.get('reply', 'No reply received'))
            print(f"Bot: {reply}")
            print("-" * 60)
        else:
            print("❌ Failed to get response")
            print()

if __name__ == "__main__":
    main()
