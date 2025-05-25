# Fix for missing imghdr in Pydroid3 (if still needed, often not necessary with recent PTB)
import types
import sys
try:
    import imghdr
except ImportError:
    print("imghdr module not found, creating a dummy one for Pydroid3.")
    imghdr_module = types.ModuleType("imghdr")
    imghdr_module.what = lambda *a, **k: None
    sys.modules["imghdr"] = imghdr_module

import requests
import time
import base64
import mimetypes
from io import BytesIO

from telegram import Bot, Update, ChatAction, ParseMode, InputFile
from telegram.ext import Dispatcher, MessageHandler, Filters, CommandHandler, CallbackContext
import telegram.error

# --- Configuration ---
BOT_TOKEN = "8065502134:AAFKlUwlHs6W7nvIpaxpZNg_okFXdyUyPGU" # Replace with your Bot Token
GEMINI_API_KEY = "AIzaSyCiO6InSNB6PpxNyAEdDuvQmW-baGFyX0U" # Replace with your Gemini API Key
GEMINI_MODEL_NAME = "gemini-1.5-flash" # Or "gemini-1.5-flash-latest"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL_NAME}:generateContent"

# System instruction to guide the bot's behavior
SYSTEM_INSTRUCTION = (
    "You are a helpful and friendly Telegram chatbot. "
    "Your responses should be informative and concise. "
    "Format important information using Markdown (e.g., **bold** for emphasis)."
    "If asked to analyze an image, describe it or answer questions based on its content."
)

# Memory store: {user_id: {"history": [messages_for_api], "size_bytes": int}}
user_histories = {}
MAX_USER_STORAGE_BYTES = 5 * 1024 * 1024  # 5 MB per user
MAX_HISTORY_TURNS = 10  # Max user/assistant turns (20 messages total) to keep for API context
MAX_TELEGRAM_MESSAGE_LENGTH = 4000 # Telegram's limit is 4096, leave some buffer

# --- Gemini API Interaction ---
def query_gemini(api_conversation_history, system_instruction_text=None, generation_config=None):
    payload = {"contents": api_conversation_history}

    if system_instruction_text:
        payload["system_instruction"] = {"parts": [{"text": system_instruction_text}]}

    if generation_config:
        payload["generationConfig"] = generation_config
    else: # Default generation config
        payload["generationConfig"] = {
            "temperature": 0.7,
            "topP": 0.95,
            "maxOutputTokens": 2048,
        }

    print(f"Sending payload to Gemini: {payload}") # For debugging

    try:
        res = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=60  # Increased timeout for potentially larger payloads (images) or longer generation
        )
        res.raise_for_status()
        response_data = res.json()
        print(f"Raw Gemini Response: {response_data}") # For debugging

        if not response_data.get("candidates"):
            prompt_feedback = response_data.get("promptFeedback")
            if prompt_feedback:
                block_reason = prompt_feedback.get("blockReason", "Unknown reason")
                print(f"Warning: Request blocked or filtered by API. Reason: {block_reason}")
                # You can check specific safetyRatings if needed
                # safety_ratings = prompt_feedback.get("safetyRatings")
                return f"I'm sorry, I can't respond to that due to content restrictions ({block_reason}). Please try something else."
            raise Exception("API Error: No candidates found in Gemini response and no promptFeedback.")

        candidate = response_data["candidates"][0]
        if not candidate.get("content") or not candidate["content"].get("parts"):
            finish_reason = candidate.get("finishReason", "UNKNOWN")
            print(f"Warning: No content parts in candidate. Finish reason: {finish_reason}")
            if finish_reason == "SAFETY":
                return "I'm unable to provide a response due to safety guidelines. Please rephrase your message."
            elif finish_reason == "MAX_TOKENS":
                return "The response was too long and got cut off by the API. Try asking for a shorter response."
            # Add more finish_reason checks if needed: RECITATION, OTHER
            return f"I couldn't generate a full response (Reason: {finish_reason}). Please try again."

        response_text = "".join(part.get("text", "") for part in candidate["content"]["parts"])
        return response_text.strip()

    except requests.exceptions.HTTPError as http_err:
        error_details = "No additional details in response."
        try:
            error_details = res.json()
        except ValueError:
            error_details = res.text
        print(f"API HTTP Error: {http_err} - Details: {error_details}")
        # Check for specific Gemini error codes if available in error_details
        # e.g. Quota exceeded, API key invalid etc.
        if res.status_code == 400: # Bad Request
             return "There was an issue with the request sent to the AI (Bad Request). Please tell the admin."
        elif res.status_code == 429: # Rate limit
             return "I'm a bit busy right now. Please try again in a few moments."
        raise Exception(f"API Error ({res.status_code}): {http_err}") # Re-raise for generic handler
    except requests.exceptions.RequestException as e:
        print(f"Network or Request Error: {e}")
        raise Exception(f"Network error while contacting AI: {e}")
    except (KeyError, IndexError, TypeError) as e: # More specific parsing errors
        print(f"Error parsing Gemini response: {e} - Full Response: {response_data if 'response_data' in locals() else 'N/A'}")
        raise Exception(f"Error understanding AI's response: {e}")


# --- Telegram Command Handlers ---
def start_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Welcome to your Gemini Chatbot! 🤖\n"
        "Send a message or an image with a caption, and I’ll reply! ✨\n"
        "Use /reset to clear our conversation history."
    )

def reset_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id in user_histories:
        user_histories.pop(user_id)
        update.message.reply_text("🗑️ Conversation history cleared! Ready for a fresh start. 🚀")
    else:
        update.message.reply_text("No history to clear. Let's chat! 😊")

# --- Message Processing Logic ---
def _process_user_message(update: Update, context: CallbackContext, text_input: str = None, image_file_info: dict = None):
    user_id = update.effective_user.id
    chat_id = update.message.chat_id

    context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    user_data = user_histories.setdefault(user_id, {"history": [], "size_bytes": 0})
    current_api_history = list(user_data["history"]) # Work with a copy for this turn

    # --- Construct current user turn for API ---
    current_user_parts = []
    history_text_for_user_turn = "" # For storing in user_histories

    if text_input:
        current_user_parts.append({"text": text_input})
        history_text_for_user_turn = text_input

    if image_file_info:
        current_user_parts.append({
            "inline_data": {
                "mime_type": image_file_info["mime_type"],
                "data": image_file_info["base64_data"]
            }
        })
        if history_text_for_user_turn:
             history_text_for_user_turn += " [Image attached]"
        else:
            history_text_for_user_turn = "[User sent an image]"


    if not current_user_parts: # Should not happen if handlers are correct
        update.message.reply_text("Please send some text or an image with a caption.")
        return

    # Add current user message to the API history for this call
    current_api_history.append({"role": "user", "parts": current_user_parts})

    try:
        ai_response = query_gemini(current_api_history, SYSTEM_INSTRUCTION)

        if not ai_response: # query_gemini might return empty or None on certain errors
            ai_response = "😞 Oops! I couldn't get a response from the AI. Please try again. 🔧"

        # Truncate if too long for Telegram
        if len(ai_response) > MAX_TELEGRAM_MESSAGE_LENGTH:
            ai_response = ai_response[:MAX_TELEGRAM_MESSAGE_LENGTH - 5] + "[...]"

        update.message.reply_text(
            ai_response,
            parse_mode=ParseMode.MARKDOWN,
            reply_to_message_id=update.message.message_id
        )

        # --- Update persistent history ---
        # Add actual user turn (text only for history simplicity)
        user_data["history"].append({"role": "user", "parts": [{"text": history_text_for_user_turn}]})
        # Add assistant response
        user_data["history"].append({"role": "model", "parts": [{"text": ai_response}]}) # Store AI's actual reply

        # Trim history to MAX_HISTORY_TURNS (1 turn = 1 user + 1 model message)
        while len(user_data["history"]) > MAX_HISTORY_TURNS * 2:
            user_data["history"].pop(0) # Remove oldest message (user or model)

        # Recalculate storage (simplified: just text parts for size)
        current_size = 0
        for entry in user_data["history"]:
            for part in entry.get("parts", []):
                if "text" in part:
                    current_size += len(part["text"].encode('utf-8'))
        user_data["size_bytes"] = current_size

        if user_data["size_bytes"] > MAX_USER_STORAGE_BYTES:
            # Simple notification, more aggressive trimming could be added if needed
            print(f"User {user_id} storage approaching limit: {user_data['size_bytes']} bytes.")
            # update.message.reply_text("FYI: Our conversation history is getting large!")

    except Exception as e:
        print(f"Error in _process_user_message for user {user_id}: {e}")
        update.message.reply_text("😞 Oops! Something went wrong. Please try again! 🔧")


def handle_text_message(update: Update, context: CallbackContext):
    text = update.message.text
    if not text: return # Should not happen with Filters.text
    _process_user_message(update, context, text_input=text)

def handle_photo_message(update: Update, context: CallbackContext):
    caption = update.message.caption if update.message.caption else "" # Allow image without caption
    photo_file_id = update.message.photo[-1].file_id # Get the largest available photo

    try:
        tg_file = context.bot.get_file(photo_file_id)
        
        # Download as bytes
        image_byte_array = BytesIO()
        tg_file.download(out=image_byte_array)
        image_bytes = image_byte_array.getvalue()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Determine MIME type
        mime_type = None
        if tg_file.file_path:
            mime_type, _ = mimetypes.guess_type(tg_file.file_path)
        
        if not mime_type or mime_type not in ["image/jpeg", "image/png", "image/gif", "image/webp"]: # Gemini supports these
            print(f"Guessed MIME type {mime_type} not ideal or unknown, defaulting to image/jpeg for photo.")
            mime_type = "image/jpeg" # Telegram photos are often JPEGs

        image_info = {"base64_data": image_base64, "mime_type": mime_type}
        _process_user_message(update, context, text_input=caption, image_file_info=image_info)

    except telegram.error.TelegramError as te:
        print(f"Telegram error downloading photo: {te}")
        update.message.reply_text("Sorry, I couldn't download the image. Please try again.")
    except Exception as e:
        print(f"Error processing photo: {e}")
        update.message.reply_text("😞 Oops! Something went wrong while processing the image. Please try again! 🔧")


# --- Main Bot Setup ---
def main():
    bot = Bot(BOT_TOKEN)
    # use_context=True is default in PTB v13+, explicit for clarity
    # For Pydroid3 and simplicity, workers=0 means synchronous processing in main thread.
    # If you had many async operations within handlers not related to PTB's own async http client,
    # then you might need workers. For this setup, 0 is fine.
    dp = Dispatcher(bot, None, workers=4, use_context=True) # Using a few workers for responsiveness

    # Add handlers
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("reset", reset_command))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_message))
    dp.add_handler(MessageHandler(Filters.photo & ~Filters.command, handle_photo_message))

    print("🤖 Bot is running... 🚀 (Polling for updates)")

    # Basic polling loop (for environments where webhooks are not straightforward)
    # For production, consider using PTB's built-in updater.start_polling() / start_webhook()
    last_update_id = None
    while True:
        try:
            updates = bot.get_updates(offset=last_update_id, timeout=10, allowed_updates=['message'])
            for update_obj in updates:
                if update_obj.update_id:
                    dp.process_update(update_obj)
                    last_update_id = update_obj.update_id + 1
        except telegram.error.NetworkError as e:
            print(f"Polling NetworkError: {e}. Retrying in 5 seconds...")
            time.sleep(5)
        except telegram.error.RetryAfter as e:
            print(f"Polling RetryAfter: Flood control, sleeping for {e.retry_after} seconds.")
            time.sleep(e.retry_after + 1) # Sleep a bit longer than requested
        except telegram.error.Unauthorized:
            print("Bot token is invalid or revoked. Halting.")
            break # Stop the bot if unauthorized
        except telegram.error.TelegramError as e:
            print(f"Polling TelegramError: {e}. Retrying in 15 seconds...")
            time.sleep(15)
        except Exception as e:
            print(f"Unhandled error in polling loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
    
