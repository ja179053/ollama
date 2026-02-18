# ollama_executor.py: Executor with Content Mode Fallback and Extension Flag
# Standard Library Imports
import io
import json
import multiprocessing
import os
import re
import shlex
import socket
import subprocess
import sys
import time
# Third-Party Imports
import requests
import shutil
import speech_recognition as sr
from datetime import datetime
#edgee tts is better tts than pyttsx3, but does not work offline
import asyncio    
import ctypes
#espeak_folder = r"D:\Ollama\eSpeak NG"
import pygame
#region toggles
def set_want_cloud():
    try:
        with open("settings.json", "r") as f:
            data = json.load(f)
            val = data.get("online", True)
            #print (val, flush=True)
            return val == True
    except:
        return True # Default to True if file is busy
#endregion
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
    with open("settings.json", "w") as f:
        json.dump(data, f, indent=4) # indent makes it readable
# Configuration
WANT_CLOUD = set_want_cloud()
USE_CLOUD = WANT_CLOUD if has_internet() else False
DEFAULT_MODEL = "gemma3:4b-it-qat" if not USE_CLOUD else "qwen3-vl:235b-cloud"
OLLAMA_API_URL = "http://localhost:11434/api/generate"
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
        pass
    
def check_to_online(prompt):
    online_keywords = ['online', 'online mode', 'qwen']
    if prompt.lower() in online_keywords:
        with open("settings.json", "r") as f:
            data = json.load(f)
            data["online"] = True
            save(data)
            sys.exit(0) # Exit on local success
def check_to_offline(prompt):
    offline_keywords = ['offline mode', 'offline', 'gemma']
    if prompt.lower().strip() in offline_keywords:
        with open("settings.json", "r") as f:
            data = json.load(f)
            data["online"] = False
            save(data)
            sys.exit(0) # Exit on local success
#region muting
def check_mute_keywords():
    try:
        with open("settings.json", "r") as f:
            data = json.load(f)
            return not data.get("mute", True)
    except:
        return True # Default to True if file is busy
def check_to_unmute(prompt):
    unmute_keywords = ['talk', 'unmute']
    if prompt.lower() in unmute_keywords:
        with open("settings.json", "r") as f:
            data = json.load(f)
            data["mute"] = False
            save(data)
            sys.exit(0) # Exit on local success
def check_to_mute(prompt):
    #print("checking prompt for mute" , prompt, flush=True)
    mute_keywords = ['shut up', 'mute', 'silence']
    if prompt.lower().strip() in mute_keywords:
        with open("settings.json", "r") as f:
            data = json.load(f)
            data["mute"] = True
            save(data)
            #print("muted", flush=True)
            sys.exit(0) # Exit on local success
#endregion
def clean_tts(text):
    print ("I said" , text, flush=True)
    """Removes asterisks, backslashes, and extra symbols for natural speech."""
    # 1. Remove Markdown bold/italic (e.g., **text** or *text*)
    text = text.encode('ascii', 'ignore').decode('ascii').strip()
    text = text.replace("**", "").replace("*", "")
    
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
def speak_task(text):
    return
    piper_dir = r"D:\ollama\piper"
    command = [os.path.join(piper_dir, "piper.exe"), "--model", os.path.join(piper_dir, "en_US-lessac-medium.onnx"), "--output_file", r"D:\Ollama\output.wav", "--overwrite"]
    subprocess.run(command, check=True, capture_output=True, input=clean_tts(text), text=True)
    #You don't need the wrapper if you are not using a web based servce
    #async def amain():
        #communicate = edge_tts.Communicate(clean_tts(text), voice)
        #await communicate.save("output.mp3")

    # Generate the audio file
    #asyncio.run(amain())
    # 3. Play the audio file
    pygame.mixer.init()
    pygame.mixer.music.load("output.wav")
    pygame.mixer.music.play()
    
    while pygame.mixer.music.get_busy():
        time.sleep(0.1)
    
    pygame.mixer.quit()

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
def say(text, file=sys.stdout):    
        print (text, flush=True)
# Start the voice in a separate process so we can kill it
        p = multiprocessing.Process(target=speak_task, args=(text.split(":", 3)[3].strip(),))
        p.start()# Start the microphone listener
        r = sr.Recognizer()
        with sr.Microphone() as source:
        # Lower the threshold so it's sensitive to your voice
            r.adjust_for_ambient_noise(source, duration=1)
            r.energy_threshold += 1000000 
        
            print(" [Listening for interruption...]", end="\r", flush=True)
        
            while p.is_alive():
                try:
                # listen() blocks for a tiny bit to check for sound
                # phrase_time_limit=1 means it checks in 1-second chunks
                    r.listen(source, timeout=0.1, phrase_time_limit=1)
                
                # If we get here, sound was detected!
                    print("\n[!] Interruption detected. Stopping speech.", flush=True)
                    p.terminate()
                    break
                except (sr.WaitTimeoutError, sr.UnknownValueError):
                # No speech detected yet, keep looping while AI is talking
                    continue    
        p.join() # Clean up the process
def get_response(payload):  
        #print ("doing something")  
        response = None
        max_retries = 3
        for api_attempt in range(max_retries):
            try:
                response = requests.post(OLLAMA_API_URL, json=payload, timeout=180)
                response.raise_for_status()
                return response
                break 
            except requests.exceptions.RequestException as e:
                # CRITICAL FAILURE: Connection issue. Fail loudly with print, then exit.
                if api_attempt < max_retries - 1 and (response is None or response.status_code in [429, 500, 502, 503, 504]):
                    time.sleep(1 * (2 ** api_attempt))
                else:
                    print(f"[CRITICAL ERROR] Ollama connection failed. Is the server running? Details: {e}", file=sys.stderr)
                    sys.exit(1) # Exit loudly
def print_duration(duration):
            print(duration, flush=True)
def save_context(summary):
    context_data = {
        "summary": summary
    }
    with open("context_history.json", "w") as f:
        json.dump(context_data, f, indent=4)
conversation_history = ""
# Main Execution Loop
def main():
    start_time = time.time()
    try:
        with open("context_history.json", "r") as f:
            data = json.load(f)
            return data["summary"], data["exchange_count"]
    except FileNotFoundError:
        # Default values if the file doesn't exist yet
        print("File history not found")
    #print(f"Internet Status: {'Online' if has_internet else 'Offline'}", flush=True)
    print(f"Targeting Model: {DEFAULT_MODEL}", flush=True)
    #print ("Want Internet", WANT_CLOUD, flush=True)
    #print ("Use Internet", USE_CLOUD, flush=True)
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
    user_prompt = " ".join(clean_prompt_parts)
    if check_mute_keywords():
        check_to_mute(user_prompt)
    else:
        check_to_unmute(user_prompt)
    if USE_CLOUD:
        check_to_offline(user_prompt)
    else:
        check_to_online(user_prompt)
        
    if check_for_real_time_query(user_prompt):
        sys.exit(0) # Exit on local success

    # NEW: Check for Content Mode activation keywords
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
            "stream": False,
            "options": {
                "system": custom_system_instruction, 
                "temperature": 0.1,
                "top_p": 0.5,
                "num_predict": 750,
            }
        }
        print_duration(time.time() - start_time) 
        # 2. Ollama API call with Retry Logic (for connection issues)
        response = get_response(payload)
        print_duration(time.time() - start_time) 
        # 3. Process the successful response
        response_data = response.json()
        generated_command = response_data.get('response', '').strip()
        conversation_history += f"{response}\n"
        #print (len(conversation_history))
        if len(conversation_history) > 10000:
            payload.prompt = f"Summarize the following conversation history concisely, keeping all key facts and user preferences:\n{conversation_history}"
            conversation_history = get_response(payload)
        if not generated_command:
            say(f"[NON-EXECUTABLE OUTPUT]: Ollama generated an empty response.", file=sys.stdout)
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
            # Report the status of conversational output
            end_time = time.time()
            current_time_str = time.strftime("%H:%M:%S", time.localtime(end_time))
            duration = end_time - start_time
            say(f"[NON-EXECUTABLE OUTPUT] {current_time_str} [{duration:.2f}s]: {generated_command}", file=sys.stdout)
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
    import multiprocessing
    multiprocessing.freeze_support()
    main()