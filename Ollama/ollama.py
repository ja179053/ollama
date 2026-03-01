# ollama_executor.py: Executor with Content Mode Fallback and Extension Flag
# Standard Library Imports
import io
import json
import locale
import math
import msvcrt
import multiprocessing
import os
import queue
speech_queue = queue.Queue()
import re
import shlex
import socket
import subprocess
import sys
import time
import threading
#import win32gui
#import win32console
# Third-Party Imports
import requests
import shutil
import speech_recognition as sr
from datetime import datetime
#edgee tts is better tts than pyttsx3, but does not work offline
#kokora sounds like a audiobook
#piper sounds human but not appealing
#espeak_folder = r"D:\Ollama\eSpeak NG"
from kokoro_onnx import Kokoro
import sounddevice as sd
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(SCRIPT_DIR, "settings.json")
STATS_FILE = os.path.join(SCRIPT_DIR, "stats.json")
kokoro = Kokoro(os.path.join(SCRIPT_DIR, "kokoro-v1.0.onnx"), os.path.join(SCRIPT_DIR, "voices-v1.0.bin"))
# Load this once when the script starts
with open(os.path.join(SCRIPT_DIR, "triggers.json"), "r") as f:
    TRIGGER_MAP = json.load(f)
with open(os.path.join(SCRIPT_DIR, "settings.json"), "r") as f:
    SETTINGS = json.load(f)
with open(STATS_FILE, 'r') as f:
        stats = json.load(f)
SELECTED_VOICE = ""
interrupted = False
time_taken = 15
conversation_history = ""
#region configuration
def has_internet():
    try:
        # Connect to Google's DNS on port 53 (DNS)
        # timeout=1 ensures your script doesn't hang for 30 seconds if offline
        socket.create_connection(("8.8.8.8", 53), timeout=1)
        #print ("internet connected")
        return True
    except OSError:
        return False
def save(data):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=4) # indent makes it readable
#endregion
# Configuration
WANT_CLOUD = SETTINGS["online"]
USE_CLOUD = WANT_CLOUD if has_internet() else False
DEFAULT_MODEL = "gemma3:4b-it-qat" if not USE_CLOUD else "qwen3-vl:235b-cloud"
OLLAMA_API_URL = "http://127.0.0.1:11434/api/generate"
# CRITICAL SYSTEM INSTRUCTION (Aggressive)
DEFAULT_SYSTEM_INSTRUCTION = (
# Updated, even more aggressive system instruction
# Add a mandatory, unique command prefix the model MUST use
"You are a command line generation expert. Your response MUST start with the prefix 'CMD_OUT:' followed immediately by a single, raw, executable command. DO NOT include any text, greetings, apologies, or explanation before or after this prefix. If you cannot generate a command, output only the single character '~' and nothing else. No yapping. If asked for code, provide only the solution. Direct answer only. No intro. No 'Understanding the Problem'. Just the code."
)
# Utility Functions (Execution Helpers - Unchanged)
GENERIC_EXECUTABLE_BLACKLIST = {'help', 'say', 'echo', 'print', 'hey', 'hi', 'hello', 'sure', 'ok', 'skip'}
chat_history = ""
# CRITICAL: Force UTF-8 Encoding for Console Output
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
except Exception:
    pass

# Notification Library Import (Used ONLY for local data success)
try:
    from plyer import notification as system_notification
except ImportError:
    def system_notification(title, message, app_name, timeout):
        print(f"\n[NOTIFICATION FAILBACK] {title}: {message}")
#region config    
#region muting
def check_mute_keywords():
    try:
        with open("settings.json", "r") as f:
            data = json.load(f)
            return not data.get("mute", True)
    except:
        return True # Default to True if file is busy
#endregion
def check_for_real_time_query(prompt):
    """Handles time queries locally and notifies on success."""
    time_keywords = ['current time', 'what time is it', 'the time now']
    
    if any(keyword in prompt.lower() for keyword in time_keywords):
        now = datetime.now()
        time_string = now.strftime("The current local time is %A, %B %d, %Y at %I:%M:%S %p.")
        
        # Only successful output is printed
        print("[LOCAL DATA RESPONSE]")
        print("[OUTPUT] {time_string}".format(time_string=time_string))
        
        send_task_notification("🕒 Local Data Query", time_string)
        return True
    
    return False 
#endregion
def clean_tts(text):
    #print ("I said" , text, flush=True)
    """Removes asterisks, backslashes, and extra symbols for natural speech."""
    # 1. Remove Markdown bold/italic (e.g., **text** or *text*)
    text = text.encode('ascii', 'ignore').decode('ascii').strip()
    text = text.replace("#", "").replace("*", "").replace("`", "")
    text = text.replace("Mmm", "").replace("mmm", "")
    #text = text.replace("\n", "")
    text = text.replace("~~", ",").replace("~", ",")
    #text = text.replace(".", ",").replace("?", ",").replace("!", ",")
    
    # 2. Remove backslashes and technical characters
    text = text.replace("\\", " ").replace("_", " ")
    
    # 3. Clean up any weird semicolon prefixes we discussed earlier
    if ";" in text:
        text = text.split(";", 1)[1]
        
    # 4. Remove multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

# Notification Functions (SILENCED ON FAILURE)
def send_task_notification(title, message):
    """Sends a system notification. Used only for success/local data."""
    if title in ["✅ Task Completed", "🕒 Local Data Query", "📄 File Created"]:
        try:
            system_notification.notify(
                title=title,
                message=message,
                app_name='CLI Assistant',
                timeout=8
            )
        except Exception:
            pass

# --- UPDATED: Content Mode Handler for Relative Save ---
def handle_content_mode(user_prompt, generated_content, base_dir, overwrite_mode, custom_ext):
    """Parses prompt for a filename and saves the generated content."""
    
    # 1. Determine the filename
    # Regex now explicitly looks for common extensions as a fallback
    filename_match = re.search(r'(\w+)(\.(txt|md|log|py|json|yml|html|css|js))', user_prompt, re.IGNORECASE)
    
    if filename_match:
        # If a name and extension are found in the prompt
        base_name = filename_match.group(1)
        # Use custom_ext if provided via flag, otherwise use the detected extension
        extension = custom_ext if custom_ext else filename_match.group(2)
        filename = f"{base_name}{extension}"
    elif custom_ext:
        # If only a custom extension is provided via flag
        filename = f"llm_output{custom_ext}"
    else:
        # Fallback to the default name and extension
        filename = "llm_output.txt"
    
    # Path used only for safety check
    absolute_path_for_check = os.path.abspath(os.path.join(base_dir, filename)) 
    
    if os.path.exists(absolute_path_for_check) and not overwrite_mode:
        print(f"[ERROR] File safety block: '{filename}' already exists. Use --ow to overwrite.", file=sys.stderr)
        return False
        
    try:
        # CRITICAL FIX: Temporarily change directory to base_dir
        original_cwd = os.getcwd()
        os.chdir(base_dir) 
        
        # Save using ONLY the filename (guaranteed relative saving)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(generated_content)
        
        # Restore the original CWD immediately
        os.chdir(original_cwd) 
        
        # Confirmation message: Prints filename and directory alias
        print(f"[FILE CREATED] Successfully wrote {len(generated_content)} bytes to file.")
        print(f"[OUTPUT] File Name: {filename} (Saved in: {base_dir})") 
        
        send_task_notification("📄 File Created", f"File '{filename}' was created successfully.")
        return True
        
    except Exception as e:
        # Restore CWD in case of error
        os.chdir(original_cwd) 
        print(f"[CRITICAL ERROR] Failed to write file '{filename}': {e}", file=sys.stderr)
        return False


def is_executable_in_path(command):
    if command.lower() in GENERIC_EXECUTABLE_BLACKLIST:
        return False
    if command == 'ls':
        return True
    return shutil.which(command) is not None

def portable_ls(base_dir, args):
    try:
        files = os.listdir(base_dir)
        files.sort()
        return True, "\n".join(files)
    except Exception as e:
        return False, f"Portable ls failed: {e}"

def speak_task():
    global interrupted    
    while True:
        try:
            # Expecting a tuple of (samples, sample_rate)
            item = speech_queue.get(timeout=5) 
            
            if item is None: break # Signal to kill the thread
            
            if interrupted: 
                speech_queue.task_done()
                interrupted = False # Reset for next playback
                continue
            
            samples, sample_rate = item
            
            # Instant playback, no generation lag
            sd.play(samples, sample_rate)
            
            while sd.get_stream().active:
                if interrupted: 
                    sd.stop()
                    break
                sd.sleep(100)

        except queue.Empty:
            # ONLY break when the queue has actually been empty for 5 seconds
            #print("Queue empty, closing voice process.")
            break

# File Safety and Execution (shell=False)
def check_and_execute_command(command_parts, base_dir, overwrite_mode):
    """Executes a list of individual commands sequentially with shell=False. Fails silently on error."""
    full_output = []
    
    for command in command_parts:
        command = command.strip()
        if not command:
            continue
            
        try:
            args = shlex.split(command, posix=False) 
        except ValueError as e:
            # Silent Failure
            return False, "Invalid command structure detected."

        first_arg = args[0] if args else ''
        target_path = None
        
        if first_arg in ['touch', 'mkdir'] and len(args) > 1:
            target_path = args[1]
        
        if target_path:
            absolute_path = os.path.abspath(os.path.join(base_dir, target_path))
            
            if os.path.exists(absolute_path) and not overwrite_mode:
                # Silent Failure
                return False, "Safety block: File exists."

        # Execute the command
        if first_arg == 'ls':
             success, output_msg = portable_ls(base_dir, args[1:])
        else:
            try:
                result = subprocess.run(args, shell=False, check=False, text=True, capture_output=True, cwd=base_dir)
                success = result.returncode == 0
                output_msg = result.stdout.strip()
            except FileNotFoundError:
                # Silent Failure
                return False, "Executable not found."
            except Exception as e:
                 # Silent Failure
                 return False, "Execution error."
        
        # Check status and continue/halt
        if not success:
            # Silent Failure
            return False, "Command failed."
        else:
            if output_msg:
                 full_output.append(output_msg)
    
    final_output = "\n".join(full_output)
    print("[SUCCESS] All commands executed successfully.")
    if final_output:
        # Only successful final output is printed
        print(f"[OUTPUT]\n{final_output}")
    return True, final_output
def say():
        #print(f"{DEFAULT_MODEL}", flush=True)
        #i dont feel the need to have two settings for a silent mode. May adjust due to user feedback
        global interrupted
        if(SETTINGS["mute"]):
            sys.exit(0)
# Start the voice in a separate process so we can kill it
        task = threading.Thread(target=speak_task)
        #task.start()
        #p = multiprocessing.Process(target=speak_task)
        #p.start()# Start the microphone listener
        r = sr.Recognizer()
        with sr.Microphone() as source:
        # Lower the threshold so it's sensitive to your voice
            r.adjust_for_ambient_noise(source, duration=1)
            r.energy_threshold += 1000000         
            print(" [Listening for interruption...]", end="\r", flush=True)        
            while task.is_alive():
                try:
                # listen() blocks for a tiny bit to check for sound
                # phrase_time_limit=1 means it checks in 1-second chunks
                    r.listen(source, timeout=0.1, phrase_time_limit=1)                
                # If we get here, sound was detected!
                    interrupt()# Stops current audio
                    #with speech_queue.mutex:
                        #speech_queue.queue.clear() # Clears the "to-do list"
                    #p.terminate()
                    break
                except (sr.WaitTimeoutError, sr.UnknownValueError):
                # No speech detected yet, keep looping while AI is talking
                    continue 
        #if not interrupted:
            #task.join() # Clean up the process
def get_response(payload):
    global actual_duration
    global voice_proc
    global interrupted
    tts_started = False
    start_time = time.time()
    stop_loading = threading.Event()    
    spinner_thread = threading.Thread(target=loading_bar, args=(stop_loading,), daemon=True)
    spinner_thread.start()    
    try:        
        # Use stream=True and a small chunk_size to keep the pipe open
        response = requests.post(OLLAMA_API_URL, json=payload, stream=True, timeout=180)
        response.raise_for_status()        
        
        first_token = True
        full_content = ""
        sentence_buffer = ""
        # Using chunk_size=1 to ensure the loop ticks the moment a byte arrives
        for line in response.iter_lines(chunk_size=1):
            if line:
                if first_token:
                    stop_loading.set()
                    spinner_thread.join(timeout=0.1)
                    actual_duration = time.time() - start_time                    
                    first_token = False
                    save_stats()
                try:
                    chunk = json.loads(line.decode('utf-8'))
                    content = chunk.get('response', '')
                    
                    if content:
                        # THE FIX: Write every character directly to the console hardware
                        for char in content:
                            msvcrt.putwch(char)
                        
                        full_content += content
                        sentence_buffer += content

                        # TTS handling (stays in the background)                        
                        if not SETTINGS["mute"] and any(c in content for c in [".", "!", "?", "\n"]):
                            if interrupted: 
                                break
                            sentence = clean_tts(sentence_buffer.strip())
                            if sentence:
                                #Use to find irredular characters
                                #print ("sentence" + sentence)
                                l = get_system_lang()
                                samples, sample_rate = kokoro.create(
                                    text=sentence, 
                                    voice=SELECTED_VOICE, 
                                    speed=1.25, 
                                    lang=l
                                )

                                # Send the raw audio to the player thread
                                speech_queue.put((samples, sample_rate))
                                sentence_buffer = ""
                                 # 2. Start the speaker ONLY if it hasn't started yet for this response
                                if not tts_started:
                                    task = threading.Thread(target=speak_task, daemon=False)
                                    tts_started = True # Ensure we don't spawn 50 threads
                                    task.start()
                except json.JSONDecodeError:
                    print("json decode error")
                    continue
        #print(speech_queue.qsize()) 
        return full_content
    except requests.exceptions.Timeout:
            print("\n[ERROR] Ollama didn't respond in time. GPU might be overloaded.")
            return ""
    except Exception as e:
            #stop_loading.set()
            print(f"\n[ERROR] {e}")
            return ""
def interrupt():
    global interrupted
    print("\n[!] Interruption detected. Stopping speech.", flush=True)
    interrupted = True
    sd.stop()  
    with speech_queue.mutex:
        speech_queue.queue.clear()
        speech_queue.all_tasks_done.notify_all()
    os._exit(0)
def await_interruption():
    #my_window = win32console.GetConsoleWindow()
        """This runs in the background while get_response is streaming."""
        while not interrupted:
            # KEYBOARD
           # if win32gui.GetForegroundWindow() == my_window:
                if msvcrt.kbhit():
                    msvcrt.getch()
                    interrupt()
                    break            
            # VOICE (Using the 'energy sliver' approach to prevent lag)
            # Add your r.listen or energy check here            
                time.sleep(0.05)
            
def print_duration(duration):
            print(duration, flush=True)
# Main Execution Loop
def loading_bar(stop_event):
    # These characters are hardcoded to the Windows console
    chars = ["|", "/", "-", "\\"]
    
    # 1. FORCED 15-SECOND COUNTDOWN
    # 150 iterations * 0.1s = 15 seconds
    for i in range(150):
        if stop_event.is_set(): break  # Stop early if AI responds fast
        
        # We calculate the seconds remaining to show progress
        secs_left = stats["duration"] - (i // 10)
        msg = f"\r{chars[i % 4]} AI is thinking... [{secs_left}s] "
        
        # Direct write to console memory
        for char in msg:
            msvcrt.putwch(char)
            
        time.sleep(0.1)

    # 2. FALLBACK SPINNER 
    # (If the 15s are up but the AI is still loading the model)
    i = 0
    while not stop_event.is_set():
        msg = f"\r{chars[i % 4]} AI is almost ready...    "
        for char in msg:
            msvcrt.putwch(char)
        time.sleep(0.1)
        i += 1
    
    # 3. CLEAN UP
    clear_msg = "\r" + (" " * 40) + "\r"
    for char in clear_msg:
        msvcrt.putwch(char)

#region saving
def save_stats():
    stats["duration"] = time_taken        
    with open(STATS_FILE, 'w') as f:
        json.dump(stats, f)
def save_context(summary):
    context_data = {
        "summary": summary
    }
    with open("context_history.json", "w") as f:
        json.dump(context_data, f, indent=4)
#endregion
def get_local_voice():
    voices_json_path = os.path.join(SCRIPT_DIR, "local_voices.json")
    
    # 1. Create it if it doesn't exist
    if not os.path.exists(voices_json_path):
        print("[SYSTEM] Voice index missing. Generating...")
        # Re-using your logic to find files
        voice_files = [
            f for f in os.listdir(SCRIPT_DIR) 
            if f.endswith((".bin", ".pth")) and "voices-v1.0" not in f
        ]
        
        initial_data = {
            "selected": 0,
            "count": len(voice_files),
            "voices": [{"name": os.path.splitext(f)[0], "file": f} for f in voice_files]
        }
        with open(voices_json_path, "w") as f:
            json.dump(initial_data, f, indent=4)
        data = initial_data
    else:
        with open(voices_json_path, "r") as f:
            data = json.load(f)

    # 2. Extract the voice based on the index
    voices_list = data.get("voices", [])
    selected_idx = data.get("selected", 0)
    if not voices_list:
        print("[ERROR] No voice files found in directory!")
        return None

    # Safety check: if index is invalid, reset to 0
    if selected_idx >= len(voices_list) or selected_idx < 0:
        selected_idx = 0
    
    return voices_list[selected_idx]

def get_system_lang():
    # This gets the default locale (e.g., ('en_US', 'UTF-8'))
    loc = locale.getdefaultlocale()[0]     
    if loc:
        # Convert en_US -> en-us (Kokoro prefers lower-case hyphens)
        return loc.replace("_", "-").lower()
    
    return "en-gb" # Fallback if system language can't be found
def main():    
    global SELECTED_VOICE
    start_time = time.time()
    SELECTED_VOICE = get_local_voice()["name"]
    try:
        with open("context_history.json", "r") as f:
            data = json.load(f)
            return data["summary"], data["exchange_count"]
    except FileNotFoundError:
        # Default values if the file doesn't exist yet
        print("File history not found", flush=False)
    #print(f"Internet Status: {'Online' if has_internet else 'Offline'}", flush=True)
    #print ("Use Internet", USE_CLOUD, flush=True)
    
    #for commnds
    raw_args = sys.argv[1:]
    overwrite_flag = False    
    custom_system_instruction = DEFAULT_SYSTEM_INSTRUCTION
    custom_extension = None # New flag for custom extension
    clean_prompt_parts = []
    # CRITICAL FIX: Determine base_output_dir from the script's own location, not os.getcwd()
    try:
        # Get the absolute path of the directory containing this script file 
        script_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        # Fallback for some execution environments
        script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

    base_output_dir = script_dir 
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        
        if arg in ['--ow', '--overwrite']:
            overwrite_flag = True
        elif arg in ['--system'] and i + 1 < len(raw_args):
            custom_system_instruction = raw_args[i + 1]
            i += 1
        elif arg in ['--ext', '--extension'] and i + 1 < len(raw_args):
            # Check if extension starts with '.', add it if missing
            ext = raw_args[i + 1]
            custom_extension = ext if ext.startswith('.') else f".{ext}"
            i += 1
        elif not arg.startswith('--'):
            clean_prompt_parts.append(arg)        
        i += 1
    
    # Prompt is missing: CRITICAL EXIT 
    if not clean_prompt_parts:
        print("[CRITICAL ERROR] Missing command prompt.", file=sys.stderr)
        sys.exit(1)
    #Once verified to be a clean prompt, a user prompt is created
    user_prompt = " ".join(clean_prompt_parts)
    #REPLACED BUNCH OF IF STATEMENTS WITH FOR LOOP TO SEARCH TRIGGERS JSON FILE
    for key, target_value, keywords in TRIGGER_MAP:
        # 1. Check if the setting is already what we want
        if SETTINGS.get(key) == target_value:
            continue            
        # 2. Check if any keyword for this state is in the prompt
        if any(word in user_prompt for word in keywords):
            SETTINGS[key] = target_value
            print(f"Triggered: {key} -> {target_value}")
            save(SETTINGS)
            sys.exit(0)
    if check_for_real_time_query(user_prompt):
        sys.exit(0) # Exit on local success
    
    #Check for Content Mode activation keywords
    #After the prompt cleaning checks are complete, Ollama has to be used.
    #Keywords can be used to perform events with the output text
    content_keywords = ['save', 'file', 'write', 'create', 'document']
    is_content_request = any(keyword in user_prompt.lower() for keyword in content_keywords) or custom_extension

    success = False
    global conversation_history
    
    try:
        # 1. Prepare the JSON payload
        conversation_history += f"User: {user_prompt}\nAssistant: "
        payload = {
            "model": DEFAULT_MODEL,
            "prompt": conversation_history,
            "stream": True,
            "options": {
                "system": custom_system_instruction, 
                "temperature": 1.0,
                "top_p": 0.5,
                "num_predict": 750,
                "keep_alive": 0,
                "repeat_penalty": 1.1
            }
        }
        # Next listen for interruptions
        monitor = threading.Thread(target=await_interruption, daemon=True)
        monitor.start()
        # 2. Ollama API call
        response = get_response(payload)
        #Next clean up the end of the program. content history. File creation
        generated_command = response.strip()
        conversation_history += f"{response}\n"
        print (len(conversation_history))   
        if len(conversation_history) > 9000:
            payload["prompt"] = f"Summarize the following conversation history concisely, keeping all key facts and user preferences:\n{conversation_history}"
            #conversation_history = get_response(payload)
        if not generated_command:
            print(f"[NON-EXECUTABLE OUTPUT]: Ollama generated an empty response.", file=sys.stdout)
            sys.exit(0)
        # --- Content Mode Path ---
        if is_content_request:
            # Pass the custom extension to the handler
            success = handle_content_mode(user_prompt, generated_command, base_output_dir, overwrite_flag, custom_extension)
            if not success:
                sys.exit(1) # Exit loudly if file writing failed
            sys.exit(0)
            
        # --- Command Mode Path (Original Logic) ---
        # 1. Define the only programs you actually care about
        ALLOWED_EXECUTABLES = {"piper.exe", "python.exe", "ollama.exe"}

# 2. Optimized Cleaning
        raw_command_line = generated_command.split('\n')[0].strip()
        tokens = raw_command_line.split()
        start_index = -1 

        for i, token in enumerate(tokens):
    # Check if the token (or the file name in the path) is in our whitelist
            if any(exe in token.lower() for exe in ALLOWED_EXECUTABLES):
                start_index = i
                break

        if start_index >= 0:
    # This keeps the full path if the AI provided one, but starts at the right spot
            raw_command_line = " ".join(tokens[start_index:])
        else:
            global time_taken
            # Report the status of conversational output
            end_time = time.time()
            current_time_str = time.strftime("%H:%M:%S", time.localtime(end_time))
            duration = end_time - start_time
            #say(f"[NON-EXECUTABLE OUTPUT] {current_time_str} [{duration:.2f}s]: {generated_command}", file=sys.stdout)
            print(f"[NON-EXECUTABLE OUTPUT] {current_time_str} [{duration:.2f}s]")
            time_taken = math.ceil(duration)
            save_stats()
            sys.exit(0) # Exit successfully (not a critical failure)

        # Print the cleaned command line before execution
        print("[RAW COMMAND]: {cmd}".format(cmd=raw_command_line))
        
        # 4. Apply safety checks and execute 
        success, message = check_and_execute_command(raw_command_line.split('&&'), base_output_dir, overwrite_flag)
            
    except Exception as e:
        # CATCH-ALL: For any unexpected script error. Must fail loudly.
        print(f"[CRITICAL ERROR] Execution script failed: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # 5. Send final notification ONLY ON SUCCESS (Command Mode)
        if success:
             send_task_notification("✅ Task Completed", "Successfully ran command for prompt: {prompt}...".format(prompt=user_prompt[:40]))
        # Note: File creation notification is handled inside handle_content_mode

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()