import atexit
import json
import os
import msvcrt
import queue
import socket
import speech_recognition as sr
import subprocess
import sys
import threading
import time
import winsound
from pathlib import Path
# ... other imports

os.system('color 2A')

def play_success_tone():
    # winsound.Beep(frequency, duration_ms)
    winsound.Beep(1000, 75) # A short, high-pitched "blip"
    #winsound.Beep(1200, 100) # A slightly higher follow-up
def play_success_tone2():
    # winsound.Beep(frequency, duration_ms)
    winsound.Beep(1000, 150) # A short, high-pitched "blip"
    winsound.Beep(800, 200) # A slightly higher follow-up
def check_muted():
    try:
        with open("settings.json", "r") as f:
            data = json.load(f)
            val = data.get("mute", True)
            result = val.lower() == "true"
            print ("Muted" if result == True else "Unmuted", flush=True)
            return result
    except:
        return True # Default to True if file is busy
# --- New Cleanup Function ---
def cleanup_socket():
    """Ensures the lock socket is closed upon exit to prevent TIME_WAIT conflicts."""
    global LOCK_SOCKET
    if LOCK_SOCKET:
        try:
            LOCK_SOCKET.close()
            print("[CLEANUP] Single-instance lock socket released.")
        except Exception as e:
            print(f"[CLEANUP ERROR] Failed to close socket gracefully: {e}")
# ... (Global flags and variables)
LOCK_SOCKET = None
# --- Configuration ---
Muted = check_muted()
CURRENT_DIR = Path(__file__).resolve().parent
MAIN_SCRIPT_PATH = CURRENT_DIR / "ollama.py"
# Unique port for the single-instance check (using a high-numbered port)
LOCK_PORT = 60000
LOCK_HOST = '127.0.0.1'
# Interval for the scheduled notification (in seconds)
# Set to 30 minutes (1800 seconds)
SCHEDULED_INTERVAL = 1800 
# Global flags
NOTIFICATIONS_ENABLED = False
LOCK_SOCKET = None 
OLLAMA_SERVICE_ENABLED = False
def check_and_bind_socket():
    """
    Attempts to bind a socket to a specific port to prevent multiple script instances.
    """
    global LOCK_SOCKET
    LOCK_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # We try to bind the socket to the lock port. If this fails, another instance is running.
        LOCK_SOCKET.bind((LOCK_HOST, LOCK_PORT))
        print(f"[INIT] Single-instance lock acquired on {LOCK_HOST}:{LOCK_PORT}.")
        # Keep the socket open to maintain the lock
    except socket.error as e:
        # Error codes for 'Address already in use'
        if e.errno == 98 or e.errno == 10048: 
            print("\n[CRITICAL]: Another instance of the CLI Listener is already running.")
            print("Please close the existing instance before running this script again.")
            sys.exit(1) 
        else:
            print(f"[CRITICAL]: Failed to acquire single-instance lock: {e}")
            sys.exit(1)
# ... (end of check_and_bind_socket function)
# --- Register Cleanup ---
atexit.register(cleanup_socket)
# --- Notification Initialization (Made optional to prevent crash) ---
try:
    from plyer import notification as system_notification
    NOTIFICATIONS_ENABLED = True
    print("[INIT] System notifications (plyer) loaded successfully.")
except ImportError:
    print("\n[NOTE]: Missing 'plyer' library. Scheduling feature disabled.")
    print("To enable scheduled reminders, please run: pip install plyer")
# --- Ollama Service Management (Made optional for stability) ---
try:
    import requests
    OLLAMA_SERVICE_ENABLED = True
    OLLAMA_URL = "http://localhost:11434"
    OLLAMA_HEALTH_ENDPOINT = f"{OLLAMA_URL}/api/tags"
    OLLAMA_SERVE_COMMAND = ["ollama", "serve"]
    print("[INIT] Ollama management tools loaded successfully.")
except ImportError:
    OLLAMA_SERVICE_ENABLED = False
    print("\n[NOTE]: Missing 'requests' library. Ollama auto-start feature disabled.")
    print("To enable Ollama auto-start and health checks, please run: pip install requests")
def check_ollama_status():
    """Checks if the Ollama service is currently running via an API call."""
    if not OLLAMA_SERVICE_ENABLED:
        return False
    try:
        # Ping the /api/tags endpoint to check if the server responds
        response = requests.get(OLLAMA_HEALTH_ENDPOINT, timeout=1)
        if response.status_code == 200:
             print("[OLLAMA] Service is already running.")
             return True
        return False
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        return False
def start_ollama_service():
    """Starts the 'ollama serve' command as a detached background process."""
    if not OLLAMA_SERVICE_ENABLED:
        return
    print("[OLLAMA] Service not found. Attempting to start 'ollama serve' in the background...")
    try:
        # Use subprocess.Popen to start Ollama as a non-blocking background process
        # We redirect streams to DEVNULL and start a new session for true backgrounding.
        subprocess.Popen(
            OLLAMA_SERVE_COMMAND,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True 
        )
        # Allow the service a moment to initialize
        print("[OLLAMA] Waiting 5 seconds for service to initialize...")
        time.sleep(5)
        # Verify startup
        if check_ollama_status():
            print("[OLLAMA] Service started successfully.")
            return True
        else:
            print("[OLLAMA ERROR] Service started, but health check failed after 5 seconds.")
            return False
    except FileNotFoundError:
        print("[OLLAMA CRITICAL ERROR]: 'ollama' executable not found in system PATH.")
        print("Please ensure Ollama is installed and its path is correctly configured.")
    except Exception as e:
        print(f"[OLLAMA CRITICAL ERROR]: Failed to start Ollama service: {e}")
    return False
# --- Notification Functions (Unchanged from previous version) ---
def send_task_notification(title, message):
    """Sends a system notification using the plyer library."""
    if not NOTIFICATIONS_ENABLED:
        return
    try:
        system_notification.notify(
            title=title,
            message=message,
            app_name='CLI Scheduler',
            timeout=10
        )
    except Exception as e:
        print(f"[NOTE]: Could not send system notification from scheduler ({e})")
def scheduled_notification_thread():
    """Runs on a separate thread, sending a notification every N seconds."""
    if not NOTIFICATIONS_ENABLED:
        return
    print(f"[SCHEDULER] Notification timer started. First alert in {SCHEDULED_INTERVAL / 60} minutes...")
    time.sleep(5) 
    while True:
        try:
            time.sleep(SCHEDULED_INTERVAL)
            message = "Remember to check your LLM training progress on your local machine."
            send_task_notification(
                title="LLM Training Reminder",
                message=message
            )
        except Exception as e:
            print(f"[SCHEDULER ERROR]: Thread encountered an error: {e}")
            break
def cli_listener():
    # --- Setup Voice Background Listener ---
    r = sr.Recognizer()
    # --- The "Gemini Live" Tuning ---
    r.pause_threshold =2.6  # Don't wait forever for me to finish (default is 1.0)
    r.non_speaking_duration = 0.4 # Shorter lead-in
    r.phrase_threshold = 0.3 # Catch shorter words like "Hey" or "No"

    stop_listening = None
    m = sr.Microphone()
    with m as source:
        r.adjust_for_ambient_noise(source, duration=0.8)
    if not Muted:
        stop_listening = r.listen_in_background(m, voice_callback)

    print("\n--- CLI Listener Active (Voice & Text) ---")
    print("Speak naturally or type your prompt.")
    print("Type 'exit' or 'quit' to shut down.")
    print("-" * 50)

    while True:
        try:
            user_input = None
            # 1. PRIORITY: Check Voice Queue
            # If the background thread found speech, this triggers IMMEDIATELY.            
            if not Muted:
                if not speech_queue.empty():
                    user_input = speech_queue.get()
                    print(f"PROMPT> {user_input} (Voice)", flush=True)                
                    
            # 2. HYBRID: Check Keyboard (Non-blocking)
            # returns True ONLY if a key is waiting in the buffer.
            elif msvcrt.kbhit():
                user_input = input("PROMPT> ")# 3. EXECUTION: If we have input (from either source), run it.
            if user_input:
                play_success_tone()                
                # Standard exit logic
                if user_input.lower() in ['exit', 'quit']:
                    if stop_listening:
                        stop_listening(wait_for_stop=False)
                    print("\nShutting down...")
                    sys.exit(0)
                if not user_input.strip():
                    continue
                # Run the command
                command = [sys.executable, str(MAIN_SCRIPT_PATH), user_input]
                #print(f"\n[EXECUTOR] Running command: {' '.join(command)}")

                # Running with text=True handles decoding automatically
                result = subprocess.run(
                    command,
                    check=False,
                    shell=False,
                    capture_output=True,
                    text=True,                # Automatically decodes output to string
                    errors='replace',         # Replaces bad characters instead of crashing
                    encoding="utf-8",       # Force UTF-8 for the output
                    stdin=subprocess.DEVNULL,
                )
                if result.stdout:
                    print(result.stdout)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)                
                print("-" * 50)

            # 4. CPU SAVER: Sleep for 50ms so the loop doesn't hog the processor.
            time.sleep(0.05)

        except (EOFError, KeyboardInterrupt):
            stop_listening(wait_for_stop=False)
            sys.exit(0)
        except Exception as e:
            print(f"\n[CRITICAL ERROR] Listener failed: {e}")
            time.sleep(1)
speech_queue = queue.Queue()
def voice_callback(recognizer, audio):
    """Callback function that runs in the background when speech is captured."""
    try:
        # Using recognize_google for simplicity
        text = recognizer.recognize_google(audio)
        if text.strip():
            speech_queue.put(text)
    except sr.UnknownValueError:
        pass # Ignore unintelligible noise
    except sr.RequestError:
        print("\n[Voice Error] Google Service down.")
        
if __name__ == "__main__":
    # 1. Single-instance check
    check_and_bind_socket()
    # 2. Ollama Service Auto-Start (new feature)
    if OLLAMA_SERVICE_ENABLED:
        if not check_ollama_status():
             start_ollama_service()
    # 3. Start the scheduled notification thread
    timer_thread = threading.Thread(target=scheduled_notification_thread, daemon=True)
    timer_thread.start()
    # 4. Start the main CLI listener loop
    cli_listener()